pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import Theme
import Components

// A settings file as a form (§8.10, Mod Configs): one card per section, one FormRow per setting with the control its
// kind asks for (a switch, a list of choices, a number, a text field); the comment above the setting is the help line,
// a stated default is the tooltip and Reset puts it back. A setting only text can change says so. Every edit goes to
// the adapter, which keeps it until Save.
Column {
    id: form

    required property var adapter
    property var sections: []
    readonly property var words: adapter.words

    spacing: Theme.sp16

    Repeater {
        model: form.sections

        Column {
            id: sectionBlock

            required property var modelData

            spacing: Theme.sp8
            width: form.width

            Txt {
                kind: "strong"
                text: sectionBlock.modelData.title
                visible: text !== ""
            }
            Card {
                padding: 0
                width: parent.width

                Column {
                    width: parent.width

                    Repeater {
                        model: sectionBlock.modelData.rows

                        FormRow {
                            id: row

                            required property int index
                            required property var modelData
                            property string current: modelData.value

                            divider: index < sectionBlock.modelData.rows.length - 1
                            help: modelData.blurb !== "" ? modelData.blurb : modelData.help
                            objectName: "setting_" + modelData.key
                            showHelpIcon: true
                            title: modelData.label
                            tooltip: modelData.tip !== "" ? modelData.tip : modelData.help

                            function changed(value) {
                                row.current = value;
                                form.adapter.setValue(row.modelData.section, row.modelData.key, value);
                            }

                            Row {
                                spacing: Theme.sp8

                                ToggleSwitch {
                                    anchors.verticalCenter: parent.verticalCenter
                                    checked: row.current === row.modelData.onValue
                                    visible: row.modelData.kind === "bool"

                                    onToggled: row.changed(checked ? row.modelData.onValue : row.modelData.offValue)
                                }
                                DropButton {
                                    anchors.verticalCenter: parent.verticalCenter
                                    fixedWidth: 200
                                    implicitHeight: Theme.controlH
                                    text: {
                                        const c = row.modelData.choices.find(x => x.value === row.current);
                                        return c ? c.label : row.current;
                                    }
                                    visible: row.modelData.kind === "choice"

                                    Repeater {
                                        model: row.modelData.choices

                                        MenuEntry {
                                            required property var modelData

                                            checked: modelData.value === row.current
                                            text: modelData.label

                                            onTriggered: row.changed(modelData.value)
                                        }
                                    }
                                }
                                SpinField {
                                    anchors.verticalCenter: parent.verticalCenter
                                    from: row.modelData.lo
                                    to: row.modelData.hi
                                    value: parseInt(row.current) || 0
                                    visible: row.modelData.kind === "int"

                                    onEdited: row.changed(String(value))
                                }
                                TextBox {
                                    anchors.verticalCenter: parent.verticalCenter
                                    echoMode: row.modelData.kind === "password" ? TextInput.Password : TextInput.Normal
                                    passwordCharacter: "*"
                                    text: row.modelData.value
                                    visible: row.modelData.kind === "text" || row.modelData.kind === "float" || row.modelData.kind === "password"

                                    onTextEdited: row.changed(text)
                                }
                                Txt {
                                    anchors.verticalCenter: parent.verticalCenter
                                    kind: "hint"
                                    text: form.words.readonly
                                    visible: row.modelData.kind === "readonly"
                                }
                                GhostButton {
                                    anchors.verticalCenter: parent.verticalCenter
                                    implicitHeight: Theme.controlSmallH
                                    text: form.words.reset
                                    visible: row.modelData.tip !== "" && row.modelData.kind !== "readonly"

                                    onClicked: form.adapter.resetValue(row.modelData.section, row.modelData.key)
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
