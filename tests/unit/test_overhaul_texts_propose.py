"""Proposing [[basic.texts]] from a download that ships the game's copies of a message binder and <language>.json
files (overhauls.basic.propose_texts), and what the engine does with the texts. Synthetic files only."""

import json
from pathlib import Path

import pytest
from fakegame import FMG_HEADER, bnd
from pydantic import ValidationError

from roundtable_souls import formats
from roundtable_souls.overhauls import basic
from roundtable_souls.overhauls.config import BasicText

BINDER = "settings/vanilla/msg/{lang}/menu_x.msgbnd.dcx"


def table(ids: list[int]) -> bytes:
    return formats.fmg.write_fmg(formats.fmg.Fmg(FMG_HEADER, {i: "t" for i in ids}))


def download(root: Path, tables: dict[str, list[int]], texts, langs=("engus", "rusru")) -> Path:
    """texts: the JSON content for engus.json and rusru.json (a dict, or raw text)."""
    for lang in langs:
        p = root / BINDER.format(lang=lang)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(bnd({f"msg/{lang}/{n}": table(ids) for n, ids in tables.items()}))
        raw = texts if isinstance(texts, str) else json.dumps(texts)
        (root / "settings" / f"{lang}.json").write_text(raw, encoding="utf-8")
    (root / "M.dll").write_bytes(b"d")
    return root


def texts_of(folder: Path) -> list[BasicText]:
    return basic.propose(folder, game="eldenring").texts


def test_the_table_holding_most_of_the_ids_is_proposed(tmp_path):
    ids = {"10": "a", "11": "b", "12": "c"}
    folder = download(tmp_path, {"Talk.fmg": [10, 11, 12, 99], "Other.fmg": [10], "Menu.fmg": [5]}, ids)
    (t,) = texts_of(folder)
    assert (t.file, t.table) == ("msg/{each}/menu_x.msgbnd.dcx", "talk.fmg")
    assert t.texts == {"rusru": "settings/rusru.json", "*": "settings/engus.json"}


def test_a_tie_or_no_majority_proposes_nothing(tmp_path):
    ids = {"10": "a", "11": "b", "12": "c", "13": "d"}
    assert texts_of(download(tmp_path / "tie", {"A.fmg": [10, 11, 12], "B.fmg": [10, 11, 12]}, ids)) == []
    assert texts_of(download(tmp_path / "few", {"A.fmg": [10, 11], "B.fmg": [12]}, ids)) == []


def test_ids_in_none_of_the_tables_propose_nothing(tmp_path):
    assert texts_of(download(tmp_path, {"A.fmg": [1, 2], "B.fmg": [3]}, {"50": "a"})) == []


@pytest.mark.parametrize("raw", ["{not json", "[1, 2]", '{"x": "a"}', '{"10": 5}', "{}"])
def test_malformed_json_proposes_nothing_and_does_not_crash(tmp_path, raw):
    assert texts_of(download(tmp_path, {"A.fmg": [10]}, raw)) == []


def test_without_a_default_json_only_languages_with_their_own_file_are_listed(tmp_path):
    folder = download(tmp_path, {"A.fmg": [10]}, {"10": "a"}, langs=("rusru",))
    (t,) = texts_of(folder)
    assert t.texts == {"rusru": "settings/rusru.json"}


def test_a_texts_path_must_stay_inside_the_mods_folder():
    for bad in ("../x.json", "/x.json", "C:/x.json", "a/../../x.json"):
        with pytest.raises(ValidationError):
            BasicText(file="msg/engus/m.msgbnd.dcx", table="t.fmg", texts={"*": bad})
    with pytest.raises(ValidationError):
        BasicText(file="../msg/m.msgbnd.dcx", table="t.fmg", texts={"*": "a.json"})


def test_the_texts_files_are_not_rows_of_the_files_table(tmp_path):
    from roundtable_souls.services import mod_configs

    folder = download(tmp_path, {"A.fmg": [10]}, {"10": "a"})
    b = basic.propose(folder, game="eldenring")
    names = [r["file"] for r in mod_configs.file_rows(b, folder, "eldenring")]
    assert "settings/engus.json" not in names and "settings/rusru.json" not in names


def test_the_form_shows_the_proposed_texts(tmp_path):
    from roundtable_souls.ui.pages.mod_configs.presenter import ModConfigsPresenter

    folder = download(tmp_path, {"A.fmg": [10]}, {"10": "a"})
    b = basic.propose(folder, game="eldenring")
    config = basic.make(id="m", label="M", game="eldenring", basic=b, folder=folder)
    choices = {"natives": [n.model_dump() for n in b.natives], "files": []}
    values = {"natives": choices["natives"], "files": {}}
    view = ModConfigsPresenter().overhaul(
        {"config": config, "level": "basic", "verified": False}, choices, values, [], True
    )
    (sec,) = [s for s in view["sections"] if s["title"] == "Texts"]
    (row,) = sec["rows"]
    assert row["kind"] == "readonly" and "table a.fmg" in row["label"] and "rusru: settings/rusru.json" in row["blurb"]
