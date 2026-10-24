pragma ComponentBehavior: Bound
import QtQuick
import Theme
import Components

// A name for a copy: save a copy of a live save, import a file, keep a backup, or rename a Library copy. One dialog;
// `mode` says which adapter call the button makes.
ModalDialog {
    id: root

    required property var adapter
    property string a: ""
    property string b: ""
    property string mode: "copy"      // copy | import | keep | rename
    readonly property var words: adapter.words

    function ask(mode_, path_, extra_, start_) {
        mode = mode_;
        a = path_;
        b = extra_ || "";
        title = mode_ === "rename" ? words.rename : mode_ === "import" ? words.importAction : mode_ === "keep" ? words.keep : words.saveCopy;
        subtitle = mode_ === "rename" ? "" : mode_ === "import" ? words.importHint : mode_ === "keep" ? words.keepHint : words.saveCopyHint;
        name.text = start_ !== undefined && start_ !== "" ? start_ : (mode_ === "copy" ? adapter.defaultName(path_) : "");
        open();
        name.forceActiveFocus();
        name.selectAll();
    }
    function apply() {
        const text = name.text.trim();
        if (text === "")
            return;
        if (mode === "copy")
            adapter.saveCopy(a, text);
        else if (mode === "import")
            adapter.importFile(a, text);
        else if (mode === "keep")
            adapter.keepAs(a, text);
        else
            adapter.renameCopy(a, b, text);
        close();
    }

    footerRow: [
        PrimaryButton {
            enabled: name.text.trim() !== ""
            text: root.mode === "rename" ? root.words.rename.replace("...", "") : root.mode === "import" ? root.words.importButton : root.words.save

            onClicked: root.apply()
        },
        GhostButton {
            text: root.words.cancel

            onClicked: root.close()
        }
    ]
    preferredWidth: 480

    TextBox {
        id: name

        maximumLength: 80
        placeholderText: root.words.name
        width: parent.width

        onAccepted: root.apply()
    }
}
