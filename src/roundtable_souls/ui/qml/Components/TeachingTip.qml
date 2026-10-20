pragma ComponentBehavior: Bound
import QtQuick
import Theme

// A first-run hint (Fluent's TeachingTip): a small callout with "Got it". Only for help and first-run hints,
// never for errors or results (v2.3 C). Floats (v2.5 D): no border, the floating shadow; the pointer stays.
Rectangle {
    id: root

    property string text

    signal dismissed

    color: "transparent"
    height: col.implicitHeight + 24
    width: Math.min(320, label.implicitWidth + 32)
    z: 20

    SoftShadow {
        elevation: "raise"
        radius: Theme.radiusOverlay
        target: body
    }
    Rectangle {
        id: body

        anchors.fill: parent
        color: Theme.surfaceCard
        radius: Theme.radiusOverlay

        Behavior on color {
            ColorAnimation {
                duration: Theme.mToggle
                easing.type: Easing.OutCubic
            }
        }
    }
    Rectangle {  // the pointer
        anchors.left: parent.left
        anchors.leftMargin: Theme.sp24
        anchors.top: parent.top
        anchors.topMargin: -5
        color: body.color
        height: 10
        rotation: 45
        width: 10
    }
    Column {
        id: col

        anchors.left: parent.left
        anchors.margins: Theme.sp12
        anchors.right: parent.right
        anchors.top: parent.top
        spacing: Theme.sp8

        Txt {
            id: label

            elide: Text.ElideNone
            text: root.text
            width: parent.width
            wrapMode: Text.WordWrap
        }
        GhostButton {
            anchors.right: parent.right
            implicitHeight: Theme.controlSmallH
            text: qsTr("Got it")

            onClicked: root.dismissed()
        }
    }
}
