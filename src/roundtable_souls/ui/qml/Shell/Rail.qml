pragma ComponentBehavior: Bound
import QtQuick
import Theme

// The navigation rail (S9-Shell B4 fills it): the colour and the width for now.
Item {
    id: root

    property bool autoCollapse: false
    property var shell
    readonly property bool collapsed: autoCollapse

    width: collapsed ? Theme.railCollapsedW : Theme.railW
}
