import QtQuick

// Drop inside any clickable Item that is not a house button (a row, a chip, a link): the hand while it is enabled,
// the arrow when it is off. House buttons, tabs and menu entries already have it.
HoverHandler {
    cursorShape: parent && parent.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
}
