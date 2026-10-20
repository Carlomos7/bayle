pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import Theme
import Components

// Check & repair for one save (the sub-page; Esc or Back closes it): a character picker, then the findings in cards,
// "May not load" first. The safe items start ticked; the footer says what the ticked boxes do and the button repairs
// them, after one more confirmation. Everything shown and every word comes from the adapter.
SidePanel {
    id: root

    required property var adapter
    readonly property var card: adapter.repairCard
    readonly property var words: adapter.words

    onOpenChanged: {
        if (!open && adapter.repairOpen)
            adapter.closeRepair();
    }
    panelWidth: 640
    title: root.words.checkRepair + (root.card.file !== undefined ? "  ·  " + root.card.file : "")

    Shortcut {
        enabled: root.open
        sequences: ["Escape"]

        onActivated: root.adapter.closeRepair()
    }
    Connections {
        function onRepairChanged() {
            root.open = root.adapter.repairOpen;
        }

        target: root.adapter
    }
    Column {
        spacing: Theme.sp16
        width: parent ? parent.width : 0

        DropButton {  // the character picker: the whole file, or one character
            fixedWidth: Theme.pickerW
            implicitHeight: Theme.controlH
            text: root.adapter.repairSlot < 0 ? root.words.wholeFile : (root.card.characters !== undefined ? root.card.characters.filter(c => c.slot - 1 === root.adapter.repairSlot).map(c => c.name).join("") : "")
            visible: root.card.characters !== undefined && root.card.characters.length > 1

            MenuEntry {
                checked: root.adapter.repairSlot < 0
                text: root.words.wholeFile

                onTriggered: root.adapter.pickRepairSlot(-1)
            }
            Repeater {
                model: root.card.characters !== undefined ? root.card.characters : []

                MenuEntry {
                    id: pick

                    required property var modelData

                    checked: root.adapter.repairSlot === modelData.slot - 1
                    text: modelData.name

                    onTriggered: root.adapter.pickRepairSlot(pick.modelData.slot - 1)
                }
            }
        }
        Repeater {  // a file that could not be read
            model: root.adapter.repairDamaged

            InfoBar {
                required property var modelData

                closable: false
                severity: "error"
                text: modelData.title + ". " + modelData.detail + " " + root.words.damagedHint
                width: parent ? parent.width : 0
            }
        }
        Txt {
            elide: Text.ElideNone
            kind: "hint"
            text: root.words.nothingToFix
            visible: root.adapter.repairGroups.length === 0 && root.adapter.repairDamaged.length === 0
            width: parent.width
        }
        Repeater {
            model: root.adapter.repairGroups

            Card {
                id: group

                required property var modelData

                width: parent.width

                Column {
                    spacing: Theme.sp8
                    width: parent.width

                    Row {
                        spacing: Theme.sp8

                        Txt {
                            kind: "section"
                            text: group.modelData.title
                        }
                        GhostButton {
                            implicitHeight: 24
                            text: root.words.all

                            onClicked: root.adapter.setGroup(group.modelData.id, true)
                        }
                        GhostButton {
                            implicitHeight: 24
                            text: root.words.none

                            onClicked: root.adapter.setGroup(group.modelData.id, false)
                        }
                    }
                    Txt {
                        color: Theme.textSecondary
                        elide: Text.ElideNone
                        kind: "hint"
                        text: group.modelData.hint
                        width: parent.width
                        wrapMode: Text.WordWrap
                    }
                    Repeater {
                        model: group.modelData.items

                        Column {
                            id: item

                            required property var modelData

                            width: parent.width

                            CheckRow {
                                checked: item.modelData.checked
                                enabled: item.modelData.enabled
                                text: item.modelData.label
                                width: parent.width

                                onToggled: root.adapter.setTick(item.modelData.key, checked)
                            }
                            Txt {
                                color: item.modelData.note !== "" ? Theme.statusDanger : Theme.textSecondary
                                kind: "caption"
                                leftPadding: 30
                                text: item.modelData.note !== "" ? item.modelData.note : item.modelData.sub
                                visible: text !== ""
                                width: parent.width
                            }
                        }
                    }
                }
            }
        }
        Txt {  // what the ticked boxes do
            color: Theme.textSecondary
            elide: Text.ElideNone
            kind: "hint"
            text: root.adapter.repairSummary
            width: parent.width
            wrapMode: Text.WordWrap
        }
        Row {
            spacing: Theme.sp8

            PrimaryButton {
                enabled: root.adapter.repairCount > 0 && !root.adapter.running
                text: root.adapter.repairButton

                onClicked: root.adapter.applyRepair()
            }
            GhostButton {
                text: root.words.back

                onClicked: root.adapter.closeRepair()
            }
        }
    }
}
