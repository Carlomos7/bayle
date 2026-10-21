pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Window
import Theme
import App
import Components

// A registered page in a top-level window of its own (S5: the Activity trial, opened from the Widgets launcher;
// the QML shell replaces this in S9 and hosts the same page unchanged). Around the page: a bar with the page's
// title and the status text, the page InfoBar, toasts bottom-right and the confirmation dialog, all driven by the
// page's Notifier (ui/notifications.py).
ApplicationWindow {
    id: win

    required property var adapter
    required property var notifier
    required property url pageUrl
    property string themeMode: "dark"   // "dark" | "tarnished" | "light" | "system", from the launcher's setting
    property string effects: "full"     // Settings > Appearance > Effects
    property string grain: "subtle"     // Settings > Appearance > Grain

    color: Theme.surfacePage
    height: 760
    minimumHeight: 480
    minimumWidth: 740
    title: win.adapter ? win.adapter.title + "  ·  Bayle Mod Manager" : "Bayle Mod Manager"
    width: 1100

    Component.onCompleted: {
        AppState.softwareRender = GraphicsInfo.api === GraphicsInfo.Software;
        AppState.setThemeMode(win.themeMode);
        AppState.effects = win.effects;
        AppState.grain = win.grain;
    }
    onEffectsChanged: AppState.effects = win.effects
    onGrainChanged: AppState.grain = win.grain
    onThemeModeChanged: AppState.setThemeMode(win.themeMode)

    Rectangle {  // the bar: title left, the status text right
        id: bar

        color: Theme.surfaceBar
        height: Theme.barRowH
        width: parent.width

        Txt {
            anchors.left: parent.left
            anchors.leftMargin: Theme.sp16
            anchors.verticalCenter: parent.verticalCenter
            kind: "strong"
            text: win.adapter ? win.adapter.title : ""
        }
        Txt {
            anchors.right: parent.right
            anchors.rightMargin: Theme.sp16
            anchors.verticalCenter: parent.verticalCenter
            color: Theme.textSecondary
            kind: "caption"
            text: win.notifier.statusText
        }
    }
    InfoBar {
        id: infoBar

        anchors.left: parent.left
        anchors.leftMargin: Theme.sp16
        anchors.right: parent.right
        anchors.rightMargin: Theme.sp16
        anchors.top: bar.bottom
        anchors.topMargin: visible ? Theme.sp8 : 0
        open: win.notifier.infoText !== ""
        severity: win.notifier.infoSeverity
        text: win.notifier.infoText
        visible: open

        onClosed: win.notifier.clear_info()
    }
    Loader {
        id: page

        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: infoBar.visible ? infoBar.bottom : bar.bottom

        Component.onCompleted: page.setSource(win.pageUrl, {
            "adapter": win.adapter
        })
        onLoaded: {
            if (item.leave !== undefined)   // a page that finishes by itself closes its window
                item.leave.connect(win.close);
        }
    }
    Overlays {
        notifiers: [win.notifier]
    }
}
