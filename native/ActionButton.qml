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
        color: control.primary ? "#ffffff" : (control.dark ? "#e4efe9" : (control.danger ? "#a63e35" : "#244e43"))
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }
    background: Rectangle {
        radius: 10
        color: control.primary ? (control.down ? "#173c32" : (control.hovered ? "#28634f" : "#204e42")) : (control.dark ? (control.hovered ? "#294c41" : "transparent") : (control.hovered ? "#eceee7" : "#ffffff"))
        border.width: control.primary || control.dark ? 0 : 1
        border.color: control.activeFocus ? "#769980" : "#dedfd6"
        Behavior on color { ColorAnimation { duration: 120 } }
    }
}
