pragma ComponentBehavior: Bound
import QtQuick
import Theme
import Components

// The page a game without support yet shows (Dark Souls III, Sekiro): what Roundtable Souls found for it, and nothing
// to press that could touch its files. Launch is blocked ("Not supported yet"); the rail shows Activity and Settings.
PageScroll {
    id: page

    required property var adapter
    readonly property var info: adapter.placeholder

    maxContentWidth: Theme.formMaxW
    objectName: "placeholderPage"

    Txt {
        kind: "page"
        text: page.info.title
    }
    Txt {
        elide: Text.ElideNone
        kind: "hint"
        text: page.info.intro
        width: parent ? parent.width : 0
        wrapMode: Text.WordWrap
    }
    Card {
        width: parent ? parent.width : 0

        Column {
            spacing: Theme.sp12
            width: parent.width

            Txt {
                kind: "section"
                text: page.info.foundTitle
            }
            Repeater {
                model: page.info.rows

                Row {
                    id: foundRow

                    required property var modelData

                    spacing: Theme.sp12

                    Txt {
                        color: Theme.textSecondary
                        text: foundRow.modelData.label
                        width: 110
                    }
                    Txt {
                        elide: Text.ElideMiddle
                        text: foundRow.modelData.value
                        width: Math.max(100, page.width - 220)
                    }
                }
            }
            Row {
                spacing: Theme.sp8

                GhostButton {
                    enabled: page.info.gameFolder !== ""
                    icon_: "Game"
                    text: page.info.gameButton

                    onClicked: page.adapter.openFolder(page.info.gameFolder)
                }
                GhostButton {
                    enabled: page.info.savesFolder !== ""
                    icon_: "Folder"
                    text: page.info.savesButton

                    onClicked: page.adapter.openFolder(page.info.savesFolder)
                }
            }
        }
    }
}
