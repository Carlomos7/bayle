pragma ComponentBehavior: Bound
import QtQuick
import Theme

// A determinate progress bar: a pill track and an accent fill; `value` runs 0 to 1.
Rectangle {
    id: root

    property real value: 0

    Accessible.name: Math.round(value * 100) + "%"
    Accessible.role: Accessible.ProgressBar
    color: Theme.fillInput
    implicitHeight: 8
    implicitWidth: 200
    radius: height / 2

    Rectangle {
        color: Theme.accent
        height: parent.height
        radius: parent.radius
        width: parent.width * Math.max(0, Math.min(1, root.value))

        Behavior on width {
            NumberAnimation {
                duration: Theme.mFast
            }
        }
    }
}
