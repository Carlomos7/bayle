pragma ComponentBehavior: Bound
import QtQuick
import Theme
import Components

// The Load order panel (§8.10), a right-hand side panel: the mod that must stay last with Fix order; the files two
// packages both ship, who wins and what is combined, Show all, Rescan; the entries me3 would refuse.
SidePanel {
    id: panel

    required property var adapter
    readonly property var data_: adapter.panel
    readonly property var words: adapter.words

    objectName: "loadOrderPanel"
    panelWidth: 460
    title: words.loadOrder

    Column {
        spacing: Theme.sp16
        width: parent ? parent.width : 0

        Column {
            spacing: Theme.sp8
            visible: !!panel.data_.stays_last
            width: parent ? parent.width : 0

            Txt {
                kind: "strong"
                text: panel.words.staysLast
            }
            HoverRow {
                implicitHeight: Math.max(Theme.rowH, stayText.implicitHeight + Theme.sp16)
                pressable: false
                width: parent ? parent.width : 0

                Txt {
                    id: stayText

                    anchors.left: parent.left
                    anchors.right: fixBtn.left
                    anchors.rightMargin: Theme.sp8
                    anchors.verticalCenter: parent.verticalCenter
                    elide: Text.ElideNone
                    text: panel.data_.stays_last ? panel.data_.stays_last.text : ""
                    wrapMode: Text.WordWrap
                }
                GhostButton {
                    id: fixBtn

                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    enabled: panel.data_.stays_last ? panel.data_.stays_last.can_fix : false
                    implicitHeight: Theme.controlSmallH
                    text: panel.words.fixOrder

                    onClicked: panel.adapter.fixOrder()
                }
            }
        }
        Column {
            spacing: Theme.sp8
            width: parent ? parent.width : 0

            Item {
                height: Theme.controlSmallH
                width: parent ? parent.width : 0

                Txt {
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    kind: "strong"
                    text: panel.words.sharedFiles
                }
                GhostButton {
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    icon_: "Sync"
                    implicitHeight: Theme.controlSmallH
                    text: panel.words.rescan

                    onClicked: panel.adapter.refresh()
                }
            }
            Txt {
                elide: Text.ElideNone
                kind: "hint"
                text: panel.data_.error || panel.data_.clash_note || ""
                width: parent ? parent.width : 0
                wrapMode: Text.WordWrap
            }
            Column {
                spacing: 0
                width: parent ? parent.width : 0

                Repeater {
                    id: clashRows

                    model: panel.data_.clashes || []

                    HoverRow {
                        id: clashRow

                        required property int index
                        required property var modelData

                        divider: index < clashRows.count - 1
                        implicitHeight: Theme.rowH
                        pressable: false
                        width: parent ? parent.width : 0

                        Column {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 2

                            Txt {
                                text: clashRow.modelData.path
                                width: parent ? parent.width : 0
                            }
                            Txt {
                                color: clashRow.modelData.lost ? Theme.statusWarning : Theme.textSecondary
                                kind: "caption"
                                text: clashRow.modelData.winner + "  >  " + clashRow.modelData.losers
                                width: parent ? parent.width : 0
                            }
                        }
                    }
                }
            }
            Txt {
                color: Theme.accent
                kind: "caption"
                text: panel.adapter.showAll ? panel.words.showFewer : panel.words.showAll + " (" + (panel.data_.clash_total || 0) + ")"
                visible: (panel.data_.clash_total || 0) > (panel.data_.clashes || []).length || panel.adapter.showAll

                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor

                    onClicked: panel.adapter.setShowAll(!panel.adapter.showAll)
                }
            }
        }
        Column {
            spacing: Theme.sp8
            width: parent ? parent.width : 0

            Txt {
                kind: "strong"
                text: panel.words.refused
            }
            Txt {
                kind: "hint"
                text: panel.words.nothingRefused
                visible: (panel.data_.refused || []).length === 0
            }
            Repeater {
                model: panel.data_.refused || []

                Txt {
                    required property var modelData

                    elide: Text.ElideNone
                    text: modelData.name + "  ·  " + modelData.why
                    width: parent ? parent.width : 0
                    wrapMode: Text.WordWrap
                }
            }
        }
    }
}
