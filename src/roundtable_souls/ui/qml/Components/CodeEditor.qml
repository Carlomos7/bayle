pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import Theme
import Roundtable.Code

// The ONE text editor (raw .me3, Edit as text for a mod's config, README and changelog, a job's log): monospace,
// syntax colours by `language` (toml, ini, json, lua, markdown; or give `fileName` and the extension picks it), a line
// number gutter, the current line marked, find / replace (Ctrl+F, F3 / Shift+F3, Esc), go to line (Ctrl+G), Tab /
// Shift+Tab indent and outdent, and no wrap unless `wrap`. For toml, ini and json the text is parsed in the
// background 400 ms after typing stops: the first error marks its line in the gutter and its words show under the
// editor (`errorLine` / `errorMessage`; they never block saving, the caller decides that). The caller's hook is
// `text` and `onEdited`.
Rectangle {
    id: root

    readonly property int errorLine: support.errorLine
    readonly property string errorMessage: support.errorMessage
    property bool diagnostics: !readOnly
    property bool error: false                  // the caller's own error state (danger ring)
    property string fileName: ""
    property bool findable: !readOnly
    property string language: ""
    property bool lineNumbers: true
    property bool mono: true
    property bool readOnly: false
    property alias text: textArea.text
    property bool wrap: false
    readonly property string languageInUse: language !== "" ? language : support.languageFor(fileName)
    readonly property int lineCount: {
        textArea.length;
        return support.lineOfPosition(textArea.length);
    }
    readonly property int barH: Math.max(findBar.open ? findBar.height : 0, gotoBar.open ? gotoBar.height : 0)
    property int firstLine: 1
    property int lastLine: 1

    signal edited

    function goToLine(n) {
        textArea.cursorPosition = support.positionOfLine(n);
        textArea.forceActiveFocus();
    }
    function showFind() {
        gotoBar.close();
        findBar.show();
    }
    function refreshGutter() {
        const y0 = flick.contentY, y1 = flick.contentY + flick.height;
        root.firstLine = support.lineOfPosition(textArea.positionAt(0, y0));
        root.lastLine = support.lineOfPosition(textArea.positionAt(0, y1));
    }

    color: Theme.fillInput
    implicitHeight: 200
    radius: Theme.radiusControl

    Behavior on color {
        ColorAnimation {
            duration: Theme.mToggle
            easing.type: Easing.OutCubic
        }
    }

    CodeSupport {
        id: support

        colors: ({
                keyword: Theme.syntaxKeyword,
                string: Theme.syntaxString,
                number: Theme.syntaxNumber,
                comment: Theme.syntaxComment,
                key: Theme.syntaxKey,
                header: Theme.syntaxHeader
            })
        language: root.languageInUse
        textDocument: textArea.textDocument
    }
    Timer {  // parse in the background once typing has stopped
        id: checkTimer

        interval: 400

        onTriggered: support.check(textArea.text)
    }
    HoverHandler {
        id: hover
    }
    FocusRing {
        active: textArea.activeFocus
        error: root.error || root.errorLine > 0
        radiusOf: Theme.radiusControl
    }
    FindBar {
        id: findBar

        anchors.left: parent.left
        anchors.margins: Theme.sp4
        anchors.right: parent.right
        anchors.top: parent.top
        area: textArea
        support: support
        z: 2
    }
    Rectangle {  // go to line
        id: gotoBar

        property bool open: false

        function close() {
            open = false;
            textArea.forceActiveFocus();
        }
        function show() {
            findBar.close();
            open = true;
            gotoField.forceActiveFocus();
            gotoField.selectAll();
        }

        anchors.left: parent.left
        anchors.margins: Theme.sp4
        anchors.right: parent.right
        anchors.top: parent.top
        color: Theme.surfaceCard
        height: open ? Theme.controlH + Theme.sp8 * 2 : 0
        radius: Theme.radiusControl
        visible: open
        z: 2

        Keys.onEscapePressed: gotoBar.close()

        TextBox {
            id: gotoField

            anchors.left: parent.left
            anchors.margins: Theme.sp8
            anchors.verticalCenter: parent.verticalCenter
            inputMethodHints: Qt.ImhDigitsOnly
            objectName: "gotoLine"
            placeholderText: qsTr("Go to line (1 to %1)").arg(root.lineCount)
            validator: IntValidator {
                bottom: 1
                top: Math.max(1, root.lineCount)
            }
            width: 220

            Keys.onReturnPressed: {
                if (acceptableInput)
                    root.goToLine(parseInt(text));
                gotoBar.close();
            }
        }
    }
    Shortcut {
        enabled: root.findable && root.visible && (textArea.activeFocus || findBar.open || gotoBar.open)
        sequences: [StandardKey.Find]

        onActivated: root.showFind()
    }
    Shortcut {
        enabled: root.findable && root.visible && (textArea.activeFocus || findBar.open)
        sequences: ["F3"]

        onActivated: findBar.matches.length ? findBar.next(false) : root.showFind()
    }
    Shortcut {
        enabled: root.findable && root.visible && (textArea.activeFocus || findBar.open)
        sequences: ["Shift+F3"]

        onActivated: findBar.matches.length ? findBar.next(true) : root.showFind()
    }
    Shortcut {
        enabled: root.visible && (textArea.activeFocus || findBar.open || gotoBar.open)
        sequences: ["Ctrl+G"]

        onActivated: {
            findBar.close();
            gotoBar.show();
        }
    }

    Item {
        id: body

        anchors.bottomMargin: status.height
        anchors.fill: parent
        anchors.topMargin: root.barH > 0 ? root.barH + Theme.sp8 : 0

        Item {  // the line number gutter: only the visible lines exist
            id: gutter

            readonly property int digits: Math.max(3, String(root.lineCount).length)

            anchors.bottom: parent.bottom
            anchors.left: parent.left
            anchors.leftMargin: Theme.sp4
            anchors.top: parent.top
            clip: true
            visible: root.lineNumbers
            width: root.lineNumbers ? digits * 8 + Theme.sp8 * 2 + 8 : 0

            Repeater {
                model: root.lineNumbers ? Math.min(root.lastLine - root.firstLine + 1, 400) : 0

                delegate: Item {
                    id: row

                    required property int index
                    readonly property int line: root.firstLine + index
                    readonly property bool bad: line === root.errorLine
                    readonly property rect r: {
                        flick.contentY;
                        textArea.contentHeight;
                        return textArea.positionToRectangle(support.positionOfLine(line));
                    }

                    height: r.height
                    width: gutter.width
                    y: r.y - flick.contentY

                    Rectangle {  // the error marker
                        anchors.left: parent.left
                        anchors.leftMargin: 2
                        anchors.verticalCenter: parent.verticalCenter
                        color: Theme.statusDanger
                        height: 8
                        radius: 4
                        visible: row.bad
                        width: 8
                    }
                    Text {
                        anchors.right: parent.right
                        anchors.rightMargin: Theme.sp8
                        color: row.bad ? Theme.statusDanger : row.line === support.lineOfPosition(textArea.cursorPosition) ? Theme.textPrimary : Theme.textSecondary
                        font.family: textArea.font.family
                        font.pixelSize: textArea.font.pixelSize
                        text: row.line
                        y: Math.max(0, (parent.height - height) / 2)
                    }
                    HoverHandler {
                        id: markHover

                        enabled: row.bad
                    }
                    ToolTip.delay: 300
                    ToolTip.text: root.errorMessage
                    ToolTip.visible: row.bad && markHover.hovered
                }
            }
        }
        Rectangle {  // the gutter's edge
            anchors.bottom: parent.bottom
            anchors.left: gutter.right
            anchors.top: parent.top
            color: Theme.borderHairline
            visible: root.lineNumbers
            width: 1
        }
        Flickable {
            id: flick

            anchors.bottom: parent.bottom
            anchors.bottomMargin: Theme.sp4
            anchors.left: gutter.right
            anchors.leftMargin: Theme.sp4
            anchors.right: parent.right
            anchors.rightMargin: Theme.sp4
            anchors.top: parent.top
            boundsBehavior: Flickable.StopAtBounds
            clip: true
            contentHeight: textArea.implicitHeight
            contentWidth: root.wrap ? width : Math.max(width, textArea.implicitWidth)

            ScrollBar.horizontal: ScrollBar {
                id: hbar

                policy: ScrollBar.AsNeeded

                contentItem: Rectangle {
                    color: Theme.textTertiary
                    implicitHeight: 6
                    opacity: hbar.pressed ? 1 : (hover.hovered || hbar.active ? 0.8 : 0)
                    radius: 3
                }
            }
            ScrollBar.vertical: ScrollBar {
                id: bar

                policy: ScrollBar.AsNeeded

                contentItem: Rectangle {
                    color: Theme.textTertiary
                    implicitWidth: 6
                    opacity: bar.pressed ? 1 : (hover.hovered || bar.active ? 0.8 : 0)
                    radius: 3

                    Behavior on opacity {
                        NumberAnimation {
                            duration: Theme.mFast
                            easing.type: Easing.OutCubic
                        }
                    }
                }
            }

            onContentYChanged: root.refreshGutter()
            onHeightChanged: root.refreshGutter()

            Rectangle {  // the current line
                color: Theme.fillHover
                height: textArea.cursorRectangle.height
                visible: textArea.activeFocus
                width: Math.max(flick.contentWidth, flick.width)
                y: textArea.cursorRectangle.y
                z: -1
            }
            Rectangle {  // the line the parse error is on
                readonly property rect r: textArea.positionToRectangle(support.positionOfLine(root.errorLine))

                color: Theme.statusDangerBg
                height: r.height
                visible: root.errorLine > 0
                width: Math.max(flick.contentWidth, flick.width)
                y: r.y
                z: -1
            }
            TextArea.flickable: TextArea {
                id: textArea

                background: null
                color: Theme.textPrimary
                font.family: root.mono ? "Cascadia Mono" : Theme.fontFamily
                font.pixelSize: root.mono ? 13 : Theme.fontBody
                readOnly: root.readOnly
                selectedTextColor: Theme.textOnAccent
                selectionColor: Theme.accent
                tabStopDistance: 4 * fontMetrics.advanceWidth(" ")
                wrapMode: root.wrap ? TextArea.Wrap : TextArea.NoWrap

                Keys.onBacktabPressed: event => {
                    if (root.readOnly)
                        return;
                    const r = support.indent(selectionStart, selectionEnd, true);
                    select(r[0], r[1]);
                    event.accepted = true;
                }
                Keys.onTabPressed: event => {
                    if (root.readOnly)
                        return;
                    const r = support.indent(selectionStart, selectionEnd, false);
                    select(r[0], r[1]);
                    event.accepted = true;
                }
                onTextChanged: {
                    if (activeFocus)
                        root.edited();
                    if (root.diagnostics)
                        checkTimer.restart();
                    Qt.callLater(root.refreshGutter);
                    if (findBar.open)
                        findBar.refresh(false);
                }

                FontMetrics {
                    id: fontMetrics

                    font: textArea.font
                }
            }
        }
    }
    Item {  // under the text: the error in words, the cursor position, the wrap switch
        id: status

        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        height: Theme.sp24

        Txt {
            anchors.left: parent.left
            anchors.leftMargin: Theme.sp8
            anchors.right: caret.left
            anchors.rightMargin: Theme.sp8
            anchors.verticalCenter: parent.verticalCenter
            color: Theme.statusDanger
            elide: Text.ElideRight
            kind: "caption"
            objectName: "codeError"
            text: root.errorLine > 0 ? root.errorMessage : ""
        }
        Txt {
            id: caret

            anchors.right: wrapButton.left
            anchors.rightMargin: Theme.sp8
            anchors.verticalCenter: parent.verticalCenter
            color: Theme.textSecondary
            kind: "caption"
            text: qsTr("Line %1, column %2").arg(support.lineOfPosition(textArea.cursorPosition)).arg(textArea.cursorPosition - support.positionOfLine(support.lineOfPosition(textArea.cursorPosition)) + 1)
        }
        GhostButton {
            id: wrapButton

            ToolTip.text: qsTr("Wrap long lines (Alt+Z)")
            anchors.right: parent.right
            anchors.rightMargin: Theme.sp4
            anchors.verticalCenter: parent.verticalCenter
            flat: !root.wrap
            implicitHeight: Theme.controlSmallH
            objectName: "wrapToggle"
            text: qsTr("Wrap")

            onClicked: root.wrap = !root.wrap

            HoverHandler {
                cursorShape: Qt.PointingHandCursor
            }
        }
    }
    Shortcut {
        enabled: root.visible && textArea.activeFocus
        sequences: ["Alt+Z"]

        onActivated: root.wrap = !root.wrap
    }
}
