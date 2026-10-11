import QtQuick
import QtTest

TestCase {
    name: "EmbeddedTerminal"
    when: windowShown
    visible: true
    width: 700; height: 450

    SignalSpy {
        id: terminalFinished
        signalName: "finished"
    }

    function test_shellStartsOnceAcrossThemeAndResizeChanges() {
        const loader = createTemporaryObject(loaderComponent, this)
        verify(loader)
        loader.setSource(Qt.resolvedUrl("../../native/EmbeddedTerminal.qml"), {
            shellProgram: "/bin/sh",
            arguments: ["-c", "printf 'terminal-ready\\n'; exit 0"],
            workingDirectory: "/tmp"
        })
        tryCompare(loader, "status", Loader.Ready)
        verify(loader.item)

        terminalFinished.target = loader.item
        terminalFinished.clear()
        compare(loader.item.darkMode, true)
        compare(loader.item.colorScheme, "HandlerDark")
        loader.item.darkMode = false
        compare(loader.item.colorScheme, "HandlerLight")
        loader.item.width = 720
        loader.item.height = 460

        tryCompare(terminalFinished, "count", 1, 5000)
        wait(250)
        compare(terminalFinished.count, 1)
        loader.destroy()
    }

    function test_keyboard_input_reaches_real_shell() {
        const loader = createTemporaryObject(loaderComponent, this)
        loader.setSource(Qt.resolvedUrl("../../native/EmbeddedTerminal.qml"), {
            shellProgram: "/bin/sh",
            arguments: ["-c", "while IFS= read -r line; do if [ \"$line\" = handler ]; then exit 0; fi; done"],
            workingDirectory: "/tmp"
        })
        tryCompare(loader, "status", Loader.Ready)
        terminalFinished.target = loader.item
        terminalFinished.clear()
        loader.item.focusTerminal()
        wait(100)
        for (const key of [Qt.Key_H, Qt.Key_A, Qt.Key_N, Qt.Key_D, Qt.Key_L, Qt.Key_E, Qt.Key_R]) keyClick(key)
        keyClick(Qt.Key_Return)
        tryCompare(terminalFinished, "count", 1, 5000)
        loader.destroy()
    }

    Component {
        id: loaderComponent
        Loader { width: 640; height: 400 }
    }
}
