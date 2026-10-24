"""A pool of worker processes for CPU-bound work (platform/cpu.py says what a task is). No Qt.

Persistent workers (this program started again with --worker) are started when tasks need them. A task is written to
an idle worker as one JSON line; a reader thread per worker completes that task's Future from the reply line, so
nothing here blocks the caller except the short write. The workers' standard input is the protocol channel and is not
inherited by other children: when this process ends, however it ends, a worker reads end of file and exits (an idle
one at once; one in the middle of a task when it finishes).

A worker that dies fails the task it was running with its standard error as the reason, and a new one starts for the
next task. If no worker can start at all, tasks run on threads of this program from then on (logged once).
"""

from __future__ import annotations

import itertools
import json
import os
import queue
import subprocess
import threading
from collections import deque
from concurrent.futures import Future
from typing import IO

from bayle.platform import cpu
from bayle.platform import logging as run_logging

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class _Job:
    def __init__(self, id: int, task: str, args: dict, future: Future):
        self.id, self.task, self.args, self.future = id, task, args, future


class _Worker:
    def __init__(self, proc: subprocess.Popen):
        self.proc = proc
        self.err = b""
        self.job: _Job | None = None
        self.pinned: list[_Job] = []  # broadcasts waiting for this worker to be free: they go before any task
        self.outbox: queue.Queue[bytes | None] = queue.Queue()  # lines for its writer thread; None closes its stdin


class CpuPool:
    def __init__(self, command: list[str] | None = None, size: int | None = None):
        self._command = command or cpu.worker_command()
        self._size = size or max(1, min(4, (os.cpu_count() or 2) - 1))
        self._lock = threading.RLock()
        self._workers: list[_Worker] = []
        self._queue: deque[_Job] = deque()
        self._ids = itertools.count(1)
        self._threads_only = False
        self._closed = False

    # ------------------------------------------------------------------ any thread
    def submit(self, task: str, args: dict) -> Future:
        """The backend platform.cpu.run_cpu uses (run_cpu has already dealt with the window's own thread)."""
        future: Future = Future()
        with self._lock:
            if self._closed:
                future.set_exception(RuntimeError("the program is closing"))
            elif self._threads_only:
                self._in_thread(_Job(0, task, args, future))
            else:
                self._queue.append(_Job(next(self._ids), task, args, future))
                self._pump()
        return future

    def broadcast(self, task: str, args: dict) -> Future:
        """The task on every live worker, before whatever is sent to it after this call."""
        future: Future = Future()
        with self._lock:
            for w in self._workers:
                w.pinned.append(_Job(next(self._ids), task, args, Future()))
            self._pump()
        future.set_result(None)
        return future

    # ------------------------------------------------------------------ under the lock
    def _send(self, worker: _Worker, job: _Job) -> None:
        worker.job = job
        # never written here: a full pipe would block everyone who needs the lock, including the reader thread
        worker.outbox.put((json.dumps({"id": job.id, "task": job.task, "args": job.args}) + "\n").encode("utf-8"))

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
                if worker is None:  # it could not start, and the queue went to threads
                    return
            self._send(worker, self._queue.popleft())

    def _spawn(self) -> _Worker | None:
        try:
            # stdin is the protocol channel, so it is a pipe; close_fds keeps other children from holding it open
            proc = subprocess.Popen(
                self._command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
                creationflags=_NO_WINDOW,
            )
        except OSError as e:
            run_logging.get_logger("cpu").warning(
                "cannot start a worker process (%s); CPU work runs on threads of this program instead", e
            )
            self._threads_only = True
            jobs, self._queue = list(self._queue), deque()
            for job in jobs:
                self._in_thread(job)
            return None
        worker = _Worker(proc)
        self._workers.append(worker)
        assert proc.stdout is not None and proc.stderr is not None
        err = threading.Thread(target=self._drain_err, args=(worker, proc.stderr), daemon=True, name="cpu-stderr")
        err.start()
        threading.Thread(target=self._write, args=(worker,), daemon=True, name="cpu-writer").start()
        threading.Thread(target=self._read, args=(worker, proc.stdout, err), daemon=True, name="cpu-reader").start()
        return worker

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

    # ------------------------------------------------------------------ writer and reader threads
    @staticmethod
    def _write(worker: _Worker) -> None:
        stdin = worker.proc.stdin
        assert stdin is not None
        try:
            while (line := worker.outbox.get()) is not None:
                stdin.write(line)
                stdin.flush()
        except OSError:
            pass  # the worker is gone: its reader thread sees the end and fails the task
        try:
            stdin.close()
        except OSError:
            pass

    @staticmethod
    def _drain_err(worker: _Worker, stream: IO[bytes]) -> None:
        for chunk in iter(lambda: stream.read1(4096), b""):  # type: ignore[attr-defined]
            worker.err = (worker.err + chunk)[-4000:]

    def _read(self, worker: _Worker, stdout: IO[bytes], err: threading.Thread) -> None:
        for line in stdout:
            with self._lock:
                job = worker.job
                try:
                    reply = json.loads(line)
                    if job is None or reply.get("id") != job.id:
                        raise ValueError("a reply nobody asked for")
                except ValueError as e:
                    run_logging.get_logger("cpu").error("a worker sent an unreadable reply: %s", e)
                    worker.proc.kill()  # out of step: the end of its output fails the task, a clean worker follows
                    break
                worker.job = None
                if reply.get("ok"):
                    job.future.set_result(reply.get("result"))
                else:
                    job.future.set_exception(cpu.remote_error(reply))
                self._pump()
        code = worker.proc.wait()
        err.join(5)
        with self._lock:
            if worker in self._workers:
                self._workers.remove(worker)
            job, worker.job = worker.job, None
            if job is not None and not job.future.done():
                why = worker.err.decode("utf-8", "replace").strip()
                job.future.set_exception(
                    RuntimeError(f"the worker process ended (exit {code}) during {job.task}: {why}")
                )
            if not self._closed:
                self._pump()

    # ------------------------------------------------------------------ exit
    def shutdown(self) -> None:
        """At exit: no more tasks; workers see their input end and leave (killed if they do not in half a second)."""
        with self._lock:
            self._closed = True
            for job in self._queue:
                job.future.set_exception(RuntimeError("the program is closing"))
            self._queue.clear()
            workers = list(self._workers)
            for w in workers:
                if w.job is not None and not w.job.future.done():
                    w.job.future.set_exception(RuntimeError("the program is closing"))
        for w in workers:
            w.outbox.put(None)
            try:
                w.proc.wait(0.5)
            except subprocess.TimeoutExpired:
                w.proc.kill()
                w.proc.wait()
