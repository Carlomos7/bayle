"""The subprocess pool (platform/cpu_pool.py, no Qt): a real worker answers tasks started from several threads, a
worker that dies fails its task with what it wrote on standard error, a pool whose workers cannot start runs tasks on
threads instead, a broadcast reaches live workers before later tasks, and a worker leaves when its parent is gone."""

import os
import subprocess
import sys
import time

import pytest

from bayle.runtime import bootstrap
from bayle.work import cpu
from bayle.work.cpu_pool import CpuPool

PROBE = "bayle.work.cpu:probe"


@pytest.fixture
def pool():
    made = []

    def make(command=None, size=1):
        made.append(CpuPool(command, size=size))
        return made[-1]

    yield make
    for p in made:
        p.shutdown()


def test_a_real_worker_answers_a_task_and_is_reused(pool):
    p = pool()
    one = p.submit(PROBE, {"value": 1}).result(60)
    two = p.submit(PROBE, {"value": 2}).result(60)
    assert (one["value"], two["value"]) == (2, 3)
    assert one["pid"] == two["pid"] != os.getpid()
    assert one["qt"] is False


def test_a_task_that_raises_comes_back_as_its_error(pool):
    with pytest.raises(ValueError, match="not a task"):
        pool().submit("os:getcwd", {}).result(60)


def test_a_worker_that_dies_fails_its_task_with_its_standard_error(pool):
    p = pool([sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"])
    with pytest.raises(RuntimeError, match=r"exit 3.*boom"):
        p.submit(PROBE, {}).result(60)


def test_workers_that_cannot_start_leave_the_work_to_threads(pool):
    p = pool(["/no/such/program"])
    assert p.submit(PROBE, {"value": 1}).result(60)["value"] == 2
    assert p.submit(PROBE, {"value": 2}).result(60)["value"] == 3
    assert p._threads_only


def test_a_new_worker_takes_the_task_after_one_died(pool, tmp_path):
    # the first worker exits at once; the second (same command) survives because the marker file now exists
    marker = tmp_path / "started"
    script = (
        "import os, sys, json\n"
        f"m = {str(marker)!r}\n"
        "if not os.path.exists(m):\n"
        "    open(m, 'w').close(); sys.exit(1)\n"
        "for line in sys.stdin:\n"
        "    r = json.loads(line)\n"
        "    print(json.dumps({'id': r['id'], 'ok': True, 'result': 7}), flush=True)\n"
    )
    p = pool([sys.executable, "-c", script])
    with pytest.raises(RuntimeError, match="exit 1"):
        p.submit(PROBE, {}).result(60)
    assert p.submit(PROBE, {}).result(60) == 7


def test_a_broadcast_reaches_a_live_worker_before_the_tasks_sent_after_it(pool, tmp_path):
    log = tmp_path / "seen.txt"
    script = (
        "import sys, json\n"
        f"log = open({str(log)!r}, 'a')\n"
        "for line in sys.stdin:\n"
        "    r = json.loads(line); log.write(r['task'] + '\\n'); log.flush()\n"
        "    print(json.dumps({'id': r['id'], 'ok': True, 'result': 1}), flush=True)\n"
    )
    p = pool([sys.executable, "-c", script])
    p.submit("a:one", {}).result(60)
    p.broadcast("a:forget", {}).result(60)
    p.submit("a:two", {}).result(60)
    p.shutdown()
    assert log.read_text().split() == ["a:one", "a:forget", "a:two"]


def test_a_submit_after_shutdown_fails(pool):
    p = pool()
    p.shutdown()
    with pytest.raises(RuntimeError, match="closing"):
        p.submit(PROBE, {}).result(5)


def _alive(pid: int) -> bool:
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True
    import ctypes

    k32 = ctypes.windll.kernel32
    k32.OpenProcess.restype = ctypes.c_void_p
    handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    code = ctypes.c_ulong()
    k32.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code))
    k32.CloseHandle(ctypes.c_void_p(handle))
    return code.value == 259  # STILL_ACTIVE


def test_an_idle_worker_exits_when_its_parent_dies_without_cleaning_up():
    parent = (
        "import os, sys\n"
        "from bayle.work.cpu_pool import CpuPool\n"
        "pool = CpuPool(size=1)\n"
        "print(pool.submit('bayle.work.cpu:probe', {}).result(60)['pid'], flush=True)\n"
        "os._exit(0)\n"  # no shutdown: the pipe to the worker just closes
    )
    out = subprocess.run([sys.executable, "-c", parent], capture_output=True, timeout=120, check=True)
    pid = int(out.stdout.split()[-1])
    end = time.monotonic() + 30
    while _alive(pid) and time.monotonic() < end:
        time.sleep(0.1)
    assert not _alive(pid)


def test_install_gives_run_cpu_the_pool(pool):
    p = pool()
    bootstrap.bind(cpu_backend=p.submit, cpu_broadcast=p.broadcast, ui_thread=None)
    try:
        assert cpu.run_cpu(PROBE, {"value": 1}).result(60)["pid"] != os.getpid()
    finally:
        bootstrap.bind(cpu_backend=None, cpu_broadcast=None, ui_thread=None)


def test_big_payloads_and_big_replies_do_not_deadlock(pool):
    # the worker answers each request with a reply bigger than a pipe buffer before it reads the next one, while
    # the next request is also bigger than a pipe buffer
    script = (
        "import sys, json\n"
        "for line in sys.stdin:\n"
        "    r = json.loads(line)\n"
        "    print(json.dumps({'id': r['id'], 'ok': True, 'result': 'y' * 1_000_000}), flush=True)\n"
    )
    p = pool([sys.executable, "-c", script])
    big = {"blob": "x" * 1_000_000}
    futures = [p.submit("a:big", big) for _ in range(4)]
    for f in futures:
        assert len(f.result(60)) == 1_000_000
