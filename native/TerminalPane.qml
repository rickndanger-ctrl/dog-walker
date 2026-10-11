pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts

Item {
    id: pane
    required property var controller
    property bool contextSide: false
    readonly property var descriptors: controller.state ? controller.terminals.filter(function(t) {
        return t.run_id === controller.state.id && (t.kind === "context") === pane.contextSide
    }) : []
    readonly property string chosenId: contextSide ? (descriptors.length ? descriptors[0].id : "")
        : descriptors.some(function(t) { return t.id === controller.selectedTerminalId })
            ? controller.selectedTerminalId : descriptors.length ? descriptors[0].id : ""

    ColumnLayout {
        anchors.fill: parent
        spacing: 0
        Flickable {
            visible: !pane.contextSide && pane.descriptors.length > 1
            Layout.fillWidth: true
            Layout.preferredHeight: 30
            Layout.minimumHeight: 30
            Layout.maximumHeight: 30
            clip: true
            contentWidth: Math.max(width, tabs.implicitWidth)
            contentHeight: height
            boundsBehavior: Flickable.StopAtBounds
            Row {
                id: tabs
                height: parent.height
                spacing: 3
                Repeater {
                    model: pane.controller.terminalRows
                    delegate: Item {
                        id: tab
                        required property string payload
                        readonly property var descriptor: JSON.parse(payload)
                        visible: !!pane.controller.state && descriptor.run_id === pane.controller.state.id
                            && descriptor.kind !== "context"
                        width: visible ? Math.max(60, caption.implicitWidth + 20) : 0
                        height: tabs.height
                        Rectangle {
                            anchors.fill: parent
                            color: pane.chosenId === tab.descriptor.id ? Theme.elevated : "transparent"
                            radius: 5
                        }
                        Copy {
                            id: caption
                            anchors.centerIn: parent
                            text: tab.descriptor.label || "Terminal"
                            font.pixelSize: 12
                            color: pane.chosenId === tab.descriptor.id ? Theme.text : Theme.muted
                        }
                        MouseArea { anchors.fill: parent; onClicked: pane.controller.selectedTerminalId = tab.descriptor.id }
                    }
                }
            }
        }
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 70
            color: pane.controller.terminalBackground || (Theme.dark ? "#131519" : "#f5f2eb")
            radius: 5
            clip: true
            Repeater {
                model: pane.controller.terminalRows
                delegate: Item {
                    id: terminalTab
                    required property string payload
                    readonly property var descriptor: JSON.parse(payload)
                    readonly property bool belongs: (descriptor.kind === "context") === pane.contextSide
                    anchors.fill: parent
                    visible: belongs && descriptor.id === pane.chosenId
                    Loader {
                        id: terminalLoader
                        objectName: "terminal-" + terminalTab.descriptor.id
                        anchors.fill: parent
                        // Each descriptor creates one PTY on its own side. Hidden
                        // sessions stay mounted when another agent is selected.
                        Component.onCompleted: if (terminalTab.belongs) setSource("file://" +
                            (pane.controller.nativeRoot || pane.controller.appRoot + "/native") + "/EmbeddedTerminal.qml", {
                                shellProgram: terminalTab.descriptor.program,
                                arguments: terminalTab.descriptor.args || [],
                                workingDirectory: terminalTab.descriptor.cwd || "",
                                darkMode: Theme.dark,
                                schemeName: pane.controller.terminalScheme || "",
                                fontFamily: pane.controller.terminalFont || "monospace",
                                fontPointSize: pane.controller.terminalFontSize || 11
                            })
                        onStatusChanged: if (status === Loader.Error) pane.controller.error = "The terminal could not load. Run scripts/install-terminal.py, then reopen Handler."
                        onVisibleChanged: if (visible && item) item.focusTerminal()
                    }
                    Binding { target: terminalLoader.item; property: "darkMode"; value: Theme.dark; when: terminalLoader.status === Loader.Ready }
                    Binding { target: terminalLoader.item; property: "schemeName"; value: pane.controller.terminalScheme || ""; when: terminalLoader.status === Loader.Ready }
                    Binding { target: terminalLoader.item; property: "fontFamily"; value: pane.controller.terminalFont || "monospace"; when: terminalLoader.status === Loader.Ready }
                    Binding { target: terminalLoader.item; property: "fontPointSize"; value: pane.controller.terminalFontSize || 11; when: terminalLoader.status === Loader.Ready }
                }
            }
            Copy {
                anchors.centerIn: parent
                width: Math.max(0, parent.width - 24)
                horizontalAlignment: Text.AlignHCenter
                visible: pane.descriptors.length === 0
                text: pane.controller.terminalAvailable ? "Opening terminal…" : "Terminal support unavailable"
                color: Theme.muted
                font.pixelSize: 12
            }
        }
    }
}
