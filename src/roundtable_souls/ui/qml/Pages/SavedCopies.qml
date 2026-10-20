pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import Theme
import Components

// Saved copies: the Library (whole files kept under a name) and the Backups (taken before every change, grouped by
// day with what triggered each). A row's menu replaces a live save with it, or keeps / renames / removes it. Every
// word comes from the adapter (ui/pages/saves/adapter.py).
Column {
    id: root

    required property var adapter
    property int tab: 0
    readonly property var words: adapter.words

    signal nameRequested(string mode, string path)
    signal renameRequested(string folder, string id, string name)

    spacing: Theme.sp12

    Row {
        spacing: Theme.sp16
        width: parent.width

        Txt {
            anchors.verticalCenter: parent.verticalCenter
            kind: "section"
            text: root.words.copies
        }
        TabRow {
            current: root.tab
            tabs: [root.words.library, root.words.backups]

            onCurrentChanged: root.tab = current
        }
    }
    Repeater {  // a Library file that cannot be read
        model: root.tab === 0 ? root.adapter.libraryProblems : []

        InfoBar {
            required property string modelData

            closable: false
            severity: "warning"
            text: modelData
            width: root.width
        }
    }
    Card {  // the Library
        padding: 0
        visible: root.tab === 0
        width: parent.width

        Column {
            width: parent.width

            Txt {
                leftPadding: Theme.padCard
                text: root.words.noLibrary
                topPadding: Theme.sp16
                bottomPadding: Theme.sp16
                visible: root.adapter.libraryRows.length === 0
                width: parent.width
                wrapMode: Text.WordWrap
                kind: "hint"
            }
            Repeater {
                model: root.adapter.libraryRows

                HoverRow {
                    id: libRow

                    required property int index
                    required property var modelData

                    divider: true
                    height: 56
                    pressable: false
                    width: parent.width

                    Column {
                        anchors.left: parent.left
                        anchors.right: libActions.left
                        anchors.rightMargin: Theme.sp8
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: Theme.sp2

                        Row {
                            spacing: Theme.sp8

                            Txt {
                                kind: "rowTitle"
                                text: libRow.modelData.name
                                width: Math.min(implicitWidth, libRow.width - 260)
                            }
                            Pill {
                                anchors.verticalCenter: parent.verticalCenter
                                text: libRow.modelData.tag
                            }
                        }
                        Txt {
                            color: libRow.modelData.note !== "" ? Theme.statusWarning : Theme.textSecondary
                            kind: "caption"
                            text: (libRow.modelData.note !== "" ? libRow.modelData.note : libRow.modelData.who + "  ·  " + libRow.modelData.when)
                            width: parent.width
                        }
                    }
                    Row {
                        id: libActions

                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: Theme.sp4

                        GhostButton {
                            text: root.words.putBack
                            visible: libRow.modelData.stranded

                            onClicked: root.adapter.finishStranded(libRow.modelData.folder, libRow.modelData.id, true)
                        }
                        GhostButton {
                            text: root.words.finish
                            visible: libRow.modelData.stranded

                            onClicked: root.adapter.finishStranded(libRow.modelData.folder, libRow.modelData.id, false)
                        }
                        IconButton {
                            ToolTip.text: root.words.copyActions
                            icon_: "More"
                            visible: !libRow.modelData.stranded

                            onClicked: libMenu.popup()

                            PopupMenu {
                                id: libMenu

                                Repeater {
                                    model: root.adapter.cards

                                    MenuEntry {
                                        id: replaceEntry

                                        required property var modelData

                                        enabled: !root.adapter.running && !libRow.modelData.missing
                                        icon_: "Download"
                                        text: root.words.replaceKind.replace("{kind}", modelData.kind)

                                        onTriggered: root.adapter.replaceFromLibrary(libRow.modelData.folder, libRow.modelData.id, replaceEntry.modelData.path)
                                    }
                                }
                                MenuSep {
                                }
                                MenuEntry {
                                    icon_: "Edit"
                                    text: root.words.rename

                                    onTriggered: root.renameRequested(libRow.modelData.folder, libRow.modelData.id, libRow.modelData.name)
                                }
                                MenuEntry {
                                    icon_: "Delete"
                                    text: root.words.remove

                                    onTriggered: root.adapter.removeCopy(libRow.modelData.folder, libRow.modelData.id)
                                }
                            }
                        }
                        IconButton {
                            ToolTip.text: root.words.remove
                            danger: true
                            icon_: "Delete"
                            visible: libRow.modelData.missing && !libRow.modelData.stranded

                            onClicked: root.adapter.removeCopy(libRow.modelData.folder, libRow.modelData.id)
                        }
                    }
                }
            }
            Row {
                leftPadding: Theme.padCard
                spacing: Theme.sp8
                topPadding: Theme.sp12
                bottomPadding: Theme.sp12

                GhostButton {
                    enabled: !root.adapter.running
                    icon_: "Download"
                    text: root.words.importAction

                    onClicked: root.adapter.pickImport()
                }
                GhostButton {
                    icon_: "Folder"
                    text: root.words.openFolder

                    onClicked: root.adapter.openLibrary()
                }
            }
        }
    }
    Card {  // the Backups
        padding: 0
        visible: root.tab === 1
        width: parent.width

        Column {
            width: parent.width

            Txt {
                bottomPadding: Theme.sp16
                kind: "hint"
                leftPadding: Theme.padCard
                text: root.words.noBackups
                topPadding: Theme.sp16
                visible: root.adapter.backupDays.length === 0
                width: parent.width
                wrapMode: Text.WordWrap
            }
            Repeater {
                model: root.adapter.backupDays

                Column {
                    id: dayColumn

                    required property var modelData

                    width: parent.width

                    Txt {
                        color: Theme.textSecondary
                        kind: "caption"
                        leftPadding: Theme.padCard
                        text: dayColumn.modelData.day
                        topPadding: Theme.sp12
                        bottomPadding: Theme.sp4
                        width: parent.width
                    }
                    Repeater {
                        model: dayColumn.modelData.rows

                        HoverRow {
                            id: bakRow

                            required property var modelData

                            divider: true
                            height: 52
                            pressable: false
                            width: dayColumn.width

                            Column {
                                anchors.left: parent.left
                                anchors.right: bakActions.left
                                anchors.rightMargin: Theme.sp8
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: Theme.sp2

                                Row {
                                    spacing: Theme.sp8

                                    Txt {
                                        kind: "rowTitle"
                                        text: bakRow.modelData.time + "  ·  " + bakRow.modelData.name
                                        width: Math.min(implicitWidth, bakRow.width - 260)
                                    }
                                    Pill {
                                        anchors.verticalCenter: parent.verticalCenter
                                        level: bakRow.modelData.unreadable ? "warning" : "accent"
                                        text: root.words.kept
                                        visible: bakRow.modelData.kept || bakRow.modelData.unreadable
                                    }
                                }
                                Txt {
                                    color: Theme.textSecondary
                                    kind: "caption"
                                    text: bakRow.modelData.trigger + "  ·  " + bakRow.modelData.size
                                    width: parent.width
                                }
                            }
                            Row {
                                id: bakActions

                                anchors.right: parent.right
                                anchors.verticalCenter: parent.verticalCenter

                                IconButton {
                                    ToolTip.text: root.words.copyActions
                                    icon_: "More"

                                    onClicked: bakMenu.popup()

                                    PopupMenu {
                                        id: bakMenu

                                        Repeater {
                                            model: root.adapter.cards

                                            MenuEntry {
                                                id: restoreEntry

                                                required property var modelData

                                                enabled: !root.adapter.running
                                                icon_: "Return"
                                                text: root.words.restoreKind.replace("{kind}", modelData.kind)

                                                onTriggered: root.adapter.restoreBackup(bakRow.modelData.path, restoreEntry.modelData.path)
                                            }
                                        }
                                        MenuSep {
                                        }
                                        MenuEntry {
                                            icon_: "Pin"
                                            text: root.words.keep

                                            onTriggered: root.nameRequested("keep", bakRow.modelData.path)
                                        }
                                        MenuEntry {
                                            text: root.words.letAgeOut
                                            visible: bakRow.modelData.kept

                                            onTriggered: root.adapter.letAgeOut(bakRow.modelData.path)
                                        }
                                        MenuEntry {
                                            icon_: "Delete"
                                            text: root.words.deleteAction

                                            onTriggered: root.adapter.deleteBackup(bakRow.modelData.path)
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
            Row {
                leftPadding: Theme.padCard
                spacing: Theme.sp12
                topPadding: Theme.sp12
                bottomPadding: Theme.sp12

                GhostButton {
                    icon_: "Folder"
                    text: root.words.openFolder

                    onClicked: root.adapter.openBackups()
                }
                Txt {
                    anchors.verticalCenter: parent.verticalCenter
                    color: Theme.textSecondary
                    kind: "caption"
                    text: root.adapter.retention
                }
            }
        }
    }
}
