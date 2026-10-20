pragma ComponentBehavior: Bound
import QtQuick
import Theme
import Components

// A live save's empty slots, each a drop spot for a character (Ctrl+V pastes the copied one into the focused slot).
// The words are the adapter's ("Empty slots:" then Slot 3, Slot 4 ...).
Flow {
    id: root

    required property var adapter
    required property var card

    leftPadding: Theme.padCard
    spacing: Theme.sp8
    topPadding: Theme.sp8

    Txt {
        color: Theme.textSecondary
        kind: "hint"
        text: root.adapter.words.emptySlots
        height: 28
        verticalAlignment: Text.AlignVCenter
    }
    Repeater {
        model: root.card.freeSlots

        Rectangle {
            id: chip

            required property int modelData
            readonly property var spec: ({
                    "type": "slot",
                    "path": root.card.path,
                    "slot": modelData
                })

            activeFocusOnTab: true
            border.color: activeFocus ? Theme.accent : Theme.borderEdge
            color: "transparent"
            height: 28
            objectName: "dropEmpty_" + root.card.file + "_" + modelData
            radius: Theme.radiusCard
            width: label.implicitWidth + 2 * Theme.sp12

            Keys.onPressed: event => {
                if ((event.modifiers & Qt.ControlModifier) && event.key === Qt.Key_V) {
                    root.adapter.pasteInto(chip.spec);
                    event.accepted = true;
                }
            }

            MouseArea {
                anchors.fill: parent

                onPressed: chip.forceActiveFocus()
            }
            DropTarget {
                anchors.fill: parent
                reasonOf: p => root.adapter.dropReason(p, chip.spec)

                onDropPayload: p => root.adapter.drop(p, chip.spec)
            }
            Txt {
                id: label

                anchors.centerIn: parent
                color: Theme.textSecondary
                kind: "caption"
                text: root.adapter.words.slot + " " + chip.modelData
            }
        }
    }
}
