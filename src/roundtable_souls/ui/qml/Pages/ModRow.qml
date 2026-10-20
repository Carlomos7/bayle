pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import Theme
import App
import Components

// One mod row (§8.10): grip · load index · toggle · name + at most two tags · status line · gear (Mod options, a
// dot when the mod has config files) · file icon (natives) · trash. Rows are not cards: transparent at rest, a fill on
// hover, a hairline divider. Dragged from the grip: the row lifts, the gold line marks where it lands, and on release
// the adapter moves it (the backend applies me3's rules and says why a move is refused). Ctrl+Up / Ctrl+Down and
// the right-click Move menu do the same. The row's data are the adapter's row model roles.
Item {
    id: holder

    required property var adapter
    required property bool has_configs
    required property string configs_tip
    required property int entry
    required property bool locked
    required property string kind
    required property string more
    required property string name
    required property bool on
    required property string path
    required property int position
    required property string status
    required property bool status_error
    required property var tags
    property int count: 0
    property Item dragLayer
    property var page
    readonly property bool held: grip.drag.active
    readonly property var words: adapter.words
    readonly property int entryIndex: holder.entry   // the profile block index

    height: Theme.rowH
    objectName: "row_" + holder.name

    Keys.onPressed: event => {
        if (!(event.modifiers & Qt.ControlModifier))
            return;
        if (event.key === Qt.Key_Up) {
            holder.adapter.moveBy(holder.entryIndex, -1);
            event.accepted = true;
        } else if (event.key === Qt.Key_Down) {
            holder.adapter.moveBy(holder.entryIndex, 1);
            event.accepted = true;
        }
    }

    DropArea {  // a lifted row of the same kind over this one: it would land here
        anchors.fill: parent

        onEntered: drag => {
            const src = drag.source as ModRow;
            if (src && src !== holder && src.kind === holder.kind) {
                holder.page.dropTarget = holder.position - 1;
                holder.page.dragKind = holder.kind;
            }
        }
    }
    Rectangle {  // the gold insertion line where the lifted row will land
        anchors.left: parent.left
        anchors.leftMargin: Theme.sp16
        anchors.right: parent.right
        anchors.rightMargin: Theme.sp16
        color: Theme.accent
        height: 2
        radius: 1
        visible: holder.page && holder.page.dragKind === holder.kind && holder.page.dropTarget === holder.position - 1 && !holder.held
        y: 0
        z: 3
    }
    Hairline {
        endInset: Theme.dividerEndInset
        inset: Theme.dividerInset
        visible: holder.position < holder.count && !holder.held
        y: Math.round(holder.height) - 1
        z: 2
    }
    Rectangle {
        id: row

        Drag.active: holder.held
        Drag.hotSpot.x: 24
        Drag.hotSpot.y: 24
        Drag.source: holder
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.verticalCenter: parent.verticalCenter
        color: holder.held ? Theme.surfaceCard : holder.activeFocus ? Theme.accentSoft : rowHover.containsMouse ? Theme.fillHover : "transparent"
        height: holder.height
        radius: holder.held ? Theme.radiusCard : 0
        width: holder.width

        states: State {
            when: holder.held

            ParentChange {
                parent: holder.dragLayer
                target: row
            }
            AnchorChanges {
                anchors.horizontalCenter: undefined
                anchors.verticalCenter: undefined
                target: row
            }
            PropertyChanges {
                row.scale: 1.02
                row.z: 10
            }
        }

        SoftShadow {
            elevation: "raise"
            radius: Theme.radiusCard
            target: row
            visible: holder.held
        }
        FocusRing {
            active: holder.activeFocus
            radiusOf: Theme.radiusCard
        }
        MouseArea {
            id: rowHover

            ToolTip.delay: Theme.mTooltipDelay
            ToolTip.text: holder.more
            ToolTip.visible: containsMouse && !holder.held && holder.more !== ""
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            anchors.fill: parent
            hoverEnabled: true

            onClicked: mouse => {
                holder.forceActiveFocus();
                if (mouse.button === Qt.RightButton && !holder.locked)
                    rowMenu.popup();
            }
        }
        PopupMenu {
            id: rowMenu

            MenuEntry {
                shortcut: "Ctrl+Up"
                text: holder.words.moveUp

                onTriggered: holder.adapter.moveBy(holder.entryIndex, -1)
            }
            MenuEntry {
                shortcut: "Ctrl+Down"
                text: holder.words.moveDown

                onTriggered: holder.adapter.moveBy(holder.entryIndex, 1)
            }
            MenuEntry {
                text: holder.words.moveTop

                onTriggered: holder.adapter.moveBy(holder.entryIndex, -1000)
            }
            MenuEntry {
                text: holder.words.moveBottom

                onTriggered: holder.adapter.moveBy(holder.entryIndex, 1000)
            }
            MenuEntry {
                text: holder.words.rename

                onTriggered: holder.adapter.openRename(holder.entryIndex)
            }
        }
        Item {  // the grip at x 16
            anchors.left: parent.left
            height: parent.height
            width: 40

            FluentIcon {
                anchors.verticalCenter: parent.verticalCenter
                color: holder.locked ? Theme.textDisabled : Theme.textIcon
                name: holder.locked ? "Pin" : "Move"
                size: Theme.iconRow
                x: Theme.sp16
            }
            MouseArea {
                id: grip

                ToolTip.text: holder.words.lockedTip
                ToolTip.visible: containsMouse && holder.locked
                anchors.fill: parent
                cursorShape: enabled ? (pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor) : Qt.ForbiddenCursor
                drag.axis: Drag.YAxis
                drag.target: row
                enabled: !holder.locked
                hoverEnabled: true
                objectName: "grip_" + holder.name

                onPressed: {
                    holder.page.dropTarget = -1;
                    holder.page.dragKind = holder.kind;
                }
                onReleased: {
                    const to = holder.page.dropTarget;
                    holder.page.dropTarget = -1;
                    holder.page.dragKind = "";
                    if (to >= 0 && to !== holder.position - 1)
                        holder.adapter.moveTo(holder.entryIndex, to);
                }
            }
        }
        Txt {  // the load index at x 40
            anchors.verticalCenter: parent.verticalCenter
            horizontalAlignment: Text.AlignRight
            kind: "caption"
            opacity: holder.on ? 1 : 0.55
            tabular: true
            text: holder.position
            width: 18
            x: 40
        }
        ToggleSwitch {  // at x 64
            anchors.verticalCenter: parent.verticalCenter
            checked: holder.on
            objectName: "toggle_" + holder.name
            x: 64

            onToggled: holder.adapter.setEnabled(holder.entryIndex, checked)
        }
        Column {  // the title at x 120
            id: titleCol

            anchors.left: parent.left
            anchors.leftMargin: 120
            anchors.right: actions.left
            anchors.rightMargin: Theme.sp8
            anchors.verticalCenter: parent.verticalCenter
            opacity: holder.on ? 1 : 0.55
            spacing: 2

            Row {
                spacing: Theme.sp8

                Txt {
                    anchors.verticalCenter: parent.verticalCenter
                    kind: "rowTitle"
                    text: holder.name
                    width: Math.min(implicitWidth, Math.max(80, titleCol.width - (holder.tags.length > 0 ? 140 : 0)))   // a long name gives way to the tag
                }
                Repeater {
                    model: holder.tags

                    Pill {
                        required property var modelData

                        anchors.verticalCenter: parent.verticalCenter
                        icon_: modelData.icon
                        level: modelData.level
                        text: modelData.text
                    }
                }
            }
            Txt {
                color: holder.status_error ? Theme.statusDanger : Theme.textSecondary
                kind: "caption"
                text: holder.status
                visible: holder.status !== ""   // a missing folder or a clash is said at every width
                width: parent ? parent.width : 0
            }
        }
        Row {  // right-side actions on one pitch
            id: actions

            anchors.right: parent.right
            anchors.rightMargin: Theme.sp16 - 6
            anchors.verticalCenter: parent.verticalCenter
            spacing: 0

            IconButton {
                ToolTip.text: holder.words.optionsTip + (holder.has_configs ? "  ·  " + holder.words.configsTip + ": " + holder.configs_tip : "")
                ToolTip.visible: hovered
                iconSize: Theme.iconRow
                icon_: "Setting"
                implicitHeight: Theme.controlH
                implicitWidth: 32
                objectName: "options_" + holder.name

                onClicked: holder.adapter.openOptions(holder.entryIndex)

                Rectangle {
                    anchors.margins: 5
                    anchors.right: parent.right
                    anchors.top: parent.top
                    color: Theme.accent
                    height: 7
                    radius: 3.5
                    visible: holder.has_configs
                    width: 7
                }
            }
            IconButton {
                ToolTip.text: holder.words.attachTip
                ToolTip.visible: hovered
                iconSize: Theme.iconRow
                icon_: "Document"
                implicitHeight: Theme.controlH
                implicitWidth: 32
                visible: holder.kind === "native"

                onClicked: holder.adapter.attachConfig(holder.entryIndex)
            }
            IconButton {
                ToolTip.text: holder.words.removeTip
                ToolTip.visible: hovered
                danger: true
                iconSize: Theme.iconRow
                icon_: "Delete"
                implicitHeight: Theme.controlH
                implicitWidth: 32
                objectName: "remove_" + holder.name

                onClicked: holder.adapter.remove(holder.entryIndex)
            }
        }
    }
}
