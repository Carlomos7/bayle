"""What the Activity page reads: job summaries, logs read back, unseen failures."""

import os

from bayle.platform import logging as rl
from bayle.platform import logging as run_logging

os.environ["QT_QPA_PLATFORM"] = "offscreen"  # always, whatever the shell sets: no real windows


def make_job(title, lines=(), outcome=None, game="eldenring", attach=None):
    job = rl.begin_job(title, game=game)
    for line in lines:
        run_logging.log(line)
    if attach:
        rl.attachment(attach[0]).write_text(attach[1], encoding="utf-8")
    rl.end_job(job, outcome)
    return job


# ----------------------------------------------------------------------------- what the index says
def test_a_job_keeps_its_summary_and_first_problem():
    make_job("install mod goblins", ["copying", "done: installed goblins (readme left out)"])
    make_job("repair", ["error: ER0000.co2 is locked by another program", "error: second problem"], "failed")
    recs = {r["title"]: r for r in rl.read_jobs()}
    assert recs["install mod goblins"]["summary"] == "installed goblins (readme left out)"
    assert recs["repair"]["problem"] == "ER0000.co2 is locked by another program"


def test_set_summary_wins_over_the_done_line():
    job = rl.begin_job("rebuild")
    run_logging.log("done: rebuilt")
    rl.set_summary("Combined 2 packs; 1 overlapping row")
    rl.end_job(job)
    assert rl.read_jobs()[0]["summary"] == "Combined 2 packs; 1 overlapping row"


def test_a_log_reads_back_as_entries_with_levels_and_continuations():
    job = make_job("check", ["first line", "warning: careful"])
    rl.begin_job("crash")
    try:
        raise ValueError("boom")
    except ValueError:
        rl.get_logger("job").exception("it broke")
    crash = rl.current_job()
    rl.end_job(crash, "failed")
    got = rl.read_job_log(job.path.name)
    levels = [(e["level"], e["text"]) for e in got["entries"]]
    assert ("info", "first line") in levels and ("warning", "warning: careful") in levels
    assert all(e["time"].count(":") == 2 and "." in e["time"] for e in got["entries"])
    tb = next(e for e in rl.read_job_log(crash.path.name)["entries"] if e["text"].startswith("it broke"))
    assert tb["level"] == "error" and "Traceback" in tb["text"] and "ValueError: boom" in tb["text"]


def test_only_the_end_of_a_huge_log_is_read():
    job = make_job("play", [f"line {i} " + "x" * 80 for i in range(400)])
    got = rl.read_job_log(job.path.name, limit=4000)
    assert got["cut"] and got["entries"][-1]["text"].startswith("=== play")
    assert all(e["time"] for e in got["entries"])  # the partial first line was dropped, not shown as garbage


def test_names_outside_the_jobs_folder_are_refused():
    assert rl.job_file("../launcher.log") is None and rl.job_file("") is None
    assert rl.read_job_log("..\\..\\x.log")["missing"] and rl.read_attachment("/etc/passwd")["missing"]


def test_unseen_failures_count_only_after_the_last_look():
    make_job("repair", ["error: x"], "failed")
    first = rl.read_jobs()[0]
    assert len(rl.unseen_failures(0)) == 1
    assert rl.unseen_failures(float(first["t"])) == []
    make_job("play", ["fine"])
    make_job("install mod y", ["error: z"], "failed")
    assert [r["title"] for r in rl.unseen_failures(float(first["t"]))] == ["install mod y"]


def test_kinds_fall_into_the_filter_groups():
    assert rl.group_of("play") == "Play" and rl.group_of("repair") == "Saves"
    assert rl.group_of("rebuild") == "Mods" and rl.group_of("install") == "Mods"
    assert rl.group_of("check") == "Other" and rl.group_of("anything") == "Other"
