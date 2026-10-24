pragma ComponentBehavior: Bound
import QtQuick
import Theme
import Components

// A tick list the adapter asks for (pickRequested): what an overhaul's installer changed to put back, the installer
// leftovers to move to the Recycle Bin. Nothing is ticked at first unless the words list rows (ticked). The words come with the request; the answer goes
// back as the ticked rows' indexes (picked), or pickCancelled when the dialog closes without one.
ModalDialog {
    id: dlg

    required property var adapter
    property string key: ""
    property var words: ({})
    property var rows: []
    property var ticked: ({})
    property bool answered: false

    objectName: "pickListDialog"
    preferredWidth: 560
    subtitle: words.body || ""
    title: words.title || ""

    function openFor(k, w, r) {
        key = k;
        words = w;
        rows = r;
        let first = {};
        for (const i of (w.ticked || []))
            first[i] = true;
        ticked = first;
        answered = false;
        open();
    }
    function answer(indexes) {
        answered = true;
        close();
        adapter.picked(key, indexes);
    }

    onClosed: {
        if (!answered)
            adapter.pickCancelled(key);
    }

    footerRow: [
        PrimaryButton {
            enabled: Object.keys(dlg.ticked).length > 0
            objectName: "pickApply"
            text: dlg.words.apply || ""

            onClicked: dlg.answer(Object.keys(dlg.ticked).map(Number))
        },
        GhostButton {
            objectName: "pickNone"
            text: dlg.words.none || ""
            visible: text !== ""

            onClicked: dlg.answer([])
        },
        GhostButton {
            text: dlg.adapter.words.cancel

            onClicked: dlg.close()
        }
    ]

    Column {
        spacing: Theme.sp4
        width: parent ? parent.width : 0

        Repeater {
            model: dlg.rows

            CheckRow {
                required property int index
                required property string modelData

                checked: dlg.ticked[index] === true
                objectName: "pickRow_" + index
                text: modelData

                onToggled: {
                    let m = Object.assign({}, dlg.ticked);
                    if (checked)
                        m[index] = true;
                    else
                        delete m[index];
                    dlg.ticked = m;
                }
            }
        }
    }
}
