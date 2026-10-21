pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import Theme
import App
import Components

// Mods (technical specification §8.10): the InfoBars, the header strip, the raw .me3 (Edit as text), Packages and
// Natives (DLLs) as ModGroups (rows dragged from the grip; the backend applies me3's rules and says why a move is
// refused), the Parameters card and the Load order panel. Everything shown and every word comes from the adapter
// (ui/pages/mods/adapter.py); the page only lays it out.
PageScroll {
    id: page

    required property var adapter
    readonly property var words: adapter.words
    property int dropTarget: -1      // the position a dragged row would land at (-1: none)
    property string dragKind: ""
    property string dropReason: ""   // why the spot under a dragged row refuses it ("" : allowed)
    property real dropTagX: 0        // where the reason is drawn (drag layer coordinates: right edge, under the line)
    property real dropTagY: 0
    property real dragY: 0           // the pointer's y in the page while a row is dragged (auto-scroll)

    objectName: "modsPage"

    function scrollToParams() {
        contentY = Math.min(paramsCard.y + 20, Math.max(0, contentHeight - height));
    }

    Component.onCompleted: page.adapter.refresh()

    Timer {  // a dragged row near the top or bottom edge scrolls the page
        interval: 16
        repeat: true
        running: page.dragKind !== ""

        onTriggered: {
            const edge = 56;
            const max = Math.max(0, page.contentHeight - page.height);
            if (page.dragY < edge)
                page.contentY = Math.max(0, page.contentY - 14);
            else if (page.dragY > page.height - edge)
                page.contentY = Math.min(max, page.contentY + 14);
        }
    }

    Connections {
        function onOptionsRequested(index) {
            page.adapter.openOptions(index);
        }
        function onDialogRequested(which, index) {
            if (which === "options")
                modOptions.openFor(index);
            else if (which === "rename")
                renameMod.openFor(index);
            else if (which === "profile-settings")
                profileSettings.openNow();
            else if (which === "versions")
                versions.openNow();
            else if (which === "add-existing-package" || which === "add-existing-native")
                addExisting.openFor(which.slice("add-existing-".length));
        }
        function onPickRequested(key, words, rows) {
            pickList.openFor(key, words, rows);
        }

        target: page.adapter
    }
    ModOptionsDialog {
        id: modOptions

        adapter: page.adapter
    }
    RenameDialog {
        id: renameMod

        adapter: page.adapter
    }
    ProfileSettingsDialog {
        id: profileSettings

        adapter: page.adapter
    }
    VersionsDialog {
        id: versions

        adapter: page.adapter
    }
    PickListDialog {
        id: pickList

        adapter: page.adapter
    }
    AddExistingDialog {
        id: addExisting

        adapter: page.adapter
    }
    InstallModDialog {
        id: installMod

        adapter: page.adapter
    }
    Item {  // the lifted row floats here, outside what the page clips
        id: dragLayer

        anchors.fill: parent
        parent: AppState.overlayLayer ? AppState.overlayLayer : page
        z: 100

        Rectangle {  // why the spot under the lifted row refuses it, in words
            border.color: Theme.statusDanger
            color: Theme.surfaceCard
            height: reasonText.implicitHeight + Theme.sp8
            objectName: "dropReasonTag"
            radius: Theme.radiusCard
            visible: page.dropReason !== ""
            width: reasonText.implicitWidth + Theme.sp16
            x: Math.max(0, page.dropTagX - width)
            y: page.dropTagY
            z: 50

            Txt {
                id: reasonText

                anchors.centerIn: parent
                color: Theme.statusDanger
                kind: "caption"
                text: page.dropReason
            }
        }
    }
    Column {  // the InfoBars (at most two)
        spacing: Theme.sp8
        visible: !page.adapter.editText
        width: parent.width

        Repeater {
            model: page.adapter.notices

            InfoBar {
                id: notice

                // the row's roles are read through `model`: a role named like an InfoBar property would bind to itself
                required property var model

                actionLabel: model.action
                closable: model.closable
                objectName: "notice_" + model.key
                open: true
                severity: model.severity
                text: model.text
                width: parent ? parent.width : 0

                onActionClicked: page.adapter.noticeAction(notice.model.key)
                onClosed: page.adapter.closeNotice(notice.model.key)
            }
        }
    }
    Txt {
        kind: "hint"
        text: page.adapter.empty
        visible: page.adapter.empty !== ""
        width: parent ? parent.width : 0
        wrapMode: Text.WordWrap
    }
    PrimaryButton {  // first run: no profile anywhere, so the one thing to do is here, not only in the top bar
        objectName: "createProfile"
        text: page.words.createProfile
        visible: page.adapter.noProfiles

        onClicked: page.adapter.createProfile()
    }
    ModsHeader {
        adapter: page.adapter
        visible: page.adapter.hasProfile
        width: parent ? parent.width : 0

        onEditTextRequested: on => {
            if (!on && page.adapter.textDirty)
                unsavedText.open();
            else
                page.adapter.setEditText(on);
        }
        onHealthClicked: {
            page.scrollToParams();
            loadOrder.open = true;
        }
    }
    Me3TextEditor {
        adapter: page.adapter
        editorHeight: Math.max(320, page.height - 260)
        visible: page.adapter.editText
        width: parent ? parent.width : 0
    }
    ModGroup {
        adapter: page.adapter
        dragLayer: dragLayer
        group: page.adapter.packageGroup
        model: page.adapter.packages
        page: page
        visible: page.adapter.hasProfile && !page.adapter.editText
        width: parent ? parent.width : 0
    }
    ModGroup {
        adapter: page.adapter
        dragLayer: dragLayer
        group: page.adapter.nativeGroup
        model: page.adapter.natives
        page: page
        visible: page.adapter.hasProfile && !page.adapter.editText
        width: parent ? parent.width : 0
    }
    ParametersCard {
        id: paramsCard

        adapter: page.adapter
        visible: page.adapter.hasProfile && !page.adapter.editText && page.adapter.parameters.visible
        width: parent ? parent.width : 0

        onDetailsRequested: loadOrder.open = true
    }
    LoadOrderPanel {  // over the page, not in its column
        id: loadOrder

        adapter: page.adapter
        parent: page
    }
    DropArea {  // files dropped from Explorer: the launcher's install flow
        anchors.fill: parent
        keys: ["text/uri-list"]
        parent: page
        z: 90

        onDropped: drop => {
            if (drop.hasUrls)
                page.adapter.installDropped(drop.urls.map(u => String(u)));
        }

        Rectangle {
            anchors.fill: parent
            anchors.margins: Theme.sp12
            border.color: Theme.accent
            border.width: 2
            color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.08)
            radius: Theme.radiusCard
            visible: parent.containsDrag

            Txt {
                anchors.centerIn: parent
                color: Theme.accent
                kind: "section"
                text: page.words.dropToInstall
            }
        }
    }
    ModalDialog {
        id: unsavedText

        preferredWidth: 460
        title: page.words.unsavedTitle

        footerRow: [
            PrimaryButton {
                enabled: page.adapter.me3Error === ""
                text: page.words.save

                onClicked: {
                    page.adapter.saveText();
                    unsavedText.close();
                    page.adapter.setEditText(false);
                }
            },
            GhostButton {
                fg: Theme.statusDanger
                text: page.words.discard

                onClicked: {
                    page.adapter.discardText();
                    unsavedText.close();
                    page.adapter.setEditText(false);
                }
            },
            GhostButton {
                text: page.words.cancel

                onClicked: unsavedText.close()
            }
        ]

        Txt {
            elide: Text.ElideNone
            text: page.words.unsavedBody
            width: parent ? parent.width : 0
            wrapMode: Text.WordWrap
        }
    }
}
