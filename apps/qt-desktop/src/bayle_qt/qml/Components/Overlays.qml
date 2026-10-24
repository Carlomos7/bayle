pragma ComponentBehavior: Bound
import QtQuick
import Theme
import App

// What a page's Notifier asks the window to show, in one place (S9-Shell A2; PageWindow and the shell both use it):
// toasts bottom-right (one at a time, a new one replaces the old), the confirmation dialog and the full
// confirmation. `notifiers` is the list to listen to: a page window passes its one Notifier, the shell passes every
// page's, so a job that ends after you left the page still speaks. A confirmation is answered to the Notifier that
// asked it (tokens are only unique per Notifier).
Item {
    id: root

    property bool confirmed: false
    property var confirmSource: null
    property int confirmToken: 0
    property var chooseSource: null
    property string chooseCancel: "cancel"
    property string chosenKey: ""
    property int chooseToken: 0
    property var fullSource: null
    property var notifiers: []
    property Item toastItem: null
    readonly property string toastText: toastItem ? toastItem.text : ""  // what is on show (tests)
    readonly property bool toastShown: !!toastItem && toastItem.visible && toastItem.opacity > 0

    function dismissToast() {
        if (root.toastItem)
            root.toastItem.dismiss();
    }

    anchors.fill: parent
    objectName: "overlays"

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
    Instantiator {
        model: root.notifiers

        delegate: Connections {
            id: link

            required property var modelData

            function onChooseRequested(token, words) {
                root.chooseSource = link.modelData;
                root.chooseToken = token;
                root.chosenKey = "";
                root.chooseCancel = words.cancel;
                choose.words = words;
                choose.open();
            }
            function onConfirmFullRequested(token, words) {
                root.fullSource = link.modelData;
                full.token = token;
                full.applied = false;
                full.words = words;
                full.optionOn = words.optionChecked;
                full.open();
            }
            function onConfirmRequested(token, title, changes, safety, applyText, destructive) {
                root.confirmSource = link.modelData;
                root.confirmToken = token;
                root.confirmed = false;
                confirm.title = title;
                confirm.message = changes.map(function (c) {
                    return "• " + c;
                }).concat(safety ? ["", safety] : []).join("
");
                confirm.primaryText = applyText;
                confirm.destructive = destructive;
                confirm.open();
            }
            function onToastActionRequested(text, isError, actionLabel, token) {
                root.dismissToast();
                root.toastItem = toastComponent.createObject(overlay, {
                    "objectName": "toast",
                    "text": text,
                    "isError": isError,
                    "actionLabel": actionLabel,
                    "action": function () {
                        link.modelData.toastAction(token);
                    }
                });
            }
            function onToastRequested(text, isError) {
                root.dismissToast();
                root.toastItem = toastComponent.createObject(overlay, {
                    "objectName": "toast",
                    "text": text,
                    "isError": isError
                });
            }

            target: link.modelData
        }
    }
    ConfirmDialog {
        id: confirm

        onClosed: root.confirmSource.answer(root.confirmToken, root.confirmed)
        onConfirm: function () {
            root.confirmed = true;
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

        onClosed: root.fullSource.answerWith(full.token, full.applied, full.optionOn)

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
    ModalDialog {  // a fork: the question, what happens, and verbs for each way (Cancel last, Esc cancels)
        id: choose

        property var words: ({})

        preferredWidth: 520
        title: words.title || ""

        footerRow: [
            Repeater {
                model: choose.words.choices || []

                delegate: Loader {
                    id: slot

                    required property var modelData

                    sourceComponent: modelData.role === "normal" && modelData.key === choose.words.cancel ? ghost : modelData.role === "normal" ? ghost : primary

                    Component {
                        id: primary

                        PrimaryButton {
                            danger: slot.modelData.role === "danger"
                            text: slot.modelData.label

                            onClicked: {
                                root.chosenKey = slot.modelData.key;
                                choose.close();
                            }
                        }
                    }
                    Component {
                        id: ghost

                        GhostButton {
                            text: slot.modelData.label

                            onClicked: {
                                root.chosenKey = slot.modelData.key;
                                choose.close();
                            }
                        }
                    }
                }
            }
        ]

        onClosed: root.chooseSource.chosen(root.chooseToken, root.chosenKey !== "" ? root.chosenKey : root.chooseCancel)

        Column {
            spacing: Theme.sp8
            width: parent.width

            Repeater {
                model: choose.words.lines || []

                Txt {
                    required property string modelData

                    elide: Text.ElideNone
                    text: modelData
                    width: parent.width
                    wrapMode: Text.WordWrap
                }
            }
            Txt {
                color: Theme.statusDanger
                elide: Text.ElideNone
                text: choose.words.warning || ""
                visible: text !== ""
                width: parent.width
                wrapMode: Text.WordWrap
            }
            Txt {
                elide: Text.ElideNone
                kind: "hint"
                text: choose.words.safety || ""
                visible: text !== ""
                width: parent.width
                wrapMode: Text.WordWrap
            }
        }
    }
}
