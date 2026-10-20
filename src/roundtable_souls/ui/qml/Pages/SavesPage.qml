pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import Theme
import Components

// Saves (technical specification §8.10): which file Play uses, the two live saves (Standard first) with their
// characters, and below them the saved copies (Library and Backups). The five operations: copy a character into a
// slot, replace a live save with a file, save a copy, back up now, import a file; Check & repair opens beside the
// page, the character sheet (read-only) too. Side by side only when each card gets 460 px, else stacked. Nothing is
// written while the game runs. Everything shown and every word comes from the adapter.
PageScroll {
    id: page

    required property var adapter
    readonly property int cardMinW: 460
    readonly property int columnWidth: Math.min(width - sideMargin * 2, maxContentWidth)
    readonly property bool wide: columnWidth >= cardMinW * 2 + Theme.sp20
    readonly property var words: adapter.words

    function askName(mode, path) {
        nameDialog.ask(mode, path, "", "");
    }

    objectName: "savesPage"

    Component.onCompleted: page.adapter.refresh()

    Connections {
        function onImportNameRequested(path, name) {
            nameDialog.ask("import", path, "", name);
        }
        function onNameAsked(mode, path) {   // a live save dropped on the Library: the same name dialog as the menu
            page.askName(mode, path);
        }

        target: page.adapter
    }
    DropArea {  // a file dropped from Explorer: import (operation 5)
        anchors.fill: parent
        keys: ["text/uri-list"]
        parent: page

        onDropped: drop => {
            if (drop.hasUrls)
                page.adapter.dropFiles(drop.urls.map(u => String(u)));
        }
    }
    InfoBar {
        closable: false
        open: page.adapter.running
        severity: "warning"
        text: page.adapter.runningBar
        width: parent.width
    }
    Item {  // the header line and the overflow
        height: Theme.controlH
        width: parent.width

        Txt {
            anchors.left: parent.left
            anchors.right: acts.left
            anchors.rightMargin: Theme.sp12
            anchors.verticalCenter: parent.verticalCenter
            elide: Text.ElideRight
            text: page.adapter.encrypted ? page.words.nightreign : page.adapter.header
        }
        GhostButton {
            id: acts

            ToolTip.text: page.words.operations
            anchors.right: parent.right
            icon_: "More"
            implicitWidth: 40
            text: ""

            onClicked: headerMenu.popup()

            PopupMenu {
                id: headerMenu

                MenuEntry {
                    enabled: !page.adapter.running
                    icon_: "Download"
                    text: page.words.importAction

                    onTriggered: page.adapter.pickImport()
                }
                MenuEntry {
                    enabled: !page.adapter.running
                    icon_: "Play"
                    text: page.words.postSession

                    onTriggered: page.adapter.postSessionRepair()
                }
            }
        }
    }
    Txt {
        color: Theme.textSecondary
        elide: Text.ElideNone
        kind: "hint"
        text: page.adapter.loading ? page.words.reading : page.words.noSaves
        visible: page.adapter.cards.length === 0
        width: parent.width
        wrapMode: Text.WordWrap
    }
    Grid {
        id: cardGrid

        columnSpacing: Theme.sp20
        columns: page.wide ? 2 : 1
        rowSpacing: Theme.sp20
        width: parent.width

        Repeater {
            model: page.adapter.cards

            LiveSaveCard {
                required property var modelData

                adapter: page.adapter
                card: modelData
                scroller: page
                width: page.wide ? Math.floor((cardGrid.width - cardGrid.columnSpacing) / 2) : cardGrid.width

                onNameRequested: (mode, path) => page.askName(mode, path)
            }
        }
    }
    SavedCopies {
        adapter: page.adapter
        scroller: page
        visible: page.adapter.cards.length > 0
        width: parent.width

        onNameRequested: (mode, path) => page.askName(mode, path)
        onRenameRequested: (folder, id, name) => nameDialog.ask("rename", folder, id, name)
    }
    CharacterSheet {
        adapter: page.adapter
        parent: page
    }
    SaveRepairPage {
        adapter: page.adapter
        parent: page
    }
    NameDialog {
        id: nameDialog

        adapter: page.adapter
    }
}
