pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Window
import Theme
import App
import Components

// The title rows (technical specification §8.10, Shell). Row 1, the menu bar on the darkest chrome colour: the logo
// (no app name) and the menus. Row 2, on the rail's colour: the rail's collapse button (far left, v2.2 A), the split
// Launch pill, the game and profile drop-downs, and the status text (the one place launcher state shows: its words,
// its colour and the link that fixes it come from the shell adapter). Under 820 px the status text becomes a dot on
// the Launch pill.
Item {
    id: root

    property real captionLeftW: 0   // space for macOS traffic lights (native chrome)
    property real captionW: 0       // space for the OS caption buttons on the right (native chrome)
    property real chromeTop: 0      // the OS title bar height when the client area extends under it
    property bool compact: false
    property bool nativeChrome: false
    readonly property int menuRowHeight: nativeChrome ? Math.max(Theme.menuRowH, Math.ceil(chromeTop)) : Theme.menuRowH
    required property var shell
    readonly property var st: shell.status
    readonly property color statusColor: st.tone === "danger" ? Theme.statusDanger : st.tone === "accent" ? Theme.accent : Theme.textSecondary
    property Window window

    function openLaunchMenu() {
        launch.openMenu();
    }

    implicitHeight: menuRowHeight + Theme.barRowH

    // ---------------------------------------------------------------- row 1: the menu bar
    Rectangle {
        id: menuRow

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        color: Theme.surfaceChrome
        height: root.menuRowHeight

        Behavior on color {
            ColorAnimation {
                duration: Theme.mPage
            }
        }

        MouseArea {  // the drag strip; stops short of the OS caption buttons under native chrome, which Qt hit-tests itself
            anchors.fill: parent
            anchors.leftMargin: root.captionLeftW
            anchors.rightMargin: root.captionW

            onDoubleClicked: root.window.visibility === Window.Maximized ? root.window.showNormal() : root.window.showMaximized()
            onPressed: root.window.startSystemMove()
        }
        Row {
            anchors.left: parent.left
            anchors.leftMargin: Theme.sp12 + root.captionLeftW
            anchors.verticalCenter: parent.verticalCenter
            spacing: 2

            Image {
                anchors.verticalCenter: parent.verticalCenter
                fillMode: Image.PreserveAspectFit
                height: 18
                source: root.shell.logoMode === "light" || (root.shell.logoMode === "auto" && !Theme.dark) ? root.shell.logoLight : root.shell.logoDark
                sourceSize: Qt.size(36, 36)
                width: 18
            }
            Item {
                height: 1
                width: 8
            }
            Repeater {
                model: root.shell.menuBar

                MenuButton {
                    id: mb

                    required property var modelData

                    menu: dataMenu
                    text: modelData.title

                    DataMenu {
                        id: dataMenu

                        rows: mb.modelData.model
                        shell: root.shell
                    }
                }
            }
        }
        Row {  // our own caption buttons, out of the Tab order like a native title bar; hidden under native chrome
            anchors.right: parent.right
            anchors.top: parent.top
            visible: !root.nativeChrome

            IconButton {
                ToolTip.text: qsTr("Minimise")
                focusPolicy: Qt.NoFocus
                hoverColor: Theme.surfaceRow
                iconSize: 11
                icon_: "ChromeMinimize"
                implicitHeight: root.menuRowHeight
                implicitWidth: 44

                onClicked: root.window.showMinimized()
            }
            IconButton {
                ToolTip.text: root.window.visibility === Window.Maximized ? qsTr("Restore") : qsTr("Maximise")
                focusPolicy: Qt.NoFocus
                hoverColor: Theme.surfaceRow
                iconSize: 11
                icon_: root.window.visibility === Window.Maximized ? "ChromeRestore" : "ChromeMaximize"
                implicitHeight: root.menuRowHeight
                implicitWidth: 44

                onClicked: root.window.visibility === Window.Maximized ? root.window.showNormal() : root.window.showMaximized()
            }
            IconButton {
                ToolTip.text: qsTr("Close")
                focusPolicy: Qt.NoFocus
                hoverColor: "#C42B1C"   // the caption red of Windows, the one colour that is not a token on purpose
                iconSize: 11
                icon_: "Close"
                implicitHeight: root.menuRowHeight
                implicitWidth: 44
                pressColor: "#A2261A"

                onClicked: root.window.close()
            }
        }
    }

    // ---------------------------------------------------------------- row 2: collapse, Launch, game, profile, status
    Item {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: menuRow.bottom
        height: Theme.barRowH

        MouseArea {
            anchors.fill: parent

            onPressed: root.window.startSystemMove()
        }
        Row {
            anchors.left: parent.left
            anchors.leftMargin: Theme.sp8
            anchors.verticalCenter: parent.verticalCenter
            spacing: Theme.gapInline

            IconButton {  // the rail's collapse button: far left, level with Launch (v2.2 A)
                ToolTip.text: root.shell.railCollapsed ? qsTr("Expand navigation") : qsTr("Collapse navigation")
                anchors.verticalCenter: parent.verticalCenter
                hoverColor: Theme.surfaceRow
                icon_: "Menu"
                implicitHeight: Theme.controlLargeH
                implicitWidth: 36
                pressColor: Theme.surfacePressed

                onClicked: root.shell.toggleRail()
            }
            LaunchPill {
                id: launch

                anchors.verticalCenter: parent.verticalCenter
                compact: root.compact
                shell: root.shell
                statusColor: root.statusColor
                statusText: root.st.text + (root.st.linkText !== "" ? "  ·  " + root.st.linkText : "")

                // the compact dot: the fix link's action when there is one, else the job in Activity
                onStatusClicked: {
                    if (root.st.linkAction !== "")
                        root.shell.followLink(root.st.linkAction);
                    else
                        root.shell.statusClicked();
                }
            }
            DropButton {
                id: gameButton

                anchors.verticalCenter: parent.verticalCenter
                enabled: root.shell.pill.state !== "busy"
                fixedWidth: Theme.pickerGameW
                icon_: "Game"
                opacity: enabled ? 1 : 0.6
                text: root.compact ? root.shell.gameShort : root.shell.gameName

                Component.onCompleted: background.radius = Theme.radiusCard  // Launch, game and profile share the radius

                Repeater {
                    model: root.shell.games

                    MenuEntry {
                        required property var modelData

                        checked: modelData.checked
                        shortcut: modelData.status
                        text: modelData.name

                        onTriggered: root.shell.requestGame(modelData.key)
                    }
                }
            }
            DropButton {
                id: profileButton

                anchors.verticalCenter: parent.verticalCenter
                enabled: root.shell.profileMenu.enabled
                fixedWidth: Theme.pickerProfileW
                opacity: enabled ? 1 : 0.6
                text: root.shell.profileMenu.current

                Component.onCompleted: background.radius = Theme.radiusCard

                Repeater {
                    model: root.shell.profileMenu.entries

                    MenuEntry {
                        required property var modelData

                        checked: modelData.checked
                        shortcut: modelData.managed ? root.shell.profileMenu.managedTag : ""
                        text: modelData.label

                        onTriggered: root.shell.pickProfile(modelData.index)
                    }
                }
                MenuSep {
                }
                MenuEntry {
                    icon_: "Add"
                    text: root.shell.profileMenu.newText

                    onTriggered: root.shell.followLink("new_profile")
                }
            }
            Item {  // the status text; its link goes to the fix; a click opens Activity; a failed job stays red until clicked
                anchors.verticalCenter: parent.verticalCenter
                height: 20
                visible: !root.compact
                width: statusRow.implicitWidth

                Row {
                    id: statusRow

                    anchors.verticalCenter: parent.verticalCenter
                    spacing: Theme.sp8

                    Spinner {
                        anchors.verticalCenter: parent.verticalCenter
                        color: Theme.accent
                        size: 12
                        visible: root.st.busy
                    }
                    Txt {
                        anchors.verticalCenter: parent.verticalCenter
                        color: root.statusColor
                        elide: Text.ElideNone
                        kind: "caption"
                        text: root.st.text
                    }
                    Txt {
                        anchors.verticalCenter: parent.verticalCenter
                        color: Theme.textSecondary
                        kind: "caption"
                        text: "·"
                        visible: root.st.linkText !== ""
                    }
                    Txt {
                        anchors.verticalCenter: parent.verticalCenter
                        color: Theme.accent
                        elide: Text.ElideNone
                        font.underline: true
                        kind: "caption"
                        text: root.st.linkText
                        visible: root.st.linkText !== ""

                        MouseArea {
                            anchors.fill: parent
                            anchors.margins: -4
                            cursorShape: Qt.PointingHandCursor

                            onClicked: root.shell.followLink(root.st.linkAction)
                        }
                    }
                }
                MouseArea {
                    ToolTip.text: qsTr("Open in Activity")
                    ToolTip.visible: containsMouse && root.st.toActivity && root.st.text !== qsTr("Ready")
                    anchors.fill: parent
                    anchors.rightMargin: root.st.linkText !== "" ? statusRow.implicitWidth / 2 : 0
                    cursorShape: root.st.toActivity ? Qt.PointingHandCursor : Qt.ArrowCursor
                    enabled: root.st.toActivity
                    hoverEnabled: true

                    onClicked: root.shell.statusClicked()
                }
            }
        }
    }

    // ---------------------------------------------------------------- first-run hints (one at a time)
    TeachingTip {
        parent: Overlay.overlay
        text: qsTr("Launch runs the selected profile. The mode word picks Profile, Offline or Vanilla.")
        visible: !root.compact && root.shell.tips.indexOf("launch") >= 0 && root.shell.pill.state === "enabled"   // not over the first-run page text while Launch is blocked
        x: 8 + 36 + 10 + 8
        y: root.implicitHeight + 6
        z: 30

        onDismissed: root.shell.dismissTip("launch")
    }
    TeachingTip {
        parent: Overlay.overlay
        text: qsTr("This folds the navigation to icons. Click again for the labels; narrow windows fold it on their own.")
        visible: !root.compact && root.shell.tips.indexOf("launch") < 0 && root.shell.tips.indexOf("rail") >= 0
        x: 8
        y: root.implicitHeight + 6
        z: 30

        onDismissed: root.shell.dismissTip("rail")
    }

    component MenuButton: Button {
        id: mbtn

        property PopupMenu menu

        anchors.verticalCenter: parent.verticalCenter
        focusPolicy: Qt.TabFocus
        hoverEnabled: true
        implicitHeight: Theme.menuRowH - 6
        implicitWidth: label.implicitWidth + 18

        background: Rectangle {
            color: mbtn.down || (mbtn.menu && mbtn.menu.visible) ? Theme.surfacePressed : mbtn.hovered ? Theme.surfaceRow : "transparent"
            radius: Theme.radiusControl
        }
        contentItem: Txt {
            id: label

            color: Theme.textPrimary
            horizontalAlignment: Text.AlignHCenter
            kind: "caption"
            text: mbtn.text
        }

        onClicked: {
            menu.parent = mbtn;
            menu.y = mbtn.height + 2;
            menu.open();
        }
    }
}
