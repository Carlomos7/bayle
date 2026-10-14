pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Window
import Theme
import App
import Components

// A registered page in a top-level window of its own (S5: the Activity trial, opened from the Widgets launcher;
// the QML shell replaces this in S9 and hosts the same page unchanged). Around the page: a bar with the page's
// title and the status text, the page InfoBar, toasts bottom-right and the confirmation dialog, all driven by the
// page's Notifier (ui/notifications.py).
ApplicationWindow {
    id: win

    required property var adapter
    required property var notifier
    required property url pageUrl
    property string themeMode: "dark"   // "dark" | "tarnished" | "light" | "system", from the launcher's setting
    property Item toastItem: null
    property int confirmToken: 0
    property bool confirmed: false

    color: Theme.surfacePage
    height: 760
    minimumHeight: 480
    minimumWidth: 740
    title: win.adapter ? win.adapter.title + "  ·  Roundtable Souls" : "Roundtable Souls"
    width: 1100

    Component.onCompleted: {
        AppState.softwareRender = GraphicsInfo.api === GraphicsInfo.Software;
        AppState.setThemeMode(win.themeMode);
    }
    onThemeModeChanged: AppState.setThemeMode(win.themeMode)

    Rectangle {  // the bar: title left, the status text right
        id: bar

        color: Theme.surfaceBar
        height: Theme.barRowH
        width: parent.width

        Txt {
            anchors.left: parent.left
            anchors.leftMargin: Theme.sp16
            anchors.verticalCenter: parent.verticalCenter
            kind: "strong"
            text: win.adapter ? win.adapter.title : ""
        }
        Txt {
            anchors.right: parent.right
            anchors.rightMargin: Theme.sp16
            anchors.verticalCenter: parent.verticalCenter
            color: Theme.textSecondary
            kind: "caption"
            text: win.notifier.statusText
        }
    }
    InfoBar {
        id: infoBar

        anchors.left: parent.left
        anchors.leftMargin: Theme.sp16
        anchors.right: parent.right
        anchors.rightMargin: Theme.sp16
        anchors.top: bar.bottom
        anchors.topMargin: visible ? Theme.sp8 : 0
        open: win.notifier.infoText !== ""
        severity: win.notifier.infoSeverity
        text: win.notifier.infoText
        visible: open

        onClosed: win.notifier.clear_info()
    }
    Loader {
        id: page

        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: infoBar.visible ? infoBar.bottom : bar.bottom

        Component.onCompleted: page.setSource(win.pageUrl, {
            "adapter": win.adapter
        })
    }
    Item {  // toasts float above the page
        id: overlay

        anchors.fill: parent
        z: 10

        Component.onCompleted: AppState.overlayLayer = overlay
    }
    Component {
        id: toastComponent

        Toast {
            anchors.bottom: parent ? parent.bottom : undefined
            anchors.bottomMargin: Theme.padDialog
            anchors.right: parent ? parent.right : undefined
            anchors.rightMargin: Theme.padDialog

            onDone: destroy()
        }
    }
    Connections {
        function onToastRequested(text, isError) {
            if (win.toastItem)
                win.toastItem.dismiss();
            win.toastItem = toastComponent.createObject(overlay, {
                "text": text,
                "isError": isError
            });
        }
        function onToastActionRequested(text, isError, actionLabel, token) {
            if (win.toastItem)
                win.toastItem.dismiss();
            win.toastItem = toastComponent.createObject(overlay, {
                "text": text,
                "isError": isError,
                "actionLabel": actionLabel,
                "action": function () {
                    win.notifier.toastAction(token);
                }
            });
        }
        function onConfirmFullRequested(token, words) {
            full.token = token;
            full.applied = false;
            full.words = words;
            full.optionOn = words.optionChecked;
            full.open();
        }
        function onConfirmRequested(token, title, changes, safety, applyText, destructive) {
            win.confirmToken = token;
            win.confirmed = false;
            confirm.title = title;
            confirm.message = changes.map(function (c) {
                return "• " + c;
            }).concat(safety ? ["", safety] : []).join("\n");
            confirm.primaryText = applyText;
            confirm.destructive = destructive;
            confirm.open();
        }

        target: win.notifier
    }
    ConfirmDialog {
        id: confirm

        onClosed: win.notifier.answer(win.confirmToken, win.confirmed)
        onConfirm: function () {
            win.confirmed = true;
        }
    }
    ModalDialog {  // a confirmation with every part: what changes, the risk, the way back, a detail, an option
        id: full

        property bool applied: false
        property bool optionOn: false
        property int token: 0
        property var words: ({})

        preferredWidth: 520
        title: words.title || ""

        footerRow: [
            PrimaryButton {
                danger: !!full.words.destructive
                text: full.words.apply || ""

                onClicked: {
                    full.applied = true;
                    full.close();
                }
            },
            GhostButton {
                text: qsTr("Cancel")

                onClicked: full.close()
            }
        ]

        onClosed: win.notifier.answerWith(full.token, full.applied, full.optionOn)

        Column {
            spacing: Theme.sp8
            width: parent.width

            Repeater {
                model: full.words.changes || []

                Txt {
                    required property string modelData

                    elide: Text.ElideNone
                    text: "• " + modelData
                    width: parent.width
                    wrapMode: Text.WordWrap
                }
            }
            Txt {
                elide: Text.ElideNone
                font.family: "Consolas"
                text: full.words.detail || ""
                visible: text !== ""
                width: parent.width
                wrapMode: Text.WrapAnywhere
            }
            Txt {
                color: Theme.statusDanger
                elide: Text.ElideNone
                text: full.words.warning || ""
                visible: text !== ""
                width: parent.width
                wrapMode: Text.WordWrap
            }
            Txt {
                elide: Text.ElideNone
                kind: "hint"
                text: full.words.safety || ""
                visible: text !== ""
                width: parent.width
                wrapMode: Text.WordWrap
            }
            CheckRow {
                checked: full.optionOn
                text: full.words.option || ""
                visible: text !== ""

                onToggled: full.optionOn = checked
            }
        }
    }
}
