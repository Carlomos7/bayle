"""CPU work in worker processes (platform/cpu.py): tasks run inline without a backend, a real worker process answers
over the line protocol without loading Qt, errors keep their kind, and the tasks moved off the window's thread give
the same results as before. The window's QProcess pool is tested in tests/ui/test_cpu_pool.py."""

import hashlib
import json
import subprocess

import pytest

from roundtable_souls.game import catalog
from roundtable_souls.game.locate import Locations
from roundtable_souls.mods import shared_mods
from roundtable_souls.platform import cpu
from roundtable_souls.services import saves


def test_a_task_runs_inline_without_a_backend():
    assert cpu.run_cpu("roundtable_souls.platform.cpu:probe", {"value": 1}).result()["value"] == 2


def test_only_the_packages_own_public_functions_are_tasks():
    for bad in ("os:getcwd", "roundtable_souls.platform.cpu:_backend", "roundtable_souls.platform.cpu:", "nonsense"):
        with pytest.raises(ValueError):
            cpu.call(bad, {})


def test_an_installed_backend_gets_the_task_and_none_goes_back_to_inline():
    seen = []
    cpu.install(lambda task, args: seen.append((task, args)) or cpu.run_inline(task, args))
    try:
        cpu.run_cpu("roundtable_souls.platform.cpu:probe", {"value": 5}).result()
    finally:
        cpu.install(None)
    assert seen == [("roundtable_souls.platform.cpu:probe", {"value": 5})]


def test_a_real_worker_process_answers_and_never_loads_qt():
    lines = [
        {"id": 1, "task": "roundtable_souls.platform.cpu:probe", "args": {"value": 1}},
        {"id": 2, "task": "roundtable_souls.platform.cpu:nothing", "args": {}},
        {"id": 3, "task": "roundtable_souls.platform.cpu:probe", "args": {"value": 9}},
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
