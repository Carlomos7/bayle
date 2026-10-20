pragma ComponentBehavior: Bound
import QtQuick
import Theme
import Components

// New profile (File, and the Launch pill's "Create a profile"): a name, and Seamless Co-op from the game folder moved
// into it when it is there. The profile is written by the one profile writer, as a logged job.
ModalDialog {
    id: root

    property bool seamless: false
    required property var shell

    function ask(suggested, seamlessOffered) {
        seamless = seamlessOffered;
        name.text = suggested;
        include.checked = seamlessOffered;
        open();
        name.forceActiveFocus();
        name.selectAll();
    }
    function apply() {
        root.shell.createProfile(name.text.trim(), root.seamless && include.checked);
        close();
    }

    footerRow: [
        PrimaryButton {
            enabled: name.text.trim() !== ""
            text: qsTr("Create")

            onClicked: root.apply()
        },
        GhostButton {
            text: qsTr("Cancel")

            onClicked: root.close()
        }
    ]
    preferredWidth: 480
    subtitle: qsTr("A new me3 profile for this game. Add mods to it from the Mods page.")
    title: qsTr("New profile")

    Column {
        spacing: Theme.sp12
        width: parent.width

        TextBox {
            id: name

            maximumLength: 80
            placeholderText: qsTr("Profile name")
            width: parent.width

            onAccepted: root.apply()
        }
        CheckRow {
            id: include

            width: parent.width
            text: qsTr("Include Seamless Co-op from the game folder (moved into the new profile)")
            visible: root.seamless
        }
        Txt {
            color: Theme.statusWarning
            elide: Text.ElideNone
            kind: "hint"
            text: qsTr("Seamless Co-op's own launcher goes to the Recycle Bin: start the game from here instead.")
            visible: root.seamless && include.checked
            width: parent.width
            wrapMode: Text.WordWrap
        }
    }
}
