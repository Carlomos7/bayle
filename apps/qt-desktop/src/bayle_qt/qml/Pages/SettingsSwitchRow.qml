pragma ComponentBehavior: Bound
import QtQuick
import Theme
import Components

// A Settings switch: the title and its one-line blurb on the left, the longer help in the (?) tooltip. A row whose
// `shown` is false (the overhaul switch for a game with none) takes no room.
FormRow {
    id: row

    required property var adapter
    required property var model

    help: model.blurb
    showHelpIcon: true
    title: model.title
    tooltip: model.help
    visible: model.shown

    ToggleSwitch {
        objectName: row.model.key + "Switch"
        checked: row.model.checked

        onToggled: row.adapter.setSwitch(row.model.key, checked)
    }
}
