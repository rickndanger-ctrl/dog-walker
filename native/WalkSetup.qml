pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: setup
    required property var controller
    readonly property bool idle: controller.online && !controller.active && !controller.chatBusy
    readonly property bool ready: idle && !!controller.job && !!controller.project
    readonly property bool compact: height < 430
    property bool importingPaste: false
    readonly property var attachedBrief: controller.brief || null
    readonly property bool canPlan: idle && !!controller.project && (!!attachedBrief || !!taskText.text.trim())
    signal choosePlan()
    signal chooseFolder()
    signal readPlan()
    signal showHelp()
    Layout.fillWidth: true
    Layout.fillHeight: true
    Layout.minimumHeight: 0
    implicitHeight: 540

    function importText(text) {
        if (!idle || !text.trim()) return
        controller.error = ""
        var value = text.trim()
        if ((value.startsWith("/") || value.startsWith("file:///")) && value.indexOf("\n") < 0)
            controller.send({op: "import", path: value})
        else controller.send({op: "import", text: text})
    }
    function reset() {
        importingPaste = false
        pasteDialog.close()
        pastedForm.text = ""; taskText.text = ""
    }
    function receiveDrop(urls, text) {
        if (!idle) return false
        var plan = "", folder = ""
        if (!urls.length) {
            if (!text.trim()) return false
            importText(text)
            return true
        }
        if (urls.length > 2) {
            controller.error = "Drop one plan and one project folder."
            return false
        }
        for (var item of urls) {
            var path = item.toString()
            if (/\.(md|dogwalk|yaml|yml|json)$/i.test(path)) {
                if (plan) { controller.error = "Drop one plan at a time."; return false }
                plan = path
            } else {
                if (folder) { controller.error = "Drop one project folder at a time."; return false }
                folder = path
            }
        }
        controller.error = ""
        if (folder) controller.send({op: "prepare_project", root: folder, auto_plan: !plan && !controller.job && !attachedBrief})
        if (plan) controller.send({op: "import", path: plan})
        return true
    }
    function start() {
        if (!ready) return
        controller.error = ""; controller.logs = ""
        controller.send({op: "start", root: controller.project, auto: controller.automatic, in_place: controller.inPlace})
    }

    function createPlan() {
        if (!canPlan) return
        controller.error = ""
        controller.send({op: "brief_plan", brief_id: attachedBrief ? attachedBrief.id : "",
            text: attachedBrief ? "" : taskText.text, answer: attachedBrief ? taskText.text : "",
            root: controller.project, plugins: controller.selectedPlugins || ["project"]})
    }
    ColumnLayout {
        anchors.fill: parent
        spacing: setup.compact ? 8 : 14
        RowLayout {
            Layout.fillWidth: true
            Copy { text: "New walk"; font.pixelSize: 22; font.weight: Font.DemiBold; Layout.fillWidth: true }
            ComboBox {
                id: modelPicker; objectName: "walkModelPicker"
                palette: MonoPalette {}
 visible: controller.modelProfiles.length > 0
                Layout.preferredWidth: 150; implicitHeight: 32
                model: controller.modelProfiles; textRole: "label"; displayText: controller.modelLabel
                contentItem: Copy { text: modelPicker.displayText; font.pixelSize: 13; verticalAlignment: Text.AlignVCenter; leftPadding: 10 }
                background: Rectangle { color: Theme.surface; radius: 5; border.color: Theme.border }
                indicator: Copy { text: "⌄"; color: Theme.muted; x: modelPicker.width - 22; y: (modelPicker.height - height) / 2 }
                enabled: setup.idle
                onActivated: function(index) {
                    var profile = controller.modelProfiles[index]
                    if (profile && profile.available) controller.send({op: "select_model", model_id: profile.id})
                }
                delegate: ItemDelegate {
                    required property var modelData; required property int index
                    palette: MonoPalette {}
 width: modelPicker.width
                    text: modelData.label + (modelData.available ? "" : " · Not installed")
                    enabled: modelData.available; highlighted: modelPicker.highlightedIndex === index
                }
            }
        }
        ScrollView {
            id: planReview; objectName: "walkPlanReview"
            Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 0
            palette: MonoPalette {}
 contentWidth: availableWidth; clip: true
            ColumnLayout {
                width: planReview.availableWidth; spacing: 10
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: messageContents.implicitHeight + 24
                    radius: 12; color: Theme.surface
                    border.width: drop.containsDrag ? 1 : 0; border.color: Theme.text
                    ColumnLayout {
                        id: messageContents; anchors.fill: parent; anchors.margins: 12; spacing: 8
                        RowLayout {
                            visible: !!setup.attachedBrief; Layout.fillWidth: true
                            Copy { Layout.fillWidth: true; text: setup.attachedBrief ? setup.attachedBrief.title + " · Markdown" : ""; font.pixelSize: 13; maximumLineCount: 1; elide: Text.ElideRight }
                            ActionButton { text: "Remove"; dark: true; implicitHeight: 26; leftPadding: 8; rightPadding: 8; enabled: setup.idle; onClicked: controller.send({op: "brief_clear"}) }
                        }
                        TextArea {
                            id: taskText; objectName: "walkTaskText"
                            Layout.fillWidth: true; Layout.preferredHeight: setup.compact ? 65 : Math.min(160, setup.height * .26)
                            placeholderText: setup.attachedBrief ? "Add instructions for this brief…" : "Describe the work, or drop a Markdown file here…"
                            font.pixelSize: 14; color: Theme.text; placeholderTextColor: Theme.faint
                            wrapMode: TextEdit.Wrap; selectByMouse: true; enabled: setup.idle && !controller.job
                            background: Item {}
                            Keys.onReturnPressed: function(event) {
                                if (event.modifiers & Qt.ShiftModifier) { event.accepted = false; return }
                                event.accepted = true
                                if (controller.job) setup.start(); else setup.createPlan()
                            }
                            Keys.onEnterPressed: function(event) {
                                if (event.modifiers & Qt.ShiftModifier) { event.accepted = false; return }
                                event.accepted = true
                                if (controller.job) setup.start(); else setup.createPlan()
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true; spacing: 4
                            ActionButton {
                                text: "Attach file"; implicitHeight: 32; dark: true; leftPadding: 8; rightPadding: 8
                                enabled: setup.idle; onClicked: setup.choosePlan()
                                contentItem: Row {
                                    spacing: 6
                                    Image { source: "icons/attach.svg"; width: 16; height: 16; anchors.verticalCenter: parent.verticalCenter }
                                    Copy { text: "Attach file"; font.pixelSize: 13 }
                                }
                            }
                            ActionButton {
                                text: "Project"; implicitHeight: 32; dark: true; leftPadding: 8; rightPadding: 8
                                enabled: setup.idle; onClicked: setup.chooseFolder()
                                contentItem: Row {
                                    spacing: 6
                                    Image { source: "icons/folder.svg"; width: 16; height: 16; anchors.verticalCenter: parent.verticalCenter }
                                    Copy { text: "Project"; font.pixelSize: 13 }
                                }
                            }
                            Item { Layout.fillWidth: true }
                            ActionButton { objectName: "pastePlanButton"; text: "Paste"; implicitHeight: 32; dark: true; leftPadding: 8; rightPadding: 8; enabled: setup.idle; onClicked: { controller.error = ""; pasteDialog.open() } }
                        }
                    }
                }
                Copy { visible: !!controller.project; Layout.fillWidth: true; text: controller.project || ""; font.pixelSize: 12; color: Theme.muted; maximumLineCount: 1; elide: Text.ElideMiddle }
                Copy { visible: !!controller.briefQuestion; Layout.fillWidth: true; text: controller.briefQuestion || ""; font.pixelSize: 13; color: Theme.text }
                Copy { visible: controller.chatBusy; Layout.fillWidth: true; text: controller.chatProgress || "Preparing your walk…"; font.pixelSize: 13; color: Theme.muted }
                RowLayout {
                    visible: !!controller.job; Layout.fillWidth: true
                    Copy { objectName: "walkPlanName"; Layout.fillWidth: true; text: controller.job ? controller.job.name : ""; font.pixelSize: 16; font.weight: Font.DemiBold; maximumLineCount: 1; elide: Text.ElideRight }
                    ActionButton { text: "Review plan"; implicitHeight: 30; dark: true; onClicked: setup.readPlan() }
                }
                Copy { visible: !!controller.job; Layout.fillWidth: true; text: controller.job ? controller.job.goal : ""; color: Theme.muted; font.pixelSize: 13; maximumLineCount: 3; elide: Text.ElideRight }
                Copy { visible: !!controller.job; Layout.fillWidth: true; text: controller.job ? controller.job.steps.length + " steps · " + (controller.job.allowed_changes || []).length + " allowed files" : ""; color: Theme.muted; font.pixelSize: 12 }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            CheckBox {
                id: originalCheck; palette: MonoPalette {}
 text: "Edit original"
                checked: controller.inPlace; enabled: setup.idle; onToggled: controller.inPlace = checked
                implicitHeight: 32
                contentItem: Copy { text: originalCheck.text; leftPadding: 22; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter }
                indicator: Rectangle { width: 14; height: 14; y: (originalCheck.height - height) / 2; color: originalCheck.checked ? Theme.text : "transparent"; border.color: Theme.muted; radius: 3; Copy { anchors.centerIn: parent; text: originalCheck.checked ? "✓" : ""; color: Theme.inverseText; font.pixelSize: 12 } }
                ToolTip.visible: hovered; ToolTip.text: "Off: work in a protected copy of your selected folder."
            }
            CheckBox {
                id: autoCheck; palette: MonoPalette {}
 text: "Auto"
                checked: controller.automatic; enabled: setup.idle; onToggled: controller.automatic = checked
                implicitHeight: 32
                contentItem: Copy { text: autoCheck.text; leftPadding: 22; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter }
                indicator: Rectangle { width: 14; height: 14; y: (autoCheck.height - height) / 2; color: autoCheck.checked ? Theme.text : "transparent"; border.color: Theme.muted; radius: 3; Copy { anchors.centerIn: parent; text: autoCheck.checked ? "✓" : ""; color: Theme.inverseText; font.pixelSize: 12 } }
            }
            Item { Layout.fillWidth: true }
            ActionButton { id: startButton; objectName: "startWalkButton"; text: controller.job ? "Start walk" : "Create walk"; implicitHeight: 36; primary: true; enabled: setup.ready || setup.canPlan; onClicked: { if (controller.job) setup.start(); else setup.createPlan() } }
        }
        Copy {
            objectName: "walkSetupStatus"; Layout.fillWidth: true; font.pixelSize: 12; color: Theme.muted
            text: !controller.online ? "Connecting…" : !setup.idle ? "Working…" : !controller.project ? "Select a project folder." : controller.job ? (controller.inPlace ? "Ready · edits the selected folder." : "Ready · works in a protected copy.") : setup.attachedBrief || taskText.text.trim() ? "Ready to create a checked plan." : "Attach a Markdown brief or describe the work."
        }
    }
    // Cover the whole setup, including its review and footer, while allowing
    // normal pointer input to the controls beneath it.
    DropArea {
        id: drop
        parent: setup
        anchors.fill: parent
        onDropped: function(event) {
            if (setup.receiveDrop(event.hasUrls ? event.urls : [], event.hasText ? event.text : "")) event.acceptProposedAction()
        }
    }
    Dialog {
        id: pasteDialog
        objectName: "pastePlanDialog"
        palette: MonoPalette {}
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(setup.width + 20, 680)
        height: Math.min(setup.height + 40, 490)
        modal: true; title: "Paste a plan"
        contentItem: ColumnLayout {
            spacing: 10
            Copy { Layout.fillWidth: true; text: "Paste the complete form text or its local file path, then import it."; font.pixelSize: 12; color: Theme.muted }
            ScrollView {
                Layout.fillWidth: true; Layout.fillHeight: true
                palette: MonoPalette {}
                TextArea { id: pastedForm; objectName: "pastedPlanText"; color: Theme.text; placeholderTextColor: Theme.faint; placeholderText: "dog_walker: 1\nname: …\ngoal: …\nsteps: …"; wrapMode: TextEdit.Wrap; font.family: "monospace"; selectByMouse: true }
            }
            Copy { Layout.fillWidth: true; visible: !!controller.error; text: controller.error; font.pixelSize: 12 }
        }
        footer: DialogButtonBox {
            palette: MonoPalette {}
            ActionButton { text: "Cancel"; enabled: !setup.importingPaste; onClicked: pasteDialog.close() }
            ActionButton {
                objectName: "importPlanButton"
                text: setup.importingPaste ? "Importing…" : "Import plan"
                primary: true
                enabled: setup.idle && !setup.importingPaste && !!pastedForm.text.trim()
                onClicked: { setup.importingPaste = true; setup.importText(pastedForm.text) }
            }
        }
    }
    Connections {
        target: controller
        function onJobChanged() { if (setup.importingPaste) { setup.importingPaste = false; pasteDialog.close() } }
        function onErrorChanged() { if (controller.error) setup.importingPaste = false }
    }
}
