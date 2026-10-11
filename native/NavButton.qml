import QtQuick
import QtQuick.Controls

Button {
    id: control
    property bool selected: false
    implicitHeight: 36
    leftPadding: 14; rightPadding: 14
    hoverEnabled: true
    contentItem: Text {
        text: control.text
        font.family: "Inter"; font.pixelSize: 14; font.weight: control.selected ? Font.DemiBold : Font.Normal
        color: control.selected ? Theme.text : Theme.muted
        verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
    }
    background: Rectangle {
        radius: 7
        color: control.selected ? Theme.elevated : control.hovered ? Theme.elevated : "transparent"
        border.width: control.activeFocus ? 1 : 0; border.color: Theme.text
    }
}
