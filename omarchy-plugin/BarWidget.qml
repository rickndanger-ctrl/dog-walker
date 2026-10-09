import QtQuick
import Quickshell
import qs.Ui

BarWidget {
    id: root
    moduleName: "rickndanger.dog-walker"
    implicitWidth: button.implicitWidth
    implicitHeight: button.implicitHeight
    BarIconButton {
        id: button
        anchors.fill: parent
        bar: root.bar
        text: "󰩃"
        tooltipText: "Dog Walker — your local model, kept on track"
        onPressed: Quickshell.execDetached([Quickshell.env("HOME") + "/.local/bin/dog-walker-gui"])
    }
}
