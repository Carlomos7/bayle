pragma ComponentBehavior: Bound
import QtQuick
import Theme
import QtQuick.Controls.Basic

// A menu separator: one hairline, stopping short of the menu's edges (v2.5 D: two lines never meet at a corner).
MenuSeparator {
    padding: Theme.sp6

    contentItem: Item {
        implicitHeight: 1

        Hairline {
            endInset: 6
            inset: 6
        }
    }
}
