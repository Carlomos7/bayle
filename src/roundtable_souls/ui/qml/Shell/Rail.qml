pragma ComponentBehavior: Bound
import QtQuick
import Theme
import App
import Components

// The navigation rail (technical specification §8.10): Mods (landing page), Mod Configs, Saves, Activity; Settings
// pinned at the bottom. The collapse button lives in the top bar (v2.2 A); the rail folds to icons when the setting
// says so or the window is narrow. A game without support shows only Activity and Settings (the adapter lists what
// to show). Activity carries the unseen-failures badge. Keys: Ctrl+1..5 in rail order.
Item {
    id: root

    property bool autoCollapse: false
    readonly property bool collapsed: (!!shell && shell.railCollapsed) || autoCollapse
    readonly property var items: shell ? shell.rail : []
    readonly property var pinned: items.filter(it => it.name === "settings")
    property var shell
    readonly property var upper: items.filter(it => it.name !== "settings")

    width: collapsed ? Theme.railCollapsedW : Theme.railW

    Behavior on width {
        NumberAnimation {
            duration: Theme.mRail
            easing.type: Easing.OutCubic
        }
    }

    Column {
        anchors.top: parent.top
        anchors.topMargin: Theme.sp12
        spacing: 2

        Repeater {
            model: root.upper

            RailItem {
                required property var modelData

                badge: modelData.badge
                iconName: modelData.icon
                label: modelData.label
                page: modelData.name
            }
        }
    }
    Column {
        anchors.bottom: parent.bottom
        anchors.bottomMargin: Theme.sp8
        spacing: 2

        Repeater {
            model: root.pinned

            RailItem {
                required property var modelData

                badge: 0
                iconName: modelData.icon
                label: modelData.label
                page: modelData.name
            }
        }
    }

    component RailItem: Rectangle {
        id: railItem

        property int badge: 0
        property string iconName
        property string label
        property string page
        readonly property bool selected: root.shell.railPage === page

        activeFocusOnTab: true
        color: mouse.pressed ? Theme.fillGhostPress : "transparent"
        height: 40
        radius: Theme.radiusControl
        width: root.width - 8
        x: 4

        Behavior on color {
            ColorAnimation {
                duration: Theme.mFast
            }
        }

        Keys.onPressed: event => {
            if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space) {
                root.shell.goTo(railItem.page);
                event.accepted = true;
            }
        }

        Smear {  // gold smear when selected, soft smear on hover (v2.8)
            anchors.fill: parent
            peak: 0.18
            radius: Theme.radiusControl
            strength: railItem.selected || mouse.containsMouse ? 1 : 0
            tint: railItem.selected ? Theme.smearSelected : Theme.smearHover
        }
        Rectangle {  // the selected item's glow: the accent bleeding from the bar at ~12%; off with Effects = Off
            anchors.left: parent.left
            anchors.leftMargin: 2
            anchors.verticalCenter: parent.verticalCenter
            height: 28
            opacity: railItem.selected && AppState.effects !== "off" ? (AppState.effects === "reduced" ? 0.6 : 1) : 0
            width: 3 + 8

            gradient: Gradient {
                orientation: Gradient.Horizontal

                GradientStop {
                    color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.12)
                    position: 0
                }
                GradientStop {
                    color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0)
                    position: 1
                }
            }

            Behavior on opacity {
                NumberAnimation {
                    duration: Theme.mFast
                }
            }
        }
        Rectangle {  // the 3 px accent bar
            anchors.left: parent.left
            anchors.leftMargin: 2
            anchors.verticalCenter: parent.verticalCenter
            color: Theme.goldText
            height: 20
            opacity: railItem.selected ? 1 : 0
            radius: 1.5
            width: 3

            Behavior on opacity {
                NumberAnimation {
                    duration: Theme.mFast
                }
            }
        }
        FocusRing {
            active: railItem.activeFocus
            radiusOf: Theme.radiusControl
        }
        FluentIcon {  // 20 px in the rail (v2.5 D)
            anchors.left: parent.left
            anchors.leftMargin: Theme.sp12
            anchors.verticalCenter: parent.verticalCenter
            color: railItem.selected ? Theme.goldText : Theme.textPrimary
            name: railItem.iconName
            size: 20
        }
        Text {
            anchors.left: parent.left
            anchors.leftMargin: 44
            anchors.verticalCenter: parent.verticalCenter
            color: railItem.selected ? Theme.goldText : Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontBody
            opacity: root.collapsed ? 0 : 1
            text: railItem.label
            visible: opacity > 0

            Behavior on opacity {
                NumberAnimation {
                    duration: Theme.mFast
                }
            }
        }
        Rectangle {  // the unseen-failures badge
            anchors.right: parent.right
            anchors.rightMargin: root.collapsed ? 2 : 10
            anchors.verticalCenter: parent.verticalCenter
            anchors.verticalCenterOffset: root.collapsed ? -11 : 0
            color: Theme.statusBadge
            height: 18
            radius: 9
            visible: railItem.badge > 0
            width: Math.max(18, badgeText.implicitWidth + 8)

            Text {
                id: badgeText

                anchors.centerIn: parent
                color: "white"
                font.pixelSize: Theme.fontCaption
                font.weight: Font.DemiBold
                text: railItem.badge > 99 ? "99+" : railItem.badge
            }
        }
        MouseArea {
            id: mouse

            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            hoverEnabled: true

            onClicked: root.shell.goTo(railItem.page)
        }
        ToolTipText {
            show: root.collapsed && mouse.containsMouse
            target: railItem
            text: railItem.label + (railItem.badge > 0 ? "  ·  " + qsTr("%1 failed since you last looked").arg(railItem.badge) : "")
        }
    }
}
