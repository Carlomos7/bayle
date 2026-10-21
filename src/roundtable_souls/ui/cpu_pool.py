"""The window's worker processes for CPU-bound work (platform/cpu.py says what a task is).

A small pool of persistent QProcess workers, started when the first task arrives. Tasks come from job threads: they
are queued on the window's thread (a queued signal), written to an idle worker, and each reply, read as the process
announces it, completes that task's Future. Nothing here waits for a process, except at exit.

A worker that dies fails the task it was running with its standard error as the reason, and a new one starts for the
next task. If no worker can start at all, tasks run on threads of this program from then on (logged once).
"""

from __future__ import annotations

import itertools
import json
import os
import threading
from collections import deque
from concurrent.futures import Future
from typing import Any

from PySide6.QtCore import QCoreApplication, QObject, QProcess, QThread, Signal

from roundtable_souls.platform import cpu
from roundtable_souls.platform import logging as run_logging

_pool: CpuPool | None = None


class _Job:
    def __init__(self, id: int, task: str, args: dict, future: Future):
        self.id, self.task, self.args, self.future = id, task, args, future


class _Worker:
    def __init__(self, proc: QProcess):
        self.proc = proc
        self.out = b""
        self.err = b""
        self.job: _Job | None = None
        self.pinned: list[_Job] = []  # broadcasts waiting for this worker to be free: they go before any task


class CpuPool(QObject):
    _submitted = Signal(object)
    _broadcasting = Signal(object)

    def __init__(self, command: list[str] | None = None, size: int | None = None):
        super().__init__()
        self._command = command or cpu.worker_command()
        self._size = size or max(1, min(4, (os.cpu_count() or 2) - 1))
        self._workers: list[_Worker] = []
        self._queue: deque[_Job] = deque()
        self._ids = itertools.count(1)
        self._threads_only = False
        self._closed = False
        self._submitted.connect(self._accept)
        self._broadcasting.connect(self._pin)

    # ------------------------------------------------------------------ any thread
    def submit(self, task: str, args: dict) -> Future:
        """The backend platform.cpu.run_cpu uses (run_cpu has already dealt with the window's own thread)."""
        if QThread.currentThread() is self.thread():
            return cpu.run_inline(task, args)
        future: Future = Future()
        self._submitted.emit(_Job(next(self._ids), task, args, future))
        return future

    def broadcast(self, task: str, args: dict) -> Future:
        """The task on every live worker, before whatever is sent to it after this call."""
        future: Future = Future()
        self._broadcasting.emit(_Job(0, task, args, future))
        return future

    # ------------------------------------------------------------------ the window's thread
    def _pin(self, job: _Job) -> None:
        for w in self._workers:
            w.pinned.append(_Job(next(self._ids), job.task, job.args, Future()))
        job.future.set_result(None)
        self._pump()

    def _accept(self, job: _Job) -> None:
        if self._closed:
            job.future.set_exception(RuntimeError("the program is closing"))
        elif self._threads_only:
            self._in_thread(job)
        else:
            self._queue.append(job)
            self._pump()

    def _send(self, worker: _Worker, job: _Job) -> None:
        worker.job = job
        line = json.dumps({"id": job.id, "task": job.task, "args": job.args}) + "\n"
        worker.proc.write(line.encode("utf-8"))

    def _pump(self) -> None:
        for w in self._workers:
            if w.job is None and w.pinned:
                self._send(w, w.pinned.pop(0))
        while self._queue and not self._threads_only:
            worker = next((w for w in self._workers if w.job is None), None)
            if worker is None:
                if len(self._workers) >= self._size:
                    return
                worker = self._spawn()
                if self._threads_only:  # it could not start, and the queue went to threads
                    return
            self._send(worker, self._queue.popleft())

    def _spawn(self) -> _Worker:
        proc = QProcess(self)
        worker = _Worker(proc)
        proc.readyReadStandardOutput.connect(lambda: self._read(worker))
        proc.readyReadStandardError.connect(lambda: self._read_err(worker))
        proc.finished.connect(lambda code, _status: self._ended(worker, code))
        proc.errorOccurred.connect(lambda error: self._failed(worker, error))
        self._workers.append(worker)
        proc.start(self._command[0], self._command[1:])
        return worker

    @staticmethod
    def _read_err(worker: _Worker) -> None:
        worker.err = (worker.err + bytes(worker.proc.readAllStandardError().data()))[-4000:]

    def _read(self, worker: _Worker) -> None:
        worker.out += bytes(worker.proc.readAllStandardOutput().data())
        while b"\n" in worker.out:
            line, worker.out = worker.out.split(b"\n", 1)
            job = worker.job
            try:
                reply = json.loads(line)
                if job is None or reply.get("id") != job.id:
                    raise ValueError("a reply nobody asked for")
            except ValueError as e:
                run_logging.get_logger("cpu").error("a worker sent an unreadable reply: %s", e)
                worker.proc.kill()  # out of step: _ended fails the task and a clean worker takes the next one
                return
            worker.job = None
            if reply.get("ok"):
                job.future.set_result(reply.get("result"))
            else:
                job.future.set_exception(cpu.remote_error(reply))
        self._pump()

    def _ended(self, worker: _Worker, code: int) -> None:
        if worker in self._workers:
            self._workers.remove(worker)
        self._read_err(worker)
        job, worker.job = worker.job, None
        if job is not None and not job.future.done():
            why = worker.err.decode("utf-8", "replace").strip()
            job.future.set_exception(RuntimeError(f"the worker process ended (exit {code}) during {job.task}: {why}"))
        self._pump()

    def _failed(self, worker: _Worker, error: QProcess.ProcessError) -> None:
        if error != QProcess.ProcessError.FailedToStart:
            return  # a crash also ends the process: _ended handles it
        if worker in self._workers:
            self._workers.remove(worker)
        if not self._threads_only:
            run_logging.get_logger("cpu").warning(
                "cannot start a worker process (%s); CPU work runs on threads of this program instead",
                worker.proc.errorString(),
            )
        self._threads_only = True
        jobs = ([worker.job] if worker.job else []) + list(self._queue)
        worker.job = None
        self._queue.clear()
        for job in jobs:
            self._in_thread(job)

    @staticmethod
    def _in_thread(job: _Job) -> None:
        def run() -> None:
            done = cpu.run_inline(job.task, job.args)
            error = done.exception()
            if error:
                job.future.set_exception(error)
            else:
                job.future.set_result(done.result())

        threading.Thread(target=run, daemon=True, name="cpu-fallback").start()

    def shutdown(self) -> None:
        """At exit: no more tasks; workers see their input end and leave (killed if they do not in half a second)."""
        self._closed = True
        for job in self._queue:
            job.future.set_exception(RuntimeError("the program is closing"))
        self._queue.clear()
        for w in list(self._workers):
            if w.job is not None and not w.job.future.done():
                w.job.future.set_exception(RuntimeError("the program is closing"))
            w.proc.closeWriteChannel()
            if not w.proc.waitForFinished(500):
                w.proc.kill()
        self._workers.clear()


def install() -> CpuPool:
    """Make this program's CPU tasks run in worker processes; shut them down when the application quits."""
    global _pool
    _pool = CpuPool()
    cpu.install(_pool.submit, _pool.broadcast, threading.get_ident())
    app: Any = QCoreApplication.instance()
    app.aboutToQuit.connect(_pool.shutdown)
    return _pool
