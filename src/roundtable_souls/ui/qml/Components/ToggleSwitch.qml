pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import Theme
import App

// The enable switch on a mod row: Fluent's pill shape. Off: 6% fill with a secondary-text outline; on: accent with
// a tight glow ring (ring 0 0 4 at glow.ring: v2.5 C). The knob moves in 140 ms with a small overshoot (v2.5 E).
Switch {
    id: root

    focusPolicy: Qt.TabFocus
    hoverEnabled: true
    implicitHeight: 22
    implicitWidth: 44

    contentItem: Item {
    }
    indicator: Item {
        implicitHeight: 22
        implicitWidth: 44

        Repeater {  // the on-state ring: 1 px rings 1 and 2 px out, fading (v2.12: was two filled 2 px slabs)
            model: 2

            Rectangle {
                required property int index

                anchors.fill: track
                anchors.margins: -(index + 1)
                border.color: Theme.glowColor
                border.width: 1
                color: "transparent"
                opacity: root.checked && AppState.effects === "full" ? Theme.glowRing.a * (index === 0 ? 0.5 : 0.2) : 0
                radius: height / 2

                Behavior on opacity {
                    NumberAnimation {
                        duration: Theme.mToggle
                        easing.type: Easing.OutCubic
                    }
                }
            }
        }
        Rectangle {
            id: track

            anchors.fill: parent
            border.color: Theme.textSecondary
            border.width: root.checked ? 0 : 1
            color: root.checked ? (root.down ? Theme.accentPress : root.hovered ? Theme.accentHover : Theme.accent) : (root.down ? Theme.fillGhostPress : root.hovered ? Theme.fillGhostHover : Theme.fillGhost)
            radius: 11

            Behavior on color {
                ColorAnimation {
                    duration: Theme.mFast
                    easing.type: Easing.OutCubic
                }
            }

            Rectangle {
                color: root.checked ? Theme.textOnAccent : Theme.textSecondary
                height: 14
                radius: 7
                width: root.down ? 16 : 14
                x: root.checked ? parent.width - width - 4 : 4
                y: 4

                Behavior on color {
                    ColorAnimation {
                        duration: Theme.mToggle
                        easing.type: Easing.OutCubic
                    }
                }
                Behavior on width {
                    NumberAnimation {
                        duration: Theme.mPress
                        easing.type: Easing.OutCubic
                    }
                }
                Behavior on x {
                    NumberAnimation {
                        duration: Theme.mToggle
                        easing.overshoot: 1.2       // about 5% past the end, then settles (v2.5 E "1.05 overshoot")
                        easing.type: Easing.OutBack
                    }
                }
            }
        }
        FocusRing {
            active: root.visualFocus
            anchors.fill: track
            radiusOf: 11
        }
    }
    HoverHandler {  // the hand over anything that can be clicked, the arrow when it is off
        cursorShape: root.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
    }
}
