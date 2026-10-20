import QtQuick

// v2.20: reads the window's safe area (Qt 6.9+ `SafeArea`). Loaded by Main only when the native chrome hints are in
// use, in its own file so a Qt without SafeArea (6.8, Design Studio) fails this one load and reports 0.
Item {
    readonly property real topInset: SafeArea.margins.top
}
