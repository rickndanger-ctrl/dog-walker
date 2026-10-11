import QtQuick
import QtTest
import "../../native" as Ui

TestCase {
    id: test
    name: "ChatKeyboard"
    when: windowShown
    visible: true
    width: 900; height: 680
    QtObject {
        id: controller
        property var chat: ({id: "fixture", title: "Keyboard test", messages: [], attachments: [], project: "/fixture", selected_plugins: []})
        property bool chatBusy: false
        property bool active: false
        property bool online: true
        property string chatProgress: ""
        property string error: ""
        property string page: "chat"
        property var selectedPlugins: []
        property var modelProfiles: []
        property string modelId: ""
        property string modelLabel: ""
        property var sent: []
        signal chatAccepted(string chatId, string text)
        function send(command) { sent = sent.concat([command]) }
        function openPath(path) {}
    }
    Ui.ChatPane { id: panel; width: 900; height: 660; controller: controller }
    SignalSpy { id: projectChooser; target: panel; signalName: "chooseProject" }
    property var input
    function init() {
        controller.chat = {id: "fixture", title: "Keyboard test", messages: [], attachments: [], project: "/fixture", selected_plugins: []}
        controller.sent = []; controller.active = false; controller.chatBusy = false; controller.online = true
        projectChooser.clear()
        panel.submitting = false
        input = findChild(panel, "chatComposer")
        verify(input !== null)
        input.text = "Hello"
        input.forceActiveFocus()
        tryCompare(input, "activeFocus", true)
    }
    function test_enter_sends_once_and_waits_for_ack() {
        keyClick(Qt.Key_Return)
        compare(controller.sent.length, 1)
        compare(controller.sent[0].op, "chat_send")
        compare(controller.sent[0].text, "Hello")
        compare(input.text, "Hello")
        keyClick(Qt.Key_Return)
        compare(controller.sent.length, 1)
        controller.chatAccepted("fixture", "Hello")
        compare(input.text, "")
        compare(panel.submitting, false)
    }
    function test_shift_enter_inserts_newline() {
        input.cursorPosition = input.text.length
        keyClick(Qt.Key_Return, Qt.ShiftModifier)
        compare(controller.sent.length, 0)
        compare(input.text, "Hello\n")
    }
    function test_enter_cannot_bypass_walk_or_offline_guard() {
        controller.active = true
        keyClick(Qt.Key_Return)
        compare(controller.sent.length, 0)
        controller.active = false; controller.online = false
        panel.submit(false)
        compare(controller.sent.length, 0)
    }
    function test_oversized_message_is_not_sent() {
        input.text = "x".repeat(8001)
        keyClick(Qt.Key_Return)
        compare(controller.sent.length, 0)
    }
    function test_create_walk_without_project_opens_chooser_and_preserves_text() {
        controller.chat = {id: "fixture", title: "Test conversation", messages: [], attachments: [], project: ""}
        var button = findChild(panel, "createWalkButton")
        verify(button.enabled)
        mouseClick(button)
        compare(projectChooser.count, 1)
        compare(controller.sent.length, 0)
        compare(input.text, "Hello")
        compare(panel.submitting, false)
        controller.chat = {id: "fixture", title: "Test conversation", messages: [], attachments: [], project: "/fixture/to-do-list"}
        mouseClick(button)
        compare(controller.sent.length, 1)
        compare(controller.sent[0].op, "chat_draft")
        compare(controller.sent[0].text, "Hello")
    }
    function test_create_walk_uses_existing_conversation_with_empty_composer() {
        input.text = ""
        controller.chat = {id: "fixture", title: "Test conversation", messages: [{role: "user", status: "complete", text: "Build a to-do app"}], attachments: [], project: "/fixture"}
        var button = findChild(panel, "createWalkButton")
        verify(button.enabled)
        mouseClick(button)
        compare(controller.sent.length, 1)
        compare(controller.sent[0].op, "chat_draft")
        compare(controller.sent[0].text, "")
    }
    function test_create_walk_preserves_busy_empty_and_length_guards() {
        var button = findChild(panel, "createWalkButton")
        input.text = ""
        verify(!button.enabled)
        input.text = "x".repeat(8001)
        verify(!button.enabled)
        input.text = "Build a to-do app"
        controller.chatBusy = true
        verify(!button.enabled)
        controller.chatBusy = false; controller.active = true
        verify(!button.enabled)
        compare(controller.sent.length, 0)
    }
}
