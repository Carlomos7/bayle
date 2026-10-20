pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Window
import Theme
import Components

// Export / Import profile: a profile's mods, order, options, settings and its mods' settings files, as a share list
// (one file) or a full export (a zip with the mods). Import shows what changes file by file and writes the ticked
// files as one undoable operation; the third view is the profile a mod download ships. Everything shown and every
// word comes from the adapter.
PageScroll {
    id: page

    required property var adapter
    readonly property var words: adapter.words
    readonly property var s: adapter.state
    readonly property string mode: adapter.mode
    property bool readmePreview: false
    property bool showChangelog: false

    maxContentWidth: Theme.formMaxW
    objectName: "profileTransferPage"

    Component.onCompleted: page.adapter.refresh()

    Item {  // the header: the profile, and the Export / Import tabs
        height: Theme.controlH
        visible: page.mode !== "bundled"
        width: parent ? parent.width : 0

        DropButton {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            implicitHeight: Theme.controlH
            objectName: "profilePicker"
            text: page.s.profileName !== "" ? page.s.profileName : page.words.noProfile

            Repeater {
                model: page.adapter.profiles

                MenuEntry {
                    required property int index
                    required property string modelData

                    checked: index === page.adapter.profileIndex
                    text: modelData

                    onTriggered: page.adapter.pickProfile(index)
                }
            }
        }
        TabRow {
            id: modeTabs

            anchors.right: parent.right
            objectName: "modeTabs"
            tabs: [page.words.tabExport, page.words.tabImport]

            onCurrentChanged: {
                const want = current === 1 ? "import" : "export";
                if (page.mode !== "bundled" && want !== page.mode)
                    page.adapter.setMode(want);
            }
        }
        Binding {
            property: "current"
            target: modeTabs
            value: page.mode === "import" ? 1 : 0
        }
    }
    Txt {
        kind: "title"
        text: page.words.bundledTitle
        visible: page.mode === "bundled"
    }
    Txt {
        elide: Text.ElideNone
        kind: "hint"
        text: !page.s.hasProfile ? page.words.noProfile : ""
        visible: text !== ""
        width: parent ? parent.width : 0
        wrapMode: Text.WordWrap
    }

    // ------------------------------------------------------------------ Export
    Column {
        id: exportView

        spacing: Theme.sp16
        visible: page.mode === "export" && page.s.hasProfile
        width: parent ? parent.width : 0

        Card {  // a running export: progress, what file, how long, Cancel
            objectName: "exportRun"
            visible: page.s.ex.run.phase === "running"
            width: parent ? parent.width : 0

            Column {
                spacing: Theme.sp8
                width: parent ? parent.width : 0

                Txt {
                    kind: "strong"
                    text: page.s.ex.run.title || page.words.exporting
                }
                ProgressBar {
                    objectName: "exportProgress"
                    value: (page.s.ex.run.pct || 0) / 100
                    width: parent ? parent.width : 0
                }
                Txt {
                    color: Theme.textSecondary
                    kind: "caption"
                    text: page.s.ex.run.file || ""
                    width: parent ? parent.width : 0
                }
                Txt {
                    color: Theme.textSecondary
                    kind: "caption"
                    text: (page.s.ex.run.bytes || "") + (page.s.ex.run.eta ? "  ·  " + page.s.ex.run.eta : "")
                }
                GhostButton {
                    enabled: !page.s.ex.run.cancelling
                    objectName: "cancelExport"
                    text: page.s.ex.run.cancelling ? page.words.cancelling : page.words.cancelExport

                    onClicked: page.adapter.cancelExport()
                }
            }
        }
        Repeater {  // how the last export ended: a new bar each time, so a closed one comes back
            model: ["done", "error", "cancelled"].indexOf(page.s.ex.run.phase) >= 0 ? [page.s.ex.run] : []

            InfoBar {
                required property var modelData

                actionLabel: modelData.phase === "done" ? page.words.showInFolder : ""
                objectName: "exportResult"
                severity: modelData.phase === "done" ? "success" : modelData.phase === "error" ? "error" : "info"
                text: modelData.text
                width: exportView.width

                onActionClicked: page.adapter.showExport()
                onClosed: page.adapter.dismissRun()
            }
        }
        TabRow {
            id: kindTabs

            objectName: "kindTabs"
            tabs: [page.words.shareList, page.words.fullExport]

            onCurrentChanged: page.adapter.setText("kind", current === 1 ? "full" : "list")
        }
        Binding {
            property: "current"
            target: kindTabs
            value: page.s.ex.kind === "full" ? 1 : 0
        }
        Txt {
            elide: Text.ElideNone
            kind: "hint"
            text: page.s.ex.kind === "full" ? page.words.fullExportAbout : page.words.shareListAbout
            width: parent ? parent.width : 0
            wrapMode: Text.WordWrap
        }
        Row {
            spacing: Theme.sp12

            Column {
                spacing: Theme.sp4

                Row {
                    spacing: Theme.sp8

                    Txt {
                        kind: "caption"
                        text: page.words.name
                    }
                    Txt {
                        color: Theme.statusDanger
                        kind: "caption"
                        text: page.words.required
                        visible: page.s.ex.nameError
                    }
                }
                TextBox {
                    error: page.s.ex.nameError
                    objectName: "exportName"
                    text: page.s.ex.name

                    onTextEdited: page.adapter.setText("name", text)
                }
            }
            Column {
                spacing: Theme.sp4

                Txt {
                    kind: "caption"
                    text: page.words.version
                }
                TextBox {
                    objectName: "exportVersion"
                    text: page.s.ex.version

                    onTextEdited: page.adapter.setText("version", text)
                }
            }
            Column {
                spacing: Theme.sp4

                Txt {
                    kind: "caption"
                    text: page.words.author
                }
                TextBox {
                    objectName: "exportAuthor"
                    text: page.s.ex.author

                    onTextEdited: page.adapter.setText("author", text)
                }
            }
        }
        Card {  // full export: which mods go in the zip
            visible: page.s.ex.kind === "full"
            width: parent ? parent.width : 0

            Column {
                spacing: Theme.sp4
                width: parent ? parent.width : 0

                Txt {
                    kind: "cardTitle"
                    text: page.words.mods
                }
                Repeater {
                    model: page.s.ex.mods

                    Row {
                        id: modRow

                        required property var modelData

                        spacing: Theme.sp8

                        CheckRow {
                            checked: modRow.modelData.checked
                            text: modRow.modelData.name

                            onToggled: page.adapter.toggleMod(modRow.modelData.key, checked)
                        }
                        Pill {
                            anchors.verticalCenter: parent.verticalCenter
                            level: modRow.modelData.large ? "warning" : "muted"
                            text: modRow.modelData.size
                        }
                        Txt {
                            anchors.verticalCenter: parent.verticalCenter
                            color: Theme.textSecondary
                            kind: "caption"
                            text: modRow.modelData.note
                            visible: text !== ""
                        }
                    }
                }
                Txt {
                    color: Theme.textSecondary
                    kind: "caption"
                    text: page.s.ex.total
                }
                Txt {
                    color: Theme.statusDanger
                    kind: "caption"
                    text: page.words.tickOne
                    visible: page.s.ex.modsError
                }
            }
        }
        Card {  // README and changelog
            visible: page.s.ex.kind === "full"
            width: parent ? parent.width : 0

            Column {
                spacing: Theme.sp8
                width: parent ? parent.width : 0

                Row {
                    spacing: Theme.sp12

                    Txt {
                        anchors.verticalCenter: parent.verticalCenter
                        kind: "cardTitle"
                        text: page.words.readme
                    }
                    GhostButton {
                        implicitHeight: Theme.controlSmallH
                        text: page.readmePreview ? page.words.readmeEdit : page.words.readmePreview

                        onClicked: page.readmePreview = !page.readmePreview
                    }
                }
                CodeArea {
                    height: 200
                    mono: false
                    objectName: "exportReadme"
                    text: page.s.ex.readme
                    visible: !page.readmePreview
                    width: parent ? parent.width : 0

                    onEdited: page.adapter.setText("readme", text)
                }
                Txt {
                    elide: Text.ElideNone
                    text: page.s.ex.readme
                    textFormat: Text.MarkdownText
                    visible: page.readmePreview
                    width: parent ? parent.width : 0
                    wrapMode: Text.WordWrap
                }
                GhostButton {
                    implicitHeight: Theme.controlSmallH
                    text: (page.showChangelog ? "- " : "+ ") + page.words.changelog

                    onClicked: page.showChangelog = !page.showChangelog
                }
                CodeArea {
                    height: 140
                    mono: false
                    objectName: "exportChangelog"
                    text: page.s.ex.changelog
                    visible: page.showChangelog
                    width: parent ? parent.width : 0

                    onEdited: page.adapter.setText("changelog", text)
                }
            }
        }
        Card {  // what else goes in
            width: parent ? parent.width : 0

            Column {
                spacing: Theme.sp8
                width: parent ? parent.width : 0

                Txt {
                    kind: "cardTitle"
                    text: page.words.include
                }
                CheckRow {
                    checked: true
                    enabled: false
                    text: page.words.withProfile
                    visible: page.s.ex.kind === "full"
                }
                CheckRow {
                    checked: page.s.ex.withConfigs
                    objectName: "withConfigs"
                    text: page.words.withConfigs

                    onToggled: page.adapter.setFlag("withConfigs", checked)
                }
                CheckRow {
                    checked: page.s.ex.withPassword
                    enabled: page.s.ex.withConfigs
                    objectName: "withPassword"
                    text: page.words.withPassword

                    onToggled: page.adapter.setFlag("withPassword", checked)
                }
                Txt {
                    color: Theme.textSecondary
                    kind: "caption"
                    text: page.words.withPasswordTip
                }
                CheckRow {
                    checked: page.s.ex.withSave
                    enabled: page.s.ex.saveName !== ""
                    objectName: "withSave"
                    text: page.words.withSave + (page.s.ex.saveName !== "" ? " (" + page.s.ex.saveName + ")" : "")
                    visible: page.s.ex.kind === "full"

                    onToggled: page.adapter.setFlag("withSave", checked)
                }
                Txt {
                    color: Theme.statusWarning
                    elide: Text.ElideNone
                    kind: "caption"
                    text: page.s.ex.saveName !== "" ? page.words.withSaveWarn : page.words.noSave
                    visible: page.s.ex.kind === "full"
                    width: parent ? parent.width : 0
                    wrapMode: Text.WordWrap
                }
            }
        }
        Txt {
            color: Theme.textSecondary
            elide: Text.ElideNone
            kind: "caption"
            objectName: "exportSummary"
            text: page.s.ex.summary
            width: parent ? parent.width : 0
            wrapMode: Text.WordWrap
        }
        InfoBar {  // a big export: the size and what is biggest
            closable: false
            objectName: "exportWarn"
            severity: "warning"
            text: page.s.ex.warn
            visible: page.s.ex.warn !== ""
            width: parent ? parent.width : 0
        }
        Row {  // the footer: output folder, Export, and why it is off
            spacing: Theme.sp12

            GhostButton {
                objectName: "chooseFolder"
                text: page.words.outFolder + ": " + (page.s.ex.folder !== "" ? page.s.ex.folder : page.words.chooseFolder)

                onClicked: page.adapter.chooseFolder()
            }
            PrimaryButton {
                enabled: page.s.ex.ready && !page.adapter.working
                objectName: "exportNow"
                text: page.adapter.working ? page.words.exporting : page.words.export

                onClicked: page.adapter.exportNow()
            }
            Txt {
                anchors.verticalCenter: parent.verticalCenter
                color: page.s.ex.nameError || page.s.ex.folderError || page.s.ex.modsError ? Theme.statusDanger : Theme.textSecondary
                kind: "caption"
                objectName: "exportReason"
                text: page.s.ex.reason
                visible: text !== "" && !page.adapter.working
            }
        }
    }

    // ------------------------------------------------------------------ Import
    Column {
        id: importView

        spacing: Theme.sp16
        visible: page.mode === "import" && page.s.hasProfile
        width: parent ? parent.width : 0

        Txt {
            elide: Text.ElideNone
            kind: "hint"
            text: page.words.importAbout
            width: parent ? parent.width : 0
            wrapMode: Text.WordWrap
        }
        Row {
            spacing: Theme.sp12

            PrimaryButton {
                enabled: !page.adapter.working
                objectName: "openFile"
                text: page.words.openFile

                onClicked: page.adapter.openFile()
            }
            Txt {
                anchors.verticalCenter: parent.verticalCenter
                kind: "strong"
                text: page.s.imp.file
            }
        }
        Txt {
            color: Theme.textSecondary
            kind: "caption"
            text: page.words.reading
            visible: page.adapter.working
        }
        Txt {
            color: Theme.statusDanger
            elide: Text.ElideNone
            text: page.s.imp.error
            visible: text !== ""
            width: parent ? parent.width : 0
            wrapMode: Text.WordWrap
        }
        Card {  // the author's README comes first
            visible: page.s.imp.readme !== ""
            width: parent ? parent.width : 0

            Column {
                spacing: Theme.sp8
                width: parent ? parent.width : 0

                Txt {
                    kind: "cardTitle"
                    text: page.words.readmeFirst
                }
                Txt {
                    elide: Text.ElideNone
                    text: page.s.imp.readme
                    textFormat: Text.MarkdownText
                    width: parent ? parent.width : 0
                    wrapMode: Text.WordWrap
                }
            }
        }
        TargetChoice {
            kind: "import"
            visible: page.s.imp.isZip
            width: parent ? parent.width : 0
        }
        Repeater {
            model: page.s.imp.cards

            FileCard {
                width: importView.width
            }
        }
        Notes {
            lines: page.s.imp.refusals
            danger: true
            width: parent ? parent.width : 0
        }
        Notes {
            title: page.words.left
            lines: page.s.imp.skipped
            width: parent ? parent.width : 0
        }
        Notes {
            title: page.words.notes
            lines: page.s.imp.notes
            width: parent ? parent.width : 0
        }
        Txt {
            color: Theme.textSecondary
            elide: Text.ElideNone
            text: page.words.nothing
            visible: page.s.imp.file !== "" && page.s.imp.cards.length === 0 && page.s.imp.refusals.length === 0 && !page.adapter.working
            width: parent ? parent.width : 0
            wrapMode: Text.WordWrap
        }
        Row {
            spacing: Theme.sp12
            visible: page.s.imp.file !== ""

            PrimaryButton {
                enabled: page.s.imp.canImport && !page.adapter.working
                objectName: "importNow"
                text: page.adapter.working ? page.words.importing : page.words.importButton

                onClicked: page.adapter.importNow()
            }
            GhostButton {
                text: page.words.cancel

                onClicked: page.adapter.cancel()
            }
            GhostButton {
                text: page.words.openZipFolder
                visible: page.s.imp.isZip

                onClicked: page.adapter.openZipFolder()
            }
        }
    }

    // ------------------------------------------------------------------ a profile a mod download ships
    Column {
        id: bundledView

        spacing: Theme.sp16
        visible: page.mode === "bundled"
        width: parent ? parent.width : 0

        Txt {
            elide: Text.ElideNone
            kind: "hint"
            text: page.words.bundledAbout
            width: parent ? parent.width : 0
            wrapMode: Text.WordWrap
        }
        DropButton {
            implicitHeight: Theme.controlH
            objectName: "whichProfile"
            text: page.s.bun.names.length > 0 ? page.s.bun.names[page.s.bun.which] : ""
            visible: page.s.bun.names.length > 1

            Repeater {
                model: page.s.bun.names

                MenuEntry {
                    required property int index
                    required property string modelData

                    checked: index === page.s.bun.which
                    text: modelData

                    onTriggered: page.adapter.pickWhich(index)
                }
            }
        }
        TargetChoice {
            kind: "bundled"
            width: parent ? parent.width : 0
        }
        Card {
            visible: page.s.bun.lines.length > 0
            width: parent ? parent.width : 0

            Column {
                spacing: Theme.sp4
                width: parent ? parent.width : 0

                Repeater {
                    model: page.s.bun.lines

                    Txt {
                        required property string modelData

                        elide: Text.ElideNone
                        text: modelData
                        width: parent ? parent.width : 0
                        wrapMode: Text.WordWrap
                    }
                }
            }
        }
        Notes {
            lines: page.s.bun.refusals
            danger: true
            width: parent ? parent.width : 0
        }
        Txt {
            color: Theme.statusDanger
            elide: Text.ElideNone
            text: page.s.imp.error
            visible: text !== ""
            width: parent ? parent.width : 0
            wrapMode: Text.WordWrap
        }
        Row {
            spacing: Theme.sp12

            PrimaryButton {
                enabled: page.s.bun.canImport && !page.adapter.working
                objectName: "importBundled"
                text: page.adapter.working ? page.words.importing : page.words.importButton

                onClicked: page.adapter.importBundled()
            }
            GhostButton {
                text: page.words.cancel

                onClicked: {
                    page.adapter.cancel();
                    Window.window.close();
                }
            }
        }
    }

    // ------------------------------------------------------------------ parts
    component TargetChoice: Column {
        id: target

        property string kind: "import"
        readonly property var choice: kind === "bundled" ? page.s.bun : page.s.imp

        spacing: Theme.sp8

        TabRow {
            id: targetTabs

            objectName: target.kind + "Target"
            tabs: [page.words.newProfile, page.words.currentProfile]

            onCurrentChanged: page.adapter.setNewProfile(current === 0)
        }
        Binding {
            property: "current"
            target: targetTabs
            value: target.choice.newProfile ? 0 : 1
        }
        Row {
            spacing: Theme.sp8
            visible: target.choice.newProfile

            Txt {
                anchors.verticalCenter: parent.verticalCenter
                kind: "caption"
                text: page.words.newName
            }
            TextBox {
                objectName: target.kind + "NewName"
                text: target.choice.newName

                onEditingFinished: page.adapter.renamed()
                onTextEdited: page.adapter.setNewName(text)
            }
        }
    }
    component FileCard: Card {
        id: card

        required property var modelData

        Column {
            spacing: Theme.sp4
            width: parent ? parent.width : 0

            CheckRow {
                checked: card.modelData.checked
                objectName: "card_" + card.modelData.key
                text: card.modelData.title + (card.modelData.isNew ? "  ·  " + page.words.newFile : "")

                onToggled: page.adapter.toggleCard(card.modelData.key, checked)
            }
            Txt {
                color: Theme.textSecondary
                kind: "caption"
                text: card.modelData.path
                width: parent ? parent.width : 0
            }
            Repeater {
                model: card.modelData.lines

                Txt {
                    required property string modelData

                    elide: Text.ElideNone
                    text: modelData
                    width: parent ? parent.width : 0
                    wrapMode: Text.WordWrap
                }
            }
            Repeater {
                model: card.modelData.leftOut

                Txt {
                    required property string modelData

                    color: Theme.textSecondary
                    elide: Text.ElideNone
                    text: modelData
                    width: parent ? parent.width : 0
                    wrapMode: Text.WordWrap
                }
            }
        }
    }
    component Notes: Column {
        id: notes

        property bool danger: false
        property var lines: []
        property string title: ""

        spacing: Theme.sp4
        visible: lines.length > 0

        Txt {
            kind: "strong"
            text: notes.title
            visible: text !== ""
        }
        Repeater {
            model: notes.lines

            Txt {
                required property string modelData

                color: notes.danger ? Theme.statusDanger : Theme.textSecondary
                elide: Text.ElideNone
                text: modelData
                width: parent ? parent.width : 0
                wrapMode: Text.WordWrap
            }
        }
    }
}
