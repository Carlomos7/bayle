"""The process-global wiring app.create_app does (G10), undone in one call. A process hosts one session; tests that
build several (or none) call reset_process_globals() before and after so no store, folder or sink leaks between them."""

from __future__ import annotations

from bayle.mods import rebuild as mod_rebuild
from bayle.platform import cpu, data_folder, instance
from bayle.platform import logging as run_logging
from bayle.storage import mirror


def reset_process_globals() -> None:
    mod_rebuild.use_hash_store(None)
    mod_rebuild.use_run_store(None)
    mirror.use(None)
    run_logging.use_job_store(None)
    run_logging.attach_notice_sink(None)
    cpu.install(None)
    # these have no "unset" in their own API (set once at start-up); a reset is the one place that needs it
    data_folder._ROOT = None
    instance._SCOPE = None
