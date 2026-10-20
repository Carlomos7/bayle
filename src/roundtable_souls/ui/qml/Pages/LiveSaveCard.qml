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
    property Flickable scroller   // the page, for the drag's auto-scroll
    readonly property var cardSpec: ({
            "type": "card",
            "path": card.path,
            "free": card.freeSlots
        })
    readonly property var words: adapter.words

    signal nameRequested(string mode, string path)

    readonly property int listH: 240   // 6 character rows; the list scrolls when the ten slots do not fit

    implicitHeight: 64 + 32 + listH + footer.implicitHeight
    padding: 0

    DropTarget {  // the card body: a character goes into the first free slot; a copy or backup replaces the save
        anchors.fill: parent
        objectName: "dropCard_" + root.card.file
        reasonOf: p => root.adapter.dropReason(p, root.cardSpec)

        onDropPayload: p => root.adapter.drop(p, root.cardSpec)
    }
    Column {
        id: body

        width: parent ? parent.width : 0

        Item {  // the header: kind, file, the one health pill
            height: 64
            width: parent.width

            DragHandle {  // the whole save, dragged to the Library (Save a copy) or the Backups (Back up now)
                id: cardGrip

                anchors.right: pill.left
                anchors.rightMargin: Theme.sp8
                anchors.verticalCenter: parent.verticalCenter
                implicitHeight: 40
                label: root.card.kind + "  ·  " + root.card.file
                objectName: "dragLive_" + root.card.file
                payload: ({
                        "type": "live",
                        "path": root.card.path
                    })
                scroller: root.scroller
                visible: !root.locked
            }
            Column {
                anchors.left: parent.left
                anchors.leftMargin: Theme.padCard
                anchors.right: cardGrip.visible ? cardGrip.left : pill.left
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
            kind: "hint"
            leftPadding: Theme.padCard
            rightPadding: Theme.padCard
            elide: Text.ElideRight
            height: text !== "" ? 32 : 0   // no empty band; the list takes the room instead
            maximumLineCount: 2
            text: root.card.error !== "" ? root.card.error : root.card.contents
            verticalAlignment: Text.AlignVCenter
            visible: text !== ""
            width: parent.width
            wrapMode: Text.WordWrap
        }
        ListView {  // all ten slots, empty ones too (they are where a character can be dropped or copied to)
            id: slotList

            activeFocusOnTab: true
            boundsBehavior: Flickable.StopAtBounds
            clip: true
            height: root.listH + (root.card.error !== "" || root.card.contents !== "" ? 0 : 32)
            highlight: Rectangle {  // the keyboard focus ring
                border.color: Theme.accent
                border.width: 2
                color: "transparent"
                visible: slotList.activeFocus
            }
            highlightMoveDuration: 0
            keyNavigationEnabled: true
            model: root.card.slots
            objectName: "slotList"
            width: parent.width
            Accessible.name: root.card.kind

            Keys.onPressed: event => {
                const cur = root.card.slots[slotList.currentIndex];
                if ((event.modifiers & Qt.ControlModifier) && cur) {   // Ctrl+C on a character, Ctrl+V on a slot
                    if (event.key === Qt.Key_C && !cur.empty && root.card.canCopyCharacters) {
                        root.adapter.copyCharacterKey(root.card.path, cur.slot);
                        event.accepted = true;
                    } else if (event.key === Qt.Key_V) {
                        root.adapter.pasteInto({
                            "type": "slot",
                            "path": root.card.path,
                            "slot": cur.slot
                        });
                        event.accepted = true;
                    }
                }
                if (event.key === Qt.Key_PageDown || event.key === Qt.Key_PageUp) {
                    slotList.contentY = Math.max(0, Math.min(slotList.contentHeight - slotList.height, slotList.contentY + (event.key === Qt.Key_PageDown ? 1 : -1) * slotList.height));
                    event.accepted = true;
                }
            }
            ScrollBar.vertical: ScrollBar {
                policy: slotList.contentHeight > slotList.height ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff   // the cue that more slots are below
                width: 8
            }
            delegate: HoverRow {
                id: row

                readonly property bool isEmpty: modelData.empty
                readonly property int slotNumber: modelData.slot
                readonly property var slotSpec: ({
                        "type": "slot",
                        "path": root.card.path,
                        "slot": modelData.slot
                    })

                required property int index
                required property var modelData

                divider: true
                implicitHeight: isEmpty ? 32 : Theme.rowH
                objectName: "slotRow_" + modelData.slot
                pressable: !isEmpty
                width: slotList.width

                onClicked: {
                    if (!isEmpty)
                        root.adapter.openSheet(root.card.path, row.modelData.slot);
                }

                DropTarget {  // this slot (empty, or the character in it is replaced after the usual confirmation)
                    anchors.fill: parent
                    anchors.leftMargin: -row.padding
                    anchors.rightMargin: -row.padding
                    objectName: "dropSlot_" + root.card.file + "_" + row.modelData.slot
                    radius: 0
                    reasonOf: p => root.adapter.dropReason(p, row.slotSpec)

                    onDropPayload: p => root.adapter.drop(p, row.slotSpec)
                }
                DragHandle {
                    id: rowGrip

                    anchors.left: parent.left
                    anchors.leftMargin: -Theme.sp8
                    implicitHeight: row.height
                    label: row.modelData.name + "  ·  " + row.modelData.levelText
                    objectName: "dragChar_" + root.card.file + "_" + row.modelData.slot
                    payload: ({
                            "type": "character",
                            "path": root.card.path,
                            "slot": row.modelData.slot
                        })
                    scroller: root.scroller
                    visible: !row.isEmpty && !root.locked && root.card.canCopyCharacters && row.modelData.runes !== ""
                }
                Txt {
                    id: slotText

                    anchors.left: rowGrip.visible ? rowGrip.right : parent.left
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
                    color: row.isEmpty ? Theme.textSecondary : Theme.textPrimary
                    kind: row.isEmpty ? "caption" : "rowTitle"
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
                    visible: !row.isEmpty

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
            }        }
        Row {  // the footer
            id: footer

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
