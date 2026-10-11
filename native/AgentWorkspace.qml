pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

SplitView {
    id: workspace
    required property var controller
    Layout.fillWidth: true
    Layout.fillHeight: true
    Layout.minimumHeight: 140
    orientation: Qt.Horizontal
    handle: Rectangle {
        implicitWidth: 8
        color: SplitHandle.hovered || SplitHandle.pressed ? Theme.border : "transparent"
    }
    ColumnLayout {
        SplitView.preferredWidth: workspace.width * .5
        SplitView.minimumWidth: 140
        spacing: 5
        Copy {
            text: (workspace.controller.modelLabel || "Local model") + " · Live context"
            font.pixelSize: 12
            color: Theme.muted
            Layout.preferredHeight: 30
            verticalAlignment: Text.AlignVCenter
        }
        TerminalPane {
            objectName: "contextTerminalPane"
            controller: workspace.controller
            contextSide: true
            Layout.fillWidth: true
            Layout.fillHeight: true
        }
    }
    ColumnLayout {
        SplitView.fillWidth: true
        SplitView.minimumWidth: 230
        spacing: 5
        RowLayout {
            Layout.fillWidth: true
            Copy { text: "Agents"; font.pixelSize: 12; color: Theme.muted; Layout.fillWidth: true }
            ComboBox {
                id: helperMode
                objectName: "agentMode"
                palette: MonoPalette {}
                model: ["Review", "Help"]
                implicitHeight: 30
                Layout.preferredWidth: 92
                enabled: workspace.controller.online && !workspace.controller.chatBusy
                contentItem: Copy { text: helperMode.displayText; font.pixelSize: 12; leftPadding: 8; verticalAlignment: Text.AlignVCenter }
                background: Rectangle { color: Theme.surface; radius: 5; border.color: Theme.border }
                indicator: Copy { text: "⌄"; font.pixelSize: 12; color: Theme.muted; x: helperMode.width - 18; y: (helperMode.height - height) / 2 }
                ToolTip.visible: hovered
                ToolTip.text: "Review watches while the model runs. Help pauses before edits."
            }
        }
        Flow {
            Layout.fillWidth: true
            Layout.minimumHeight: implicitHeight
            spacing: 4
            ActionButton {
                objectName: "agentShell"
                text: "Shell"; implicitHeight: 28; leftPadding: 10; rightPadding: 10
                enabled: workspace.controller.online && workspace.controller.terminalAvailable
                onClicked: workspace.controller.terminalAction("shell")
            }
            Repeater {
                model: ["claude", "codex"]
                ActionButton {
                    required property string modelData
                    objectName: "agent-" + modelData
                    text: modelData === "claude" ? "Claude" : "Codex"
                    implicitHeight: 28; leftPadding: 10; rightPadding: 10
                    enabled: workspace.controller.online && workspace.controller.terminalAvailable
                        && !!workspace.controller.helperClients[modelData]
                        && (helperMode.currentIndex === 0 || (!workspace.controller.external && !workspace.controller.chatBusy
                            && workspace.controller.state && ["completed", "aborted"].indexOf(workspace.controller.state.status) < 0))
                    onClicked: workspace.controller.terminalAction("helper", modelData, helperMode.currentIndex === 0 ? "review" : "drive")
                }
            }
        }
        TerminalPane {
            objectName: "agentTerminalPane"
            controller: workspace.controller
            Layout.fillWidth: true
            Layout.fillHeight: true
        }
    }
}
