import QtQuick
import "../.runtime/qml/QMLTermWidget" as TerminalPlugin

/*
 * Native terminal surface backed by the pinned QMLTermWidget plugin.
 * Keep this component behind a Loader so the rest of Handler works when the
 * optional local plugin has not been built yet.
 */
Item {
    id: root

    property string shellProgram: "/bin/bash"
    property var arguments: []
    property string workingDirectory: ""
    property bool darkMode: true
    property string schemeName: ""
    property string fontFamily: "monospace"
    property int fontPointSize: 11
    property alias colorScheme: terminal.colorScheme
    property bool shellStarted: false

    signal finished()

    function copy() {
        terminal.copyClipboard()
    }

    function paste() {
        terminal.pasteClipboard()
    }

    function focusTerminal() {
        terminal.forceActiveFocus()
    }

    TerminalPlugin.QMLTermWidget {
        id: terminal
        anchors.fill: parent
        focus: true
        font.family: root.fontFamily
        font.pointSize: root.fontPointSize
        colorScheme: root.schemeName || (root.darkMode ? "HandlerDark" : "HandlerLight")
        session: TerminalPlugin.QMLTermSession {
            id: terminalSession
            shellProgram: root.shellProgram
            shellProgramArgs: root.arguments
            initialWorkingDirectory: root.workingDirectory
            onFinished: root.finished()
        }

    }

    // Wait for the split layout to settle before attaching the PTY. Starting
    // at a zero-size viewport can wrap and discard the initial context.
    Timer {
        interval: 60
        running: !root.shellStarted && terminal.width >= 80 && terminal.height >= 40
        repeat: false
        onTriggered: {
            root.shellStarted = true
            terminalSession.startShellProgram()
            if (root.visible) terminal.forceActiveFocus()
        }
    }

    Shortcut {
        sequence: "Ctrl+Shift+C"
        context: Qt.WindowShortcut
        enabled: root.visible && terminal.activeFocus
        onActivated: root.copy()
    }

    Shortcut {
        sequence: "Ctrl+Shift+V"
        context: Qt.WindowShortcut
        enabled: root.visible && terminal.activeFocus
        onActivated: root.paste()
    }
}
