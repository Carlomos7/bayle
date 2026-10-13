pragma ComponentBehavior: Bound
import QtQuick
import Theme
import Components

// Profile settings (§8.10, the profile gear): the me3 options a profile can set (Save file, Online matchmaking,
// Neutralise Arxan, Memory patch, Heap size). Each change is written at once through the adapter (online asks first);
// the words and explanations are the launcher's own (mods.profile.SETTING_TEXT through tr()).
ModalDialog {
    id: dlg

    required property var adapter
    property var values: ({})
    readonly property var words: adapter.words

    objectName: "profileSettingsDialog"
    preferredWidth: 560
    title: words.settingsTitle

    function openNow() {
        values = adapter.settingsFor();
        saveBox.text = values.savefile || "";
        heap.value = values.mem_patch_heap_size || 0;
        open();
    }

    footerRow: [
        GhostButton {
            text: dlg.words.cancel

            onClicked: dlg.close()
        }
    ]

    Column {
        spacing: 0
        width: parent ? parent.width : 0

        FormRow {
            first: true
            help: dlg.words.setting_savefile_help
            title: dlg.words.setting_savefile
            width: parent ? parent.width : 0

            TextBox {
                id: saveBox

                implicitWidth: Theme.inputW

                onEditingFinished: dlg.adapter.setSetting("savefile", text)
            }
        }
        Repeater {
            model: ["start_online", "disable_arxan", "mem_patch"]

            FormRow {
                id: triRow

                required property string modelData

                help: dlg.words["setting_" + modelData + "_help"]
                title: dlg.words["setting_" + modelData]
                width: parent ? parent.width : 0

                DropButton {
                    fixedWidth: Theme.inputShortW + 40
                    implicitHeight: Theme.controlH
                    objectName: "setting_" + triRow.modelData
                    text: [dlg.words.meDefault, dlg.words.on, dlg.words.off][dlg.values[triRow.modelData] || 0]

                    MenuEntry {
                        text: dlg.words.meDefault

                        onTriggered: dlg.adapter.setSetting(triRow.modelData, 0)
                    }
                    MenuEntry {
                        text: dlg.words.on

                        onTriggered: dlg.adapter.setSetting(triRow.modelData, 1)
                    }
                    MenuEntry {
                        text: dlg.words.off

                        onTriggered: dlg.adapter.setSetting(triRow.modelData, 2)
                    }
                }
            }
        }
        FormRow {
            help: dlg.words.setting_mem_patch_heap_size_help
            last: true
            title: dlg.words.setting_mem_patch_heap_size
            width: parent ? parent.width : 0

            SpinField {
                id: heap

                enabled: dlg.values.heapApplies !== false
                from: 0
                to: 65536

                onEdited: dlg.adapter.setSetting("mem_patch_heap_size", value)
            }
        }
    }
    Connections {  // a written setting comes back through the page's refresh: read the values again
        function onChanged() {
            if (dlg.opened)
                dlg.values = dlg.adapter.settingsFor();
        }

        target: dlg.adapter
    }
}
