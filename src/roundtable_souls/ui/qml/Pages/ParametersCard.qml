pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import Theme
import Components

// Parameters and rebuild (§8.10): the state pill, the reasons and the contributing packs, one main button labelled
// by the state (Combine / Rebuild), Undo or Redo rebuild when one can be taken back, and the overflow (keep the newest
// backups, allow the rebuild tool, details). While the game runs the state stays on the pill and the block is a line.
Card {
    id: card

    required property var adapter
    readonly property var p: adapter.parameters
    readonly property var words: adapter.words

    signal detailsRequested

    objectName: "parametersCard"
    padding: Theme.padCard

    Column {
        spacing: Theme.gapStack
        width: parent ? parent.width : 0

        Item {
            height: Theme.controlSmallH
            width: parent ? parent.width : 0

            Row {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                spacing: Theme.gapInline

                FluentIcon {
                    anchors.verticalCenter: parent.verticalCenter
                    name: "Code"
                    size: 18
                }
                Txt {
                    anchors.verticalCenter: parent.verticalCenter
                    kind: "strong"
                    text: card.words.parameters
                }
                Pill {
                    anchors.verticalCenter: parent.verticalCenter
                    icon_: card.p.level === "success" ? "Accept" : card.p.level === "danger" ? "Cancel" : "Info"
                    level: card.p.level || "muted"
                    text: card.p.pill || ""
                    visible: text !== ""
                }
            }
            GhostButton {
                id: paramsMore

                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                icon_: "More"
                implicitHeight: Theme.controlSmallH
                implicitWidth: 36
                text: ""

                onClicked: paramsMenu.open()

                PopupMenu {
                    id: paramsMenu

                    y: paramsMore.height + 4

                    MenuEntry {
                        text: card.words.keepNewest

                        onTriggered: card.adapter.trimBackups()
                    }
                    MenuEntry {
                        height: visible ? implicitHeight : 0
                        text: card.words.allowTool
                        visible: card.adapter.notices.count > 0

                        onTriggered: card.adapter.allowTool()
                    }
                    MenuSep {
                    }
                    MenuEntry {
                        icon_: "ChevronRight"
                        text: card.words.details

                        onTriggered: card.detailsRequested()
                    }
                }
            }
        }
        Repeater {
            model: card.p.reasons || []

            Txt {
                required property string modelData

                elide: Text.ElideNone
                kind: "hint"
                text: "• " + modelData
                width: parent ? parent.width : 0
                wrapMode: Text.WordWrap
            }
        }
        Row {
            spacing: Theme.sp8
            visible: (card.p.blocked || "") !== ""

            FluentIcon {
                anchors.verticalCenter: parent.verticalCenter
                color: Theme.statusWarning
                name: "Info"
                size: 13
            }
            Txt {
                anchors.verticalCenter: parent.verticalCenter
                color: Theme.statusWarning
                kind: "caption"
                text: card.p.blocked || ""
            }
        }
        Row {
            spacing: Theme.sp8

            GhostButton {  // one accent button per view is Install mod's: this one stays a ghost button
                enabled: (card.p.blocked || "") === ""
                fg: card.p.level === "warning" || card.p.level === "danger" ? Theme.accent : Theme.textPrimary
                icon_: "Sync"
                implicitHeight: Theme.controlH
                objectName: "rebuildButton"
                text: card.p.action || ""
                visible: text !== ""

                onClicked: card.adapter.rebuild()
            }
            GhostButton {
                icon_: "Return"
                implicitHeight: Theme.controlH
                text: card.adapter.rebuildUndo
                visible: text !== ""

                onClicked: card.adapter.undoRebuild()
            }
        }
    }
}
