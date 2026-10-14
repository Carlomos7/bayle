pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import Theme

// A setting row: title and a help line on the left, the control on the right (Settings, forms, dialogs). Like
// HoverRow it has no border, no radius and no raised fill (v2.5 D): hover = 4% fill, `divider` draws the hairline
// at the bottom (56 px in, 16 px short of the right edge). `flat` keeps working (no hover fill at all).
Rectangle {
    id: root

    default property alias control: slot.data
    property bool divider: false
    property bool first: false
    property bool flat: false
    property string help: ""
    property bool last: false
    property bool showHelpIcon: false
    property string title
    property string tooltip: ""

    bottomLeftRadius: last ? Theme.radiusCard : 0
    bottomRightRadius: last ? Theme.radiusCard : 0
    color: !flat && hover.containsMouse ? Theme.fillHover : "transparent"
    implicitHeight: Math.max(Theme.rowH, col.implicitHeight + 20)
    radius: 0
    topLeftRadius: first ? Theme.radiusCard : 0
    topRightRadius: first ? Theme.radiusCard : 0
    width: parent ? parent.width : 400

    Behavior on color {
        ColorAnimation {
            duration: Theme.mFast
            easing.type: Easing.OutCubic
        }
    }

    MouseArea {
        id: hover

        acceptedButtons: Qt.NoButton
        anchors.fill: parent
        hoverEnabled: true
    }
    Column {
        id: col

        anchors.left: parent.left
        anchors.leftMargin: Theme.sp16
        anchors.right: slot.left
        anchors.rightMargin: Theme.sp16
        anchors.verticalCenter: parent.verticalCenter
        spacing: Theme.sp4

        Row {
            spacing: Theme.gapInline

            Txt {
                anchors.verticalCenter: parent.verticalCenter
                text: root.title
            }
            IconButton {
                ToolTip.text: root.tooltip
                anchors.verticalCenter: parent.verticalCenter
                fg: Theme.textSecondary
                iconSize: 13
                icon_: "Help"
                implicitHeight: 22
                implicitWidth: 22
                visible: root.showHelpIcon && root.tooltip !== ""
            }
        }
        Txt {
            elide: Text.ElideNone
            kind: "hint"
            text: root.help
            visible: root.help !== ""
            width: col.width
            wrapMode: Text.WordWrap
        }
    }
    Item {
        id: slot

        anchors.right: parent.right
        anchors.rightMargin: Theme.sp16
        anchors.verticalCenter: parent.verticalCenter
        height: childrenRect.height
        width: childrenRect.width
    }
    Hairline {
        endInset: Theme.dividerEndInset
        inset: Theme.dividerInset
        visible: root.divider
        y: Math.round(root.height) - 1
    }
}
