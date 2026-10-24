"""RowsModel.set_rows tells the views as little as it can: nothing for the same rows, dataChanged for the rows that
differ when the count is the same, a reset otherwise (a reset rebuilds every delegate)."""

from bayle_qt.models import RowsModel


def watch(model: RowsModel) -> list:
    seen: list = []
    model.modelReset.connect(lambda: seen.append("reset"))
    model.dataChanged.connect(lambda a, b, *_: seen.append((a.row(), b.row())))
    return seen


def test_the_same_rows_tell_nothing():
    m = RowsModel(("a",))
    m.set_rows([{"a": 1}, {"a": 2}])
    seen = watch(m)
    m.set_rows([{"a": 1}, {"a": 2}])
    assert seen == []


def test_the_same_count_tells_only_the_rows_that_differ():
    m = RowsModel(("a",))
    m.set_rows([{"a": i} for i in range(6)])
    seen = watch(m)
    m.set_rows([{"a": 0}, {"a": 9}, {"a": 9}, {"a": 3}, {"a": 4}, {"a": 9}])
    assert seen == [(1, 2), (5, 5)]
    assert [r["a"] for r in m.rows()] == [0, 9, 9, 3, 4, 9]


def test_another_count_resets():
    m = RowsModel(("a",))
    m.set_rows([{"a": 1}])
    seen = watch(m)
    m.set_rows([{"a": 1}, {"a": 2}])
    assert seen == ["reset"] and m.count == 2
