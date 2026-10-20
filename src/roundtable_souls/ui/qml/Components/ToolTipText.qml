pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import Theme

// A tooltip (v2.5 E): 500 ms delay, a dark card, 12 px type, no arrow, no border, the floating shadow. `placement`
// "right" sits beside `target` (a collapsed rail item), "below" centres under it (icon buttons).
ToolTip {
    id: tip

    property string placement: "right"
    property bool show: false
    property Item target

    delay: Theme.mTooltipDelay
    font.family: Theme.fontFamily
    font.pixelSize: Theme.fontCaption
    leftPadding: Theme.sp10
    padding: Theme.sp6
    rightPadding: Theme.sp10
    visible: show
    x: !target ? 0 : placement === "below" ? Math.round((target.width - width) / 2) : target.width + 8
    y: !target ? 0 : placement === "below" ? target.height + 6 : Math.round((target.height - height) / 2)

    background: Item {
        SoftShadow {
            elevation: "raise"
            radius: Theme.radiusControl
            target: body
        }
        Rectangle {
            id: body

            anchors.fill: parent
            color: Theme.surfaceCard
            radius: Theme.radiusControl

            Behavior on color {
                ColorAnimation {
                    duration: Theme.mToggle
                    easing.type: Easing.OutCubic
                }
            }
        }
    }
    contentItem: Text {
        color: Theme.textPrimary
        font: tip.font
        text: tip.text
        wrapMode: Text.WordWrap
    }
    enter: Transition {
        NumberAnimation {
            duration: Theme.mFast
            easing.type: Easing.OutCubic
            from: 0
            property: "opacity"
            to: 1
        }
    }
    exit: Transition {
        NumberAnimation {
            duration: Theme.mFast
            easing.type: Easing.OutCubic
            from: 1
            property: "opacity"
            to: 0
        }
    }
}
