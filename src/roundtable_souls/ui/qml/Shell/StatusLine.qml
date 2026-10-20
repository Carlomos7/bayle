pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import Theme
import Components

// The one line of launcher state (technical specification §8.10, Shell): the status text (its words, colour and link
// come from the shell adapter) and the link that fixes it. It sits in the top bar and, under 820 px, in a strip under
// it, so what Launch is waiting for or blocked by is always said in words, never by a coloured dot alone. The text
// gives way (elides) before the link does; the link is a button, so Tab reaches it and Enter or Space follows it.
Item {
    id: root

    property real maxWidth: 100000
    required property var shell
    readonly property var st: shell.status
    readonly property color tone: st.tone === "danger" ? Theme.statusDanger : st.tone === "warning" ? Theme.statusWarning : st.tone === "accent" ? Theme.accent : Theme.textSecondary

    height: 20
    width: Math.min(row.implicitWidth, maxWidth)

    Row {
        id: row

        anchors.verticalCenter: parent.verticalCenter
        spacing: Theme.sp8

        Spinner {
            anchors.verticalCenter: parent.verticalCenter
            color: Theme.accent
            size: 12
            visible: root.st.busy
        }
        Txt {
            id: label

            anchors.verticalCenter: parent.verticalCenter
            color: root.tone
            elide: Text.ElideRight
            kind: "caption"
            text: root.st.text
            width: Math.min(implicitWidth, Math.max(60, root.maxWidth - (root.st.linkText !== "" ? link.implicitWidth + 36 : 0) - (root.st.busy ? 20 : 0)))
        }
        Txt {
            anchors.verticalCenter: parent.verticalCenter
            color: Theme.textSecondary
            kind: "caption"
            text: "·"
            visible: root.st.linkText !== ""
        }
        Button {
            id: link

            anchors.verticalCenter: parent.verticalCenter
            focusPolicy: Qt.TabFocus
            hoverEnabled: true
            padding: 0
            text: root.st.linkText
            visible: text !== ""

            background: Item {
                FocusRing {
                    active: link.visualFocus
                    radiusOf: 3
                }
            }
            contentItem: Txt {
                color: Theme.accent
                elide: Text.ElideNone
                font.underline: true
                kind: "caption"
                text: link.text
            }

            HoverHandler {
                cursorShape: Qt.PointingHandCursor
            }

            onClicked: root.shell.followLink(root.st.linkAction)
        }
    }
    MouseArea {  // a click on the words opens the job in Activity (a failed job stays red until looked at)
        ToolTip.text: root.st.toActivity ? qsTr("Open in Activity") : root.st.text   // the whole words when they were cut short
        ToolTip.visible: containsMouse && (root.st.toActivity ? !root.st.idle : label.truncated)
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.top: parent.top
        cursorShape: root.st.toActivity ? Qt.PointingHandCursor : Qt.ArrowCursor
        hoverEnabled: true
        width: label.x + label.width

        onClicked: {
            if (root.st.toActivity)
                root.shell.statusClicked();
        }
    }
}
