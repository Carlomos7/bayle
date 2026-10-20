pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Window
import Theme

// The title rows (S9-Shell B5 fills them): the menu row on the chrome colour, the bar row on the rail's colour.
Item {
    id: root

    property bool compact: false
    property var shell
    property Window window
    readonly property int menuRowHeight: Theme.menuRowH

    implicitHeight: menuRowHeight + Theme.barRowH

    function openLaunchMenu() {
    }

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        color: Theme.surfaceChrome
        height: root.menuRowHeight
    }
}
