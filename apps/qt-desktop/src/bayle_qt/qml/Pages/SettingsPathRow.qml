pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import Theme
import Components

// A Settings location row: the path field (Blank = detect), Browse..., Clear, and an overflow menu with the page twin
// of the File menu's folder opener (and, for me3, its logs, releases and "read again"). Own file so Design Studio's 2D
// view can show the page (it ignores inline components).
FormRow {
    id: pathRow

    required property var adapter
    required property string rowKey
    property var menu: []
    property string placeholder
    property string value

    Row {
        spacing: Theme.gapInline

        TextBox {
            id: field

            readonly property bool shortShown: !activeFocus && text !== ""

            color: shortShown ? "transparent" : Theme.textPrimary   // the elided copy below shows instead
            objectName: pathRow.rowKey + "Field"
            placeholderText: pathRow.placeholder
            text: pathRow.value
            width: Theme.inputW

            onEditingFinished: if (text !== pathRow.value)
                pathRow.adapter.setLocation(pathRow.rowKey, text)

            Txt {  // a long path keeps its drive and its file name; the middle is cut
                anchors.fill: parent
                anchors.leftMargin: Theme.sp10
                anchors.rightMargin: Theme.sp8
                elide: Text.ElideMiddle
                text: field.text
                verticalAlignment: Text.AlignVCenter
                visible: field.shortShown
            }
        }
        GhostButton {
            implicitHeight: Theme.controlH
            text: pathRow.adapter.words.browse

            onClicked: pathRow.adapter.browse(pathRow.rowKey)
        }
        IconButton {
            ToolTip.text: qsTr("Clear: detect it again")
            anchors.verticalCenter: parent.verticalCenter
            icon_: "Cancel"
            iconSize: 12
            implicitHeight: Theme.controlH
            implicitWidth: 32
            visible: pathRow.value !== ""

            onClicked: pathRow.adapter.clearLocation(pathRow.rowKey)
        }
        IconButton {
            id: more

            ToolTip.text: pathRow.adapter.words.more
            anchors.verticalCenter: parent.verticalCenter
            icon_: "More"
            implicitHeight: Theme.controlH
            implicitWidth: 32

            onClicked: moreMenu.open()

            PopupMenu {
                id: moreMenu

                y: more.height

                Repeater {
                    model: pathRow.menu

                    MenuEntry {
                        required property var modelData

                        enabled: modelData.enabled
                        text: modelData.label

                        onTriggered: pathRow.adapter.rowAction(pathRow.rowKey, modelData.key)
                    }
                }
            }
        }
    }
}
