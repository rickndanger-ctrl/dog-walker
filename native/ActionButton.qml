import QtQuick
import QtQuick.Controls

Button {
    id: control
    property bool primary: false
    property bool dark: false
    property bool danger: false
    implicitHeight: 44
    leftPadding: 20; rightPadding: 20
    hoverEnabled: true
    font.family: "Inter"
    font.pixelSize: 14
    font.weight: Font.DemiBold
    opacity: enabled ? 1 : 0.42
    contentItem: Text {
        text: control.text
        font: control.font
        color: control.primary ? (Theme.dark ? "#000000" : "#ffffff") : Theme.text
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }
    background: Rectangle {
        radius: 8
        color: control.primary ? (control.down ? Theme.muted : (control.hovered ? Theme.muted : Theme.accent)) : (control.dark ? (control.hovered ? Theme.elevated : "transparent") : (control.hovered ? Theme.hover : Theme.surface))
        border.width: control.primary || control.dark ? 0 : 1
        border.color: control.activeFocus ? Theme.text : Theme.border
    }
}
