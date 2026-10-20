pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import Theme
import Components

// Mod options (§8.10): the entry's me3 keys. Enabled; Load after / Load before (each other entry of the same kind,
// with "optional"); a package's id; for a DLL Optional, Load early, Initializer (none / a function / a wait) and
// Finalizer; for an Elden Ring package "This mod must stay last" and its rebuild-tool file; the config files a DLL has.
// The config files are never edited here. Save writes through the adapter (a Version, Undo in the toast).
ModalDialog {
    id: dlg

    required property var adapter
    property var data_: ({})
    property var after: ({})       // id -> optional (bool); a key present = listed
    property var before: ({})
    readonly property var words: adapter.words

    objectName: "modOptionsDialog"
    preferredWidth: 560
    title: (words.optionsTitle || "").replace("{name}", data_.name || "")

    function openFor(index) {
        const d = adapter.optionsFor(index);
        if (!d || d.index === undefined)
            return;
        data_ = d;
        let a = {}, b = {};
        for (const x of d.loadAfter)
            a[x.id] = x.optional;
        for (const x of d.loadBefore)
            b[x.id] = x.optional;
        after = a;
        before = b;
        enabledBox.checked = d.enabled;
        idBox.text = d.id;
        optionalBox.checked = d.optional;
        earlyBox.checked = d.loadEarly;
        initMenu.kind = d.initKind;
        initValue.text = d.initValue;
        finiBox.text = d.finalizer;
        lastBox.checked = d.overlay === 1;
        rebuildBox.text = d.rebuildFile;
        open();
    }
    function toggle(map, id, on) {
        let m = Object.assign({}, map);
        if (on)
            m[id] = m[id] === undefined ? false : m[id];
        else
            delete m[id];
        return m;
    }
    function list(map) {
        return Object.keys(map).map(function (k) {
            return {
                "id": k,
                "optional": map[k]
            };
        });
    }

    footerRow: [
        PrimaryButton {
            objectName: "saveOptions"
            text: dlg.words.save

            onClicked: {
                dlg.adapter.saveOptions(dlg.data_.index, {
                    "enabled": enabledBox.checked,
                    "id": idBox.text,
                    "loadAfter": dlg.list(dlg.after),
                    "loadBefore": dlg.list(dlg.before),
                    "optional": optionalBox.checked,
                    "loadEarly": earlyBox.checked,
                    "initKind": initMenu.kind,
                    "initValue": initValue.text,
                    "finalizer": finiBox.text,
                    "overlay": dlg.data_.overlay === -1 ? -1 : (lastBox.checked ? 1 : 0),
                    "rebuildFile": rebuildBox.text
                });
                dlg.close();
            }
        },
        GhostButton {
            text: dlg.words.cancel

            onClicked: dlg.close()
        }
    ]

    Column {
        spacing: Theme.sp8
        width: parent ? parent.width : 0

        CheckRow {
            id: enabledBox

            text: dlg.words.enabled
        }
        FormRow {
            title: dlg.words.packageId
            visible: dlg.data_.kind === "package"
            width: parent ? parent.width : 0

            TextBox {
                id: idBox

                implicitWidth: Theme.inputW
            }
        }
        Repeater {  // Load after, then Load before
            model: [
                {
                    "key": "after",
                    "title": dlg.words.loadAfter
                },
                {
                    "key": "before",
                    "title": dlg.words.loadBefore
                }
            ]

            Column {
                id: depSection

                required property var modelData
                readonly property var map: modelData.key === "after" ? dlg.after : dlg.before

                spacing: Theme.sp4
                width: parent ? parent.width : 0

                Txt {
                    kind: "strong"
                    text: depSection.modelData.title
                }
                Txt {
                    kind: "hint"
                    text: dlg.words.noDeps
                    visible: (dlg.data_.others || []).length === 0
                }
                Repeater {
                    model: dlg.data_.others || []

                    Row {
                        id: depRow

                        required property string modelData
                        readonly property bool listed: depSection.map[modelData] !== undefined

                        spacing: Theme.sp16

                        CheckRow {
                            checked: depRow.listed
                            text: depRow.modelData

                            onToggled: {
                                if (depSection.modelData.key === "after")
                                    dlg.after = dlg.toggle(dlg.after, depRow.modelData, checked);
                                else
                                    dlg.before = dlg.toggle(dlg.before, depRow.modelData, checked);
                            }
                        }
                        CheckRow {
                            checked: depRow.listed && depSection.map[depRow.modelData] === true
                            enabled: depRow.listed
                            text: dlg.words.optionalDep

                            onToggled: {
                                let m = Object.assign({}, depSection.map);
                                m[depRow.modelData] = checked;
                                if (depSection.modelData.key === "after")
                                    dlg.after = m;
                                else
                                    dlg.before = m;
                            }
                        }
                    }
                }
            }
        }
        Column {  // a DLL's own keys
            spacing: Theme.sp8
            visible: dlg.data_.kind === "native"
            width: parent ? parent.width : 0

            CheckRow {
                id: optionalBox

                text: dlg.words.optionalNative
            }
            CheckRow {
                id: earlyBox

                text: dlg.words.loadEarly
            }
            FormRow {
                help: dlg.words.initializerHelp
                showHelpIcon: true
                title: dlg.words.initializer
                tooltip: dlg.words.initializerTip
                width: parent ? parent.width : 0

                Row {
                    spacing: Theme.sp8

                    DropButton {
                        id: initMenu

                        property int kind: 0

                        fixedWidth: 170
                        implicitHeight: Theme.controlH
                        text: kind === 1 ? dlg.words.initFunction : kind === 2 ? dlg.words.initDelay : dlg.words.initNone

                        MenuEntry {
                            text: dlg.words.initNone

                            onTriggered: initMenu.kind = 0
                        }
                        MenuEntry {
                            text: dlg.words.initFunction

                            onTriggered: initMenu.kind = 1
                        }
                        MenuEntry {
                            text: dlg.words.initDelay

                            onTriggered: initMenu.kind = 2
                        }
                    }
                    TextBox {
                        id: initValue

                        implicitWidth: Theme.inputShortW
                        visible: initMenu.kind !== 0
                    }
                }
            }
            FormRow {
                showHelpIcon: true
                title: dlg.words.finalizer
                tooltip: dlg.words.finalizerTip
                width: parent ? parent.width : 0

                TextBox {
                    id: finiBox

                    implicitWidth: Theme.inputW
                }
            }
        }
        Column {  // an Elden Ring package: the mod that must stay last, set by hand
            spacing: Theme.sp8
            visible: dlg.data_.overlay !== undefined && dlg.data_.overlay !== -1
            width: parent ? parent.width : 0

            CheckRow {
                id: lastBox

                ToolTip.text: dlg.words.staysLastHelp
                ToolTip.visible: hovered || visualFocus
                text: dlg.words.staysLastOption
            }
            FormRow {
                title: dlg.words.rebuildFile
                visible: lastBox.checked
                width: parent ? parent.width : 0

                TextBox {
                    id: rebuildBox

                    implicitWidth: Theme.inputW
                }
            }
        }
        Txt {
            kind: "hint"
            text: dlg.words.configFiles + ": " + (dlg.data_.configs || []).join(", ")
            visible: (dlg.data_.configs || []).length > 0
            width: parent ? parent.width : 0
            wrapMode: Text.WordWrap
        }
        GhostButton {
            icon_: "Link"
            objectName: "openOnModConfigs"
            text: dlg.words.openOnModConfigs
            visible: (dlg.data_.configs || []).length > 0

            onClicked: {
                dlg.adapter.attachConfig(dlg.data_.index);
                dlg.close();
            }
        }
    }
}
