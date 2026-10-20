pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import Theme
import App

// The grip a row is dragged from (never the row itself, so a click never starts a drag). While dragging: the source
// dims, a one-line ghost (the label) follows the pointer in the overlay layer, the cursor is a closed hand (a
// forbidden sign over a spot that refuses: `refused`), Esc cancels, and the `scroller` page scrolls on a timer when
// the pointer nears its top or bottom edge. Drop spots are DropTarget items; they read `payload` from the source.
Item {
    id: root

    property string label: ""
    property var payload: ({})
    property bool refused: false     // the spot under the pointer refuses this drag
    property Flickable scroller      // the page to auto-scroll
    readonly property bool dragging: ma.drag.active
    property real pointerY: 0

    implicitHeight: Theme.rowH
    implicitWidth: 28
    objectName: "dragHandle"
    opacity: dragging ? 0.4 : 1

    Keys.onEscapePressed: event => {
        if (root.dragging) {
            ghost.Drag.cancel();
            ma.cancelled = true;
            event.accepted = true;
        }
    }

    FluentIcon {
        anchors.centerIn: parent
        color: Theme.textIcon
        name: "Move"
        size: Theme.iconRow
    }
    MouseArea {
        id: ma

        property bool cancelled: false

        anchors.fill: parent
        cursorShape: root.refused && root.dragging ? Qt.ForbiddenCursor : (pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor)
        drag.target: ghost
        objectName: "dragGrip"

        onPositionChanged: mouse => {
            if (root.dragging && root.scroller)
                root.pointerY = ma.mapToItem(root.scroller, mouse.x, mouse.y).y;
        }
        onReleased: {
            if (!cancelled && ghost.Drag.active)
                ghost.Drag.drop();   // deliver the drop to the spot under the pointer
        }
        onPressed: {
            cancelled = false;
            root.forceActiveFocus();   // Esc reaches the handle
        }
    }
    Timer {  // near an edge of the page the page scrolls, on a timer, not per pixel
        interval: 16
        repeat: true
        running: root.dragging && root.scroller !== null && !ma.cancelled

        onTriggered: {
            const s = root.scroller;
            const edge = 56;
            if (root.pointerY < edge)
                s.contentY = Math.max(0, s.contentY - 14);
            else if (root.pointerY > s.height - edge)
                s.contentY = Math.min(Math.max(0, s.contentHeight - s.height), s.contentY + 14);
        }
    }
    Rectangle {  // the ghost: icon + name, one line
        id: ghost

        Drag.active: ma.drag.active && !ma.cancelled
        Drag.hotSpot.x: 12
        Drag.hotSpot.y: 12
        Drag.keys: ["rs-drag"]
        Drag.source: root
        color: Theme.surfaceCard
        border.color: Theme.accent
        height: 28
        objectName: "dragGhost"
        radius: Theme.radiusCard
        visible: root.dragging && !ma.cancelled
        width: ghostText.implicitWidth + 2 * Theme.sp12

        states: State {
            when: root.dragging

            ParentChange {
                parent: AppState.overlayLayer ? AppState.overlayLayer : root
                target: ghost
            }
        }

        Txt {
            id: ghostText

            anchors.centerIn: parent
            kind: "caption"
            text: root.label
        }
    }
}
