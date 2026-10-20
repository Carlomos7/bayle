pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import Theme
import Components

// Mod Configs (§8.10): left, the profile's mods with settings files (Seamless Co-op first) and their files; the app's
// one vertical divider; right, the breadcrumb "Mod / file", the path, Edit as text, and the file as a form (INI,
// flat TOML), Seamless Co-op's panel, Markdown or plain text. Footer: Reset all / Discard / Save (Ctrl+S). Under
// 640 px the tree and the file take turns, with Back. Everything shown and every word comes from the adapter.
Item {
    id: page

    required property var adapter
    readonly property var words: adapter.words
    readonly property bool narrow: width < 640
    property bool showFile: false

    objectName: "modConfigsPage"

    Component.onCompleted: page.adapter.refresh()

    Connections {
        function onPickRequested(key, words, rows) {
            pickList.openFor(key, words, rows);
        }

        target: page.adapter
    }
    PickListDialog {
        id: pickList

        adapter: page.adapter
    }

    Shortcut {
        enabled: page.visible   // the shell keeps pages alive: only the one on show saves
        sequences: [StandardKey.Save]

        onActivated: page.adapter.save()
    }
    Item {  // the header: the profile's name (picked in the top bar)
        id: header

        anchors.left: parent.left
        anchors.leftMargin: Theme.sp16
        anchors.right: parent.right
        anchors.rightMargin: Theme.sp16
        anchors.top: parent.top
        anchors.topMargin: Theme.sp8
        height: 40

        Txt {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            elide: Text.ElideRight
            kind: "rowTitle"
            objectName: "profileTitle"
            text: page.adapter.profileName !== "" ? page.adapter.profileName : page.words.noProfile
        }
    }
    Flickable {  // the tree
        id: tree

        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.top: header.bottom
        anchors.topMargin: Theme.sp8
        clip: true
        contentHeight: treeColumn.implicitHeight + Theme.sp16
        visible: !page.narrow || !page.showFile
        width: page.narrow ? page.width : (page.width < 900 ? 220 : 300)

        Column {
            id: treeColumn

            spacing: Theme.sp4
            width: tree.width - Theme.sp16 * 2
            x: Theme.sp16

            Txt {
                elide: Text.ElideNone
                kind: "hint"
                text: !page.adapter.hasProfile ? page.words.noProfile : page.adapter.nodes.length > 0 && page.narrow ? page.words.pickFile : ""
                visible: text !== ""
                width: parent.width
                wrapMode: Text.WordWrap
            }
            GhostButton {
                icon_: "Add"
                implicitHeight: Theme.controlSmallH
                objectName: "addOverhaulSetup"
                text: page.words.addOverhaul
                visible: page.adapter.hasProfile

                onClicked: page.adapter.addOverhaulSetup("")
            }
            Repeater {
                model: page.adapter.nodes

                Column {
                    id: node

                    required property var modelData

                    spacing: 2
                    width: treeColumn.width

                    Txt {
                        color: node.modelData.muted ? Theme.textSecondary : Theme.textPrimary
                        kind: "strong"
                        text: node.modelData.name
                        width: parent.width
                    }
                    Txt {
                        elide: Text.ElideNone
                        kind: "hint"
                        text: node.modelData.sub
                        visible: text !== ""
                        width: parent.width
                        wrapMode: Text.WordWrap
                    }
                    Repeater {
                        model: node.modelData.files

                        HoverRow {
                            id: fileRow

                            required property var modelData

                            implicitHeight: 32
                            objectName: "file_" + modelData.name
                            selected: modelData.path === page.adapter.selectedFile
                            width: node.width

                            onClicked: {
                                page.adapter.selectFile(node.modelData.key, fileRow.modelData.path);
                                page.showFile = true;
                            }

                            Txt {
                                anchors.verticalCenter: parent.verticalCenter
                                text: fileRow.modelData.name
                                x: Theme.sp16
                            }
                        }
                    }
                    GhostButton {
                        implicitHeight: Theme.controlSmallH
                        objectName: "setUpAsOverhaul"
                        text: page.words.setUpAsOverhaul
                        visible: node.modelData.kind === "native" || node.modelData.kind === "package"

                        onClicked: page.adapter.addOverhaulSetup(node.modelData.key)
                    }
                }
            }
        }
    }
    Rectangle {  // the app's one vertical divider (v2.5)
        id: divider

        anchors.bottom: parent.bottom
        anchors.top: header.bottom
        color: Theme.borderHairline
        visible: !page.narrow
        width: 1
        x: tree.width
    }
    Item {  // the file
        id: detail

        anchors.bottom: parent.bottom
        anchors.left: page.narrow ? parent.left : divider.right
        anchors.right: parent.right
        anchors.top: header.bottom
        visible: !page.narrow || page.showFile

        Column {
            id: top

            anchors.left: parent.left
            anchors.leftMargin: Theme.sp16
            anchors.right: parent.right
            anchors.rightMargin: Theme.sp16
            anchors.top: parent.top
            anchors.topMargin: Theme.sp8
            spacing: Theme.sp4

            GhostButton {
                icon_: "Return"
                text: page.words.back
                visible: page.narrow

                onClicked: page.showFile = false
            }
            Item {
                height: Math.max(crumbText.implicitHeight, Theme.controlSmallH)
                width: parent.width

                Txt {
                    id: crumbText

                    anchors.left: parent.left
                    anchors.right: editRow.left
                    anchors.verticalCenter: parent.verticalCenter
                    kind: "rowTitle"
                    text: page.adapter.crumb !== "" ? page.adapter.crumb : page.words.pickFile
                }
                Row {
                    id: editRow

                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: Theme.sp8
                    visible: page.adapter.selectedFile !== ""

                    GhostButton {
                        anchors.verticalCenter: parent.verticalCenter
                        icon_: "Link"
                        implicitHeight: Theme.controlSmallH
                        objectName: "attachFile"
                        text: page.words.attach
                        visible: page.adapter.canAttach

                        onClicked: page.adapter.attachFile()
                    }
                    GhostButton {
                        anchors.verticalCenter: parent.verticalCenter
                        implicitHeight: Theme.controlSmallH
                        text: page.words.detach
                        visible: page.adapter.selectedAttached

                        onClicked: page.adapter.detachFile(page.adapter.selectedFile)
                    }
                    Txt {
                        anchors.verticalCenter: parent.verticalCenter
                        kind: "caption"
                        text: page.words.editAsText
                        visible: page.adapter.canEditText
                    }
                    ToggleSwitch {
                        anchors.verticalCenter: parent.verticalCenter
                        checked: page.adapter.editText
                        objectName: "editAsText"
                        visible: page.adapter.canEditText

                        onToggled: page.adapter.setEditText(checked)
                    }
                }
            }
            Txt {
                kind: "hint"
                text: page.adapter.selectedFile
                visible: text !== ""
                width: parent.width
            }
        }
        Flickable {
            id: body

            anchors.bottom: page.adapter.selectedFile !== "" ? footer.top : parent.bottom
            anchors.bottomMargin: Theme.sp8
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: top.bottom
            anchors.topMargin: Theme.sp12
            clip: true
            contentHeight: bodyColumn.implicitHeight + Theme.sp16

            Column {
                id: bodyColumn

                spacing: Theme.sp16
                width: body.width - Theme.sp16 * 2
                x: Theme.sp16

                ConfigForm {
                    adapter: page.adapter
                    sections: page.adapter.fileKind === "form" ? page.adapter.sections : []
                    visible: page.adapter.fileKind === "form"
                    width: parent.width
                }
                SeamlessPanel {
                    adapter: page.adapter
                    visible: page.adapter.fileKind === "seamless"
                    width: parent.width
                }
                OverhaulSetupForm {
                    adapter: page.adapter
                    visible: page.adapter.fileKind === "overhaul"
                    width: parent.width
                }
                Txt {
                    elide: Text.ElideNone
                    text: page.adapter.fileKind === "markdown" ? page.adapter.text : ""
                    textFormat: Text.MarkdownText
                    visible: page.adapter.fileKind === "markdown"
                    width: parent.width
                    wrapMode: Text.WordWrap
                }
                CodeArea {
                    height: Math.max(320, body.height - Theme.sp16)
                    objectName: "configText"
                    text: page.adapter.fileKind === "text" ? page.adapter.text : ""
                    visible: page.adapter.fileKind === "text"
                    width: parent.width

                    onEdited: page.adapter.edit(text)
                }
            }
        }
        Rectangle {  // the save bar: always in the same place, the state in words
            id: footer

            anchors.bottom: parent.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            color: Theme.surfacePage
            height: 56
            visible: page.adapter.selectedFile !== ""

            Hairline {}
            Txt {
                id: changeLabel

                Accessible.role: Accessible.AlertMessage
                anchors.left: parent.left
                anchors.leftMargin: Theme.sp16
                anchors.right: buttons.left
                anchors.rightMargin: Theme.sp8
                anchors.verticalCenter: parent.verticalCenter
                color: page.adapter.dirty ? Theme.accent : Theme.textSecondary
                kind: "caption"
                text: page.adapter.changeText
            }
            Row {
                id: buttons

                anchors.right: parent.right
                anchors.rightMargin: Theme.sp16
                anchors.verticalCenter: parent.verticalCenter
                spacing: Theme.gapInline

                PrimaryButton {
                    enabled: page.adapter.dirty
                    objectName: "saveConfig"
                    text: page.words.save

                    onClicked: page.adapter.save()
                }
                GhostButton {
                    enabled: page.adapter.dirty
                    text: page.words.discard

                    onClicked: page.adapter.discard()
                }
                GhostButton {
                    text: page.words.resetAll
                    visible: page.adapter.fileKind === "form"

                    onClicked: page.adapter.resetAll()
                }
            }
        }
        Column {  // nothing picked yet
            anchors.centerIn: body
            spacing: Theme.sp4
            visible: page.adapter.selectedFile === "" && page.adapter.nodes.length > 0
            width: Math.min(body.width - Theme.sp32, 360)

            Txt {
                horizontalAlignment: Text.AlignHCenter
                kind: "rowTitle"
                text: page.words.emptyPickTitle
                width: parent.width
            }
            Txt {
                elide: Text.ElideNone
                horizontalAlignment: Text.AlignHCenter
                kind: "hint"
                text: page.words.emptyPickBody
                width: parent.width
                wrapMode: Text.WordWrap
            }
        }
    }
    Column {  // no mod in this profile has a settings file
        anchors.centerIn: parent
        spacing: Theme.sp8
        visible: page.adapter.hasProfile && page.adapter.nodes.length === 0 && !page.adapter.loading
        width: Math.min(page.width - Theme.sp32, 380)

        Txt {
            horizontalAlignment: Text.AlignHCenter
            kind: "rowTitle"
            text: page.words.emptyNoFilesTitle
            width: parent.width
        }
        Txt {
            elide: Text.ElideNone
            horizontalAlignment: Text.AlignHCenter
            kind: "hint"
            text: page.words.emptyNoFilesBody
            width: parent.width
            wrapMode: Text.WordWrap
        }
        PrimaryButton {
            anchors.horizontalCenter: parent.horizontalCenter
            objectName: "goToMods"
            text: page.words.goToMods

            onClicked: page.adapter.openMods()
        }
    }
}
