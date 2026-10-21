"""MarkdownView formats Markdown (a heading is a heading, not "# text"); a plain text file is not formatted."""

from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine

from roundtable_souls.ui.qml_env import QML_DIR


def _size(engine, text, markdown):
    component = QQmlComponent(engine)
    component.setData(
        (
            "import QtQuick\nimport Theme\nimport Components\n"
            f"MarkdownView {{ width: 400; markdown: {str(markdown).lower()}; text: {text!r} }}"
        ).encode(),
        QUrl.fromLocalFile(str(QML_DIR / "probe.qml")),
    )
    obj = component.create()
    assert obj is not None, [e.toString() for e in component.errors()]
    return obj.property("contentHeight"), obj.property("contentWidth")


def test_a_heading_renders_as_a_heading_and_plain_text_is_not_formatted(qt_app):
    engine = QQmlEngine()
    engine.addImportPath(str(QML_DIR))
    heading_h, _ = _size(engine, "# Title", True)
    body_h, _ = _size(engine, "Title", True)
    assert heading_h > body_h  # set larger than body text
    raw_h, _ = _size(engine, "# Title", False)
    assert raw_h < heading_h  # as plain text, "# Title" stays one body-size line
