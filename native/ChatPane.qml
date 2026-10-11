pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: panel
    required property var controller
    property bool submitting: false
    property string submittedText: ""
    readonly property bool hasWalkRequest: composer.text.trim().length > 0 || (!!controller.chat && controller.chat.messages.some(function(message) { return message.role === "user" && message.status === "complete" }))
    readonly property bool canCreateWalk: controller.online && !!controller.chat && !controller.chatBusy && !submitting && !controller.active && composer.text.length <= 8000 && hasWalkRequest
    signal chooseProject()
    signal attachFiles()
    signal showTools()
    Layout.fillWidth: true
    Layout.fillHeight: true
    spacing: 18

    function submit(draft) {
        if (!controller.online || !controller.chat || controller.chatBusy || controller.active || submitting || composer.text.length > 8000) return
        if (!draft && !composer.text.trim()) return
        if (draft && !hasWalkRequest) return
        if (draft && !controller.chat.project) { panel.chooseProject(); return }
        controller.error = ""
        submitting = true; submittedText = composer.text
        controller.send({op: draft ? "chat_draft" : "chat_send", chat_id: controller.chat.id,
                         text: composer.text, plugins: controller.selectedPlugins})
    }
    RowLayout {
        Layout.fillWidth: true
        Copy { Layout.fillWidth: true; text: controller.chat && controller.chat.messages.length ? controller.chat.title : "New chat"; font.pixelSize: 21; font.weight: Font.DemiBold; maximumLineCount: 1; elide: Text.ElideRight }
        ComboBox {
            id: modelPicker
            palette: MonoPalette {}
            visible: controller.modelProfiles.length > 0
            Layout.preferredWidth: 190
            implicitHeight: 36
            model: controller.modelProfiles
            textRole: "label"
            displayText: controller.modelLabel
            contentItem: Text {
                leftPadding: 10
                rightPadding: modelPicker.indicator.width + 8
                text: modelPicker.displayText
                font: modelPicker.font
                color: modelPicker.enabled ? Theme.text : Theme.faint
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
            }
            indicator: Text {
                text: "⌄"
                color: Theme.muted
                font.pixelSize: 16
                anchors.right: parent.right
                anchors.rightMargin: 10
                anchors.verticalCenter: parent.verticalCenter
            }
            background: Rectangle {
                radius: 7
                color: Theme.surface
                border.width: modelPicker.activeFocus ? 1 : 0
                border.color: Theme.strongBorder
            }
            currentIndex: {
                for (var i = 0; i < controller.modelProfiles.length; i++)
                    if (controller.modelProfiles[i].id === controller.modelId) return i
                return -1
            }
            enabled: controller.online && !controller.chatBusy && !controller.active
            onActivated: function(index) {
                var profile = controller.modelProfiles[index]
                if (profile && profile.available) controller.send({op: "select_model", model_id: profile.id})
            }
            delegate: ItemDelegate {
                required property int index
                required property var modelData
                width: modelPicker.width
                text: modelData.label + (modelData.available ? "" : " · Not installed")
                enabled: modelData.available
                highlighted: modelPicker.highlightedIndex === index
            }
            ToolTip.visible: hovered
            ToolTip.text: "Choose the model for your next task. Only one model runs at a time."
        }
    }
    RowLayout {
        Layout.fillWidth: true; spacing: 10
        ActionButton { text: controller.chat && controller.chat.project ? "⌁  " + controller.chat.project.split("/").pop() : "+  Project"; enabled: !controller.chatBusy; onClicked: panel.chooseProject() }
        Copy { visible: !!controller.chat && !!controller.chat.project; Layout.fillWidth: true; text: controller.chat ? controller.chat.project : ""; color: Theme.muted; font.pixelSize: 11; maximumLineCount: 1; elide: Text.ElideMiddle }
        Item { visible: !controller.chat || !controller.chat.project; Layout.fillWidth: true }
        ActionButton { text: "Tools · " + controller.selectedPlugins.length; enabled: !controller.chatBusy; onClicked: panel.showTools() }
    }
    ScrollView {
                palette: MonoPalette {}
        id: conversationView
        Layout.fillWidth: true; Layout.fillHeight: true
        contentWidth: availableWidth; clip: true
        ScrollBar.vertical.policy: ScrollBar.AsNeeded
        ColumnLayout {
            id: messages
            width: conversationView.availableWidth
            spacing: 18
            ColumnLayout {
                visible: !controller.chat || controller.chat.messages.length === 0
                Layout.fillWidth: true; Layout.preferredWidth: messages.width; Layout.topMargin: 30; Layout.bottomMargin: 20; spacing: 8
                Copy { text: "Start with a message"; font.pixelSize: 17; font.weight: Font.DemiBold; Layout.alignment: Qt.AlignHCenter }
                Copy { text: "Ask a question or describe what you want to work on."; horizontalAlignment: Text.AlignHCenter; color: Theme.muted; lineHeight: 1.4; Layout.alignment: Qt.AlignHCenter }
            }
            Repeater {
                model: controller.chat ? controller.chat.messages : []
                ColumnLayout {
                    id: messageRow
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: 6
                    readonly property bool user: modelData.role === "user"
                    readonly property bool system: modelData.role === "system"
                    Copy { text: messageRow.user ? "YOU" : messageRow.system ? "WALK CONTEXT" : "LOCAL MODEL"; font.pixelSize: 9; font.letterSpacing: 1.2; color: Theme.muted; Layout.leftMargin: 0 }
                    Item {
                        Layout.fillWidth: true
                        Layout.leftMargin: 0
                        Layout.rightMargin: 20
                        implicitHeight: messageBody.implicitHeight + 12
                        ColumnLayout {
                            id: messageBody
                            anchors.fill: parent; anchors.topMargin: 6; anchors.bottomMargin: 6; spacing: 10
                            RowLayout {
                                visible: messageRow.modelData.status === "working"
                                BusyIndicator {
                palette: MonoPalette {} running: visible; implicitWidth: 24; implicitHeight: 24 }
                                Copy { Layout.fillWidth: true; text: controller.chatProgress || "Thinking locally…"; color: Theme.muted }
                            }
                            TextArea {
                                visible: messageRow.modelData.status !== "working"
                                Layout.fillWidth: true
                                text: messageRow.modelData.text
                                readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap
                                textFormat: TextEdit.PlainText
                                color: messageRow.modelData.status === "error" ? Theme.text : Theme.text
                                font.family: "Inter"; font.pixelSize: messageRow.system ? 11 : 14
                                topPadding: 0; bottomPadding: 0; leftPadding: 0; rightPadding: 0
                                background: null
                            }
                            Flow {
                                Layout.fillWidth: true; spacing: 8
                                visible: !!messageRow.modelData.attachments && messageRow.modelData.attachments.length > 0
                                Repeater {
                                    model: messageRow.modelData.attachments || []
                                    Column {
                                        required property var modelData
                                        spacing: 4
                                        Image { visible: parent.modelData.kind === "image"; source: parent.modelData.preview || ""; width: 110; height: 76; fillMode: Image.PreserveAspectFit }
                                        Copy { text: parent.modelData.name; font.pixelSize: 10; color: Theme.muted; width: 110; maximumLineCount: 1; elide: Text.ElideMiddle }
                                    }
                                }
                            }
                            ActionButton {
                                visible: !!messageRow.modelData.draft_id && !!controller.chat && !!controller.chat.draft && controller.chat.draft.id === messageRow.modelData.draft_id
                                text: "Review plan  →"; primary: true; enabled: !controller.chatBusy && !controller.active
                                onClicked: controller.send({op: "chat_use_draft", chat_id: controller.chat.id, draft_id: messageRow.modelData.draft_id})
                            }
                            ActionButton { visible: messageRow.modelData.status === "error"; text: "Open saved chat  ↗"; onClicked: controller.openPath(controller.chat.folder) }
                        }
                    }
                }
            }
            Item { implicitHeight: 4 }
        }
        Connections {
            target: controller
            function onChatChanged() { Qt.callLater(function() { conversationView.contentItem.contentY = Math.max(0, messages.height - conversationView.availableHeight) }) }
        }
    }
    Connections {
        target: controller
        function onChatAccepted(chatId, text) {
            if (controller.chat && chatId === controller.chat.id && text === panel.submittedText) {
                if (composer.text === panel.submittedText) composer.text = ""
                panel.submitting = false
            }
        }
        function onErrorChanged() { if (controller.error) panel.submitting = false }
    }
    Flow {
        Layout.fillWidth: true
        spacing: 8
        visible: !!controller.chat && controller.chat.attachments.length > 0
        Repeater {
            model: controller.chat ? controller.chat.attachments : []
            Paper {
                required property var modelData
                width: Math.min(240, attachmentRow.implicitWidth + 20); height: 48; radius: 12
                RowLayout {
                    id: attachmentRow
                    anchors.fill: parent; anchors.margins: 10; spacing: 8
                    Image { visible: parent.parent.modelData.kind === "image"; source: parent.parent.modelData.preview || ""; Layout.preferredWidth: 30; Layout.preferredHeight: 30; fillMode: Image.PreserveAspectFit }
                    Copy { Layout.fillWidth: true; text: parent.parent.modelData.name; font.pixelSize: 11; maximumLineCount: 1; elide: Text.ElideMiddle }
                    ToolButton { text: "×"; contentItem: Copy { text: "×"; horizontalAlignment: Text.AlignHCenter } enabled: !controller.chatBusy; onClicked: controller.send({op: "chat_remove_attachment", chat_id: controller.chat.id, id: parent.parent.modelData.id}) }
                }
            }
        }
    }
    Paper {
        Layout.fillWidth: true
        implicitHeight: composerColumn.implicitHeight + 24
        radius: 16; border.width: fileDrop.containsDrag ? 1 : 0; border.color: Theme.strongBorder
        DropArea {
            id: fileDrop
            anchors.fill: parent
            onDropped: function(event) {
                if (!event.hasUrls || !controller.chat || controller.chatBusy) return
                for (var file of event.urls) controller.send({op: "chat_attach", chat_id: controller.chat.id, path: file.toString()})
                event.acceptProposedAction()
            }
        }
        ColumnLayout {
            id: composerColumn
            anchors.fill: parent; anchors.margins: 12; spacing: 10
            ScrollView {
                palette: MonoPalette {}
                Layout.fillWidth: true; Layout.preferredHeight: Math.max(58, Math.min(120, composer.contentHeight + 12))
                TextArea {
                    id: composer
                    objectName: "chatComposer"
                    placeholderText: "Write a message…"; placeholderTextColor: Theme.faint
                    enabled: controller.online && !controller.chatBusy
                    wrapMode: TextEdit.Wrap; selectByMouse: true
                    font.family: "Inter"; font.pixelSize: 14; color: Theme.text
                    background: null
                    Keys.onPressed: function(event) {
                        if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter) && !(event.modifiers & Qt.ShiftModifier)) { panel.submit(false); event.accepted = true }
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true; spacing: 8
                ActionButton { text: "+  Attach"; enabled: controller.online && !controller.chatBusy; onClicked: panel.attachFiles() }
                Item { Layout.fillWidth: true }
                ActionButton { objectName: "createWalkButton"; text: "Create a walk"; enabled: panel.canCreateWalk; onClicked: panel.submit(true) }
                ActionButton { text: controller.chatBusy ? "Stop" : "Send  ↑"; primary: !controller.chatBusy; enabled: controller.online && (controller.chatBusy || (!!controller.chat && !panel.submitting && composer.text.trim().length > 0 && composer.text.length <= 8000 && !controller.active)); onClicked: controller.chatBusy ? controller.send({op: "chat_cancel"}) : panel.submit(false) }
            }
        }
    }
    Copy { Layout.fillWidth: true; text: controller.active ? "Your model is on a walk. Pause it to continue chatting." : controller.chat && !controller.chat.project && panel.hasWalkRequest ? "Choose a project folder to create a walk." : "Chat to explore. Review a plan before it runs.  ·  Enter to send  ·  Shift + Enter for a new line"; horizontalAlignment: Text.AlignHCenter; color: Theme.muted; font.pixelSize: 10 }
}
