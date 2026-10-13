pragma ComponentBehavior: Bound
import QtQuick
import App
import Theme

// A panel that slides in from the page's right edge (the Load order panel, a character's detail). Fill `content`.
// Under `fullBelow` px of page width it covers the whole page instead, with Back. Floats (v2.5 D / F): no border
// in full mode, a 1 px edge on its left otherwise, the floating shadow; the header divider is a hairline inset 16.
// Acrylic: `acrylicSlot` behind the body holds the Acrylic (blur + Theme.surfaceAcrylic; v2.5 F).
Item {
    id: root

    property bool acrylic: false   // v2.15 (owner): overlays are opaque; the blur is opt-in per instance
    default property alias content: inner.data
    readonly property bool full: (Window.window ? Window.window.width : (parent ? parent.width : 0)) < fullBelow  // v2.2 C: the window's width, as the Saves cards' breakpoint
    property int fullBelow: 1000
    property bool open: false
    property int panelWidth: 400               // the panel's preferred width; it is capped at 60 % of the page
    property string title

    anchors.fill: parent
    visible: open || dimmer.opacity > 0
    z: 50

    Item {  // the visuals live on the window's overlay layer (v2.5 F), a sibling of the inset surface with its
        //  geometry, so the acrylic's capture of the surface never includes the panel itself; without the layer
        //  (a bare page) they stay here
        id: panelLayer

        anchors.fill: parent
        parent: AppState.overlayLayer ? AppState.overlayLayer : root
        visible: root.visible
        z: 50

        Rectangle {  // dim the page behind
            id: dimmer

            anchors.fill: parent
            color: Theme.fillDim
            opacity: root.open ? 1 : 0
            topLeftRadius: Theme.radiusInset

            Behavior on opacity {
                NumberAnimation {
                    duration: Theme.mRail
                    easing.type: Easing.OutCubic
                }
            }

            MouseArea {
                anchors.fill: parent
                hoverEnabled: true

                onClicked: root.open = false
            }
        }
        SoftShadow {
            offsetY: 0
            elevation: "float"
            radius: 0
            target: panel
            visible: !root.full
        }
        Item {
            id: panel

            height: parent.height
            // v2.14: never more than 60 % of the page, so the page behind stays readable at 1000-1300 px
            width: root.full ? parent.width : Math.min(root.panelWidth, Math.round(parent.width * 0.6))
            x: root.open ? parent.width - width : parent.width

            Behavior on x {
                NumberAnimation {
                    duration: Theme.mRail
                    easing.type: Easing.OutCubic
                }
            }

            Item {
                id: acrylicSlot

                anchors.fill: parent

                Acrylic {  // 24 px blur of the page behind + the 70 / 80 % card tint; the opaque card without blur
                    active: root.acrylic
                    anchors.fill: parent
                    edge: false
                    radius: 0
                    topLeftRadius: root.full ? Theme.radiusInset : 0
                }
            }
            Rectangle {  // the shape the shadow follows; the acrylic paints the fill
                id: body

                anchors.fill: parent
                color: "transparent"
                topLeftRadius: root.full ? Theme.radiusInset : 0
            }
            Rectangle {  // the edge (only when the panel floats over the page)
                antialiasing: false
                color: Theme.borderEdge
                height: parent.height
                visible: !root.full
                width: 1
            }
            MouseArea {
                anchors.fill: parent
                hoverEnabled: true
            }  // swallow clicks
            Item {
                id: head

                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                height: 56

                Row {
                    anchors.left: parent.left
                    anchors.leftMargin: Theme.sp16
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: Theme.gapInline

                    GhostButton {
                        icon_: "Return"
                        implicitHeight: Theme.controlSmallH
                        text: qsTr("Back")
                        visible: root.full

                        onClicked: root.open = false
                    }
                    Txt {
                        anchors.verticalCenter: parent.verticalCenter
                        kind: "section"
                        text: root.title
                    }
                }
                IconButton {
                    anchors.right: parent.right
                    anchors.rightMargin: Theme.sp12
                    anchors.verticalCenter: parent.verticalCenter
                    iconSize: 12
                    icon_: "Close"
                    visible: !root.full

                    onClicked: root.open = false
                }
                Hairline {
                    endInset: Theme.sp16
                    inset: Theme.sp16
                    y: Math.round(head.height) - 1
                }
            }
            Flickable {
                anchors.bottom: parent.bottom
                anchors.left: parent.left
                anchors.margins: Theme.sp16
                anchors.right: parent.right
                anchors.top: head.bottom
                boundsBehavior: Flickable.StopAtBounds
                clip: true
                contentHeight: inner.childrenRect.height + 16

                Item {
                    id: inner

                    width: parent.width
                }
            }
        }
    }
}
