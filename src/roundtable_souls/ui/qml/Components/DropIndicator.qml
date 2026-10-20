import QtQuick
import Theme

// The insertion line of a drag (spec §8.10): gold where the drop is allowed; red where me3's rules (or a running job) would refuse it (the words are drawn by the page, above the lifted row). Used by Mods rows; Saves uses the same colours.
Item {
    id: root

    property Item overlay          // the page's drag overlay: the reason is drawn there, above the lifted row
    property string reason: ""


    height: 2
    objectName: "dropIndicator"

    Rectangle {
        anchors.fill: parent
        color: root.reason !== "" ? Theme.statusDanger : Theme.accent
        radius: 1
    }
}
