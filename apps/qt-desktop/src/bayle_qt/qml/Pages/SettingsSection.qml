pragma ComponentBehavior: Bound
import QtQuick
import Theme
import Components

// A Settings section (v2.5 D): the title with its icon OUTSIDE the card, as the Mods groups do, and the settings as the
// rows of ONE card with hairline dividers; the end rows take the card's corners. The rows are declared
// statically, so `relayout` sets first / last / divider from their order (and again when children change).
Column {
    id: section

    property string iconName
    default property alias rows: col.data
    property string title

    function relayout() {
        const kids = [];
        for (let i = 0; i < col.children.length; i++)
            if (col.children[i].visible && "divider" in col.children[i])  // a Repeater is a child too: skip it
                kids.push(col.children[i]);
        for (let i = 0; i < kids.length; i++) {
            const k = kids[i];
            k.first = i === 0;
            k.last = i === kids.length - 1;
            k.divider = i < kids.length - 1;
        }
    }

    spacing: Theme.sp8
    width: parent.width

    Component.onCompleted: relayout()

    Row {
        spacing: Theme.gapInline

        FluentIcon {
            anchors.verticalCenter: parent.verticalCenter
            name: section.iconName
            size: 18
        }
        Txt {
            anchors.verticalCenter: parent.verticalCenter
            kind: "section"
            text: section.title
        }
    }
    Card {
        padding: 0
        width: parent.width

        Column {
            id: col

            spacing: 0
            width: parent.width

            onChildrenChanged: section.relayout()
        }
    }
}
