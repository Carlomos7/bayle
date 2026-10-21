pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Window
import Theme
import App
import Components

// A one-shot message window for the places with no launcher around them (a failed start, a Steam shortcut's Play
// that did not start): a heading, what to know, and one to three buttons. The first button is the primary one.
// ui/message_box.py builds it and waits for `answered`.
ApplicationWindow {
    id: win

    property var buttons: ["OK"]
    property string detail: ""
    property string heading: ""
    property bool done: false

    signal answered(int index)

    function pick(index) {
        win.done = true;
        win.answered(index);
        win.close();
    }

    color: Theme.surfacePage
    font.family: Theme.fontFamily
    height: column.implicitHeight + Theme.sp24 * 2
    maximumHeight: height
    maximumWidth: width
    minimumHeight: height
    minimumWidth: width
    title: "Bayle Mod Manager"
    width: 460

    Component.onCompleted: AppState.setThemeMode("dark")
    onClosing: if (!win.done) {
        win.done = true;
        win.answered(-1);
    }

    Column {
        id: column

        anchors.left: parent.left
        anchors.margins: Theme.sp24
        anchors.right: parent.right
        anchors.top: parent.top
        spacing: Theme.sp12

        Txt {
            elide: Text.ElideNone
            kind: "strong"
            text: win.heading
            width: parent.width
            wrapMode: Text.Wrap
        }
        Txt {
            color: Theme.textSecondary
            elide: Text.ElideNone
            text: win.detail
            visible: text !== ""
            width: parent.width
            wrapMode: Text.Wrap
        }
        Row {
            layoutDirection: Qt.RightToLeft
            spacing: Theme.sp8
            width: parent.width

            Repeater {
                model: win.buttons

                Loader {
                    required property int index
                    required property string modelData

                    sourceComponent: index === 0 ? primary : ghost

                    Component {
                        id: primary

                        PrimaryButton {
                            text: modelData
                            onClicked: win.pick(index)
                        }
                    }
                    Component {
                        id: ghost

                        GhostButton {
                            text: modelData
                            onClicked: win.pick(index)
                        }
                    }
                }
            }
        }
    }
}
