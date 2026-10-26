"""Golden SHA-256 of what each merge rule and a whole merger run produce, from small deterministic inputs.

Later refactor phases move the merging code; none of them may change a single output byte. If one of these hashes
changes, the merge changed (or the input factory did): that is a behaviour change, decide it on purpose, don't re-record.
"""

import hashlib
import json
import struct

import pytest
from fakegame import bnd, dcx, fmg
from test_esd_merge import game_script, with_option
from test_param_merge import pack, set_word, vanilla

from bayle.adapters import formats
from bayle.adapters.formats.esd import write_esd
from bayle.adapters.formats.tae import IMPORT, STANDARD, TAE, Animation, Event, write_tae
from bayle.adapters.merging import merger
from bayle.adapters.merging.changes import Result
from bayle.adapters.merging.rules import bnd4 as bnd4_rule
from bayle.adapters.merging.rules import esd as esd_rule
from bayle.adapters.merging.rules import fmg as fmg_rule
from bayle.adapters.merging.rules import param as param_rule
from bayle.adapters.merging.rules import tae as tae_rule

GOLDEN = {
    "bnd4": "9be34e336f64e12747824f0de91147243caebe77f2a90940eeb3a60b4a8e4995",
    "fmg": "ae309f4e040219a62b254e45ce08b9027081e6da742eb7791b8b9869941efe35",
    "esd": "d609808614694567e2cd2465898b217486f768e25f33a9da97ec9eb2e32357dc",
    "tae": "3449a3a80a07ece19df3fcc8e8daff33eb361e5f69df14a777d8ee116d60569a",
    "param": "ea516bbaa70d52ed952b2dce7586928e9ac1b4b54aaf8967cd7e2e80db9cfe93",
    "merger": "667d48a342bceda4531f13e763d97698b6e729d1ddc2e341ce28e28ff640090e",
    "merger-report": "383f43c0fd5c8835f2efe383a3993cfe999c422f96a86a512fdd7b94d395e44a",
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def report(r: Result) -> bytes:
    """Everything a merge says besides the bytes, in a stable text."""
    parts = {k: getattr(r, k) for k in ("changed", "clashes", "removed", "notes", "warnings", "omissions")}
    return json.dumps({**parts, "merged": r.merged}, sort_keys=True).encode()


# ----------------------------------------------------------------------------- inputs
HKX = {"a.hkx": b"walk", "b.hkx": b"run", "c.hkx": b"roll"}
FMG_GAME = {1: "one", 2: "two", 3: "three"}


def _tae(*animations: Animation) -> bytes:
    flags = b"\x01\x00\x01\x02\x02\x01\x01\x01"
    return write_tae(TAE(2000, 37, flags, "skeleton.hkt", "c9990.SIB", list(animations)))


def _anim(i: int, *events: Event) -> Animation:
    return Animation(i, STANDARD, bytes([0, 0, 0, 0]) + struct.pack("<i", 0), "a000.hkt", list(events), [])


def _event(start: float, end: float, kind: int, value: int) -> Event:
    return Event(start, end, kind, 0, struct.pack("<i", value) + bytes(12))


TAE_GAME = _tae(
    _anim(0, _event(0.0, 0.5, 129, 7)),
    _anim(1, _event(0.1, 0.4, 700, 3)),
    Animation(2, IMPORT, struct.pack("<ii", 5, -1), "a002.hkt"),
)
TAE_A = _tae(
    _anim(0, _event(0.0, 0.5, 129, 8)),
    _anim(1, _event(0.1, 0.4, 700, 3)),
    Animation(2, IMPORT, struct.pack("<ii", 5, -1), "a002.hkt"),
)
TAE_B = _tae(
    _anim(0, _event(0.0, 0.5, 129, 7)),
    _anim(1, _event(0.1, 0.4, 700, 4)),
    Animation(2, IMPORT, struct.pack("<ii", 5, -1), "a002.hkt"),
    _anim(9, _event(0.0, 1.0, 1, 2)),
)

ESD_GAME = write_esd(game_script())
ESD_A = write_esd(with_option(game_script(), 10, 1000, 4, 120))
ESD_B = write_esd(with_option(game_script(), 20, 2000, 4, 130))


def _inner(first: bytes, second: bytes) -> bytes:
    return bnd({"i1.bin": first, "i2.bin": second})


# ----------------------------------------------------------------------------- one rule at a time
def _results() -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    game = bnd(HKX)
    mod_a = bnd({"a.hkx": b"sekiro walk", "c.hkx": b"roll"})  # changes a, leaves out b
    mod_b = bnd({**HKX, "a.hkx": b"other walk", "new.hkx": b"added"})  # clashes on a, adds new
    out["bnd4"] = bnd4_rule.merge(game, [("a", mod_a), ("b", mod_b)], "", lambda *_: None).data
    fm = fmg_rule.merge(
        fmg(FMG_GAME),
        [("a", fmg({1: "ONE", 2: "two", 3: "three"})), ("b", fmg({1: "uno", 3: "three", 4: "four"}))],
        "t.fmg",
    )
    out["fmg"] = fm.data
    out["esd"] = esd_rule.merge(ESD_GAME, [("a", ESD_A), ("b", ESD_B)], "t000001000.esd").data
    out["tae"] = tae_rule.merge(TAE_GAME, [("a", TAE_A), ("b", TAE_B)], "a00.tae").data
    base = vanilla()
    combined, _ = param_rule.combine(
        base,
        [
            ("a", pack({"EquipParamWeapon": set_word(1000, 0, 111)})),
            ("b", pack({"EquipParamWeapon": set_word(2000, 1, 222), "SpEffectParam": set_word(10, 3, 5)})),
        ],
    )
    # the file is encrypted with a random IV: the hash is of the decrypted binder, which is what the game reads
    out["param"] = formats.regulation.binder_bytes(formats.regulation.read_regulation(combined).bnd)
    return out


def _whole_run() -> Result:
    def archive(fmg_texts, inner, esd, tae, extra=None):
        files = {
            "t.fmg": fmg(fmg_texts),
            "inner.bnd": inner,
            "t000001000.esd": esd,
            "a00.tae": tae,
            "plain.bin": b"plain game",
        }
        return dcx(bnd({**files, **(extra or {})}))

    game = archive(FMG_GAME, _inner(b"one", b"x"), ESD_GAME, TAE_GAME)
    a = archive({1: "ONE", 2: "two", 3: "three"}, _inner(b"ONE", b"x"), ESD_A, TAE_A, {"plain.bin": b"plain a"})
    b = archive({1: "uno", 3: "three", 4: "four"}, _inner(b"one", b"y"), ESD_B, TAE_B, {"plain.bin": b"plain b"})
    return merger.merge(game, [("a", a), ("b", b)], name="test.msgbnd.dcx")


@pytest.mark.parametrize("rule", ["bnd4", "fmg", "esd", "tae", "param"])
def test_each_rules_output_is_byte_identical_to_the_recorded_one(rule):
    assert sha(_results()[rule]) == GOLDEN[rule]


def test_a_whole_merger_run_gives_the_recorded_bytes_and_report():
    r = _whole_run()
    assert sha(r.data) == GOLDEN["merger"]
    assert sha(report(r)) == GOLDEN["merger-report"]


def test_the_outputs_do_not_depend_on_the_run():
    assert _results() == _results() and sha(_whole_run().data) == sha(_whole_run().data)
