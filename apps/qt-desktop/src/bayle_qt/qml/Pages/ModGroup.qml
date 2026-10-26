pragma ComponentBehavior: Bound
import QtQuick
import Theme
import Components

// A group on the Mods page (Packages, Natives (DLLs)): the header with the count, its lines ("N folders ... are not
// loaded · Add...", "<entry> loads nothing · Remove"), then one card of rows (ModRow), or one muted line when empty.
Column {
    id: groupRoot

    required property var adapter
    property Item dragLayer
    property var group: ({})
    property var model
    property var page

    spacing: Theme.sp8

    Row {
        spacing: Theme.sp8

        Txt {
            id: groupTitle

            kind: "section"
            text: groupRoot.group.title || ""
        }
        Txt {
            anchors.baseline: groupTitle.baseline
            kind: "hint"
            text: groupRoot.group.count || ""
        }
    }
    Repeater {
        model: groupRoot.group.lines || []

        Row {
            id: lineRow

            required property var modelData

            spacing: Theme.sp8

            Pill {
                anchors.verticalCenter: parent.verticalCenter
                icon_: "Info"
                level: "muted"
                text: groupRoot.adapter.words.loadsNothing
                visible: lineRow.modelData.index >= 0
            }
            Txt {
                anchors.verticalCenter: parent.verticalCenter
                kind: "hint"
                text: lineRow.modelData.text + "  ·"
            }
            Txt {
                anchors.verticalCenter: parent.verticalCenter
                color: Theme.accent
                kind: "caption"
                objectName: "lineAction_" + lineRow.modelData.index
                text: lineRow.modelData.action

                MouseArea {
                    anchors.fill: parent
                    anchors.margins: -4
                    cursorShape: Qt.PointingHandCursor

                    onClicked: {
                        if (lineRow.modelData.index >= 0)
                            groupRoot.adapter.removeHolder(lineRow.modelData.index);
                        else
                            groupRoot.adapter.addExisting(groupRoot.group.kind);
                    }
                }
            }
        }
    }
    Txt {
        kind: "hint"
        text: groupRoot.group.empty || ""
        visible: text !== ""
    }
    Card {  // one group = one card: rows inside, hairline dividers, no bordered rows
        padding: 0
        visible: rowList.count > 0
        width: parent ? parent.width : 0

        ListView {
            id: rowList

            height: contentHeight
            interactive: false
            model: groupRoot.model
            spacing: 0
            width: parent ? parent.width : 0

            delegate: ModRow {
                adapter: groupRoot.adapter
                count: rowList.count
                dragLayer: groupRoot.dragLayer
                page: groupRoot.page
                width: rowList.width
            }
        }
    }
}
