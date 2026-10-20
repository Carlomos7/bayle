pragma ComponentBehavior: Bound
import QtQuick
import Theme
import Components

// Versions (§8.10, the profile gear): the copies kept before each change to the profile, newest first, each with
// Restore (itself undoable from the toast).
ModalDialog {
    id: dlg

    required property var adapter
    property var rows: []
    readonly property var words: adapter.words

    objectName: "versionsDialog"
    preferredWidth: 560
    subtitle: words.versionsBody
    title: words.versionsTitle

    function openNow() {
        rows = adapter.versionsList();
        open();
    }

    footerRow: [
        GhostButton {
            text: dlg.words.close

            onClicked: dlg.close()
        }
    ]

    Column {
        spacing: 0
        width: parent ? parent.width : 0

        Txt {
            kind: "hint"
            text: dlg.words.noVersions
            visible: dlg.rows.length === 0
        }
        Repeater {
            id: list

            model: dlg.rows

            HoverRow {
                id: versionRow

                required property int index
                required property var modelData

                divider: index < list.count - 1
                implicitHeight: Theme.rowH
                pressable: false
                width: parent ? parent.width : 0

                Column {
                    anchors.left: parent.left
                    anchors.right: restoreBtn.left
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 2

                    Txt {
                        tabular: true
                        text: versionRow.modelData.when
                    }
                    Txt {
                        kind: "caption"
                        text: versionRow.modelData.why
                        width: parent ? parent.width : 0
                    }
                }
                GhostButton {
                    id: restoreBtn

                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    icon_: "Return"
                    implicitHeight: Theme.controlSmallH
                    text: dlg.words.restore

                    onClicked: {
                        dlg.adapter.restoreVersion(versionRow.modelData.path);
                        dlg.close();
                    }
                }
            }
        }
    }
}
