pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import Theme
import App
import Components

// The Launch pill (technical specification §8.10, Shell): one gold pill, no divider. The left zone (play icon and
// "Launch") runs the current mode; the right zone (the mode word and a chevron) opens the mode menu. States, from the
// shell adapter: enabled (gold), busy (the play icon becomes a spinner, "Launching..." or "Updating..."), running
// ("Running", greyed) and blocked (greyed; the reason is in the status text with its link). The pill keeps its width
// while busy (the mode zone hides and the left zone takes the room). Under 820 px the status text folds into a
// coloured dot on the pill: its text is the tooltip and a click runs the link. Ctrl+L launches, Ctrl+Shift+L opens
// the mode menu; the pill is in the Tab order but never focused at start.
Item {
    id: root

    property bool compact: false
    readonly property bool enabledNow: p.state === "enabled"
    readonly property color fg: greyed ? Theme.textTertiary : Theme.goldText
    readonly property bool glowOn: !greyed && AppState.effects !== "off"
    readonly property bool greyed: p.state === "blocked" || p.state === "running"
    readonly property bool hoveredNow: leftMouse.containsMouse || rightMouse.containsMouse
    readonly property int leftW: Math.max(launchMetrics.width, launchingMetrics.width, updatingMetrics.width) + 16 + 8 + 24
    readonly property var p: shell.pill
    readonly property int rightW: rightRow.implicitWidth + 16
    required property var shell
    readonly property bool showMode: p.state === "enabled" || p.state === "blocked"
    property color statusColor: Theme.textSecondary
    property string statusText: ""

    signal statusClicked

    function openMenu() {
        if (showMode)
            modeMenu.open();
    }

    activeFocusOnTab: true
    implicitHeight: Theme.controlLargeH
    implicitWidth: leftW + rightW + (compact ? 18 : 0)

    Keys.onPressed: event => {
        if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space) && root.enabledNow) {
            root.shell.launch();
            event.accepted = true;
        } else if (event.key === Qt.Key_Down) {
            root.openMenu();
            event.accepted = true;
        }
    }

    TextMetrics {
        id: launchMetrics

        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontBody
        font.weight: Font.DemiBold
        text: qsTr("Launch")
    }
    TextMetrics {
        id: launchingMetrics

        font: launchMetrics.font
        text: qsTr("Launching...")
    }
    TextMetrics {
        id: updatingMetrics

        font: launchMetrics.font
        text: qsTr("Updating...")
    }
    FocusRing {
        active: root.activeFocus  // mouse clicks go to the MouseAreas, never to the root, so this is keyboard-only
        radiusOf: Theme.radiusLaunch
    }
    GildedFrame {  // the primary style, the game's inner double frame, a faint resting glow (v2.9)
        anchors.fill: parent
        dim: root.greyed
        glow: true
        hot: root.hoveredNow && root.enabledNow
        inner: true
        pressed: leftMouse.pressed || rightMouse.pressed
        radius: Theme.radiusLaunch
    }
    Rectangle {  // the hovered half lights up alone (no drawn divider)
        color: leftMouse.pressed || rightMouse.pressed ? Theme.goldFillTopHover : Theme.goldFillTop
        height: parent.height - 8
        opacity: root.hoveredNow && root.enabledNow ? 1 : 0
        radius: 2
        width: leftMouse.containsMouse ? leftZone.width - 5 : rightZone.width - 5
        x: leftMouse.containsMouse ? 4 : leftZone.width + 1
        y: 4

        Behavior on opacity {
            NumberAnimation {
                duration: Theme.mFast
            }
        }
    }
    Item {
        id: leftZone

        anchors.left: parent.left
        height: parent.height
        width: root.showMode ? root.leftW : root.width - (root.compact ? 18 : 0)

        Behavior on width {
            NumberAnimation {
                duration: Theme.mPage
                easing.type: Easing.OutCubic
            }
        }

        Row {
            anchors.centerIn: parent
            spacing: Theme.sp8

            Item {  // the play icon morphs into the spinner (crossfade and a small scale); the layout does not move
                anchors.verticalCenter: parent.verticalCenter
                height: 16
                width: 16

                FluentIcon {
                    anchors.centerIn: parent
                    color: root.fg
                    name: "Play"
                    opacity: root.p.state === "busy" ? 0 : 1
                    scale: root.p.state === "busy" ? 0.6 : 1
                    size: 16

                    Behavior on opacity {
                        NumberAnimation {
                            duration: Theme.mPage
                        }
                    }
                    Behavior on scale {
                        NumberAnimation {
                            duration: Theme.mPage
                            easing.type: Easing.OutCubic
                        }
                    }
                }
                Spinner {
                    anchors.centerIn: parent
                    color: root.fg
                    opacity: root.p.state === "busy" ? 1 : 0
                    scale: root.p.state === "busy" ? 1 : 0.6
                    size: 16
                    visible: opacity > 0

                    Behavior on opacity {
                        NumberAnimation {
                            duration: Theme.mPage
                        }
                    }
                    Behavior on scale {
                        NumberAnimation {
                            duration: Theme.mPage
                            easing.type: Easing.OutCubic
                        }
                    }
                }
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                color: root.fg
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontBody
                font.weight: Font.DemiBold
                text: root.p.text
            }
        }
        MouseArea {
            id: leftMouse

            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            enabled: root.enabledNow
            hoverEnabled: true

            onClicked: root.shell.launch()
        }
    }
    Item {
        id: rightZone

        anchors.left: leftZone.right
        height: parent.height
        opacity: root.showMode ? 1 : 0
        visible: opacity > 0
        width: root.rightW

        Behavior on opacity {
            NumberAnimation {
                duration: Theme.mFast
            }
        }

        Row {
            id: rightRow

            anchors.centerIn: parent
            spacing: Theme.sp8

            Text {
                anchors.verticalCenter: parent.verticalCenter
                color: root.fg
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontBody
                font.weight: Font.Medium
                opacity: 0.72
                text: root.p.modeText
            }
            FluentIcon {
                anchors.verticalCenter: parent.verticalCenter
                color: root.fg
                name: "ChevronDown"
                size: 12
            }
        }
        MouseArea {
            id: rightMouse

            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            hoverEnabled: true

            onClicked: root.openMenu()
        }
    }
    Rectangle {  // the status dot (compact windows): the status text as its tooltip, a click runs the link
        Accessible.name: root.statusText
        Accessible.role: Accessible.Button

        Accessible.onPressAction: root.statusClicked()
        anchors.right: parent.right
        anchors.rightMargin: 7
        anchors.verticalCenter: parent.verticalCenter
        color: root.statusColor
        height: 8
        radius: 4
        visible: root.compact
        width: 8

        Behavior on color {
            ColorAnimation {
                duration: Theme.mFast
            }
        }

        MouseArea {
            ToolTip.delay: 200
            ToolTip.text: root.statusText
            ToolTip.visible: containsMouse
            anchors.fill: parent
            anchors.margins: -6
            cursorShape: Qt.PointingHandCursor
            hoverEnabled: true

            onClicked: root.statusClicked()
        }
    }
    PopupMenu {
        id: modeMenu

        minWidth: root.width
        y: root.height + 4

        Repeater {
            model: root.shell.modeMenu

            MenuEntry {
                required property var modelData

                checked: modelData.checked
                icon_: modelData.mode === "profile" ? "Play" : modelData.mode === "offline" ? "Cloud" : "Game"
                text: modelData.text

                onTriggered: root.shell.setMode(modelData.mode)
            }
        }
    }
}
