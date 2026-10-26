"""Every block the launcher writes into a save is signed: the game checks each entry's MD5 when it loads a save and
refuses one with a stale checksum ("Save data is corrupted"; in-game test T3, evidence E-023). The live-save tests in
tests/integration check the other writers on a copy of a real save; this one needs no save and runs everywhere."""

from bayle.modules.saves import regulation as R


def _save_with(block: bytes) -> bytearray:
    data = bytearray(R.UD11_OFF + R.UD11_SIZE)
    data[R.UD11_OFF : R.UD11_OFF + len(block)] = block
    return data


def test_a_rebuilt_regulation_block_is_signed_and_healthy():
    reg = bytes(range(256)) * 0x1100  # a plausible size (over 1 MB), not all zeros
    block = R.rebuild_block(reg, R.HEALTHY_HEADER)
    assert len(block) == R.UD11_SIZE
    healthy, used, header = R.block_status(_save_with(block))
    assert healthy and header == R.HEALTHY_HEADER and used == len(reg)  # what follows the MD5 and the header


def test_a_block_changed_after_signing_is_not_healthy():
    """What the game itself refuses: one byte changed, the MD5 left as it was."""
    data = _save_with(R.rebuild_block(bytes(range(256)) * 0x1100, R.HEALTHY_HEADER))
    data[R.UD11_OFF + 0x40] ^= 0xFF
    healthy, _used, _header = R.block_status(data)
    assert not healthy
