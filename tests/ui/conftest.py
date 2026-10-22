"""Guards for the UI suite.

I/O boundary: the services pages read through call assert_not_ui_thread(); here it is switched on, so a page that reads
the disk on the UI thread fails its test (a test host that runs background work inline wraps it in as_worker()).

UI-stall guard (views/conftest.py starts the watch): a test fails when one turn of the UI thread's event loop runs
longer than STALL_MS (ui/stall.py: 250 ms for offscreen CI; the target on real hardware is stall.TARGET_MS = 50 ms),
with the main thread's stack sampled during the slowest stall in the message. Set RS_UI_STALL_MS to change it, 0 to
switch it off. A test that must block longer (a cold QML compile) is marked @pytest.mark.ui_stall_ok."""

import os

import pytest

from bayle.platform import threads
from bayle.ui import stall

STALL_MS = float(os.environ.get("RS_UI_STALL_MS", stall.TEST_MS))


@pytest.fixture(autouse=True)
def _io_stays_off_the_ui_thread():
    threads.enable()
    yield
    threads.disable()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    stalls = getattr(item, "ui_stalls", None)
    if report.when == "call" and report.passed and stalls:
        ms, stack = max(stalls)
        report.outcome = "failed"
        report.longrepr = (
            f"the UI thread was blocked for {ms:.0f} ms (limit {STALL_MS:.0f} ms; {len(stalls)} stall(s)); "
            f"the slowest, sampled while it ran:\n{stack or '(no stack sampled)'}"
        )
