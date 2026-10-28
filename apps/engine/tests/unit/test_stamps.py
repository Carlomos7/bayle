"""A page's stamp travels through JSON to the web view and back as `expect`: it must survive a JavaScript number."""

import os

from bayle.modules.mods import mod_configs, mods_page


def test_stamps_fit_a_javascript_number(tmp_path):
    f = tmp_path / "Test.me3"
    f.write_text("x")
    ns = 1_793_000_000_123_456_789  # a 2026 mtime with every nanosecond digit set
    os.utime(f, ns=(ns, ns))
    for stamp in (mod_configs.stamp, mods_page.stamp):
        got = stamp(f)
        assert got is not None
        assert all(abs(v) <= 2**53 for v in got)
        assert float(got[0]) == got[0]  # a JS client sends back exactly what it was given
