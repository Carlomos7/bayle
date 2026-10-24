pragma ComponentBehavior: Bound
import QtQuick
import Theme
import Components

// Edit as text (§8.10): the raw .me3 in the code editor, the first parse error inline, Save (accent) / Discard. Save
// goes through the profile writer (a .bak, a Version); unparsable text keeps Save off.
Column {
    id: editor

    required property var adapter
    property int editorHeight: 320
    readonly property var words: adapter.words

    spacing: Theme.sp8

    CodeEditor {
        height: editor.editorHeight
        language: "toml"
        objectName: "me3Editor"
        text: editor.adapter.me3Text
        width: parent ? parent.width : 0

        onEdited: editor.adapter.edit(text)
    }
    Txt {
        color: Theme.statusDanger
        elide: Text.ElideNone
        kind: "caption"
        text: editor.adapter.me3Error
        visible: text !== ""
        width: parent ? parent.width : 0
        wrapMode: Text.WordWrap
    }
    Row {
        anchors.right: parent ? parent.right : undefined
        spacing: Theme.gapInline

        Txt {
            anchors.verticalCenter: parent.verticalCenter
            color: editor.adapter.textDirty ? Theme.accent : Theme.textSecondary
            kind: "caption"
            text: editor.adapter.textDirty ? editor.words.unsaved : editor.words.saved
        }
        GhostButton {
            enabled: editor.adapter.textDirty
            text: editor.words.discard

            onClicked: editor.adapter.discardText()
        }
        PrimaryButton {
            enabled: editor.adapter.textDirty && editor.adapter.me3Error === ""
            objectName: "saveTextButton"
            text: editor.words.save

            onClicked: editor.adapter.saveText()
        }
    }
}
