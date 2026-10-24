pragma ComponentBehavior: Bound
import QtQuick
import App
import Theme

// The inset page's atmosphere (v2.5 F), under the page content and over the surface colour:
//   1. blooms: pre-rendered 1024 px PNGs (gen_atmosphere.py), never scaled; dark = gold top-left (8 %) + ember
//      bottom-right (5 %), light = moonlight top-left (7 %, the frost bloom of v2.5 C at the inset corner) + white
//      bottom-right. Blooms stay in every Effects mode.
//   2. the vignette: 8 % black at the corners, dark theme only, off with Effects = Off.
//   3. the grain (Grain.qml), on top of both.
//   4. the luminous edge: a 1 px line where the inset meets the L, accent 0 > 12 % > 0 along the top edge and down
//      the left edge (Theme.atmosphereLuminousEdge); the gradient is 0 at the rounded corner, so no gap shows.
// `clip` is rectangular, so the bloom would paint the 12 px outside the inset's rounded corner: a Canvas patch
// repaints the bar colour there (software-safe; MultiEffect is not).
Item {
    id: root

    property bool cornerPatch: true
    property bool luminousEdge: true

    clip: true

    Image {  // bloom A: top-left. The PNG's centre is at 1/3 of the image; the centre lands ~200 px in and ~50 px down
        cache: true
        height: 1024
        smooth: true
        source: Qt.resolvedUrl(Theme.dark ? "../../assets/atmosphere/bloom-dark-a.png" : "../../assets/atmosphere/bloom-light-a.png")
        sourceSize: Qt.size(1024, 1024)
        width: 1024
        x: Math.round(Math.min(200, root.width * 0.18)) - 341
        y: 50 - 341
    }
    Image {  // bloom B: bottom-right. The PNG's centre is at 2/3; the centre lands ~160 px in from the right, ~100 px up
        cache: true
        height: 1024
        smooth: true
        source: Qt.resolvedUrl(Theme.dark ? "../../assets/atmosphere/bloom-dark-b.png" : "../../assets/atmosphere/bloom-light-b.png")
        sourceSize: Qt.size(1024, 1024)
        width: 1024
        x: Math.round(root.width - 160) - 682
        y: Math.round(root.height - 100) - 682
    }
    Image {  // the vignette: dark only; the gradient stretches cleanly
        anchors.fill: parent
        cache: true
        fillMode: Image.Stretch
        smooth: true
        source: Qt.resolvedUrl("../../assets/atmosphere/vignette-1024.png")
        sourceSize: Qt.size(1024, 1024)
        visible: Theme.dark && AppState.effects !== "off"
    }
    Grain {
        anchors.fill: parent
    }
    Canvas {  // the bar colour outside the inset's rounded corner (the Item clip is square)
        id: patch

        property color fill: Theme.surfaceBar

        antialiasing: true
        height: Theme.radiusInset
        visible: root.cornerPatch
        width: Theme.radiusInset

        onFillChanged: requestPaint()
        onPaint: {
            const c = getContext("2d");
            const r = width;
            c.reset();
            c.clearRect(0, 0, r, r);
            c.fillStyle = patch.fill;
            c.fillRect(0, 0, r, r);
            c.globalCompositeOperation = "destination-out";
            c.beginPath();
            c.arc(r, r, r, 0, Math.PI * 2);
            c.fill();
        }
    }
    Rectangle {  // the luminous edge along the top of the inset
        antialiasing: false
        height: 1
        visible: root.luminousEdge
        width: Math.max(0, root.width - Theme.radiusInset)
        x: Theme.radiusInset
        y: 0

        gradient: Gradient {
            orientation: Gradient.Horizontal

            GradientStop {
                color: "transparent"
                position: 0
            }
            GradientStop {
                color: Theme.atmosphereLuminousEdge
                position: 0.5
            }
            GradientStop {
                color: "transparent"
                position: 1
            }
        }
    }
    Rectangle {  // and down the left edge, where the inset meets the rail
        antialiasing: false
        height: Math.max(0, root.height - Theme.radiusInset)
        visible: root.luminousEdge
        width: 1
        x: 0
        y: Theme.radiusInset

        gradient: Gradient {
            orientation: Gradient.Vertical

            GradientStop {
                color: "transparent"
                position: 0
            }
            GradientStop {
                color: Theme.atmosphereLuminousEdge
                position: 0.5
            }
            GradientStop {
                color: "transparent"
                position: 1
            }
        }
    }
}
