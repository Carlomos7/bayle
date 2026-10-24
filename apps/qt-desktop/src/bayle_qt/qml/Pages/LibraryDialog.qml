pragma ComponentBehavior: Bound
import QtQuick
import Theme
import Components

// Library: the game-file mods that several profiles use from one copy. Each mod lists its versions as "Installed
// <date>" (with the label when it has one), the size and who uses it; Remove unused versions deletes the ones nobody
// uses, after a confirm. A version's id is never shown.
ModalDialog {
    id: dlg

    required property var adapter
    property var rows: []
    readonly property var words: adapter.words

    objectName: "libraryDialog"
    preferredWidth: 600
    subtitle: words.libraryBody
    title: words.libraryTitle

    function openNow() {
        rows = adapter.libraryList();
        open();
    }

    footerRow: [
        GhostButton {
            objectName: "libraryRemoveUnused"
            text: dlg.words.removeUnused
            visible: dlg.rows.length > 0

            onClicked: {
                dlg.close();
                dlg.adapter.removeUnused();
            }
        },
        GhostButton {
            text: dlg.words.close

            onClicked: dlg.close()
        }
    ]

    Column {
        spacing: Theme.sp12
        width: parent ? parent.width : 0

        Txt {
            kind: "hint"
            text: dlg.words.libraryEmpty
            visible: dlg.rows.length === 0
            width: parent.width
            wrapMode: Text.WordWrap
        }
        Repeater {
            model: dlg.rows

            Column {
                id: modBlock

                required property var modelData

                spacing: 2
                width: parent ? parent.width : 0

                Row {
                    spacing: Theme.sp8

                    Txt {
                        kind: "rowTitle"
                        text: modBlock.modelData.name
                    }
                    Txt {
                        anchors.baseline: parent.children[0].baseline
                        kind: "caption"
                        text: modBlock.modelData.size
                    }
                }
                Repeater {
                    model: modBlock.modelData.versions

                    Row {
                        id: ver

                        required property var modelData

                        spacing: Theme.sp8
                        width: parent ? parent.width : 0

                        Txt {
                            kind: "caption"
                            text: ver.modelData.title + "  ·  " + ver.modelData.size
                        }
                        Txt {
                            color: ver.modelData.unused ? Theme.statusWarning : Theme.textSecondary
                            kind: "caption"
                            text: ver.modelData.usedBy
                        }
                    }
                }
            }
        }
    }
}
