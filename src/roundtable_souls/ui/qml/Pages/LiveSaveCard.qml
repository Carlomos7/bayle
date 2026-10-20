pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import Theme
import Components

// One live save (Standard or Seamless Co-op) of the Saves page: the kind and file, one health pill, the characters
// (a mark only on a slot with a finding), and the footer: Check & repair (accent only when a repair exists) and the
// overflow with the operations on this file. A character's menu copies it into any slot of any live save. Everything
// shown and every word comes from the adapter (ui/pages/saves/adapter.py).
Card {
    id: root

    required property var adapter
    required property var card
    readonly property bool locked: adapter.running
    readonly property var words: adapter.words

    signal nameRequested(string mode, string path)

    implicitHeight: body.implicitHeight
    padding: 0

    Column {
        id: body

        width: parent ? parent.width : 0

        Item {  // the header: kind, file, the one health pill
            height: 64
            width: parent.width

            Column {
                anchors.left: parent.left
                anchors.leftMargin: Theme.padCard
                anchors.right: pill.left
                anchors.rightMargin: Theme.sp12
                anchors.verticalCenter: parent.verticalCenter
                spacing: Theme.sp2

                Txt {
                    kind: "section"
                    text: root.card.kind
                    width: parent.width
                }
                Txt {
                    kind: "hint"
                    text: root.card.file + "  ·  " + root.card.modified + (root.card.role !== "" ? "  ·  " + root.card.role : "")
                    width: parent.width
                }
            }
            Pill {
                id: pill

                anchors.right: parent.right
                anchors.rightMargin: Theme.padCard
                anchors.verticalCenter: parent.verticalCenter
                filled: true
                level: root.card.healthLevel
                text: root.card.health
            }
        }
        Txt {  // what is wrong with the file as a whole, in words (the details are in Check & repair)
            color: Theme.textSecondary
            elide: Text.ElideNone
            kind: "hint"
            leftPadding: Theme.padCard
            rightPadding: Theme.padCard
            text: root.card.error !== "" ? root.card.error : root.card.contents
            visible: text !== ""
            width: parent.width
            wrapMode: Text.WordWrap
        }
        Repeater {
            model: root.card.characters

            HoverRow {
                id: row

                required property int index
                required property var modelData

                divider: true
                width: body.width

                onClicked: root.adapter.openSheet(root.card.path, row.modelData.slot)

                Txt {
                    id: slotText

                    anchors.verticalCenter: parent.verticalCenter
                    color: Theme.textSecondary
                    kind: "caption"
                    text: row.modelData.slot
                    width: 20
                }
                Txt {
                    anchors.left: slotText.right
                    anchors.right: meta.left
                    anchors.rightMargin: Theme.sp8
                    anchors.verticalCenter: parent.verticalCenter
                    kind: "rowTitle"
                    text: row.modelData.name
                }
                Row {
                    id: meta

                    anchors.right: more.left
                    anchors.rightMargin: Theme.sp8
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: Theme.sp12

                    Pill {
                        anchors.verticalCenter: parent.verticalCenter
                        level: "warning"
                        text: row.modelData.mark
                        visible: row.modelData.mark !== ""
                    }
                    Txt {
                        anchors.verticalCenter: parent.verticalCenter
                        color: Theme.textSecondary
                        kind: "caption"
                        text: row.modelData.levelText + (row.modelData.runes !== "" ? "  ·  " + row.modelData.runes : "")
                        width: implicitWidth
                    }
                }
                IconButton {
                    id: more

                    ToolTip.text: root.words.copyTo
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    enabled: !root.locked && root.card.canCopyCharacters && row.modelData.runes !== ""
                    icon_: "More"

                    onClicked: charMenu.popup()

                    PopupMenu {
                        id: charMenu

                        Repeater {
                            model: more.enabled ? root.adapter.copyTargets(root.card.path, row.modelData.slot) : []

                            MenuEntry {
                                id: target

                                required property var modelData

                                text: modelData.label

                                onTriggered: root.adapter.copyCharacter(root.card.path, row.modelData.slot, target.modelData.path, target.modelData.slot)
                            }
                        }
                    }
                }
            }
        }
        Txt {  // the empty slots, as targets
            color: Theme.textTertiary
            kind: "hint"
            leftPadding: Theme.padCard
            text: root.words.emptySlots + " " + root.card.freeSlots.join(", ")
            topPadding: Theme.sp8
            visible: root.card.freeSlots.length > 0 && root.card.characters.length > 0
            width: parent.width
        }
        Row {  // the footer
            bottomPadding: Theme.padCard
            leftPadding: Theme.padCard
            spacing: Theme.sp8
            topPadding: Theme.sp12

            PrimaryButton {
                text: root.words.checkRepair
                visible: root.card.canRepair

                onClicked: root.adapter.openRepair(root.card.path)
            }
            GhostButton {
                icon_: "Info"
                text: root.words.checkRepair
                visible: !root.card.canRepair

                onClicked: root.adapter.openRepair(root.card.path)
            }
            GhostButton {
                id: menuButton

                ToolTip.text: root.words.operations
                icon_: "More"
                implicitWidth: 40
                text: ""

                onClicked: menu.popup()

                PopupMenu {
                    id: menu

                    MenuEntry {
                        enabled: !root.locked
                        icon_: "Save"
                        text: root.words.backUpNow

                        onTriggered: root.adapter.backUpNow(root.card.path)
                    }
                    MenuEntry {
                        enabled: !root.locked
                        icon_: "Add"
                        text: root.words.saveCopy

                        onTriggered: root.nameRequested("copy", root.card.path)
                    }
                    MenuEntry {
                        enabled: !root.locked
                        icon_: "Download"
                        text: root.words.replaceWith

                        onTriggered: root.adapter.replaceFromFile(root.card.path)
                    }
                    PopupMenu {
                        title: root.words.replaceLibrary

                        Repeater {
                            model: root.adapter.libraryRows.slice(0, 8)

                            MenuEntry {
                                id: copyEntry

                                required property var modelData

                                enabled: !root.locked && !modelData.missing && !modelData.stranded
                                text: modelData.name

                                onTriggered: root.adapter.replaceFromLibrary(copyEntry.modelData.folder, copyEntry.modelData.id, root.card.path)
                            }
                        }
                    }
                    MenuSep {
                    }
                    MenuEntry {
                        icon_: "Copy"
                        text: root.words.copyReport

                        onTriggered: root.adapter.copyReport(root.card.path)
                    }
                    MenuEntry {
                        icon_: "Folder"
                        text: root.words.openFolder

                        onTriggered: root.adapter.openFolder(root.card.path)
                    }
                }
            }
        }
    }
}
