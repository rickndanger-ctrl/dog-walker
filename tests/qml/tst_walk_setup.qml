import QtQuick
import QtTest
import "../../native" as Ui

TestCase {
    id: test
    name: "WalkSetup"
    when: windowShown
    visible: true
    width: 900; height: 680
    QtObject {
        id: controller
        property bool online: true
        property bool active: false
        property bool chatBusy: false
        property var job: null
        property var brief: null
        property string briefQuestion: ""
        property string chatProgress: ""
        property var selectedPlugins: ["project"]
        property string project: ""
        property string error: ""
        property string logs: ""
        property bool automatic: true
        property bool inPlace: false
        property var modelProfiles: []
        property string modelId: ""
        property string modelLabel: ""
        property var sent: []
        function send(command) { sent = sent.concat([command]) }
    }
    Ui.WalkSetup { id: panel; width: 612; height: 430; controller: controller }
    function job() {
        return {name: "Build bridge", goal: "Copy text between phone and computer", steps: [{title: "Build", review: false}]}
    }
    function init() {
        var dialog = findChild(panel, "pastePlanDialog")
        if (dialog) dialog.close()
        panel.importingPaste = false
        panel.width = 612; panel.height = 430
        controller.online = true; controller.active = false; controller.chatBusy = false
        panel.reset(); controller.brief = null; controller.briefQuestion = ""
        controller.job = null; controller.project = ""; controller.error = ""; controller.logs = ""
        controller.automatic = true; controller.inPlace = false; controller.sent = []
        var input = findChild(panel, "pastedPlanText")
        if (input) input.text = ""
    }
    function test_start_is_visible_and_explains_missing_inputs() {
        var start = findChild(panel, "startWalkButton")
        verify(start.visible)
        verify(!start.enabled)
        compare(findChild(panel, "walkSetupStatus").text, "Select a project folder.")
        controller.job = job()
        verify(!start.enabled)
        compare(findChild(panel, "walkSetupStatus").text, "Select a project folder.")
        controller.project = "/project"
        verify(start.enabled)
        mouseClick(start)
        compare(controller.sent.length, 1)
        compare(controller.sent[0].op, "start")
        compare(controller.sent[0].root, "/project")
        compare(controller.sent[0].in_place, false)
    }
    function test_two_item_drop_accepts_either_order_without_starting() {
        for (var urls of [["file:///project", "file:///Desktop/plan.dogwalk"], ["file:///Desktop/plan.dogwalk", "file:///project"]]) {
            controller.sent = []
            verify(panel.receiveDrop(urls, ""))
            compare(controller.sent.length, 2)
            compare(controller.sent[0].op, "prepare_project")
            compare(controller.sent[0].auto_plan, false)
            compare(controller.sent[1].op, "import")
        }
    }
    function test_form_text_and_copied_path_import() {
        var form = "dog_walker: 1\nname: Clipboard bridge\n"
        verify(panel.receiveDrop([], form))
        compare(controller.sent[0].op, "import")
        compare(controller.sent[0].text, form)
        panel.importText("/Desktop/Phone Clipboard Bridge.dogwalk")
        compare(controller.sent[1].path, "/Desktop/Phone Clipboard Bridge.dogwalk")
    }
    function test_reject_multiple_plans_before_sending_anything() {
        verify(!panel.receiveDrop(["file:///a.dogwalk", "file:///b.dogwalk"], ""))
        compare(controller.sent.length, 0)
        compare(controller.error, "Drop one plan at a time.")
    }
    function test_paste_has_visible_import_and_preserves_invalid_input() {
        mouseClick(findChild(panel, "pastePlanButton"))
        var dialog = findChild(panel, "pastePlanDialog")
        tryCompare(dialog, "visible", true)
        var input = findChild(panel, "pastedPlanText")
        var submit = findChild(panel, "importPlanButton")
        verify(submit.visible)
        verify(!submit.enabled)
        input.text = "broken: form"
        verify(submit.enabled)
        mouseClick(submit)
        compare(controller.sent.length, 1)
        compare(controller.sent[0].text, "broken: form")
        controller.error = "Invalid form"
        compare(panel.importingPaste, false)
        verify(dialog.visible)
        compare(input.text, "broken: form")
        input.text = "dog_walker: 1\nname: Bridge"
        mouseClick(submit)
        compare(controller.sent.length, 2)
        controller.job = job()
        tryCompare(dialog, "visible", false)
    }
    function test_long_plan_cannot_push_start_below_window() {
        var steps = []
        for (var i = 0; i < 50; i++) steps.push({title: "Long step " + i, review: true})
        controller.job = {name: "Long plan", goal: "Details ".repeat(250), steps: steps}
        controller.project = "/project"
        wait(50)
        var start = findChild(panel, "startWalkButton")
        var point = start.mapToItem(panel, 0, 0)
        verify(start.visible && start.enabled)
        verify(point.y >= 0 && point.y + start.height <= panel.height + 1, "Start must fit in the fixed footer")
        var review = findChild(panel, "walkPlanReview")
        verify(review.height >= 90, "Plan review must retain readable space")
        verify(findChild(panel, "walkPlanName").height > 0)
    }
    function test_markdown_drop_is_attachment_and_never_infers_folder_or_starts() {
        verify(panel.receiveDrop(["file:///Desktop/any%20brief.md"], ""))
        compare(controller.sent.length, 1)
        compare(controller.sent[0].op, "import")
        compare(controller.sent[0].path, "file:///Desktop/any%20brief.md")
        compare(controller.project, "")
    }
    function test_message_enter_requires_project_and_creates_plan_without_starting() {
        var input = findChild(panel, "walkTaskText")
        input.text = "Build a notes app"
        input.forceActiveFocus()
        keyClick(Qt.Key_Return)
        compare(controller.sent.length, 0)
        controller.project = "/chosen/project"
        keyClick(Qt.Key_Return)
        compare(controller.sent.length, 1)
        compare(controller.sent[0].op, "brief_plan")
        compare(controller.sent[0].root, "/chosen/project")
        compare(controller.sent[0].text, "Build a notes app")
    }
    function test_markdown_attachment_and_extra_instructions_use_chosen_project() {
        controller.brief = {id: "brief-id", title: "My task"}
        controller.project = "/my/folder"
        findChild(panel, "walkTaskText").text = "Keep it simple"
        panel.createPlan()
        compare(controller.sent.length, 1)
        compare(controller.sent[0].brief_id, "brief-id")
        compare(controller.sent[0].answer, "Keep it simple")
        compare(controller.sent[0].root, "/my/folder")
        compare(controller.sent[0].op, "brief_plan")
    }
    function test_shift_enter_inserts_newline_without_planning() {
        controller.project = "/project"
        var input = findChild(panel, "walkTaskText")
        input.text = "A"; input.forceActiveFocus(); input.cursorPosition = 1
        keyClick(Qt.Key_Return, Qt.ShiftModifier)
        compare(controller.sent.length, 0)
        compare(input.text, "A\n")
    }
    function test_offline_and_busy_guards_preserved() {
        controller.job = job(); controller.project = "/project"
        for (var property of ["active", "chatBusy"]) {
            controller[property] = true
            panel.start()
            verify(!panel.receiveDrop(["file:///a.dogwalk"], ""))
            controller[property] = false
        }
        controller.online = false
        panel.start()
        compare(controller.sent.length, 0)
    }
    function test_small_tiled_window_keeps_plan_and_start_visible() {
        panel.width = 493; panel.height = 326
        controller.job = job(); controller.project = "/project"
        wait(50)
        var start = findChild(panel, "startWalkButton")
        var point = start.mapToItem(panel, 0, 0)
        verify(point.y >= 0 && point.y + start.height <= panel.height + 1)
        verify(findChild(panel, "walkPlanReview").height >= 36)
        verify(findChild(panel, "walkPlanName").height > 0)
    }
}
