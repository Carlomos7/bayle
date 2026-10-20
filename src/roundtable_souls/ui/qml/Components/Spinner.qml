pragma ComponentBehavior: Bound
import QtQuick
import Theme

// A small indeterminate ring (the busy Launch button, a running job).
Item {
    id: root

    property color color: Theme.textOnAccent
    property int size: 16
    property int thickness: 2

    implicitHeight: size
    implicitWidth: size

    Canvas {
        id: ringCanvas

        anchors.fill: parent

        RotationAnimation on rotation {
            duration: 900
            from: 0
            loops: Animation.Infinite
            running: root.visible
            to: 360
        }

        onPaint: {
            const ctx = getContext("2d");
            ctx.reset();
            ctx.lineWidth = root.thickness;
            ctx.strokeStyle = root.color;
            ctx.lineCap = "round";
            ctx.beginPath();
            ctx.arc(width / 2, height / 2, (width - root.thickness) / 2, 0, Math.PI * 1.4);
            ctx.stroke();
        }

        Connections {
            function onColorChanged() {
                ringCanvas.requestPaint();
            }

            target: root
        }
    }
}
