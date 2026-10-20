pragma ComponentBehavior: Bound
import QtQuick
import Theme
import Components

// Rename an installed mod (§8.3): one name, used for its folder and (a package) its id. The adapter says live whether
// the name is allowed and what would change; Rename writes through the adapter as a logged job with Undo.
ModalDialog {
    id: dlg

    required property var adapter
    property int entry: -1
    property var info: ({
            "ok": false,
            "lines": [],
            "refusals": []
        })
    readonly property var words: adapter.words

    function openFor(index) {
        const current = adapter.renameCurrent(index);
        if (current === "")
            return;
        entry = index;
        title = words.renameTitle.replace("{name}", current);
        subtitle = words.renameHint;
        name.text = current;
        refresh();
        open();
        name.forceActiveFocus();
        name.selectAll();
    }
    function refresh() {
        info = entry < 0 ? info : adapter.renamePreview(entry, name.text);
    }
    function apply() {
        refreshTimer.stop();
        refresh();
        if (!info.ok)
            return;
        adapter.rename(entry, name.text.trim());
        close();
    }

    footerRow: [
        PrimaryButton {
            enabled: dlg.info.ok
            objectName: "renameApply"
            text: dlg.words.renameButton

            onClicked: dlg.apply()
        },
        GhostButton {
            text: dlg.words.cancel

            onClicked: dlg.close()
        }
    ]
    objectName: "renameDialog"
    preferredWidth: 520

    TextBox {
        id: name

        maximumLength: 80
        placeholderText: dlg.words.renameNew
        width: parent.width

        onAccepted: dlg.apply()
        onTextChanged: refreshTimer.restart()  // the preview reads the profiles: not on every keystroke
    }
    Timer {
        id: refreshTimer

        interval: 300

        onTriggered: dlg.refresh()
    }
    Repeater {
        model: dlg.info.refusals

        Txt {
            required property string modelData

            color: Theme.statusDanger
            kind: "hint"
            text: modelData
            width: parent ? parent.width : 0
            wrapMode: Text.WordWrap
        }
    }
    Repeater {
        model: dlg.info.ok ? dlg.info.lines : []

        Txt {
            required property string modelData

            kind: "hint"
            text: modelData
            width: parent ? parent.width : 0
            wrapMode: Text.WordWrap
        }
    }
}
