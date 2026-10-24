pragma ComponentBehavior: Bound
import QtQuick
import Theme

// A spot a DragHandle can drop on (a slot, a card, the Library, the Backups). `reasonOf(payload)` says in words why
// the spot refuses a drag ("" when it takes it); `dropped(payload)` fires on a valid or refused drop alike (the page's
// adapter says the refusal after release, never silently). A soft accent fill marks a valid spot; a red outline and
// the reason mark a refusing one.
DropArea {
    id: root

    property var lastSource: null
    property var reasonOf: payload => ""
    property string reason: ""
    property int radius: Theme.radiusCard
    readonly property bool taking: containsDrag && reason === ""

    signal dropPayload(var payload)

    keys: ["rs-drag"]

    onEntered: drag => {
        const src = drag.source;
        root.lastSource = src;
        root.reason = src ? root.reasonOf(src.payload) : "";
        if (src)
            src.refused = root.reason !== "";
    }
    onExited: {
        if (root.lastSource)
            root.lastSource.refused = false;
        root.reason = "";
    }
    onDropped: drop => {
        const src = drop.source;
        if (src) {
            src.refused = false;
            root.dropPayload(src.payload);
        }
        root.reason = "";
    }

    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.12)
        border.color: Theme.accent
        border.width: 1
        radius: root.radius
        visible: root.taking
    }
    Rectangle {
        anchors.fill: parent
        color: "transparent"
        border.color: Theme.statusDanger
        border.width: 1
        objectName: "dropRefused"
        radius: root.radius
        visible: root.containsDrag && root.reason !== ""
    }
    Rectangle {  // the reason, at the drop spot
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.verticalCenter: parent.verticalCenter
        color: Theme.surfaceCard
        border.color: Theme.statusDanger
        height: why.implicitHeight + Theme.sp8
        objectName: "dropReasonTag"
        radius: Theme.radiusCard
        visible: root.containsDrag && root.reason !== ""
        width: Math.min(why.implicitWidth + Theme.sp16, root.width)

        Txt {
            id: why

            anchors.centerIn: parent
            color: Theme.statusDanger
            elide: Text.ElideRight
            kind: "caption"
            text: root.reason
            width: parent.width - Theme.sp16
        }
    }
}
