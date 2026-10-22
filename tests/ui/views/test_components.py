"""Every component in ui/qml/Components instantiates on its own, off-screen, with no QML warning, in the dark and the
light theme: a missing import, property or asset shows here before a page uses the component."""

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine

from bayle.ui.qml_env import QML_DIR

COMPONENTS = sorted(
    line.split(" ")[0]
    for line in (QML_DIR / "Components" / "qmldir").read_text(encoding="utf-8").splitlines()[1:]
    if line.strip()
)


@pytest.mark.parametrize("dark", [True, False], ids=["dark", "light"])
@pytest.mark.parametrize("name", COMPONENTS)
def test_the_component_loads_with_no_warning(qt_app, name, dark):
    engine = QQmlEngine()
    engine.addImportPath(str(QML_DIR))
    warnings = []
    engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    component = QQmlComponent(engine)
    source = (
        "import QtQuick\nimport Theme\nimport Components\n"
        f"Item {{ width: 600; height: 400; Component.onCompleted: Theme.dark = {str(dark).lower()}\n"
        f"    {name} {{}}\n}}\n"
    )
    component.setData(source.encode(), QUrl.fromLocalFile(str(QML_DIR / "probe.qml")))
    obj = component.create()
    errors = [e.toString() for e in component.errors()]
    try:
        assert obj is not None, errors
        qt_app.processEvents()
        assert errors == [] and warnings == []
    finally:
        if obj is not None:
            obj.deleteLater()
        qt_app.processEvents()
