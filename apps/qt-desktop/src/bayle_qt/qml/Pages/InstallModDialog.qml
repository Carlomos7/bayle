pragma ComponentBehavior: Bound
import QtQuick
import Theme
import Components

// Install mod (technical specification §8.2, "Dialogs kept"): the folder name (and id for a package), what to
// install as a tick list, where regulation.bin goes, the mod that must stay last, and the one note about what
// happens. One dialog for "From archive or DLL...", "From folder..." and files dropped on the page; several drops
// open it one after another. Every word and decision comes from the adapter (ui/pages/mods/install_adapter.py).
ModalDialog {
    id: dlg

    required property var adapter
    readonly property var inst: adapter.installer
    property var v: ({})
    readonly property var w: inst.words

    function tone(level) {
        return level === "error" ? Theme.statusDanger : level === "warning" ? Theme.statusWarning : Theme.textSecondary;
    }
    function openNow() {
        v = inst.view;
        nameBox.text = v.name || "";
        idBox.text = v.id || "";
        open();
    }

    objectName: "installModDialog"
    preferredWidth: 640
    subtitle: v.what || ""
    title: v.title || ""

    footerRow: [
        PrimaryButton {
            enabled: !!dlg.v.canInstall
            objectName: "installGo"
            text: dlg.v.busy ? dlg.w.working : (dlg.v.installText || dlg.w.install)

            onClicked: {
                if (dlg.inst.accept())
                    dlg.close();
            }
        },
        GhostButton {
            objectName: "installImportInstead"
            text: dlg.w.importInstead
            visible: !!dlg.v.profilesInside

            onClicked: {
                if (dlg.inst.importInstead())
                    dlg.close();
            }
        },
        GhostButton {
            objectName: "installCancel"
            text: dlg.w.cancel

            onClicked: dlg.close()
        }
    ]

    onClosed: inst.dialogClosed()

    Connections {
        function onViewChanged() {
            if (Object.keys(dlg.inst.view).length === 0)
                return;
            dlg.v = dlg.inst.view;
            if (!nameBox.activeFocus)
                nameBox.text = dlg.v.name;
            if (!idBox.activeFocus)
                idBox.text = dlg.v.id;
        }
        function onOpenRequested() {
            dlg.openNow();
        }

        target: dlg.inst
    }
    Column {
        spacing: Theme.sp8
        width: parent ? parent.width : 0

        Column {  // the archive holds more than one mod: which
            spacing: Theme.sp4
            visible: (dlg.v.variants || []).length > 1
            width: parent.width

            Txt {
                kind: "hint"
                text: dlg.w.variantLabel
            }
            DropButton {
                implicitHeight: Theme.controlH
                objectName: "installVariant"
                text: dlg.v.variant || ""

                Repeater {
                    model: dlg.v.variants || []

                    MenuEntry {
                        required property string modelData

                        checked: modelData === dlg.v.variant
                        text: modelData

                        onTriggered: dlg.inst.setVariant(modelData)
                    }
                }
            }
        }
        Row {  // the folder name, and the package id beside it
            spacing: Theme.sp12
            width: parent.width

            Column {
                spacing: Theme.sp4
                width: dlg.v.idShown ? (parent.width - Theme.sp12) / 2 : parent.width

                Txt {
                    kind: "strong"
                    text: dlg.v.nameLabel || ""
                }
                TextBox {
                    id: nameBox

                    error: !!dlg.v.nameError
                    objectName: "installName"
                    width: parent.width

                    onTextEdited: dlg.inst.setName(text)
                }
                Txt {
                    elide: Text.ElideNone
                    kind: "hint"
                    text: dlg.v.where || ""
                    visible: text !== ""
                    width: parent.width
                    wrapMode: Text.WordWrap
                }
            }
            Column {
                spacing: Theme.sp4
                visible: !!dlg.v.idShown
                width: (parent.width - Theme.sp12) / 2

                Txt {
                    kind: "strong"
                    text: dlg.w.id
                }
                TextBox {
                    id: idBox

                    error: !!dlg.v.idError
                    objectName: "installId"
                    width: parent.width

                    onTextEdited: dlg.inst.setId(text)
                }
                Txt {
                    color: dlg.v.idError ? Theme.statusDanger : Theme.textSecondary
                    elide: Text.ElideNone
                    kind: "hint"
                    text: dlg.v.idNote || ""
                    width: parent.width
                    wrapMode: Text.WordWrap
                }
            }
        }
        Column {  // what to install
            spacing: 0
            visible: (dlg.v.items || []).length > 0
            width: parent.width

            Txt {
                bottomPadding: Theme.sp4
                kind: "strong"
                text: dlg.w.whatToInstall
            }
            Repeater {
                model: dlg.v.items || []

                Item {
                    id: row

                    required property var modelData

                    height: Theme.rowCompactH
                    width: parent.width

                    CheckRow {
                        id: tick

                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        checked: row.modelData.on
                        text: row.modelData.name

                        onToggled: dlg.inst.setTick(row.modelData.name, checked)
                    }
                    Txt {
                        anchors.left: tick.right
                        anchors.leftMargin: Theme.sp12
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        horizontalAlignment: Text.AlignRight
                        kind: "caption"
                        text: row.modelData.what + "  ·  " + row.modelData.size
                    }
                }
            }
            Txt {
                elide: Text.ElideNone
                kind: "hint"
                text: dlg.w.itemsNote
                topPadding: Theme.sp4
                width: parent.width
                wrapMode: Text.WordWrap
            }
        }
        Column {  // regulation.bin
            id: regCol

            readonly property var reg: dlg.v.regulation || ({})

            spacing: Theme.sp4
            visible: !!reg.shown
            width: parent.width

            Txt {
                kind: "strong"
                text: dlg.w.regulation
            }
            Txt {
                elide: Text.ElideNone
                kind: "hint"
                text: regCol.reg.about || ""
                width: parent.width
                wrapMode: Text.WordWrap
            }
            DropButton {
                implicitHeight: Theme.controlH
                objectName: "installPlace"
                text: (regCol.reg.places || [])[regCol.reg.placeIndex] || ""
                visible: !!regCol.reg.placeShown

                Repeater {
                    model: regCol.reg.places || []

                    MenuEntry {
                        required property int index
                        required property string modelData

                        checked: index === regCol.reg.placeIndex
                        text: modelData

                        // the last entry is "Last"; any earlier one is "before the package that must stay last"
                        onTriggered: dlg.inst.setPlaceLast(index === regCol.reg.places.length - 1)
                    }
                }
            }
            CheckRow {
                checked: !!regCol.reg.rebuild
                objectName: "installRebuild"
                text: regCol.reg.rebuildText || ""
                visible: !!regCol.reg.rebuildShown

                onToggled: dlg.inst.setRebuild(checked)
            }
            Txt {
                color: dlg.tone(regCol.reg.effectLevel)
                elide: Text.ElideNone
                kind: "hint"
                text: regCol.reg.effect || ""
                visible: text !== ""
                width: parent.width
                wrapMode: Text.WordWrap
            }
            Txt {
                elide: Text.ElideNone
                kind: "hint"
                text: regCol.reg.notes || ""
                visible: text !== ""
                width: parent.width
                wrapMode: Text.WordWrap
            }
        }
        Column {  // the Library: a new version of a Shared mod, or identical copies in other profiles
            id: libraryCol

            readonly property var lib: dlg.v.library || ({})

            spacing: Theme.sp4
            visible: !!lib.shown
            width: parent.width

            Txt {
                elide: Text.ElideNone
                kind: "hint"
                text: libraryCol.lib.text || ""
                width: parent.width
                wrapMode: Text.WordWrap
            }
            Repeater {
                model: libraryCol.lib.options || []

                CheckRow {
                    required property var modelData

                    checked: libraryCol.lib.choice === modelData.key
                    objectName: "installLibrary_" + modelData.key
                    text: modelData.text

                    onToggled: dlg.inst.setLibraryChoice(modelData.key)
                }
            }
        }
        Column {  // the mod that must stay last
            id: lastCol

            readonly property var last: dlg.v.last || ({})

            spacing: Theme.sp4
            visible: !!last.shown
            width: parent.width

            Txt {
                color: dlg.tone(lastCol.last.level)
                elide: Text.ElideNone
                kind: "hint"
                text: lastCol.last.text || ""
                width: parent.width
                wrapMode: Text.WordWrap
            }
            CheckRow {
                checked: !!lastCol.last.on
                objectName: "installAfterLast"
                text: lastCol.last.check || ""

                onToggled: dlg.inst.setAfterLast(checked)
            }
        }
        Column {  // the overhaul option (S3g), only while the preview switch is on
            id: optionCol

            readonly property var option: dlg.v.option || ({})

            spacing: Theme.sp4
            visible: !!option.shown
            width: parent.width

            Hairline {
                endInset: 0
                inset: 0
            }
            CheckRow {
                checked: !!optionCol.option.ticked
                enabled: !optionCol.option.locked
                objectName: "installOverhaul"
                text: dlg.w.overhaulOption

                onToggled: dlg.inst.setOverhaul(checked)
            }
            Row {
                leftPadding: 30
                spacing: Theme.gapInline
                width: parent.width

                Pill {
                    id: badge

                    icon_: "Accept"
                    level: optionCol.option.badgeLevel || "muted"
                    text: optionCol.option.badge || ""
                    visible: text !== ""
                }
                Txt {
                    color: dlg.tone(optionCol.option.level)
                    elide: Text.ElideNone
                    kind: "hint"
                    text: optionCol.option.text || ""
                    width: parent.width - 30 - (badge.visible ? badge.width + Theme.gapInline : 0)
                    wrapMode: Text.WordWrap
                }
            }
        }
        Txt {  // the switch is off: one line naming it
            elide: Text.ElideNone
            kind: "hint"
            text: (dlg.v.option || ({})).hint || ""
            visible: text !== ""
            width: parent.width
            wrapMode: Text.WordWrap
        }
        Column {  // what installing as an overhaul does
            id: previewCol

            readonly property var pv: dlg.v.overhaul || ({})

            spacing: Theme.sp4
            visible: !!pv.shown
            width: parent.width

            Txt {
                kind: "hint"
                text: dlg.w.working
                visible: !previewCol.pv.ready
            }
            Repeater {
                model: previewCol.pv.lines || []

                Txt {
                    required property string modelData

                    elide: Text.ElideNone
                    text: modelData
                    width: previewCol.width
                    wrapMode: Text.WordWrap
                }
            }
            Repeater {
                model: previewCol.pv.notes || []

                Txt {
                    required property string modelData

                    elide: Text.ElideNone
                    kind: "hint"
                    text: modelData
                    width: previewCol.width
                    wrapMode: Text.WordWrap
                }
            }
            Repeater {
                model: previewCol.pv.refusals || []

                InfoBar {
                    required property string modelData

                    closable: false
                    severity: "error"
                    text: modelData
                    width: previewCol.width
                }
            }
        }
        Column {  // the setup's DLLs: how each loads, set before installing
            spacing: Theme.sp4
            visible: (dlg.v.natives || []).length > 0
            width: parent.width

            Repeater {
                model: dlg.v.natives || []

                Column {
                    id: dllCol

                    required property var modelData

                    spacing: Theme.sp4
                    width: parent.width

                    Txt {
                        text: dllCol.modelData.file
                        width: parent.width
                    }
                    CheckRow {
                        checked: !!dllCol.modelData.load_early
                        objectName: "installDllEarly"
                        text: dlg.w.dllEarly

                        onToggled: dlg.inst.setNative(dllCol.modelData.file, "early", checked ? "true" : "false")
                    }
                    CheckRow {
                        checked: !!dllCol.modelData.after_others
                        objectName: "installDllAfter"
                        text: dlg.w.dllAfter

                        onToggled: dlg.inst.setNative(dllCol.modelData.file, "after", checked ? "true" : "false")
                    }
                    Txt {
                        kind: "hint"
                        text: dlg.w.dllInit
                    }
                    TextBox {
                        objectName: "installDllInit"
                        text: dllCol.modelData.initializer || ""
                        width: parent.width

                        onEditingFinished: dlg.inst.setNative(dllCol.modelData.file, "init", text)
                    }
                }
            }
        }
        Column {  // the texts the setup adds to the game's message binders: the table each is set in
            spacing: Theme.sp4
            visible: (dlg.v.texts || []).length > 0
            width: parent.width

            Repeater {
                model: dlg.v.texts || []

                Row {
                    id: textRow

                    required property var modelData

                    spacing: Theme.sp8
                    width: parent.width

                    Txt {
                        anchors.verticalCenter: parent.verticalCenter
                        text: textRow.modelData.label
                        width: parent.width - 220 - Theme.sp8
                    }
                    DropButton {
                        anchors.verticalCenter: parent.verticalCenter
                        fixedWidth: 200
                        implicitHeight: Theme.controlH
                        objectName: "installTextTable"
                        text: textRow.modelData.chosen

                        Repeater {
                            model: textRow.modelData.choices

                            MenuEntry {
                                required property var modelData

                                checked: modelData.value === textRow.modelData.table
                                text: modelData.label

                                onTriggered: dlg.inst.setTable(textRow.modelData.file, modelData.value)
                            }
                        }
                    }
                }
            }
        }
        Column {  // the setup's Files table: what is done with each file, changed before installing
            spacing: Theme.sp4
            visible: (dlg.v.files || []).length > 0
            width: parent.width

            Repeater {
                model: dlg.v.files || []

                Column {
                    id: fileRow

                    required property var modelData

                    spacing: Theme.sp4
                    width: parent.width

                    Row {
                        spacing: Theme.sp8
                        width: parent.width

                        Txt {
                            anchors.verticalCenter: parent.verticalCenter
                            text: fileRow.modelData.file
                            width: parent.width - 200 - Theme.sp8
                        }
                        DropButton {
                            anchors.verticalCenter: parent.verticalCenter
                            fixedWidth: 200
                            implicitHeight: Theme.controlH
                            objectName: "installFileAction"
                            text: {
                                const c = fileRow.modelData.choices.find(x => x.value === fileRow.modelData.action);
                                return c ? c.label : fileRow.modelData.action;
                            }

                            Repeater {
                                model: fileRow.modelData.choices

                                MenuEntry {
                                    required property var modelData

                                    checked: modelData.value === fileRow.modelData.action
                                    text: modelData.label

                                    onTriggered: dlg.inst.setFile(fileRow.modelData.file, modelData.value)
                                }
                            }
                        }
                    }
                    TextBox {  // on its own line: the path is long and the row has no room for it
                        objectName: "installFileTarget"
                        text: fileRow.modelData.target
                        visible: fileRow.modelData.action === "place"
                        width: parent.width

                        onEditingFinished: dlg.inst.setFile(fileRow.modelData.file, "place:" + text)
                    }
                }
            }
        }
        Txt {  // what will happen
            color: dlg.tone(dlg.v.noteLevel)
            elide: Text.ElideNone
            kind: "hint"
            objectName: "installNote"
            text: dlg.v.note || ""
            width: parent.width
            wrapMode: Text.WordWrap
        }
    }
}
