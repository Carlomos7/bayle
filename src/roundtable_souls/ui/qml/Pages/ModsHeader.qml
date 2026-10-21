pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Theme
import Components

// The Mods header strip (§8.10): profile name · counts · merge-health pill · Edit as text · Install mod (the page's
// one accent button) · Profile folder · profile gear (settings, versions, delete) · overflow (Rescan, Add existing).
// One RowLayout, so the halves never overlap; as the page narrows the counts, the "Edit as text" label and the
// "Profile folder" label give way, then the switch moves into More.
Item {
    id: header

    required property var adapter
    readonly property var words: adapter.words
    readonly property bool narrow: width < 760

    signal editTextRequested(bool on)
    signal healthClicked

    implicitHeight: 40

    RowLayout {
        anchors.fill: parent
        spacing: Theme.gapInline

        Item {  // the profile (picked in the top bar): click the name to rename it
            id: nameArea

            property string problem: ""
            property bool editing: false

            function begin() {
                if (editing)
                    return;
                const why = header.adapter.profileRenameBlock();
                if (why !== "") {
                    problem = why;
                    blockedHide.restart();
                    return;
                }
                problem = "";
                edit.text = header.adapter.title;
                editing = true;
                edit.forceActiveFocus();
                edit.selectAll();
            }
            function cancel() {
                editing = false;
                problem = "";
            }
            function apply() {
                if (!editing || edit.text === header.adapter.title)
                    return cancel();
                checkNow.stop();
                const why = header.adapter.renameProfile(edit.text);
                if (why !== "")
                    problem = why;
                else
                    cancel();
            }

            Layout.alignment: Qt.AlignVCenter
            Layout.maximumWidth: editing ? 640 : 420
            implicitHeight: 32
            implicitWidth: nameRow.implicitWidth

            Row {
                id: nameRow

                anchors.verticalCenter: parent.verticalCenter
                spacing: Theme.gapInline

                Txt {
                    anchors.verticalCenter: parent.verticalCenter
                    Accessible.name: header.words.profileRenameTip
                    Accessible.role: Accessible.Button
                    elide: Text.ElideRight
                    kind: "rowTitle"
                    objectName: "profileTitle"
                    text: header.adapter.title
                    visible: !nameArea.editing
                    width: Math.min(implicitWidth, 360)

                    HandCursor {
                    }
                    TapHandler {
                        onTapped: nameArea.begin()
                    }
                    HoverHandler {
                        id: nameHover
                    }
                    ToolTip.text: header.words.profileRenameTip
                    ToolTip.visible: nameHover.hovered && !nameArea.editing
                }
                IconButton {  // always shown, focusable (Tab), named by its tooltip
                    ToolTip.text: header.words.profileRenameTip
                    anchors.verticalCenter: parent.verticalCenter
                    icon_: "Edit"
                    iconSize: 14
                    implicitHeight: 28
                    implicitWidth: 28
                    objectName: "profileRenameHint"
                    visible: !nameArea.editing

                    onClicked: nameArea.begin()
                }
                TextBox {
                    id: edit

                    Accessible.name: header.words.profileRenameField
                    anchors.verticalCenter: parent.verticalCenter
                    error: nameArea.problem !== ""
                    implicitWidth: 260
                    maximumLength: 120
                    objectName: "profileNameEdit"
                    visible: nameArea.editing

                    Keys.onEnterPressed: nameArea.apply()
                    Keys.onEscapePressed: nameArea.cancel()
                    Keys.onReturnPressed: nameArea.apply()
                    onActiveFocusChanged: if (!activeFocus && nameArea.editing)
                        nameArea.cancel()
                    onTextEdited: checkNow.restart()
                }
                Txt {
                    anchors.verticalCenter: parent.verticalCenter
                    color: Theme.statusDanger
                    elide: Text.ElideRight
                    kind: "hint"
                    objectName: "profileNameProblem"
                    text: nameArea.problem !== "" ? nameArea.problem : (nameArea.editing ? header.words.profileRenameHelp : "")
                    visible: nameArea.editing || nameArea.problem !== ""
                    width: Math.min(implicitWidth, 320)
                }
            }
            Timer {  // the live name check, once typing pauses
                id: checkNow

                interval: 250

                onTriggered: nameArea.problem = edit.text === header.adapter.title ? "" : header.adapter.profileNameCheck(edit.text)
            }
            Timer {  // a refusal to start (a job is running): said for a moment
                id: blockedHide

                interval: 4000

                onTriggered: if (!nameArea.editing)
                    nameArea.problem = ""
            }
            Connections {
                function onProfileRenameRequested() {
                    nameArea.begin();
                }

                target: header.adapter
            }
        }
        Txt {
            Layout.alignment: Qt.AlignVCenter
            kind: "hint"
            text: "·  " + header.adapter.counts
            visible: header.width >= 980 && !nameArea.editing
        }
        Pill {
            Layout.alignment: Qt.AlignVCenter
            ToolTip.text: header.words.healthTip
            ToolTip.visible: healthHover.hovered
            clickable: true
            icon_: header.adapter.health.level === "success" ? "Accept" : "Info"
            level: header.adapter.health.level || "muted"
            objectName: "healthPill"
            text: header.adapter.health.text || ""
            visible: text !== ""

            onClicked: header.healthClicked()

            HoverHandler {
                id: healthHover
            }
        }
        Item {
            Layout.fillWidth: true
            Layout.minimumWidth: 8
        }
        Row {
            Layout.alignment: Qt.AlignVCenter
            spacing: Theme.gapInline
            visible: !header.narrow

            Txt {
                anchors.verticalCenter: parent.verticalCenter
                kind: "caption"
                text: header.words.editAsText
            }
            ToggleSwitch {
                anchors.verticalCenter: parent.verticalCenter
                checked: header.adapter.editText
                objectName: "editTextSwitch"

                onToggled: {
                    const want = checked;
                    checked = Qt.binding(function () {
                        return header.adapter.editText;
                    });
                    header.editTextRequested(want);
                }
            }
        }
        PrimaryButton {
            id: installBtn

            Layout.alignment: Qt.AlignVCenter
            dropDown: true
            icon_: "Download"
            text: header.words.install

            onClicked: installMenu.open()

            PopupMenu {
                id: installMenu

                y: installBtn.height + Theme.sp4

                MenuEntry {
                    icon_: "ZipFolder"
                    text: header.words.installFile

                    onTriggered: header.adapter.install(false)
                }
                MenuEntry {
                    icon_: "Folder"
                    text: header.words.installFolder

                    onTriggered: header.adapter.install(true)
                }
            }
        }
        GhostButton {
            Layout.alignment: Qt.AlignVCenter
            ToolTip.text: header.words.profileFolder
            ToolTip.visible: (hovered || visualFocus) && text === ""
            icon_: "Folder"
            implicitWidth: text === "" ? 40 : 140
            text: header.width >= 1060 ? header.words.profileFolder : ""

            onClicked: header.adapter.openProfileFolder()
        }
        GhostButton {
            id: gearBtn

            Layout.alignment: Qt.AlignVCenter
            ToolTip.text: header.words.gearTip
            ToolTip.visible: (hovered || visualFocus) && !gearMenu.opened
            icon_: "Setting"
            implicitWidth: 40
            objectName: "gearButton"
            text: ""

            onClicked: gearMenu.open()

            PopupMenu {
                id: gearMenu

                y: gearBtn.height + 4

                MenuEntry {
                    icon_: "Setting"
                    text: header.words.profileSettings

                    onTriggered: header.adapter.openProfileSettings()
                }
                MenuEntry {
                    icon_: "History"
                    text: header.words.versions

                    onTriggered: header.adapter.openVersions()
                }
                MenuEntry {
                    icon_: "Share"
                    objectName: "exportProfile"
                    text: header.words.exportProfile

                    onTriggered: header.adapter.openProfileTransfer("export")
                }
                MenuEntry {
                    icon_: "Download"
                    objectName: "importProfile"
                    text: header.words.importProfile

                    onTriggered: header.adapter.openProfileTransfer("import")
                }
                MenuSep {
                }
                MenuEntry {
                    icon_: "Delete"
                    text: header.words.deleteProfile

                    onTriggered: header.adapter.deleteProfile()
                }
            }
        }
        GhostButton {
            id: moreBtn

            Layout.alignment: Qt.AlignVCenter
            ToolTip.text: header.words.more
            ToolTip.visible: (hovered || visualFocus) && !moreMenu.opened
            icon_: "More"
            implicitWidth: 40
            text: ""

            onClicked: moreMenu.open()

            PopupMenu {
                id: moreMenu

                y: moreBtn.height + 4

                MenuEntry {
                    checked: header.adapter.editText
                    height: visible ? implicitHeight : 0
                    icon_: "Edit"
                    text: header.words.editAsText
                    visible: header.narrow

                    onTriggered: header.editTextRequested(!header.adapter.editText)
                }
                MenuEntry {
                    icon_: "Sync"
                    shortcut: "F5"
                    text: header.words.rescan

                    onTriggered: header.adapter.refresh()
                }
                MenuEntry {
                    icon_: "Add"
                    text: header.words.addExisting

                    onTriggered: header.adapter.addExisting("package")
                }
                MenuEntry {
                    height: visible ? implicitHeight : 0
                    icon_: "Folder"
                    objectName: "adoptIntoLibrary"
                    text: header.words.adoptMenu
                    visible: header.adapter.canAdopt

                    onTriggered: header.adapter.adoptIntoLibrary()
                }
                MenuSep {  // overhauls installed with the launcher (a preview, shown while its switch is on)
                    height: visible ? implicitHeight : 0
                    visible: header.adapter.overhaul.visible === true
                }
                MenuEntry {
                    height: visible ? implicitHeight : 0
                    icon_: "Folder"
                    objectName: "installOverhaul"
                    text: header.adapter.overhaul.install || ""
                    visible: header.adapter.overhaul.visible === true

                    onTriggered: header.adapter.installOverhaul()
                }
                MenuEntry {
                    enabled: header.adapter.overhaul.can_remove === true
                    height: visible ? implicitHeight : 0
                    icon_: "Delete"
                    objectName: "removeOverhaul"
                    text: header.adapter.overhaul.remove || ""
                    visible: header.adapter.overhaul.visible === true

                    onTriggered: header.adapter.removeOverhaul()
                }
                MenuEntry {
                    enabled: header.adapter.overhaul.can_clean === true
                    height: visible ? implicitHeight : 0
                    icon_: "Broom"
                    objectName: "cleanLeftovers"
                    text: header.adapter.overhaul.clean || ""
                    visible: header.adapter.overhaul.visible === true

                    onTriggered: header.adapter.cleanLeftovers()
                }
            }
        }
    }
}
