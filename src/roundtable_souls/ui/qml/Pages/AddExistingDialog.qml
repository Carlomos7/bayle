pragma ComponentBehavior: Bound
import QtQuick
import Theme
import Components

// Add existing (the group's "not loaded · Add..." line): the mod folders (or DLLs) in the profile no entry loads, as
// a tick list; each one ticked gets its own entry, last in the load order. Nothing is copied or moved.
ModalDialog {
    id: dlg

    required property var adapter
    property string kind: "package"
    property var rows: []
    property var picked: ({})
    readonly property var words: adapter.words

    objectName: "addExistingDialog"
    preferredWidth: 520
    subtitle: words.addBody
    title: kind === "package" ? words.addPackagesTitle : words.addNativesTitle

    function openFor(k) {
        kind = k;
        rows = adapter.unlistedFor(k);
        picked = {};
        open();
    }

    footerRow: [
        PrimaryButton {
            enabled: Object.keys(dlg.picked).length > 0
            objectName: "addPicked"
            text: dlg.words.add

            onClicked: {
                dlg.adapter.addPaths(dlg.kind, Object.keys(dlg.picked));
                dlg.close();
            }
        },
        GhostButton {
            text: dlg.words.cancel

            onClicked: dlg.close()
        }
    ]

    Column {
        spacing: Theme.sp4
        width: parent ? parent.width : 0

        Txt {
            kind: "hint"
            text: dlg.words.nothingToAdd
            visible: dlg.rows.length === 0
        }
        Repeater {
            model: dlg.rows

            CheckRow {
                required property var modelData

                checked: dlg.picked[modelData.path] === true
                text: modelData.label

                onToggled: {
                    let m = Object.assign({}, dlg.picked);
                    if (checked)
                        m[modelData.path] = true;
                    else
                        delete m[modelData.path];
                    dlg.picked = m;
                }
            }
        }
    }
}
