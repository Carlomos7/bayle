pragma ComponentBehavior: Bound
import QtQuick
import Theme

// A row of tabs with the accent underline (dialog tabs, the saved-copies Library / Backups tabs). The baseline is a
// hairline; the selected tab's underline is 2 px accent.
Item {
    id: root

    property int current: 0
    property var tabs: []

    implicitHeight: Theme.controlH
    implicitWidth: row.implicitWidth

    Row {
        id: row

        spacing: Theme.sp4

        Repeater {
            model: root.tabs

            Item {
                id: tabItem

                required property int index
                required property var modelData
                property bool selected: root.current === index

                height: Theme.controlH
                width: label.implicitWidth + 24

                Rectangle {
                    anchors.bottomMargin: 2
                    anchors.fill: parent
                    color: tabMouse.containsMouse ? Theme.fillHover : "transparent"
                    radius: Theme.radiusControl

                    Behavior on color {
                        ColorAnimation {
                            duration: Theme.mFast
                            easing.type: Easing.OutCubic
                        }
                    }
                }
                Txt {
                    id: label

                    anchors.centerIn: parent
                    color: tabItem.selected ? Theme.textPrimary : Theme.textSecondary
                    font.weight: tabItem.selected ? Font.DemiBold : Font.Normal
                    text: tabItem.modelData
                }
                Rectangle {
                    anchors.bottom: parent.bottom
                    anchors.horizontalCenter: parent.horizontalCenter
                    color: Theme.accent
                    height: 2
                    radius: 1
                    visible: tabItem.selected
                    width: parent.width - 16
                }
                MouseArea {
                    id: tabMouse

                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    hoverEnabled: true

                    onClicked: root.current = tabItem.index
                }
            }
        }
    }
    Hairline {
        y: Math.round(root.height) - 1
    }
}
