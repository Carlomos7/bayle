"""The window's pool of QProcess workers (ui/cpu_pool.py): a real worker answers a task started from another thread,
a worker that dies fails its task with what it wrote on standard error, and a pool whose workers cannot start runs
tasks on threads instead."""

import os
import sys
import threading
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pytest

pytest.importorskip("PySide6.QtCore")
from PySide6.QtGui import QGuiApplication

from bayle.platform import cpu
from bayle.ui.cpu_pool import CpuPool

PROBE = "bayle.platform.cpu:probe"


@pytest.fixture
def app():
    return QGuiApplication.instance() or QGuiApplication([])


def ask(pool, app, task=PROBE, **args):
    """Start the task from a thread (as a job does) while this thread runs the events, as the window's does."""
    got = {}
    t = threading.Thread(target=lambda: got.update(f=pool.submit(task, args)))
    t.start()
    end = time.monotonic() + 60
    while (not got or not got["f"].done()) and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)
    t.join()
    return got["f"]


def test_a_real_worker_answers_a_task_and_is_reused(app):
    pool = CpuPool(size=1)
    try:
        one = ask(pool, app, value=1).result(0)
        two = ask(pool, app, value=2).result(0)
    finally:
        pool.shutdown()
    assert (one["value"], two["value"]) == (2, 3)
    assert one["pid"] == two["pid"] != os.getpid()
    assert one["qt"] is False


def test_a_task_that_raises_comes_back_as_its_error(app):
    pool = CpuPool(size=1)
    try:
        with pytest.raises(ValueError, match="not a task"):
            ask(pool, app, task="os:getcwd").result(0)
    finally:
        pool.shutdown()


def test_a_worker_that_dies_fails_its_task_with_its_standard_error(app):
    pool = CpuPool([sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"], size=1)
    try:
        with pytest.raises(RuntimeError, match=r"exit 3.*boom"):
            ask(pool, app).result(0)
    finally:
        pool.shutdown()


def test_workers_that_cannot_start_leave_the_work_to_threads(app):
    pool = CpuPool(["/no/such/program"], size=1)
    try:
        assert ask(pool, app, value=1).result(0)["value"] == 2
        assert ask(pool, app, value=2).result(0)["value"] == 3
        assert pool._threads_only
    finally:
        pool.shutdown()


def test_from_the_windows_own_thread_a_task_runs_inline(app):
    pool = CpuPool(size=1)
    assert pool.submit(PROBE, {"value": 1}).result(0)["pid"] == os.getpid()
    assert cpu.run_inline(PROBE, {}).done()


def test_a_broadcast_reaches_a_live_worker_before_the_tasks_sent_after_it(app, tmp_path):
    log = tmp_path / "seen.txt"
    script = (
        "import sys, json\n"
        f"log = open({str(log)!r}, 'a')\n"
        "for line in sys.stdin:\n"
        "    r = json.loads(line); log.write(r['task'] + '\\n'); log.flush()\n"
        "    print(json.dumps({'id': r['id'], 'ok': True, 'result': 1}), flush=True)\n"
    )
    pool = CpuPool([sys.executable, "-c", script], size=1)
    try:
        ask(pool, app, task="a:one").result(0)
        done = {}
        threading.Thread(target=lambda: done.update(f=pool.broadcast("a:forget", {}))).start()
        end = time.monotonic() + 30
        while "f" not in done or not done["f"].done():
            app.processEvents()
            assert time.monotonic() < end
        ask(pool, app, task="a:two")
    finally:
        pool.shutdown()
    assert log.read_text().split() == ["a:one", "a:forget", "a:two"]
