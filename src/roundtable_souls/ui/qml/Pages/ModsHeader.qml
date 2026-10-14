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

        Txt {
            Layout.alignment: Qt.AlignVCenter
            Layout.fillWidth: true
            Layout.maximumWidth: Math.ceil(implicitWidth)
            Layout.minimumWidth: 80
            Layout.preferredWidth: Math.ceil(implicitWidth)
            kind: "page"
            text: header.adapter.title
        }
        Txt {
            Layout.alignment: Qt.AlignVCenter
            kind: "hint"
            text: "·  " + header.adapter.counts
            visible: header.width >= 980
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
                visible: header.width >= 880
            }
            ToggleSwitch {
                ToolTip.text: header.words.editAsText
                ToolTip.visible: hovered && header.width < 880
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
            ToolTip.visible: hovered && text === ""
            icon_: "Folder"
            implicitWidth: text === "" ? 40 : 140
            text: header.width >= 1060 ? header.words.profileFolder : ""

            onClicked: header.adapter.openProfileFolder()
        }
        GhostButton {
            id: gearBtn

            Layout.alignment: Qt.AlignVCenter
            ToolTip.text: header.words.gearTip
            ToolTip.visible: hovered && !gearMenu.opened
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
            ToolTip.visible: hovered && !moreMenu.opened
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
            }
        }
    }
}
