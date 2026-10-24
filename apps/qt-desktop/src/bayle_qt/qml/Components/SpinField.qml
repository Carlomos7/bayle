pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import Theme

// A number field (generated config forms): 6% fill, no border at rest, accent ring on focus. The stepper appears
// on hover or focus instead of stacked arrows that are always visible (v2.5 E).
Rectangle {
    id: root

    property bool error: false
    property int from: -999999
    property int to: 999999
    property int value: 0

    signal edited

    color: Theme.fillInput
    implicitHeight: Theme.controlH
    implicitWidth: Theme.inputShortW
    radius: Theme.radiusControl

    Behavior on color {
        ColorAnimation {
            duration: Theme.mToggle
            easing.type: Easing.OutCubic
        }
    }

    HoverHandler {
        id: hover
    }
    FocusRing {
        active: field.activeFocus
        error: root.error
        radiusOf: Theme.radiusControl
    }
    TextField {
        id: field

        anchors.left: parent.left
        anchors.right: arrows.left
        anchors.verticalCenter: parent.verticalCenter
        background: null
        color: Theme.textPrimary
        font.family: Theme.fontFamily
        font.features: ({
                "tnum": 1
            })
        font.pixelSize: Theme.fontBody
        leftPadding: Theme.sp10
        selectByMouse: true
        selectedTextColor: Theme.textOnAccent
        selectionColor: Theme.accent
        text: String(root.value)

        validator: IntValidator {
            bottom: root.from
            top: root.to
        }

        onEditingFinished: {
            root.value = parseInt(text) || 0;
            root.edited();
        }
    }
    Column {
        id: arrows

        anchors.right: parent.right
        anchors.rightMargin: 3
        anchors.verticalCenter: parent.verticalCenter
        opacity: hover.hovered || field.activeFocus ? 1 : 0
        visible: opacity > 0

        Behavior on opacity {
            NumberAnimation {
                duration: Theme.mFast
                easing.type: Easing.OutCubic
            }
        }

        IconButton {
            iconSize: 9
            icon_: "Up"
            implicitHeight: 13
            implicitWidth: 20

            onClicked: {
                root.value = Math.min(root.to, root.value + 1);
                root.edited();
            }
        }
        IconButton {
            iconSize: 9
            icon_: "Down"
            implicitHeight: 13
            implicitWidth: 20

            onClicked: {
                root.value = Math.max(root.from, root.value - 1);
                root.edited();
            }
        }
    }
}
