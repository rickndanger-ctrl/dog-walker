pragma Singleton
import QtQuick
QtObject {
    property bool dark: true
    readonly property color canvas: dark ? "#101010" : "#ffffff"
    readonly property color sidebar: dark ? "#070707" : "#f3f3f3"
    readonly property color surface: dark ? "#1b1b1b" : "#f5f5f5"
    readonly property color elevated: dark ? "#252525" : "#eaeaea"
    readonly property color hover: dark ? "#303030" : "#e3e3e3"
    readonly property color text: dark ? "#f2f2f2" : "#181818"
    readonly property color muted: dark ? "#aaaaaa" : "#636363"
    readonly property color faint: dark ? "#858585" : "#757575"
    readonly property color border: dark ? "#363636" : "#d6d6d6"
    readonly property color strongBorder: dark ? "#666666" : "#999999"
    readonly property color accent: dark ? "#ffffff" : "#171717"
    readonly property color inverseText: dark ? "#000000" : "#ffffff"
}
