pragma ComponentBehavior: Bound
import QtQuick
import Theme
import Components

// Settings (technical specification §8.10; launcher-wide only): Locations, Launch, Backups, Appearance, Updates, Logs
// and About. Nothing per profile (Mod Configs, the profile gear) or per mod lives here. Everything shown and every
// word comes from the adapter (ui/pages/settings/adapter.py); the update notices are the one flow the launcher owns,
// shown here and in the older window alike (the buttons run the launcher's own paths, with its checks).
PageScroll {
    id: page

    required property var adapter
    readonly property var words: adapter.words

    function levelColor(level) {
        return level === "error" ? Theme.statusDangerBg : level === "warning" ? Theme.statusWarningBg : level === "success" ? Theme.statusSuccessBg : Theme.statusInfoBg;
    }

    maxContentWidth: Theme.formMaxW
    objectName: "settingsPage"

    Component.onCompleted: {
        page.adapter.refresh();
        page.adapter.readMe3();
    }

    Repeater {  // the update flow, the advisory and the move from the old install
        model: page.adapter.notices

        Rectangle {
            id: bar

            required property var model

            color: page.levelColor(bar.model.level)
            implicitHeight: barCol.implicitHeight + Theme.sp16 * 2
            radius: Theme.radiusControl
            width: parent ? parent.width : 0

            Column {
                id: barCol

                anchors.left: parent.left
                anchors.leftMargin: Theme.sp16
                anchors.right: parent.right
                anchors.rightMargin: bar.model.closable ? 48 : Theme.sp16
                anchors.top: parent.top
                anchors.topMargin: Theme.sp16
                spacing: Theme.sp8

                Txt {
                    kind: "strong"
                    text: bar.model.title
                    width: parent.width
                    wrapMode: Text.WordWrap
                }
                Txt {
                    kind: "hint"
                    text: bar.model.body
                    visible: text !== ""
                    width: parent.width
                    wrapMode: Text.WordWrap
                }
                Row {
                    spacing: Theme.gapInline
                    visible: bar.model.actions.length > 0

                    Repeater {
                        model: bar.model.actions

                        Item {
                            id: act

                            required property var modelData

                            height: Theme.controlH
                            width: act.modelData.primary ? primary.width : ghost.width

                            PrimaryButton {
                                id: primary

                                implicitHeight: Theme.controlH
                                text: act.modelData.label
                                visible: act.modelData.primary

                                onClicked: page.adapter.noticeAction(bar.model.id, act.modelData.key)
                            }
                            GhostButton {
                                id: ghost

                                implicitHeight: Theme.controlH
                                text: act.modelData.label
                                visible: !act.modelData.primary

                                onClicked: page.adapter.noticeAction(bar.model.id, act.modelData.key)
                            }
                        }
                    }
                }
            }
            IconButton {
                anchors.right: parent.right
                anchors.rightMargin: Theme.sp8
                anchors.top: parent.top
                anchors.topMargin: Theme.sp8
                icon_: "Close"
                iconSize: 11
                implicitHeight: Theme.controlSmallH
                implicitWidth: 28
                visible: bar.model.closable

                onClicked: page.adapter.dismissNotice(bar.model.id)
            }
        }
    }
    SettingsSection {
        iconName: "Folder"
        title: page.words.locations

        Repeater {
            model: page.adapter.locations

            SettingsPathRow {
                id: locRow

                required property var model

                adapter: page.adapter
                help: model.help
                menu: model.menu
                placeholder: model.placeholder
                rowKey: model.key
                title: model.title
                value: model.value
            }
        }
        FormRow {
            title: page.adapter.me3Text

            GhostButton {
                icon_: "Sync"
                implicitHeight: Theme.controlH
                text: qsTr("Read again")

                onClicked: page.adapter.readMe3()
            }
        }
        Repeater {
            model: page.adapter.me3Switches

            SettingsSwitchRow {
                adapter: page.adapter
            }
        }
    }
    SettingsSection {
        iconName: "Play"
        title: page.words.launch

        FormRow {
            help: page.words.launchHint
            title: ""
        }
        Repeater {
            model: page.adapter.launchSwitches

            SettingsSwitchRow {
                adapter: page.adapter
            }
        }
        FormRow {
            help: page.words.leftoverHelp
            title: page.words.leftover

            GhostButton {
                icon_: "Broom"
                implicitHeight: Theme.controlH
                text: page.words.clearNow

                onClicked: page.adapter.clearLeftovers()
            }
        }
        FormRow {
            help: page.words.offlineBlurb
            showHelpIcon: true
            title: page.words.offline
            tooltip: page.words.offlineHelp
        }
        Repeater {
            model: page.adapter.offlineSwitches

            SettingsSwitchRow {
                adapter: page.adapter
            }
        }
        FormRow {
            help: page.words.steamHelp
            implicitHeight: page.width < 900 ? 3 * Theme.controlH + 2 * Theme.gapInline + 24 : Theme.rowH
            title: page.words.steam

            Flow {  // the buttons stack under each other when the page is narrow
                spacing: Theme.gapInline
                width: page.width < 900 ? 220 : steamCopyTarget.implicitWidth + steamCopyOptions.implicitWidth + steamPoint.implicitWidth + 2 * Theme.gapInline

                GhostButton {
                    id: steamCopyTarget

                    icon_: "Copy"
                    implicitHeight: Theme.controlH
                    text: page.words.copyTarget

                    onClicked: page.adapter.copySteam("target")
                }
                GhostButton {
                    id: steamCopyOptions

                    icon_: "Copy"
                    implicitHeight: Theme.controlH
                    text: page.words.copyOptions

                    onClicked: page.adapter.copySteam("options")
                }
                GhostButton {
                    id: steamPoint

                    icon_: "Link"
                    implicitHeight: Theme.controlH
                    text: page.words.pointSteam

                    onClicked: page.adapter.pointSteamShortcuts()
                }
            }
        }
    }
    SettingsSection {
        iconName: "History"
        title: page.words.backups

        FormRow {
            help: page.words.backupsLocationHelp
            title: page.words.backupsLocation

            Row {
                spacing: Theme.gapInline

                Txt {
                    anchors.verticalCenter: parent.verticalCenter
                    color: Theme.textSecondary
                    elide: Text.ElideMiddle
                    kind: "caption"
                    text: page.adapter.backupsLocation
                    width: Theme.inputW
                }
                GhostButton {
                    icon_: "Folder"
                    implicitHeight: Theme.controlH
                    text: page.words.openFolder

                    onClicked: page.adapter.openFolder("backups")
                }
            }
        }
        FormRow {
            help: page.words.backupsKeepHelp
            title: page.words.backupsKeep

            SpinField {
                objectName: "backupsKeepField"
                from: page.adapter.keepFrom
                to: page.adapter.keepTo
                value: page.adapter.backupsKeep

                onEdited: page.adapter.setBackupsKeep(value)
            }
        }
    }
    SettingsSection {
        iconName: "Brush"
        title: page.words.appearance

        FormRow {
            help: page.words.themeHelp
            title: page.words.theme

            DropButton {
                fixedWidth: Theme.pickerW
                implicitHeight: Theme.controlH
                text: page.adapter.labels.theme

                Repeater {
                    model: page.adapter.themes

                    MenuEntry {
                        required property string key
                        required property string label

                        checked: key === page.adapter.theme
                        text: label

                        onTriggered: page.adapter.setChoice("theme", key)
                    }
                }
            }
        }
        FormRow {
            help: page.words.effectsHelp
            title: page.words.effects

            DropButton {
                fixedWidth: Theme.pickerW
                implicitHeight: Theme.controlH
                text: page.adapter.labels.effects

                Repeater {
                    model: page.adapter.effectsChoices

                    MenuEntry {
                        required property string key
                        required property string label

                        checked: key === page.adapter.effects
                        text: label

                        onTriggered: page.adapter.setChoice("effects", key)
                    }
                }
            }
        }
        FormRow {
            help: page.words.grainHelp
            title: page.words.grain

            DropButton {
                enabled: page.adapter.effects !== "off"
                fixedWidth: Theme.pickerW
                implicitHeight: Theme.controlH
                text: page.adapter.labels.grain

                Repeater {
                    model: page.adapter.grains

                    MenuEntry {
                        required property string key
                        required property string label

                        checked: key === page.adapter.grain
                        text: label

                        onTriggered: page.adapter.setChoice("grain", key)
                    }
                }
            }
        }
        FormRow {
            help: page.words.logoHelp
            title: page.words.logo

            DropButton {
                fixedWidth: Theme.pickerW
                implicitHeight: Theme.controlH
                text: page.adapter.labels.logo

                Repeater {
                    model: page.adapter.logos

                    MenuEntry {
                        required property string key
                        required property string label

                        checked: key === page.adapter.logo
                        text: label

                        onTriggered: page.adapter.setChoice("logo", key)
                    }
                }
            }
        }
    }
    SettingsSection {
        iconName: "Update"
        title: page.words.updates

        FormRow {
            help: page.adapter.launcherLine
            title: page.adapter.versionText

            Row {
                spacing: Theme.gapInline

                GhostButton {
                    icon_: "Sync"
                    implicitHeight: Theme.controlH
                    enabled: !page.adapter.updateChecking
                    text: page.words.check

                    onClicked: page.adapter.checkForUpdates()
                }
                GhostButton {
                    icon_: "Globe"
                    implicitHeight: Theme.controlH
                    text: page.words.releases

                    onClicked: page.adapter.openReleases()
                }
            }
        }
        FormRow {
            help: page.words.channelHelp
            title: page.words.channel

            DropButton {
                fixedWidth: Theme.pickerW
                implicitHeight: Theme.controlH
                text: page.adapter.labels.launcher_channel

                Repeater {
                    model: page.adapter.channels

                    MenuEntry {
                        required property string key
                        required property string label

                        checked: key === page.adapter.channel
                        text: label

                        onTriggered: page.adapter.setChoice("launcher_channel", key)
                    }
                }
            }
        }
        Repeater {
            model: page.adapter.updateSwitches

            SettingsSwitchRow {
                adapter: page.adapter
            }
        }
    }
    SettingsSection {
        iconName: "Document"
        title: page.words.logs

        FormRow {
            title: page.words.logsFolder

            GhostButton {
                icon_: "Folder"
                implicitHeight: Theme.controlH
                text: page.words.openFolder

                onClicked: page.adapter.openFolder("logs")
            }
        }
        FormRow {
            help: page.words.saveLogsHelp
            title: page.words.saveLogs

            GhostButton {
                icon_: "Save"
                implicitHeight: Theme.controlH
                text: page.words.save

                onClicked: page.adapter.saveLogs()
            }
        }
        FormRow {
            help: page.adapter.dataFolder
            title: page.words.settingsFolder

            GhostButton {
                icon_: "Folder"
                implicitHeight: Theme.controlH
                text: page.words.openFolder

                onClicked: page.adapter.openFolder("settings")
            }
        }
        FormRow {
            help: page.words.logLevelHelp
            title: page.words.logLevel

            DropButton {
                fixedWidth: Theme.pickerW
                implicitHeight: Theme.controlH
                text: page.adapter.labels.log_level

                Repeater {
                    model: page.adapter.logLevels

                    MenuEntry {
                        required property string key
                        required property string label

                        checked: key === page.adapter.logLevel
                        text: label

                        onTriggered: page.adapter.setChoice("log_level", key)
                    }
                }
            }
        }
    }
    SettingsSection {
        iconName: "Info"
        title: page.words.about

        FormRow {
            help: page.words.aboutHelp
            title: page.adapter.versionText

            Row {
                spacing: Theme.gapInline

                GhostButton {
                    implicitHeight: Theme.controlH
                    text: page.words.licence

                    onClicked: page.adapter.openLicence("LICENSE")
                }
                GhostButton {
                    implicitHeight: Theme.controlH
                    text: page.words.notices

                    onClicked: page.adapter.openLicence("THIRD_PARTY_NOTICES.md")
                }
            }
        }
    }
}
