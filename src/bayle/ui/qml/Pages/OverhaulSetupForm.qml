pragma ComponentBehavior: Bound
import QtQuick
import Theme
import Components

// The Overhaul setup (§8.10, Mod Configs): how a mod the profile treats as an overhaul is set up. The basic level is
// the generated rows of ConfigForm (per DLL: load early, load after the other DLLs, initializer; the settings files
// kept on updates; the merged copies, each untickable); it always loads last, which is said, not asked. A hand-edited
// (advanced) or verified setup shows what it does, read-only; Edit as text changes an advanced one. Save, Discard,
// Edit as text and the turn-off menu entry are the page's. Everything shown comes from the adapter.
Column {
    id: form

    required property var adapter
    readonly property var ov: adapter.overhaul
    readonly property var words: adapter.words

    spacing: Theme.sp16

    Txt {
        kind: "strong"
        text: (form.ov.label || "") + "  ·  " + (form.ov.status || "")
        width: parent.width
    }
    Txt {
        elide: Text.ElideNone
        kind: "hint"
        text: form.ov.loadsLast || ""
        visible: text !== "" && (form.ov.sections || []).length > 0
        width: parent.width
        wrapMode: Text.WordWrap
    }
    Txt {
        elide: Text.ElideNone
        kind: "hint"
        objectName: "overhaulNote"
        text: form.ov.note || ""
        visible: text !== ""
        width: parent.width
        wrapMode: Text.WordWrap
    }
    ConfigForm {
        adapter: form.adapter
        sections: form.ov.sections || []
        width: parent.width
    }
    Column {
        spacing: Theme.sp4
        visible: (form.ov.steps || []).length > 0
        width: parent.width

        Txt {
            kind: "strong"
            text: form.ov.stepsTitle || ""
        }
        Repeater {
            model: form.ov.steps || []

            Txt {
                required property string modelData

                elide: Text.ElideNone
                text: modelData
                width: form.width
                wrapMode: Text.WordWrap
            }
        }
    }
}
