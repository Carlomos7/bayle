"""The game-level checks on a combined regulation (backlog P1, P2, P8): what the game would not read is reported,
what it could not take is refused. Small regulation files built here."""

import pytest
from test_param_merge import pack, regulation, row, rows_of, table, vanilla

from roundtable_souls import formats
from roundtable_souls.merging.rules import param as pm


def test_a_table_the_game_does_not_know_is_reported_by_the_pack_that_adds_it():
    extra = regulation(
        {
            "EquipParamWeapon": table("EQUIP_PARAM_WEAPON_ST", [(1000, row(1, 2, 3, 4)), (2000, row(5, 6, 7, 8))]),
            "SpEffectParam": table("SP_EFFECT_PARAM_ST", [(10, row(9, 9, 9, 9))]),
            "ModOnlyParam": table("MOD_ONLY_ST", [(1, row(1))]),
        }
    )
    out, rep = pm.combine(vanilla(), [("x", extra)])
    assert set(rows_of(out, "ModOnlyParam")) == {1}  # still taken, as before
    assert rep.packs[0].warnings == ["x adds ModOnlyParam, which the game does not read"]
    assert "  warning: x adds ModOnlyParam, which the game does not read" in rep.lines()


def test_rows_with_negative_ids_are_reported():
    def add(p):
        p.rows.append(formats.param.Row(0xFFFFFFFF, row(1), ""))
        p.rows.append(formats.param.Row(0x80000000, row(2), ""))

    out, rep = pm.combine(vanilla(), [("neg", pack({"SpEffectParam": add}))])
    assert set(rows_of(out, "SpEffectParam")) == {10, 0xFFFFFFFF, 0x80000000}
    assert rep.packs[0].warnings == [
        "neg sets 2 rows of SpEffectParam with a negative ID (-1, -2147483648), which the game's lookup never finds"
    ]


def test_more_rows_than_the_game_can_count_is_refused(monkeypatch):
    assert pm.MAX_ROWS == 65_535  # the game's row count is 16 bits
    monkeypatch.setattr(pm, "MAX_ROWS", 4)  # the limit, made small: adding 65,536 rows here takes minutes

    def grow(first):
        def fn(p):
            p.rows += [formats.param.Row(first + i, row(i), "") for i in range(2)]

        return fn

    packs = [("a", pack({"SpEffectParam": grow(100_000)})), ("b", pack({"SpEffectParam": grow(200_000)}))]
    with pytest.raises(pm.TableLimit, match=r"SpEffectParam would have 5 rows; the game reads at most 4 per table"):
        pm.combine(vanilla(), packs)
    pm.combine(vanilla(), packs[:1])  # 3 rows: within the limit


def test_a_result_missing_one_of_the_games_tables_is_refused(monkeypatch):
    real = pm.missing_tables
    base = formats.regulation.read_regulation(vanilla())
    names = [e.name or "" for e in base.bnd.entries]
    assert real(names, base.bnd) == []
    base.bnd.entries = [e for e in base.bnd.entries if "SpEffectParam" not in (e.name or "")]
    assert real(names, base.bnd) == ["SpEffectParam"]
    monkeypatch.setattr(pm, "missing_tables", lambda _names, _built: ["KeyAssignParam_TypeA"])
    with pytest.raises(pm.TableLimit, match="lacks KeyAssignParam_TypeA, which the game's own regulation has"):
        pm.combine(vanilla(), [("x", pack({"SpEffectParam": lambda p: None}))])
