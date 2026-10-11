import QtQuick
import QtTest
import "../../native" as Ui

TestCase {
    id: test
    name: "AgentWorkspace"
    when: windowShown
    visible: true
    width: 850; height: 550
    ListModel { id: rows }
    QtObject {
        id: controller
        property bool online: true
        property bool terminalAvailable: true
        property bool external: false
        property bool chatBusy: false
        property var helperClients: ({claude: true, codex: true})
        property var state: ({id: "test-walk", status: "running"})
        property string modelLabel: "Ornith"
        property var terminals: []
        property var terminalRows: rows
        property string selectedTerminalId: ""
        property string terminalScheme: ""
        property string terminalBackground: ""
        property string terminalFont: "monospace"
        property int terminalFontSize: 9
        property string nativeRoot: Qt.resolvedUrl("../../native").toString().replace(/^file:\/\//, "")
        property string error: ""
        property var calls: []
        function terminalAction(kind, provider, mode) { calls = calls.concat([{kind: kind, provider: provider || "", mode: mode || ""}]) }
        function add(kind, key, label) {
            var value = {id: "test-walk:" + key, run_id: "test-walk", kind: kind, label: label,
                program: "/bin/sh", args: ["-c", "printf 'Terminal ready\\n'; while IFS= read -r line; do :; done"], cwd: "/tmp"}
            terminals = terminals.concat([value])
            rows.append({payload: JSON.stringify(value)})
            return value.id
        }
    }
    Ui.AgentWorkspace { id: workspace; width: 640; height: 360; controller: controller }
    function init() {
        rows.clear(); controller.terminals = []; controller.calls = []; controller.error = ""
        controller.external = false; controller.chatBusy = false
        controller.state = {id: "test-walk", status: "running"}
        workspace.width = 640; workspace.height = 360
        findChild(workspace, "agentMode").currentIndex = 0
        controller.add("context", "context", "Live context")
        controller.selectedTerminalId = controller.add("shell", "shell", "Shell")
        wait(50)
    }
    function cleanup() { rows.clear(); controller.terminals = [] }
    function test_review_agent_stays_on_right_without_restarting_left_context() {
        var context = findChild(workspace, "contextTerminalPane")
        var agents = findChild(workspace, "agentTerminalPane")
        var left = findChild(context, "terminal-test-walk:context")
        tryCompare(left, "status", Loader.Ready)
        var original = left.item
        mouseClick(findChild(workspace, "agent-claude"))
        compare(controller.calls[0].mode, "review")
        compare(controller.calls[0].provider, "claude")
        controller.selectedTerminalId = controller.add("helper", "claude-review", "Claude · Review")
        wait(50)
        compare(context.descriptors.length, 1)
        compare(agents.descriptors.length, 2)
        compare(context.chosenId, "test-walk:context")
        compare(agents.chosenId, "test-walk:claude-review")
        compare(left.item, original)
        compare(controller.error, "")
    }
    function test_help_is_explicit_and_unavailable_for_external_or_finished_walks() {
        var mode = findChild(workspace, "agentMode")
        var codex = findChild(workspace, "agent-codex")
        mode.currentIndex = 1
        mouseClick(codex)
        compare(controller.calls[0].mode, "drive")
        controller.external = true
        verify(!codex.enabled)
        controller.external = false
        controller.state = {id: "test-walk", status: "completed"}
        verify(!codex.enabled)
        mode.currentIndex = 0
        verify(codex.enabled)
    }
    function test_small_workspace_keeps_agent_controls_inside_right_pane() {
        workspace.width = 410; workspace.height = 260
        wait(50)
        for (var name of ["agentMode", "agentShell", "agent-claude", "agent-codex"]) {
            var button = findChild(workspace, name)
            var point = button.mapToItem(workspace, 0, 0)
            verify(point.x >= 0 && point.x + button.width <= workspace.width + 1, name)
            verify(point.y >= 0 && point.y + button.height <= workspace.height + 1, name)
        }
    }
}
