"""CPU work in worker processes (platform/cpu.py): tasks run inline without a backend, a real worker process answers
over the line protocol without loading Qt, errors keep their kind, and the tasks moved off the window's thread give
the same results as before. The subprocess pool is tested in tests/unit/test_cpu_pool.py."""

import hashlib
import json
import logging
import subprocess
import threading

import pytest

from bayle.game import catalog
from bayle.game.locate import Locations
from bayle.mods import shared_mods
from bayle.platform import cpu
from bayle.runtime import bootstrap
from bayle.saves import analyze, caches, item_names
from bayle.services import jobs, saves


def test_a_task_runs_inline_without_a_backend():
    assert cpu.run_cpu("bayle.platform.cpu:probe", {"value": 1}).result()["value"] == 2


def test_only_the_packages_own_public_functions_are_tasks():
    for bad in ("os:getcwd", "bayle.platform.cpu:_backend", "bayle.platform.cpu:", "nonsense"):
        with pytest.raises(ValueError):
            cpu.call(bad, {})


def test_an_installed_backend_gets_the_task_and_none_goes_back_to_inline():
    seen = []
    bootstrap.bind(cpu_backend=lambda task, args: seen.append((task, args)) or cpu.run_inline(task, args))
    try:
        cpu.run_cpu("bayle.platform.cpu:probe", {"value": 5}).result()
    finally:
        bootstrap.bind(cpu_backend=None, cpu_broadcast=None, ui_thread=None)
    assert seen == [("bayle.platform.cpu:probe", {"value": 5})]


def test_a_real_worker_process_answers_and_never_loads_qt():
    lines = [
        {"id": 1, "task": "bayle.platform.cpu:probe", "args": {"value": 1}},
        {"id": 2, "task": "bayle.platform.cpu:nothing", "args": {}},
        {"id": 3, "task": "bayle.platform.cpu:probe", "args": {"value": 9}},
    ]
    done = subprocess.run(
        cpu.worker_command(),
        input="".join(json.dumps(x) + "\n" for x in lines).encode(),
        capture_output=True,
        timeout=120,
        check=True,
    )
    first, bad, last = (json.loads(x) for x in done.stdout.decode().splitlines())
    assert first["ok"] and first["result"]["value"] == 2 and first["result"]["qt"] is False
    assert not bad["ok"] and bad["kind"] == "AttributeError"
    assert last["ok"] and last["result"]["value"] == 10 and last["result"]["pid"] == first["result"]["pid"]


def test_a_failed_reply_comes_back_as_the_same_kind_of_error_for_builtins():
    assert isinstance(cpu.remote_error({"kind": "FileNotFoundError", "error": "x"}), FileNotFoundError)
    assert isinstance(cpu.remote_error({"kind": "ValueError", "error": "x"}), ValueError)
    assert isinstance(cpu.remote_error({"kind": "LibraryError", "error": "x"}), cpu.TaskError)
    assert not isinstance(cpu.remote_error({"kind": "SystemExit", "error": "x"}), SystemExit)


def test_tree_hash_is_the_hash_of_the_files_through_a_task_and_inline(tmp_path):
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "x.bin").write_bytes(b"one")
    (tmp_path / "a" / "b" / "y.bin").write_bytes(b"two!")
    h = hashlib.sha256()
    for rel, data in (("a/b/y.bin", b"two!"), ("a/x.bin", b"one")):
        h.update(f"{rel}\0{len(data)}\0{hashlib.sha256(data).hexdigest()}\n".encode())
    assert shared_mods.tree_hash(tmp_path) == (h.hexdigest()[: shared_mods.ID_LENGTH], 7)
    assert shared_mods.tree_hash_job(str(tmp_path)) == list(shared_mods.tree_hash(tmp_path))


def test_save_info_is_the_same_through_a_task_as_the_direct_call(tmp_path):
    save = tmp_path / "ER0000.sl2"
    save.write_bytes(b"not a save" * 10)
    loc = Locations(catalog.ELDEN_RING)
    assert saves.save_info(save, loc=loc) == saves._save_info(save, loc=loc)


# ----------------------------------------------------------------------------- the window's thread, and stale caches
@pytest.fixture
def ui_thread():
    bootstrap.bind(
        cpu_backend=None, cpu_broadcast=None, ui_thread=threading.get_ident()
    )  # this (the test's) thread plays the window's
    cpu._warned.clear()
    yield
    bootstrap.bind(cpu_backend=None, cpu_broadcast=None, ui_thread=None)


def test_cpu_work_on_the_ui_thread_raises_in_strict_mode(ui_thread):
    with pytest.raises(cpu.UiThreadError):
        cpu.run_cpu("bayle.platform.cpu:probe", {})
    got = {}
    t = threading.Thread(target=lambda: got.update(f=cpu.run_cpu("bayle.platform.cpu:probe", {})))
    t.start()
    t.join()
    assert got["f"].result()["value"] == 1  # another thread is fine


def test_outside_strict_mode_it_runs_inline_and_warns_once_per_call_site(ui_thread, monkeypatch, caplog):
    monkeypatch.delenv("PYTEST_CURRENT_TEST")
    monkeypatch.delenv("ROUNDTABLE_SOULS_STRICT_CPU", raising=False)
    monkeypatch.setattr("bayle.platform.logging.get_logger", lambda name=None: logging.getLogger("rs.cpu"))
    with caplog.at_level(logging.WARNING, logger="rs.cpu"):
        for _ in range(3):
            assert cpu.run_cpu("bayle.platform.cpu:probe", {}).result()["value"] == 1
        cpu.run_cpu("bayle.platform.cpu:probe", {})  # a second call site
    warned = [r for r in caplog.records if "UI thread" in r.getMessage()]
    assert len(warned) == 2 and "test_cpu.py" in warned[0].getMessage()


def test_invalidate_goes_to_the_workers_and_forget_clears_the_caches(monkeypatch):
    sent = []
    bootstrap.bind(cpu_broadcast=lambda task, args: sent.append((task, args)))
    try:
        cpu.invalidate("item_names")
    finally:
        bootstrap.bind(cpu_backend=None, cpu_broadcast=None, ui_thread=None)
    assert sent == [("bayle.saves.caches:forget", {"kind": "item_names"})]
    monkeypatch.setattr(item_names, "_CACHE", ("k", "v"))
    monkeypatch.setattr(analyze, "_GAME_IDS", ("s", frozenset({1})))
    caches.forget("item_names")
    assert item_names._CACHE is None and analyze._GAME_IDS is not None
    caches.forget("all")
    assert analyze._GAME_IDS is None
    with pytest.raises(ValueError):
        caches.forget("nothing")


def test_finishing_a_job_tells_the_workers(monkeypatch):
    told = []
    monkeypatch.setattr(cpu, "invalidate", told.append)
    monkeypatch.setattr(jobs.run_logging, "begin_job", lambda *a, **k: None)
    monkeypatch.setattr(jobs.run_logging, "end_job", lambda *a, **k: None)
    jobs.run_job(lambda launch, loc: None, None, Locations(catalog.ELDEN_RING), "t")
    assert told == ["item_names"]
