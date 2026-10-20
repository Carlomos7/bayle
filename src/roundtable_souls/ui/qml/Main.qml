pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Window
import Theme
import App
import Components
import Shell

// The launcher's window (technical specification §8.10, Shell): the menu bar and top bar over the rail and the page,
// which form the L-shaped unit: chrome darkest, the bar and the rail one colour, the page a lighter inset with a
// rounded top-left corner. One engine, one window: each page is made the first time it is visited and kept alive
// (unsaved edits and scroll survive a switch; the unsaved prompt runs on leaving). Everything shown comes from the
// shell adapter (ui/launcher/adapter.py) and each page's own adapter.
ApplicationWindow {
    id: win

    readonly property real captionLeftW: nativeChrome && Qt.platform.os === "osx" ? 78 : 0  // the traffic lights
    readonly property real captionW: nativeChrome && Qt.platform.os === "windows" ? Math.round(chromeTop * 1.5) * 3 : 0  // Qt draws 3 buttons, each 1.5x the bar height
    property real chromeTop: 0  // the OS title bar height (from the probe), 0 when not native
    readonly property bool compact: width < Theme.compactBelow
    readonly property var currentNotifier: shell.notifierFor(shell.currentPage)
    required property var shell

    // Window chrome (v2.20). Windows and macOS on Qt 6.9+: the OS keeps the frame (rounded corners, shadow, Snap
    // Layouts, resize borders and the caption buttons) and our client area extends under the title bar, where the
    // menu row sits. Elsewhere, and off-screen (renders, the self-test): a frameless window with our own caption
    // buttons and edge resizers.
    readonly property bool nativeChrome: (Qt.platform.os === "windows" || Qt.platform.os === "osx") && Qt.platform.pluginName !== "offscreen" && Qt.ExpandedClientAreaHint !== undefined

    color: Theme.surfaceBar
    flags: nativeChrome ? Qt.Window | Qt.ExpandedClientAreaHint | Qt.NoTitleBarBackgroundHint | Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint | Qt.WindowCloseButtonHint : Qt.Window | Qt.FramelessWindowHint | Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint
    font.family: Theme.fontFamily
    height: 760
    minimumHeight: 540
    minimumWidth: 740
    title: "Roundtable Souls " + shell.version + " - " + shell.gameName
    width: 1100

    Component.onCompleted: {
        AppState.softwareRender = GraphicsInfo.api === GraphicsInfo.Software;
        AppState.setThemeMode(shell.themeMode);
        AppState.effects = shell.effects;
        AppState.grain = shell.grain;
    }
    onClosing: close => {
        if (!shell.closeApproved) {
            close.accepted = false;
            shell.requestClose();
        }
    }

    Connections {
        function onAppearanceChanged() {
            AppState.setThemeMode(win.shell.themeMode);
            AppState.effects = win.shell.effects;
            AppState.grain = win.shell.grain;
        }
        function onClosePrompt() {
            closeJob.open();
        }
        function onNewProfileRequested(suggested, seamless) {
            newProfile.ask(suggested, seamless);
        }
        function onQuitRequested() {
            win.close();
        }
        function onUnsavedPrompt(token, words, action) {
            unsaved.token = token;
            unsaved.words = words;
            unsaved.action = action;
            unsaved.open();
        }

        target: win.shell
    }

    // The themed card for every attached ToolTip (the one shared instance), as in the prototype.
    Item {
        Component.onCompleted: {
            const shared = ToolTip.toolTip;
            if (!shared)
                return;
            shared.delay = Theme.mTooltipDelay;
            shared.padding = 6;
            shared.leftPadding = 10;
            shared.rightPadding = 10;
            shared.font.family = Theme.fontFamily;
            shared.font.pixelSize = Theme.fontCaption;
            shared.palette.toolTipBase = Qt.binding(() => Theme.surfaceCard);
            shared.palette.toolTipText = Qt.binding(() => Theme.textPrimary);
            shared.palette.dark = Qt.binding(() => Theme.borderEdge);
            shared.background.radius = Theme.radiusControl;
            shared.y = Qt.binding(() => shared.parent ? shared.parent.height + 6 : 0);
        }
    }

    // ---------------------------------------------------------------- keys (v2 §9, v2.1 K)
    // Every menu entry with a shortcut works from here, enabled as the menu says.
    Repeater {
        model: win.shell.shortcuts

        delegate: Item {
            id: key

            required property var modelData

            Shortcut {
                enabled: !!win.shell.menuEnabled[key.modelData.id]
                sequence: key.modelData.sequence

                onActivated: win.shell.menuAction(key.modelData.id)
            }
        }
    }
    Shortcut {
        sequence: "Ctrl+L"

        onActivated: win.shell.launch()
    }
    Shortcut {
        sequence: "Ctrl+Shift+L"

        onActivated: topBar.openLaunchMenu()
    }
    Shortcut {
        sequence: "Ctrl+Tab"

        onActivated: win.shell.cycleGame(1)
    }
    Shortcut {
        sequence: "Ctrl+Shift+Tab"

        onActivated: win.shell.cycleGame(-1)
    }
    Shortcut {
        sequence: "F5"

        onActivated: win.shell.rescan()
    }
    Shortcut {
        enabled: win.shell.currentPage !== "modConfigs"   // that page saves with its own Ctrl+S
        sequences: [StandardKey.Save]

        onActivated: win.shell.saveCurrent()
    }
    Shortcut {
        enabled: win.shell.canGoBack   // a page's own side panels close themselves
        sequence: "Escape"

        onActivated: win.shell.back()
    }

    // ---------------------------------------------------------------- the L
    Loader {  // the OS title bar's height, in its own file so a Qt without SafeArea fails only this load
        id: chromeProbe

        anchors.fill: parent
        source: win.nativeChrome ? Qt.resolvedUrl("Shell/ChromeProbe.qml") : ""

        onLoaded: win.chromeTop = Qt.binding(() => (item as ChromeProbe).topInset)
    }
    TopBar {
        id: topBar

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        captionLeftW: win.captionLeftW
        captionW: win.captionW
        chromeTop: win.chromeTop
        compact: win.compact
        nativeChrome: win.nativeChrome
        shell: win.shell
        window: win
    }
    Rail {
        id: rail

        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.top: topBar.bottom
        autoCollapse: win.compact
        shell: win.shell
    }
    Rectangle {  // the inset page surface: the corner the L makes is rounded
        id: surface

        anchors.bottom: parent.bottom
        anchors.left: rail.right
        anchors.right: parent.right
        anchors.top: topBar.bottom
        clip: true
        color: Theme.surfacePage
        topLeftRadius: Theme.radiusInset

        Behavior on color {
            ColorAnimation {
                duration: Theme.mPage
            }
        }

        Atmosphere {  // blooms, vignette, grain, the luminous edge: under the page, over the surface colour
            anchors.fill: parent
        }
        InfoBar {  // a lasting condition of the page on show (its Notifier's InfoBar)
            id: infoBar

            anchors.left: parent.left
            anchors.leftMargin: Theme.sp16
            anchors.right: parent.right
            anchors.rightMargin: Theme.sp16
            anchors.top: parent.top
            anchors.topMargin: visible ? Theme.sp8 : 0
            open: !!win.currentNotifier && win.currentNotifier.infoText !== ""
            severity: win.currentNotifier ? win.currentNotifier.infoSeverity : "info"
            text: win.currentNotifier ? win.currentNotifier.infoText : ""
            visible: open
            z: 5

            onClosed: win.currentNotifier.clear_info()
        }
        Item {  // the pages, side by side, one on show
            id: pageHost

            anchors.bottom: hintBar.top
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: infoBar.visible ? infoBar.bottom : parent.top

            Repeater {
                model: win.shell.pageNames

                delegate: Loader {
                    id: slot

                    readonly property bool current: win.shell.currentPage === modelData
                    required property string modelData

                    function ensure() {
                        const adapter = win.shell.adapterFor(modelData);
                        if (!active && adapter) {  // a page never loads without its adapter
                            setSource(win.shell.pageUrl(modelData), {
                                "adapter": adapter
                            });
                            active = true;
                        }
                    }

                    active: false
                    anchors.fill: parent
                    opacity: current ? 1 : 0
                    visible: opacity > 0

                    Behavior on opacity {
                        NumberAnimation {
                            duration: Theme.mPage
                        }
                    }

                    Component.onCompleted: {
                        if (current)
                            ensure();
                    }
                    onCurrentChanged: {
                        if (current)
                            ensure();
                    }
                    onLoaded: {
                        if (item.leave !== undefined)   // a page that finishes by itself (the bundled profile's Cancel)
                            item.leave.connect(win.shell.back);
                    }
                }
            }
        }
        Item {  // the hint bar (v2.8; v2.11): its own row, so it never covers a page's footer or last row
            id: hintBar

            readonly property bool shown: !win.compact && win.height >= 640

            anchors.bottom: parent.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            clip: true
            height: shown ? 34 : 0
            visible: shown

            Hairline {
            }
            Row {
                anchors.left: parent.left
                anchors.leftMargin: 28
                anchors.verticalCenter: parent.verticalCenter
                spacing: Theme.sp16

                Repeater {
                    model: [["Ctrl+L", qsTr("Launch")], ["Ctrl+1-5", qsTr("Pages")], ["F5", qsTr("Rescan")], ["Esc", qsTr("Back")]]

                    Row {
                        id: hintRow

                        required property var modelData

                        spacing: Theme.sp8

                        Rectangle {
                            border.color: Theme.borderEdge
                            border.width: 1
                            color: "transparent"
                            height: 18
                            radius: Theme.radiusTag
                            width: keyText.implicitWidth + 12

                            Text {
                                id: keyText

                                anchors.centerIn: parent
                                color: Theme.textSecondary
                                font.family: Theme.fontFamily
                                font.pixelSize: 11
                                font.weight: Font.DemiBold
                                text: hintRow.modelData[0]
                            }
                        }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            color: Theme.textSecondary   // the tertiary grey is 3.5:1 on the light page, under AA for 12 px text
                            font.family: Theme.fontFamily
                            font.pixelSize: 12
                            text: hintRow.modelData[1]
                        }
                    }
                }
            }
        }
    }
    Item {  // the L's rounded corner, kept rounded whatever scrolls under it
        anchors.left: surface.left
        anchors.top: surface.top
        height: Theme.radiusInset + 1
        width: Theme.radiusInset + 1
        z: 50

        Canvas {
            id: cornerCanvas

            anchors.fill: parent

            onPaint: {
                const c = getContext("2d"), r = Theme.radiusInset;
                c.reset();
                c.fillStyle = Theme.surfaceBar;
                c.beginPath();
                c.moveTo(0, 0);
                c.lineTo(r + 1, 0);
                c.lineTo(r + 1, 0.5);
                c.arc(r + 0.5, r + 0.5, r, -Math.PI / 2, Math.PI, true);
                c.lineTo(0, r + 1);
                c.closePath();
                c.fill();
                c.strokeStyle = Theme.borderEdge;
                c.lineWidth = 1;
                c.beginPath();
                c.arc(r + 0.5, r + 0.5, r, Math.PI, -Math.PI / 2, false);
                c.stroke();
            }

            Connections {
                function onDarkChanged() {
                    cornerCanvas.requestPaint();
                }
                function onVariantChanged() {
                    cornerCanvas.requestPaint();
                }

                target: Theme
            }
        }
    }
    Rectangle {  // top edge of the inset page
        color: Theme.borderEdge
        height: 1
        width: surface.width - Theme.radiusInset
        x: surface.x + Theme.radiusInset + 1
        y: surface.y
        z: 50
    }
    Rectangle {  // left edge of the inset page
        color: Theme.borderEdge
        height: surface.height - Theme.radiusInset
        width: 1
        x: surface.x
        y: surface.y + Theme.radiusInset + 1
        z: 50
    }
    Overlays {  // toasts, confirmations and forks: from the shell's Notifier and every page's
        anchors.fill: surface
        notifiers: win.shell.allNotifiers
        z: 100
    }

    // ---------------------------------------------------------------- window-level dialogs
    ModalDialog {
        id: unsaved

        property string action: ""
        property bool answered: false
        property int token: 0
        property var words: []

        preferredWidth: 460
        subtitle: qsTr("Before %1, these are not saved yet:").arg(action)
        title: qsTr("Unsaved changes")

        footerRow: [
            PrimaryButton {
                text: qsTr("Save")

                onClicked: {
                    unsaved.answered = true;
                    unsaved.close();
                    win.shell.unsavedAnswer(unsaved.token, "save");
                }
            },
            GhostButton {
                fg: Theme.statusDanger
                text: qsTr("Discard")

                onClicked: {
                    unsaved.answered = true;
                    unsaved.close();
                    win.shell.unsavedAnswer(unsaved.token, "discard");
                }
            },
            GhostButton {
                text: qsTr("Cancel")

                onClicked: unsaved.close()
            }
        ]

        onAboutToShow: answered = false
        onClosed: {
            if (!answered)
                win.shell.unsavedAnswer(token, "cancel");
        }

        Column {
            spacing: Theme.sp4
            width: parent.width

            Repeater {
                model: unsaved.words

                Txt {
                    required property string modelData

                    elide: Text.ElideNone
                    text: "• " + modelData
                    width: parent.width
                    wrapMode: Text.WordWrap
                }
            }
        }
    }
    ModalDialog {
        id: closeJob

        preferredWidth: 480
        subtitle: qsTr("The game is left alone; the save repair and the cleanup after it are skipped.")
        title: qsTr("Close while a job runs?")

        footerRow: [
            PrimaryButton {
                danger: true
                text: qsTr("Close anyway")

                onClicked: {
                    closeJob.close();
                    win.shell.closeConfirmed();
                }
            },
            GhostButton {
                text: qsTr("Cancel")

                onClicked: closeJob.close()
            }
        ]

        Txt {
            elide: Text.ElideNone
            text: qsTr("Nothing is written by closing. Run Check & repair on the Saves page later if the game was played.")
            width: parent.width
            wrapMode: Text.WordWrap
        }
    }

    NewProfileDialog {
        id: newProfile

        shell: win.shell
    }

    // ---------------------------------------------------------------- the file and folder dialogs (ShellHost's pickers)
    FileDialog {
        objectName: "openFileDialog"
    }
    FileDialog {
        objectName: "saveFileDialog"

        fileMode: FileDialog.SaveFile
    }
    FolderDialog {
        objectName: "folderDialog"
    }
    Edge {
        cursorShape: Qt.SizeHorCursor
        edges: Qt.LeftEdge
        width: band

        anchors {
            bottom: parent.bottom
            bottomMargin: band
            left: parent.left
            top: parent.top
            topMargin: band
        }
    }
    Edge {
        cursorShape: Qt.SizeHorCursor
        edges: Qt.RightEdge
        width: band

        anchors {
            bottom: parent.bottom
            bottomMargin: band
            right: parent.right
            top: parent.top
            topMargin: band
        }
    }
    Edge {
        cursorShape: Qt.SizeVerCursor
        edges: Qt.BottomEdge
        height: band

        anchors {
            bottom: parent.bottom
            left: parent.left
            leftMargin: band
            right: parent.right
            rightMargin: band
        }
    }
    Edge {
        cursorShape: Qt.SizeVerCursor
        edges: Qt.TopEdge
        height: band

        anchors {
            left: parent.left
            leftMargin: band
            right: parent.right
            rightMargin: band
            top: parent.top
        }
    }
    Edge {
        cursorShape: Qt.SizeFDiagCursor
        edges: Qt.TopEdge | Qt.LeftEdge
        height: band
        width: band

        anchors {
            left: parent.left
            top: parent.top
        }
    }
    Edge {
        cursorShape: Qt.SizeBDiagCursor
        edges: Qt.TopEdge | Qt.RightEdge
        height: band
        width: band

        anchors {
            right: parent.right
            top: parent.top
        }
    }
    Edge {
        cursorShape: Qt.SizeBDiagCursor
        edges: Qt.BottomEdge | Qt.LeftEdge
        height: band
        width: band

        anchors {
            bottom: parent.bottom
            left: parent.left
        }
    }
    Edge {
        cursorShape: Qt.SizeFDiagCursor
        edges: Qt.BottomEdge | Qt.RightEdge
        height: band
        width: band

        anchors {
            bottom: parent.bottom
            right: parent.right
        }
    }

    // resize edges (frameless window): 6 px bands and corners hand off to the system
    component Edge: MouseArea {
        property int band: 6
        property int edges

        enabled: !win.nativeChrome   // the OS owns the resize borders when the frame is native
        hoverEnabled: true
        visible: !win.nativeChrome

        onPressed: win.startSystemResize(edges)
    }
}
