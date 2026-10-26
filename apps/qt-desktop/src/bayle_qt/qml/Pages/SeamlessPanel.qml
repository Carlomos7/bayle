pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import Theme
import Components

// Seamless Co-op's own panel (§8.10, Mod Configs): the password with its hint, difficulty (party-size presets and
// the per-player numbers), the language (the game's, or a translation in its locale folder), the other settings as a
// generated form, and "Share with a friend": Copy / Paste / Load / Save settings, and the parameters fingerprint
// co-op partners compare. Edits wait in the adapter until Save.
Column {
    id: panel

    required property var adapter
    readonly property var s: adapter.seamless
    readonly property var words: adapter.words

    spacing: Theme.sp16

    Card {
        padding: 0
        visible: panel.s.hasPassword === true
        width: parent.width

        FormRow {
            help: panel.words.passwordHint
            objectName: "seamlessPassword"
            title: panel.words.password

            Row {
                spacing: Theme.sp8

                TextBox {
                    id: pwBox

                    property bool shown: false

                    Accessible.name: panel.words.password
                    echoMode: shown ? TextInput.Normal : TextInput.Password
                    passwordCharacter: "*"
                    text: panel.s.password || ""

                    onTextEdited: panel.adapter.setValue("PASSWORD", "cooppassword", text)
                }
                GhostButton {
                    anchors.verticalCenter: parent.verticalCenter
                    implicitHeight: Theme.controlSmallH
                    objectName: "showPassword"
                    text: pwBox.shown ? panel.words.hidePassword : panel.words.showPassword

                    onClicked: pwBox.shown = !pwBox.shown
                }
            }
        }
    }
    Txt {
        kind: "strong"
        text: panel.words.difficulty
        visible: (panel.s.scaling || []).length > 0
    }
    Card {
        padding: 0
        visible: (panel.s.scaling || []).length > 0
        width: parent.width

        Column {
            width: parent.width

            FormRow {
                divider: true
                help: panel.s.scalingHint || ""
                title: panel.words.preset

                DropButton {
                    fixedWidth: 240
                    implicitHeight: Theme.controlH
                    objectName: "seamlessPreset"
                    text: {
                        const i = (panel.s.presetKeys || []).indexOf(panel.s.preset);
                        return i >= 0 ? (panel.s.presets || [])[i] : panel.s.preset || "";
                    }

                    Repeater {
                        model: panel.s.presetKeys || []

                        MenuEntry {
                            required property int index
                            required property string modelData

                            checked: modelData === panel.s.preset
                            text: (panel.s.presets || [])[index] || ""

                            onTriggered: panel.adapter.setPreset(modelData)
                        }
                    }
                }
            }
            Repeater {
                model: panel.s.scaling || []

                FormRow {
                    required property int index
                    required property var modelData

                    divider: index < (panel.s.scaling || []).length - 1
                    title: modelData.label

                    SpinField {
                        from: 0
                        to: 1000
                        value: modelData.value

                        onEdited: panel.adapter.setValue("SCALING", modelData.key, String(value))
                    }
                }
            }
        }
    }
    Card {
        padding: 0
        width: parent.width

        FormRow {
            title: panel.words.language

            DropButton {
                fixedWidth: 240
                implicitHeight: Theme.controlH
                objectName: "seamlessLanguage"
                text: {
                    const l = (panel.s.languages || []).find(x => x.value === panel.s.language);
                    return l ? l.label : panel.s.language || "";
                }

                Repeater {
                    model: panel.s.languages || []

                    MenuEntry {
                        required property var modelData

                        checked: modelData.value === panel.s.language
                        text: modelData.label

                        onTriggered: panel.adapter.setValue("LANGUAGE", "mod_language_override", modelData.value)
                    }
                }
            }
        }
    }
    Txt {
        kind: "strong"
        text: panel.words.otherSettings
        visible: panel.adapter.sections.length > 0
    }
    ConfigForm {
        adapter: panel.adapter
        sections: panel.adapter.sections
        width: parent.width
    }
    Txt {
        kind: "strong"
        text: panel.words.share
    }
    Card {
        width: parent.width

        Column {
            spacing: Theme.sp8
            width: parent.width

            Txt {
                elide: Text.ElideNone
                kind: "hint"
                text: panel.words.shareBody
                width: parent.width
                wrapMode: Text.WordWrap
            }
            Flow {
                spacing: Theme.sp8
                width: parent.width

                GhostButton {
                    icon_: "Copy"
                    objectName: "copySettings"
                    text: panel.words.copy

                    onClicked: panel.adapter.copySettings()
                }
                GhostButton {
                    icon_: "Paste"
                    text: panel.words.paste

                    onClicked: panel.adapter.pasteSettings()
                }
                GhostButton {
                    icon_: "Folder"
                    text: panel.words.load

                    onClicked: panel.adapter.loadSettings()
                }
                GhostButton {
                    icon_: "Save"
                    text: panel.words.saveAs

                    onClicked: panel.adapter.saveSettingsAs()
                }
            }
            Txt {
                elide: Text.ElideNone
                kind: "caption"
                text: (panel.s.fingerprint || "") + ((panel.s.fingerprintNote || "") !== "" ? "\n" + panel.s.fingerprintNote : "")
                visible: (panel.s.fingerprint || "") !== ""
                width: parent.width
                wrapMode: Text.WordWrap
            }
        }
    }
}
