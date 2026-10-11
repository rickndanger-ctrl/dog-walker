pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import Quickshell
import Quickshell.Io

ShellRoot {
    id: app
    property string appRoot: Quickshell.env("DOG_WALKER_APP_ROOT") || Quickshell.shellDir.replace(/\/native\/?$/, "")
    property string nativeRoot: Quickshell.shellDir
    property string page: "chat"
    property var chat: null
    property var chats: []
    property var projects: []
    property string activeProjectId: ""
    readonly property var projectChats: chats.filter(function(c) { return activeProjectId ? c.project_id === activeProjectId : !c.project_id })
    property bool chatBusy: false
    property string chatProgress: ""
    property var modelProfiles: []
    property var helperClients: ({})
    property bool terminalAvailable: false
    property string terminalScheme: ""
    property string terminalBackground: ""
    property string terminalFont: "monospace"
    property int terminalFontSize: 11
    property var terminals: []
    property alias terminalRows: terminalRowsModel
    property string selectedTerminalId: ""
    property var brief: null
    property string briefQuestion: ""
    property string recommendedProjectRoot: Quickshell.env("HOME") + "/Projects"
    readonly property real walkProgressValue: !state ? 0 : state.status === "completed" ? 1 : Math.min(1, state.history.length / Math.max(1, walkJob ? walkJob.steps.length : 1))
    property string modelId: ""
    property string modelLabel: ""
    property var plugins: []
    property var selectedPlugins: ["project", "browser", "obsidian"]
    signal chatAccepted(string chatId, string text)
    property var job: null
    property var walkJob: null
    property var state: null
    property var runs: []
    property var inbox: []
    property string inboxPath: ""
    property string project: ""
    property bool automatic: true
    property bool inPlace: false
    property bool active: false
    property bool external: false
    property bool review: false
    property string reviewId: ""
    property var companionReplies: ({})
    property bool online: false
    property var health: ({})
    property string error: ""
    property string reason: ""
    property string logs: ""
    property string captureResult: ""
    property bool details: false
    property string importOnReady: Quickshell.env("DOG_WALKER_OPEN_FILE") || ""
    readonly property string statusText: !state ? "Ready for a walk" : external ? "Open in another window" : review ? "Needs your review" : state.status === "completed" ? "Walk complete" : state.status === "aborted" ? "Walk stopped" : state.status === "paused" ? "Walk paused" : state.phase === "evaluating" ? "Checking the work" : "Working through the plan"
    readonly property var shownResult: state ? state.result || (state.status === "completed" ? state.previous_result : null) : null
    readonly property var shownEvaluation: state ? state.evaluation || (state.status === "completed" ? state.last_evaluation : null) : null

    function send(command) {
        if (!bridge.running || !online) { error = "The local engine is not connected. Close and reopen Handler."; return }
        bridge.write(JSON.stringify(command) + "\n")
    }
    function openPath(path) { if (path) Quickshell.execDetached(["xdg-open", path]) }
    function importFile(path) { error = ""; send({op: "import", path: path}) }
    function newWalk() {
        if (active || chatBusy) return false
        if (online) send({op: "brief_clear"})
        job = null; brief = null; briefQuestion = ""; project = ""; error = ""; page = "new"
        walkSetup.reset()
        return true
    }
    function control(action) { send({op: "control", action: action, run_id: state ? state.id : "", review_id: reviewId}) }
    function resumeWalk() { send({op: "resume", run_id: state ? state.id : ""}) }
    function terminalAction(kind, provider, mode) {
        if (state) send({op: "terminal", run_id: state.id, kind: kind, provider: provider || "", mode: mode || "review", embedded: true})
    }
    function acceptTerminalTheme(m) {
        terminalScheme = m.terminal_scheme || ""
        terminalBackground = m.terminal_background || ""
        terminalFont = m.terminal_font || "monospace"
        terminalFontSize = m.terminal_font_size || 11
    }
    function acceptMessage(m) {
        if (m.type === "hello") {
            online = true; health = m.health; plugins = m.plugins || []; Theme.dark = m.theme !== "light"
            modelProfiles = m.model_profiles || []; modelId = m.model_id || ""; modelLabel = m.model_label || ""
            helperClients = m.helper_clients || {}
            terminalAvailable = !!m.terminal_available
            acceptTerminalTheme(m)
            recommendedProjectRoot = m.project_area || recommendedProjectRoot
            send({op: "chat_open"})
            if (importOnReady) { var f = importOnReady; importOnReady = ""; importFile(f) }
        } else if (m.type === "theme") {
            Theme.dark = m.theme !== "light"
        } else if (m.type === "terminal_theme") {
            acceptTerminalTheme(m)
        } else if (m.type === "model_selected") {
            modelProfiles = m.model_profiles || modelProfiles
            modelId = m.model_id || ""
            modelLabel = m.model_label || ""
        } else if (m.type === "project_selected") {
            project = m.root; if (m.clear_plan) { job = null; briefQuestion = "" }; page = "new"; error = ""
        } else if (m.type === "brief") {
            brief = m.brief; briefQuestion = ""; job = null; page = "new"; error = ""
        } else if (m.type === "brief_question") {
            briefQuestion = m.message; page = "new"
        } else if (m.type === "terminal_ready") {
            var next = terminals.slice()
            var index = next.findIndex(function(t) { return t.id === m.terminal.id })
            if (index < 0) {
                next.push(m.terminal)
                terminalRowsModel.append({payload: JSON.stringify(m.terminal)})
            } else next[index] = m.terminal
            terminals = next
            if (m.terminal.kind !== "context" && !m.restored) selectedTerminalId = m.terminal.id
            page = "walk"; error = ""
        } else if (m.type === "job") {
            job = m.job; if (m.hasOwnProperty("brief")) brief = m.brief; briefQuestion = ""; automatic = job.mode === "auto"; page = "new"; error = ""; details = false
            if (m.project) project = m.project
        } else if (m.type === "chat") {
            chat = m.chat; chatBusy = m.busy; chatProgress = m.progress || ""
            if (chat && chat.selected_plugins) selectedPlugins = chat.selected_plugins
        } else if (m.type === "chat_accepted") {
            chatAccepted(m.chat_id, m.text)
        } else if (m.type === "state") {
            if (!state || state.id !== m.state.id) {
                var matching = terminals.filter(function(t) { return t.run_id === m.state.id && t.kind !== "context" })
                selectedTerminalId = matching.length ? matching[0].id : ""
            }
            state = m.state; active = m.active; external = m.external; review = m.needs_review; reason = m.reason
            reviewId = m.review_id || ""
            walkJob = m.job
        } else if (m.type === "selected") {
            page = "walk"; error = ""
            if (state && terminalAvailable && !terminals.some(function(t) { return t.run_id === state.id && t.kind === "context" }))
                terminalAction("workspace")
        } else if (m.type === "library") {
            runs = m.runs; inbox = m.inbox; inboxPath = m.inbox_path; chats = m.chats || []; projects = (m.projects || []).filter(function(p) { return !p.archived }); activeProjectId = m.active_project_id || ""
        } else if (m.type === "log") {
            logs = (logs + "\n" + m.text).slice(-30000)
        } else if (m.type === "error") {
            error = m.message
        } else if (m.type === "settings") {
            modelPath.text = m.settings.model_path; endpoint.text = m.settings.endpoint
            catalog.text = m.settings.catalog; launcher.text = (m.settings.start_command || []).join("\n")
            settingsDialog.open()
        } else if (m.type === "saved_settings") {
            settingsDialog.close()
        } else if (m.type === "phone_info") {
            phoneAddress.text = m.url; phoneCode.text = m.pair_code.match(/.{1,4}/g).join("-")
            phoneInstructions.text = m.instructions; phoneDialog.open()
        } else if (m.type === "finished") {
            active = false; review = false
        } else if (m.type === "command_result") {
            var replies = Object.assign({}, companionReplies)
            replies[m.request_id] = m
            var keys = Object.keys(replies)
            if (keys.length > 50) delete replies[keys[0]]
            companionReplies = replies
        }
    }
    ListModel { id: terminalRowsModel }
    Process {
        id: bridge
        command: [app.appRoot + "/.venv/bin/python", "-u", "-m", "dog_walker.desktop"]
        workingDirectory: app.appRoot
        stdinEnabled: true
        running: true
        onStarted: write(JSON.stringify({op: "hello"}) + "\n")
        onExited: { app.online = false; app.active = false; app.chatBusy = false; app.error = "The local engine closed. Your chats and walks are saved. Reopen Handler to continue." }
        stdout: SplitParser {
            onRead: function(line) {
                try { app.acceptMessage(JSON.parse(line)) }
                catch(e) { app.error = "Could not read the local engine response."; console.warn(e) }
            }
        }
        stderr: SplitParser { onRead: function(line) { console.warn("Handler engine:", line) } }
    }
    Timer { interval: 1500; running: app.online; repeat: true; onTriggered: app.send({op: "refresh"}) }
    IpcHandler {
        target: "dogwalker"
        function open(path: string): string {
            window.visible = true
            if (Quickshell.env("HYPRLAND_INSTANCE_SIGNATURE"))
                Quickshell.execDetached(["hyprctl", "eval", 'for _,w in ipairs(hl.get_windows()) do if w.title == "Handler" then hl.dispatch(hl.dsp.focus({window=w})) end end'])
            if (path) {
                if (app.online) app.importFile(path)
                else app.importOnReady = path
            }
            return "ok"
        }
        // Read-only diagnostics are also used by smoke tests; they do not start jobs.
        function snapshot(): string {
            return JSON.stringify({page: app.page, connected: app.online, job: app.job ? app.job.name : "", state: app.state ? app.state.id : "", error: app.error, capture: app.captureResult, progress: app.walkProgressValue, chat: app.chat ? app.chat.id : "", chat_busy: app.chatBusy, active: app.active, project: app.project, model: app.modelId, setup_ready: walkSetup.ready, terminals: app.terminals.length, terminal_selected: app.selectedTerminalId, brief: app.brief ? app.brief.title : ""})
        }
        // Preview-only setup helpers: importing/selecting never starts a walk.
        function setupDrop(payload: string): string {
            try { var input = JSON.parse(payload); return walkSetup.receiveDrop(input.urls || [], input.text || "") ? "accepted" : "rejected" }
            catch(e) { return "rejected" }
        }
        function selectModel(id: string): string { app.send({op: "select_model", model_id: id}); return "requested" }
        function newWalk(): string { return app.newWalk() ? "ok" : "busy" }
        function capture(path: string): string {
            app.captureResult = "pending"
            canvas.grabToImage(function(result) { app.captureResult = result.saveToFile(path) ? "saved" : "failed" })
            return "requested"
        }
        function showWalk(id: string): string { app.send({op: "load", id: id}); return "requested" }
        function library(): string { app.page = "library"; return "ok" }
        function openTerminal(kind: string): string {
            if (["live", "shell", "workspace", "context"].indexOf(kind) < 0 || !app.state) return "rejected"
            app.terminalAction(kind); return "requested"
        }
        function selectTerminal(id: string): string { app.selectedTerminalId = id; return "ok" }
        function companionSnapshot(): string {
            return JSON.stringify({connected: app.online, active: app.active, external: app.external,
                review: app.review, review_id: app.reviewId, reason: app.reason, state: app.state, job: app.walkJob,
                helper_controls: true})
        }
        function companionControl(payload: string): string {
            try {
                var cmd = JSON.parse(payload)
                if (!app.online || !app.state || cmd.run_id !== app.state.id || app.external) return "unavailable"
                if (["approve", "retry", "pause", "resume"].indexOf(cmd.action) < 0) return "rejected"
                if (["approve", "retry"].indexOf(cmd.action) >= 0 && (!app.review || cmd.review_id !== app.reviewId)) return "stale"
                app.send({op: cmd.action === "resume" ? "resume" : "control", action: cmd.action,
                    run_id: cmd.run_id, review_id: cmd.review_id, request_id: cmd.request_id, source: cmd.source === "helper" ? "helper" : "phone"})
                return "sent"
            } catch(e) { return "rejected" }
        }
        function companionReply(id: string): string { return JSON.stringify(app.companionReplies[id] || null) }
        function showPhone(): string { window.visible = true; app.send({op: "phone"}); return "requested" }
        function showHelp(): string { window.visible = true; helpDialog.open(); return "ok" }
    }
    FileDialog {
        id: fileDialog
        title: "Attach a brief or plan"
        nameFilters: ["Briefs and plans (*.md *.dogwalk *.yaml *.yml *.json)", "All files (*)"]
        onAccepted: app.importFile(selectedFile.toString())
    }
    FolderDialog { id: folderDialog; title: "Choose your project folder"; currentFolder: "file://" + (app.project || app.recommendedProjectRoot); onAccepted: app.send({op: "prepare_project", root: selectedFolder.toString(), auto_plan: !app.job && !app.brief}) }
    FolderDialog { id: chatFolderDialog; title: "Choose a project folder"; currentFolder: "file://" + ((app.chat && app.chat.project) || app.recommendedProjectRoot); onAccepted: if (app.chat) app.send({op: "chat_project", chat_id: app.chat.id, root: selectedFolder.toString()}) }
    FolderDialog { id: savedProjectFolder; title: "Add an existing project"; currentFolder: "file://" + app.recommendedProjectRoot; onAccepted: { var root = decodeURIComponent(selectedFolder.toString().replace(/^file:\/\//, "")); app.send({op: "project_create", root: root, name: root.split("/").pop()}); app.page = "chat" } }
    FileDialog {
        id: attachmentDialog
        title: "Add files or pictures"
        fileMode: FileDialog.OpenFiles
        nameFilters: ["Pictures (*.png *.jpg *.jpeg *.webp)", "Documents and code (*.pdf *.txt *.md *.csv *.json *.yaml *.yml *.py *.js *.ts *.tsx *.qml *.html *.css)", "All files (*)"]
        selectedNameFilter.index: 2
        onAccepted: {
            if (!app.chat) return
            for (var file of selectedFiles) app.send({op: "chat_attach", chat_id: app.chat.id, path: file.toString()})
        }
    }

    FloatingWindow {
        id: window
        title: "Handler"
        implicitWidth: 1280; implicitHeight: 800
        minimumSize: Qt.size(720, 400)
        color: Theme.canvas
        onClosed: { app.send({op: "shutdown"}); Qt.quit() }

        Rectangle {
            id: canvas
            anchors.fill: parent
            color: Theme.canvas
        RowLayout {
            anchors.fill: parent
            spacing: 0
            Rectangle {
                Layout.preferredWidth: window.width < 900 ? 164 : 204
                Layout.fillHeight: true
                color: Theme.sidebar
                ColumnLayout {
                    anchors.fill: parent; anchors.margins: 20
                    spacing: 4
                    RowLayout {
                        spacing: 12
                        Image { source: "cane-corso.png"; Layout.preferredWidth: 42; Layout.preferredHeight: 42 }
                        Copy { text: "Handler"; font.pixelSize: 20; font.weight: Font.DemiBold; color: Theme.text }
                    }
                    NavButton { Layout.topMargin: 24; Layout.fillWidth: true; text: "+  New chat"; enabled: !app.chatBusy; onClicked: { app.send({op: "chat_new", project_id: app.activeProjectId || null}); app.page = "chat" } }
                    NavButton { Layout.fillWidth: true; text: "+  New walk"; enabled: !app.active && !app.chatBusy; onClicked: app.newWalk() }
                    ScrollView {
                        Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 0; contentWidth: availableWidth; clip: true
                        palette: MonoPalette {}
                        ColumnLayout {
                            width: parent.width; spacing: 3
                            RowLayout {
                                Layout.fillWidth: true; Layout.topMargin: 22; Layout.bottomMargin: 6
                                Copy { text: "Projects"; font.pixelSize: 11; color: Theme.faint; Layout.fillWidth: true }
                                ToolButton { palette: MonoPalette {} text: "+"; contentItem: Copy { text: "+"; horizontalAlignment: Text.AlignHCenter } enabled: !app.chatBusy; onClicked: savedProjectFolder.open(); ToolTip.visible: hovered; ToolTip.text: "Add project folder" }
                            }
                            Copy { visible: !app.projects.length; text: "Add a project to organize chats."; font.pixelSize: 11; color: Theme.muted; Layout.fillWidth: true }
                            Repeater {
                                model: app.projects
                                NavButton {
                                    required property var modelData
                                    Layout.fillWidth: true; text: "▱  " + modelData.name; selected: app.activeProjectId === modelData.id
                                    enabled: !app.chatBusy && modelData.available
                                    onClicked: { app.send({op: "project_open", project_id: modelData.id}); app.page = "chat" }
                                    ToolTip.visible: hovered; ToolTip.text: modelData.root
                                }
                            }
                            Copy { Layout.topMargin: 20; Layout.bottomMargin: 8; text: app.activeProjectId ? "PROJECT CHATS" : "RECENT CHATS"; font.pixelSize: 9; font.letterSpacing: 1.4; color: Theme.faint }
                            Repeater {
                                model: app.projectChats.slice(0,12)
                                NavButton {
                                    required property var modelData
                                    Layout.fillWidth: true; text: modelData.title; selected: app.page === "chat" && app.chat && app.chat.id === modelData.id
                                    enabled: !app.chatBusy
                                    onClicked: { app.send({op: "chat_open", id: modelData.id}); app.page = "chat" }
                                    ToolTip.visible: hovered; ToolTip.text: modelData.title
                                }
                            }
                            NavButton { Layout.fillWidth: true; text: "All conversations"; onClicked: app.page = "conversations" }
                        }
                    }
                    Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.border }
                    NavButton { Layout.fillWidth: true; text: "Walks"; selected: app.page === "library"; onClicked: { app.page = "library"; app.send({op: "refresh"}) } }
                    NavButton { visible: !!app.state; Layout.fillWidth: true; text: "Current walk"; selected: app.page === "walk"; onClicked: app.page = "walk" }
                    NavButton { Layout.fillWidth: true; text: "Tools & connections"; selected: app.page === "tools"; onClicked: app.page = "tools" }
                    NavButton { Layout.fillWidth: true; text: "Settings  ···"; onClicked: sidebarMenu.open() }
                    Menu {
                        id: sidebarMenu; palette: MonoPalette {}
                        MenuItem { text: Theme.dark ? "Switch to light mode" : "Switch to dark mode"; onTriggered: app.send({op: "set_theme", theme: Theme.dark ? "light" : "dark"}) }
                        MenuItem { text: "Model settings"; onTriggered: app.send({op: "settings"}) }
                        MenuItem { text: "Plan inbox"; onTriggered: { app.page = "inbox"; app.send({op: "refresh"}) } }
                        MenuItem { text: "Phone companion"; onTriggered: app.send({op: "phone"}) }
                        MenuItem { text: "Help"; onTriggered: helpDialog.open() }
                    }
                    Copy { Layout.topMargin: 8; text: "●  Local model"; font.pixelSize: 10; color: Theme.muted }
                }
            }
            ColumnLayout {
                Layout.fillWidth: true; Layout.fillHeight: true
                Layout.margins: window.width < 900 || window.height < 620 ? 16 : 32
                spacing: window.height < 620 ? 8 : 14
                RowLayout {
                    visible: app.page !== "new"
                    Layout.fillWidth: true
                    Copy { text: app.page === "walk" ? "Current walk" : app.page === "library" ? "Saved walks" : app.page === "inbox" ? "Plan inbox" : app.page === "tools" ? "Tools" : app.page === "conversations" ? "Saved conversations" : app.page === "chat" ? "Workspace" : "Review plan"; font.pixelSize: 12; color: Theme.muted }
                    Item { Layout.fillWidth: true }
                    Rectangle {
                        visible: app.page !== "chat" && app.page !== "new"
                        implicitWidth: 114; implicitHeight: 30; radius: 3; color: Theme.elevated
                        Copy { anchors.centerIn: parent; text: app.modelLabel || "Local model"; color: Theme.text; font.pixelSize: 11; font.weight: Font.DemiBold }
                    }
                }
                Paper {
                    visible: !!app.error
                    Layout.fillWidth: true; implicitHeight: errorRow.implicitHeight + 24
                    color: Theme.elevated; border.color: Theme.strongBorder
                    RowLayout {
                        id: errorRow
                        anchors.fill: parent; anchors.margins: 12
                        Copy { Layout.fillWidth: true; text: app.error; color: Theme.text }
                        ActionButton { text: "Dismiss"; onClicked: app.error = "" }
                    }
                }
                ChatPane { visible: app.page === "chat"; controller: app; onChooseProject: chatFolderDialog.open(); onAttachFiles: attachmentDialog.open(); onShowTools: app.page = "tools" }
                ScrollView {
                palette: MonoPalette {}
                    visible: app.page === "tools"
                    Layout.fillWidth: true; Layout.fillHeight: true; contentWidth: availableWidth; clip: true
                    ColumnLayout {
                        width: parent.width; spacing: 18
                        Copy { text: "Tools"; font.pixelSize: 25; font.weight: Font.DemiBold; Layout.fillWidth: true }
                        Copy { Layout.fillWidth: true; text: "Choose the tools your next plan can use. Review their access before starting the walk."; color: Theme.muted }
                        Repeater {
                            model: app.plugins
                            Paper {
                                required property var modelData
                                Layout.fillWidth: true; implicitHeight: toolContent.implicitHeight + 32
                                ColumnLayout {
                                    id: toolContent
                                    anchors.fill: parent; anchors.margins: 16; spacing: 8
                                    RowLayout {
                                        Layout.fillWidth: true
                                        Copy { Layout.fillWidth: true; text: parent.parent.parent.modelData.name; font.pixelSize: 17; font.weight: Font.DemiBold }
                                        Switch {
                palette: MonoPalette {}
                                            checked: app.selectedPlugins.indexOf(parent.parent.parent.modelData.id) >= 0
                                            enabled: !!app.chat && !app.chatBusy
                                            onToggled: {
                                                var id = parent.parent.parent.modelData.id
                                                var next = app.selectedPlugins.filter(function(p) { return p !== id })
                                                if (checked) next.push(id)
                                                app.send({op: "chat_plugins", chat_id: app.chat.id, plugins: next})
                                            }
                                        }
                                    }
                                    Copy { Layout.fillWidth: true; text: parent.parent.modelData.description; color: Theme.muted; font.pixelSize: 12 }
                                    Copy { Layout.fillWidth: true; visible: parent.parent.modelData.adapter === "obsidian"; text: parent.parent.modelData.settings.root || ""; color: Theme.muted; font.pixelSize: 11 }
                                }
                            }
                        }
                        RowLayout {
                            ActionButton { text: "Back to chat"; onClicked: app.page = "chat" }
                            ActionButton { text: "Plugin guide  ↗"; onClicked: app.openPath(app.appRoot + "/docs/PLUGINS.md") }
                        }
                    }
                }
                WalkSetup {
                    id: walkSetup
                    visible: app.page === "new"
                    controller: app
                    onChoosePlan: fileDialog.open()
                    onChooseFolder: folderDialog.open()
                    onReadPlan: fullPlanDialog.open()
                    onShowHelp: helpDialog.open()
                }
                ScrollView {
                palette: MonoPalette {}
                    visible: app.page === "library" || app.page === "inbox" || app.page === "conversations"
                    Layout.fillWidth: true; Layout.fillHeight: true; contentWidth: availableWidth; clip: true
                    ColumnLayout {
                        width: parent.width; spacing: 15
                        Copy { text: app.page === "inbox" ? "Plan inbox" : app.page === "conversations" ? "Conversations" : "Walks"; font.pixelSize: 23; font.weight: Font.DemiBold; Layout.fillWidth: true }
                        Copy { Layout.fillWidth: true; text: app.page === "inbox" ? "Save completed forms in your inbox. Select one to review and start." : app.page === "conversations" ? "Your ideas, files, and plans stay here between visits." : "Pick up a paused walk or open the results of a finished one."; color: Theme.muted }
                        ActionButton { visible: app.page === "inbox"; text: "Open inbox folder  ↗"; onClicked: app.openPath(app.inboxPath) }
                        Copy { visible: (app.page === "library" ? app.runs : app.page === "conversations" ? app.chats : app.inbox).length === 0; text: "Nothing here yet. Start with a conversation."; color: Theme.muted }
                        Repeater {
                            model: app.page === "library" ? app.runs : app.page === "conversations" ? app.chats : app.inbox
                            Paper {
                                required property var modelData
                                Layout.fillWidth: true; implicitHeight: 84
                                RowLayout {
                                    anchors.fill: parent; anchors.margins: 16; spacing: 12
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        Copy { Layout.fillWidth: true; text: modelData.name || modelData.title; font.weight: Font.DemiBold; maximumLineCount: 1; elide: Text.ElideRight }
                                        Copy { Layout.fillWidth: true; text: app.page === "library" ? (modelData.phase === "reviewing" && modelData.status === "running" ? "Needs review" : modelData.status) + " · " + modelData.step : app.page === "conversations" ? "Saved on this computer" : "Ready to import"; font.pixelSize: 12; color: Theme.muted }
                                    }
                                    ActionButton { text: "Open  →"; enabled: !app.active && !app.chatBusy; onClicked: { if (app.page === "library") app.send({op: "load", id: modelData.id}); else if (app.page === "conversations") { app.send({op: "chat_open", id: modelData.id}); app.page = "chat" } else app.importFile(modelData.path) } }
                                }
                            }
                        }
                    }
                }
                WalkWorkspace {
                    visible: app.page === "walk"
                    Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 0
                    controller: app
                }

            }
        }
        }
        Dialog {
                palette: MonoPalette {}
            id: helpDialog
            anchors.centerIn: parent
            width: Math.min(window.width - 60, 720); height: Math.min(window.height - 60, 650)
            modal: true; title: "Your first walk, step by step"; standardButtons: Dialog.Close
            ScrollView {
                palette: MonoPalette {}
                anchors.fill: parent; contentWidth: availableWidth; clip: true
                ColumnLayout {
                    width: parent.width; spacing: 20
                    Copy { Layout.fillWidth: true; text: "You choose the task. Handler checks each step and asks for your decision when needed."; font.pixelSize: 15 }
                    Repeater {
                        model: [
                            {title: "1. Attach the task", body: "Open New walk. Drop a Markdown file into the message box, click Attach file, or type your task. You can also attach a completed .dogwalk plan. Chat remains available for discussing work and attaching pictures."},
                            {title: "2. Choose the project", body: "Click the folder icon, Project, and choose where to work. The chooser starts in your Projects area. New projects can use an empty folder. The brief's location never selects the working folder."},
                            {title: "3. Review the plan", body: "Create walk prepares a checked plan with your selected local model. Answer any questions, then use Review plan to check the allowed files, steps and commands. A completed official form can skip planning. Edit original works in your selected folder; leaving it unchecked makes a protected copy."},
                            {title: "4. Start and watch", body: "Keep Auto walk on to advance checked steps, then press Start walk once. The first local-model step can take a few minutes. Progress and Show details explain what is happening. Keep the computer awake and this app open. Pause walk stops work and retains partial edits."},
                            {title: "5. Review on desktop or phone", body: "When Needs your review appears, read the summary and checks. Approve & continue accepts this checkpoint; checks run again before advancing. Retry step requests the authored correction. Failed checks require a correction and cannot be approved away. For your phone, enable Tailscale on both devices, open Phone companion here, visit its address, and pair. Your phone shows this same walk and review."},
                            {title: "6. Check the result or resume later", body: "Walk complete shows the outcome and final checks. Open results opens the workspace containing the edits. In Protected copy mode, review and copy or merge wanted changes yourself; the original project is not silently replaced. To continue a paused walk, use Walks → Open → Resume walk. An interrupted step needs an explicit retry."}
                        ]
                        ColumnLayout {
                            required property var modelData
                            Layout.fillWidth: true; spacing: 8
                            Copy { Layout.fillWidth: true; text: modelData.title; font.pixelSize: 17; font.weight: Font.DemiBold }
                            Copy { Layout.fillWidth: true; text: modelData.body; color: Theme.muted; lineHeight: 1.25 }
                        }
                    }
                    RowLayout {
                        ActionButton { text: "Open agent form  ↗"; onClicked: app.openPath(app.appRoot + "/forms") }
                        ActionButton { text: "Open inbox  ↗"; onClicked: app.openPath(app.inboxPath) }
                    }
                }
            }
        }
        Dialog {
                palette: MonoPalette {}
            id: fullPlanDialog
            anchors.centerIn: parent; width: Math.min(window.width - 60, 720); height: Math.min(window.height - 60, 580)
            modal: true; title: "Full job plan"; standardButtons: Dialog.Close
            ScrollView {
                palette: MonoPalette {}
                anchors.fill: parent; contentWidth: availableWidth
                Copy { width: parent.width; text: app.job ? app.job.name + "\n\n" + app.job.goal + "\n\nAllowed changes\n" + (app.job.allowed_changes || []).join("\n") + "\n\nConstraints\n" + (app.job.constraints || []).join("\n") + "\n\n" + app.job.steps.map(function(s) { return s.title + "\n" + (s.prompt || "Saved step prompt is in the run log.") + "\n\nChecks\n" + JSON.stringify(s.checks || [], null, 2) }).join("\n\n──────────\n\n") : "" }
            }
        }
        Dialog {
                palette: MonoPalette {}
            id: phoneDialog
            anchors.centerIn: parent; width: Math.min(window.width - 60, 620)
            modal: true; title: "Phone companion"; standardButtons: Dialog.Close
            ColumnLayout {
                width: parent.width; spacing: 12
                Copy { id: phoneInstructions; Layout.fillWidth: true; font.pixelSize: 13 }
                Copy { text: "Private phone address"; font.weight: Font.DemiBold }
                TextField { id: phoneAddress; Layout.fillWidth: true; readOnly: true; selectByMouse: true }
                Copy { text: "Pairing code"; font.weight: Font.DemiBold }
                TextField { id: phoneCode; Layout.fillWidth: true; readOnly: true; selectByMouse: true; font.pixelSize: 24; font.family: "monospace" }
                Copy { Layout.fillWidth: true; text: "Approve, retry, pause, and resume from your phone. Failed checks cannot be approved away. Only your paired Tailscale account can connect."; font.pixelSize: 12; color: Theme.muted }
            }
        }
        Dialog {
                palette: MonoPalette {}
            id: settingsDialog
            anchors.centerIn: parent; width: Math.min(window.width - 60, 650)
            modal: true; title: "Local model settings"; standardButtons: Dialog.Cancel
            ColumnLayout {
                width: parent.width; spacing: 10
                Copy { Layout.fillWidth: true; text: "Connect a local llama.cpp server with a Codex-compatible Responses API. No cloud addresses are accepted. Model downloads and initial dependency setup are separate."; font.pixelSize: 12 }
                CheckBox { id: advancedConnection; text: "Advanced connection"; checked: false }
                ColumnLayout {
                    visible: advancedConnection.checked
                    Layout.fillWidth: true; spacing: 10
                    Copy { text: "Model file (.gguf)" }
                    TextField { id: modelPath; Layout.fillWidth: true; placeholderText: "/absolute/path/model.gguf" }
                    Copy { text: "Local endpoint" }
                    TextField { id: endpoint; Layout.fillWidth: true; placeholderText: "http://127.0.0.1:18081/v1" }
                    Copy { text: "Codex model catalog (JSON file)" }
                    TextField { id: catalog; Layout.fillWidth: true }
                    Copy { text: "Model launcher (one argument per line; blank for already running server)"; Layout.fillWidth: true; font.pixelSize: 12 }
                    TextArea { id: launcher; Layout.fillWidth: true; implicitHeight: 65; font.family: "monospace" }
                    Copy { Layout.fillWidth: true; text: "Prerequisites: " + (app.health.codex ? "Codex ✓  " : "Codex missing  ") + (app.health.worker ? "Model ✓  " : "Model missing  ") + (app.health.catalog ? "Catalog ✓  " : "Catalog missing  ") + (app.health.judge ? "Judge cached ✓" : "Judge not downloaded"); font.pixelSize: 11; color: Theme.muted }
                    ActionButton { text: "Save local settings"; primary: true; enabled: !app.active; onClicked: app.send({op: "save_settings", settings: {model_path: modelPath.text, endpoint: endpoint.text, catalog: catalog.text, start_command: launcher.text.trim() ? launcher.text.trim().split("\n") : []}}) }
                }
            }
        }
    }
}
