pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import Theme
import Components

// The character sheet, read-only (S9; the editor is S9b): Overview (where, runes, what the slot needs) and Stats (the
// eight attributes with bars to 99, the level they add up to, and what the save stores for HP, FP and stamina).
// Journey, playtime and last played are not shown: the game-model could not verify where the save keeps them.
SidePanel {
    id: root

    required property var adapter
    readonly property var sheet: adapter.sheet
    property int tab: 0
    readonly property var words: adapter.words

    function pair(label, value) {
        return {
            "label": label,
            "value": value
        };
    }

    panelWidth: 460
    title: root.sheet.name !== undefined ? root.sheet.name : ""

    Column {
        spacing: Theme.sp16
        width: parent ? parent.width : 0

        Row {
            spacing: Theme.sp12

            TabRow {
                current: root.tab
                tabs: [root.words.overview, root.words.stats]

                onCurrentChanged: root.tab = current
            }
            GhostButton {
                ToolTip.text: root.words.sheetReadOnly
                ToolTip.visible: hovered || visualFocus
                enabled: false
                icon_: "Edit"
                text: root.words.edit
            }
        }
        Txt {
            color: Theme.textSecondary
            elide: Text.ElideNone
            kind: "hint"
            text: root.words.sheetReadOnly
            width: parent.width
            wrapMode: Text.WordWrap
        }
        Column {  // Overview
            spacing: Theme.sp8
            visible: root.tab === 0
            width: parent.width

            Repeater {
                model: root.sheet.name === undefined ? [] : [root.pair(root.words.level, root.sheet.level), root.pair(root.words.body, root.sheet.body), root.pair(root.words.where, root.sheet.where), root.pair(root.words.torrent, root.sheet.torrent), root.pair(root.words.runesHeld, root.sheet.runes), root.pair(root.words.runesMemory, root.sheet.memory), root.pair(root.words.modItems, root.sheet.mods !== "" ? root.sheet.mods : root.words.none)]

                Row {
                    id: fact

                    required property var modelData

                    spacing: Theme.sp12

                    Txt {
                        color: Theme.textSecondary
                        text: fact.modelData.label
                        width: 130
                    }
                    Txt {
                        elide: Text.ElideNone
                        text: String(fact.modelData.value)
                        width: Math.max(80, (fact.parent ? fact.parent.width : 300) - 130 - Theme.sp12)
                        wrapMode: Text.WordWrap
                    }
                }
            }
            Repeater {  // what this slot needs, with the way to Check & repair
                model: root.sheet.findings !== undefined ? root.sheet.findings : []

                Row {
                    id: need

                    required property var modelData

                    spacing: Theme.sp8

                    Pill {
                        level: "warning"
                        text: need.modelData.title + "  ·  " + need.modelData.count
                    }
                    GhostButton {
                        implicitHeight: 20
                        text: root.words.checkRepair

                        onClicked: {
                            root.adapter.closeSheet();
                            root.adapter.openRepair(root.sheet.path);
                            root.adapter.pickRepairSlot(root.sheet.slot - 1);
                        }
                    }
                }
            }
        }
        Column {  // Stats
            spacing: Theme.sp8
            visible: root.tab === 1
            width: parent.width

            Repeater {
                model: root.sheet.attributes !== undefined ? root.sheet.attributes : []

                Row {
                    id: attr

                    required property var modelData

                    spacing: Theme.sp12

                    Txt {
                        text: attr.modelData.label
                        width: 110
                    }
                    Txt {
                        horizontalAlignment: Text.AlignRight
                        tabular: true
                        text: attr.modelData.value
                        width: 30
                    }
                    Rectangle {  // a bar to 99
                        anchors.verticalCenter: parent.verticalCenter
                        color: Theme.dark ? Qt.rgba(1, 1, 1, 0.06) : Qt.rgba(0, 0, 0, 0.06)
                        height: 6
                        radius: 3
                        width: 180

                        Rectangle {
                            color: Theme.statBar
                            height: parent.height
                            radius: 3
                            width: Math.round(parent.width * Math.min(attr.modelData.value, 99) / 99)
                        }
                    }
                }
            }
            Txt {
                color: Theme.textSecondary
                text: root.sheet.levelFromAttributes !== undefined ? root.words.levelFrom.replace("{n}", root.sheet.levelFromAttributes) : ""
                topPadding: Theme.sp8
            }
            Txt {
                color: Theme.textSecondary
                kind: "caption"
                text: root.words.atLastSave
                topPadding: Theme.sp8
            }
            Repeater {
                model: root.sheet.derived !== undefined ? root.sheet.derived : []

                Row {
                    id: derived

                    required property var modelData

                    spacing: Theme.sp12

                    Txt {
                        color: Theme.textSecondary
                        text: derived.modelData.label
                        width: 110
                    }
                    Txt {
                        tabular: true
                        text: derived.modelData.value
                    }
                }
            }
        }
    }
    onOpenChanged: {
        if (!open && adapter.sheetOpen)
            adapter.closeSheet();
    }

    Connections {
        function onSheetChanged() {
            root.open = root.adapter.sheetOpen;
        }

        target: root.adapter
    }
}
