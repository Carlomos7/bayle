pragma ComponentBehavior: Bound
import QtQuick
import Theme
import Roundtable.Code

// Read-only formatted text: Qt's own Markdown (headings, lists, code blocks, links) in the type tokens, selectable.
// A plain text file sets `markdown: false` and shows as it is. Only http / https links open, in the browser. It sizes
// itself to its text, so it sits in a scrolling parent.
TextEdit {
    id: root

    property bool markdown: true

    function openLink(url) {
        if (/^https?:\/\//i.test(url))
            Qt.openUrlExternally(url);
    }
    function restyle() {
        if (markdown)
            support.restyle(textDocument, Theme.accent.toString(), Theme.syntaxString.toString(), Theme.fillInput.toString(), "Cascadia Mono,Consolas,Courier New");
    }

    color: Theme.textPrimary
    font.family: markdown ? Theme.fontFamily : "Cascadia Mono"
    font.pixelSize: Theme.fontBody
    readOnly: true
    selectByMouse: true
    selectedTextColor: Theme.textOnAccent
    selectionColor: Theme.accent
    textFormat: markdown ? TextEdit.MarkdownText : TextEdit.PlainText
    wrapMode: TextEdit.Wrap

    Component.onCompleted: restyle()
    onLinkActivated: link => openLink(link)
    onTextChanged: Qt.callLater(restyle)

    Connections {
        function onDarkChanged() {
            root.restyle();
        }

        target: Theme
    }
    MarkdownSupport {
        id: support

    }
    HoverHandler {
        cursorShape: root.hoveredLink !== "" ? Qt.PointingHandCursor : Qt.IBeamCursor
    }
}
