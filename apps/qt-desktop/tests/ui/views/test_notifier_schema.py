"""The Qt Notifier is an adapter over the views.common schema: the dialogs get the schema's words, nothing else."""

from bayle.work.prompts import Choice, Choose, Confirm

from bayle_qt.notifications import Notifier


def test_confirm_shows_the_schema_words_and_answers_once(qt_app):
    n, shown, answers = Notifier(), [], []
    n.confirmRequested.connect(lambda *args: shown.append(args))
    words = Confirm("Rename folders?", ("a becomes b.",), "Rename", safety="Undo in Activity.")
    token = n.confirm(words, answers.append, destructive=True)
    assert shown == [(token, "Rename folders?", ["a becomes b."], "Undo in Activity.", "Rename", True)]
    n.answer(token, True)
    n.answer(token, True)
    assert answers == [True] and n.waiting() == 0


def test_choose_shows_the_schema_words(qt_app):
    n, shown, keys = Notifier(), [], []
    n.chooseRequested.connect(lambda token, words: shown.append(words))
    token = n.choose(
        Choose("Back up?", ("l1",), (Choice("go", "Go", "primary"), Choice("cancel", "Cancel"))), keys.append
    )
    assert shown[0]["choices"] == [
        {"key": "go", "label": "Go", "role": "primary"},
        {"key": "cancel", "label": "Cancel", "role": "normal"},
    ]
    n.chosen(token, "go")
    assert keys == ["go"]
