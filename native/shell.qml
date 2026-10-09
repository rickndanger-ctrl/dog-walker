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
    property string page: "new"
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
    readonly property string statusText: !state ? "Ready for a walk" : external ? "Open in another window" : review ? "Needs your review" : state.status === "completed" ? "Walk complete" : state.status === "aborted" ? "Walk stopped" : state.status === "paused" ? "Walk paused" : state.phase === "evaluating" ? "Checking the work" : "Walking your model"
    readonly property var shownResult: state ? state.result || (state.status === "completed" ? state.previous_result : null) : null
    readonly property var shownEvaluation: state ? state.evaluation || (state.status === "completed" ? state.last_evaluation : null) : null

    function send(command) {
        if (!bridge.running || !online) { error = "The local engine is not connected. Close and reopen Dog Walker."; return }
        bridge.write(JSON.stringify(command) + "\n")
    }
    function openPath(path) { if (path) Quickshell.execDetached(["xdg-open", path]) }
    function importFile(path) { error = ""; send({op: "import", path: path}) }
    function control(action) { send({op: "control", action: action, run_id: state ? state.id : "", review_id: reviewId}) }
    function resumeWalk() { send({op: "resume", run_id: state ? state.id : ""}) }
    function acceptMessage(m) {
        if (m.type === "hello") {
            online = true; health = m.health
            if (importOnReady) { var f = importOnReady; importOnReady = ""; importFile(f) }
        } else if (m.type === "job") {
            job = m.job; automatic = job.mode === "auto"; page = "new"; error = ""; details = false
        } else if (m.type === "state") {
            state = m.state; active = m.active; external = m.external; review = m.needs_review; reason = m.reason
            reviewId = m.review_id || ""
            walkJob = m.job
        } else if (m.type === "selected") {
            page = "walk"; error = ""
        } else if (m.type === "library") {
            runs = m.runs; inbox = m.inbox; inboxPath = m.inbox_path
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
    Process {
        id: bridge
        command: [app.appRoot + "/.venv/bin/python", "-u", "-m", "dog_walker.desktop"]
        workingDirectory: app.appRoot
        stdinEnabled: true
        running: true
        onStarted: write(JSON.stringify({op: "hello"}) + "\n")
        onExited: { app.online = false; app.active = false; app.error = "The local engine closed. Your saved walks are retained. Reopen Dog Walker to continue." }
        stdout: SplitParser {
            onRead: function(line) {
                try { app.acceptMessage(JSON.parse(line)) }
                catch(e) { app.error = "Could not read the local engine response."; console.warn(e) }
            }
        }
        stderr: SplitParser { onRead: function(line) { console.warn("Dog Walker engine:", line) } }
    }
    Timer { interval: 1500; running: app.online; repeat: true; onTriggered: app.send({op: "refresh"}) }
    IpcHandler {
        target: "dogwalker"
        function open(path: string): string {
            window.visible = true
            if (Quickshell.env("HYPRLAND_INSTANCE_SIGNATURE"))
                Quickshell.execDetached(["hyprctl", "eval", 'for _,w in ipairs(hl.get_windows()) do if w.title == "Dog Walker" then hl.dispatch(hl.dsp.focus({window=w})) end end'])
            if (path) {
                if (app.online) app.importFile(path)
                else app.importOnReady = path
            }
            return "ok"
        }
        // Read-only diagnostics are also used by smoke tests; they do not start jobs.
        function snapshot(): string {
            return JSON.stringify({page: app.page, connected: app.online, job: app.job ? app.job.name : "", state: app.state ? app.state.id : "", error: app.error, capture: app.captureResult, progress: walkProgress.value})
        }
        function capture(path: string): string {
            app.captureResult = "pending"
            canvas.grabToImage(function(result) { app.captureResult = result.saveToFile(path) ? "saved" : "failed" })
            return "requested"
        }
        function showWalk(id: string): string { app.send({op: "load", id: id}); return "requested" }
        function library(): string { app.page = "library"; return "ok" }
        function companionSnapshot(): string {
            return JSON.stringify({connected: app.online, active: app.active, external: app.external,
                review: app.review, review_id: app.reviewId, reason: app.reason, state: app.state, job: app.walkJob})
        }
        function companionControl(payload: string): string {
            try {
                var cmd = JSON.parse(payload)
                if (!app.online || !app.state || cmd.run_id !== app.state.id || app.external) return "unavailable"
                if (["approve", "retry", "pause", "resume"].indexOf(cmd.action) < 0) return "rejected"
                if (["approve", "retry"].indexOf(cmd.action) >= 0 && (!app.review || cmd.review_id !== app.reviewId)) return "stale"
                app.send({op: cmd.action === "resume" ? "resume" : "control", action: cmd.action,
                    run_id: cmd.run_id, review_id: cmd.review_id, request_id: cmd.request_id, source: "phone"})
                return "sent"
            } catch(e) { return "rejected" }
        }
        function companionReply(id: string): string { return JSON.stringify(app.companionReplies[id] || null) }
        function showPhone(): string { window.visible = true; app.send({op: "phone"}); return "requested" }
    }
    FileDialog {
        id: fileDialog
        title: "Import a Dog Walker job"
        nameFilters: ["Dog Walker forms (*.dogwalk *.yaml *.yml *.json)", "All files (*)"]
        onAccepted: app.importFile(selectedFile.toString())
    }
    FolderDialog { id: folderDialog; title: "Choose the project to work on"; onAccepted: app.project = decodeURIComponent(selectedFolder.toString().replace(/^file:\/\//, "")) }

    FloatingWindow {
        id: window
        title: "Dog Walker"
        implicitWidth: 1120; implicitHeight: 780
        minimumSize: Qt.size(900, 620)
        color: "#f6f4ee"
        onClosed: { app.send({op: "shutdown"}); Qt.quit() }

        Rectangle {
            id: canvas
            anchors.fill: parent
            color: "#f6f4ee"
        RowLayout {
            anchors.fill: parent
            spacing: 0
            Rectangle {
                Layout.preferredWidth: 222
                Layout.fillHeight: true
                color: "#193c32"
                ColumnLayout {
                    anchors.fill: parent; anchors.margins: 24
                    spacing: 12
                    RowLayout {
                        spacing: 12
                        Image { source: "icon.svg"; Layout.preferredWidth: 42; Layout.preferredHeight: 42 }
                        Copy { text: "dog walker"; font.pixelSize: 20; font.weight: Font.DemiBold; color: "#f5f2df" }
                    }
                    Copy { Layout.topMargin: 24; Layout.fillWidth: true; text: "Your local AI.\nKept on track."; color: "#a5c1b3"; font.pixelSize: 15; lineHeight: 1.4 }
                    Copy { Layout.topMargin: 30; text: "WORKSPACE"; color: "#7fa595"; font.pixelSize: 10; font.letterSpacing: 2 }
                    ActionButton {
                        Layout.fillWidth: true; text: "+   New walk"; dark: true
                        onClicked: {
                            if (app.active) { app.error = "Pause the current walk before starting another."; return }
                            app.page = "new"; app.job = null; app.error = ""
                        }
                    }
                    ActionButton { Layout.fillWidth: true; text: "Saved walks"; dark: true; onClicked: { app.page = "library"; app.send({op: "refresh"}) } }
                    ActionButton { Layout.fillWidth: true; text: "Inbox" + (app.inbox.length ? "   · " + app.inbox.length : ""); dark: true; onClicked: { app.page = "inbox"; app.send({op: "refresh"}) } }
                    ActionButton { visible: !!app.state; Layout.fillWidth: true; text: "Current walk"; dark: true; onClicked: app.page = "walk" }
                    Item { Layout.fillHeight: true }
                    Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: "#355649" }
                    ActionButton { Layout.fillWidth: true; text: "Local model settings"; dark: true; onClicked: app.send({op: "settings"}) }
                    ActionButton { Layout.fillWidth: true; text: "Phone companion"; dark: true; onClicked: app.send({op: "phone"}) }
                    Copy { text: "●  No cloud connection"; font.pixelSize: 11; color: "#acd0b0" }
                    Copy { text: "Dog Walker  /  0.3"; font.pixelSize: 10; color: "#7fa595" }
                }
            }
            ColumnLayout {
                Layout.fillWidth: true; Layout.fillHeight: true
                Layout.margins: 32
                spacing: 20
                RowLayout {
                    Layout.fillWidth: true
                    Copy { text: app.page === "walk" ? "YOUR WALK" : app.page === "library" ? "WALK LIBRARY" : app.page === "inbox" ? "JOB INBOX" : "A LITTLE GUIDANCE. A LOT OF PROGRESS."; font.pixelSize: 10; font.letterSpacing: 1.5; color: "#77867b" }
                    Item { Layout.fillWidth: true }
                    Rectangle {
                        implicitWidth: 114; implicitHeight: 30; radius: 15; color: "#e4eddf"
                        Copy { anchors.centerIn: parent; text: "●  Runs locally"; color: "#3b6248"; font.pixelSize: 11; font.weight: Font.DemiBold }
                    }
                }
                Paper {
                    visible: !!app.error
                    Layout.fillWidth: true; implicitHeight: errorRow.implicitHeight + 24
                    color: "#fff0e6"; border.color: "#e6c3a8"
                    RowLayout {
                        id: errorRow
                        anchors.fill: parent; anchors.margins: 12
                        Copy { Layout.fillWidth: true; text: app.error; color: "#923d26" }
                        ActionButton { text: "Dismiss"; onClicked: app.error = "" }
                    }
                }
                // Welcome / new-job view.
                ScrollView {
                    visible: app.page === "new"
                    Layout.fillWidth: true; Layout.fillHeight: true
                    clip: true
                    contentWidth: availableWidth
                    ColumnLayout {
                        width: parent.width
                        spacing: 20
                        Copy { Layout.fillWidth: true; text: app.job ? "Ready to walk." : "Big plans. Small steps."; font.pixelSize: 36; font.weight: Font.DemiBold; font.letterSpacing: -1 }
                        Copy { Layout.fillWidth: true; text: app.job ? "Review your job, choose a project, and let your local model get to work." : "Give your agent a plan. Dog Walker takes it one step at a time,\nchecks the work, and asks you when it needs a hand."; color: "#738073"; lineHeight: 1.4; font.pixelSize: 15 }
                        Paper {
                            visible: !app.job
                            Layout.fillWidth: true; implicitHeight: 260
                            border.color: drop.containsDrag ? "#7fa487" : "#dedfd2"
                            color: drop.containsDrag ? "#f1f7ec" : "#ffffff"
                            DropArea {
                                id: drop; anchors.fill: parent
                                onDropped: function(event) {
                                    if (event.hasUrls && event.urls.length === 1) app.importFile(event.urls[0].toString())
                                    else app.error = "Drop one completed local .dogwalk file here."
                                }
                            }
                            ColumnLayout {
                                anchors.centerIn: parent; spacing: 12
                                Image { Layout.alignment: Qt.AlignHCenter; source: "icon.svg"; Layout.preferredWidth: 54; Layout.preferredHeight: 54 }
                                Copy { Layout.alignment: Qt.AlignHCenter; text: "Drop your job form here"; font.pixelSize: 20; font.weight: Font.DemiBold }
                                Copy { Layout.alignment: Qt.AlignHCenter; text: "One .dogwalk file. A complete plan."; color: "#849080" }
                                RowLayout {
                                    Layout.alignment: Qt.AlignHCenter; spacing: 10
                                    ActionButton { text: "Choose a file"; primary: true; enabled: app.online && !app.active; onClicked: fileDialog.open() }
                                    ActionButton { text: "Paste a form"; enabled: app.online && !app.active; onClicked: pasteDialog.open() }
                                }
                            }
                        }
                        RowLayout {
                            visible: !app.job; Layout.fillWidth: true; spacing: 16
                            Paper {
                                Layout.fillWidth: true; implicitHeight: 175
                                ColumnLayout {
                                    anchors.fill: parent; anchors.margins: 20; spacing: 10
                                    Copy { text: "01  /  LET YOUR AGENT PREPARE IT"; font.pixelSize: 10; font.letterSpacing: 1; color: "#81907c" }
                                    Copy { text: "The official job form"; font.pixelSize: 18; font.weight: Font.DemiBold }
                                    Copy { Layout.fillWidth: true; text: "Hand your agent the form and instructions. It returns a plan Dog Walker understands."; color: "#738073"; font.pixelSize: 12 }
                                    ActionButton { text: "Agent form  ↗"; onClicked: app.openPath(app.appRoot + "/forms") }
                                }
                            }
                            Paper {
                                Layout.fillWidth: true; implicitHeight: 175
                                ColumnLayout {
                                    anchors.fill: parent; anchors.margins: 20; spacing: 10
                                    Copy { text: "02  /  KEEP YOUR WORK YOURS"; font.pixelSize: 10; font.letterSpacing: 1; color: "#81907c" }
                                    Copy { text: "Local. Clear. In control."; font.pixelSize: 18; font.weight: Font.DemiBold }
                                    Copy { Layout.fillWidth: true; text: "No Jev. No cloud fallback. A protected workspace, visible checks, and saved progress."; color: "#738073"; font.pixelSize: 12 }
                                    ActionButton { text: "Open job inbox  ↗"; onClicked: app.openPath(app.inboxPath) }
                                }
                            }
                        }
                        Paper {
                            visible: !!app.job
                            Layout.fillWidth: true
                            implicitHeight: previewColumn.implicitHeight + 40
                            ColumnLayout {
                                id: previewColumn; anchors.fill: parent; anchors.margins: 20; spacing: 14
                                Copy { Layout.fillWidth: true; text: app.job ? app.job.name : ""; font.pixelSize: 22; font.weight: Font.DemiBold }
                                Copy { Layout.fillWidth: true; text: app.job ? app.job.goal : ""; color: "#738073" }
                                Copy { Layout.fillWidth: true; text: app.job && Array.isArray(app.job.allowed_changes) ? "Allowed file changes: " + (app.job.allowed_changes.join(", ") || "none (read only)") : "This job has no file allowlist. Its authored checks and protected files still apply."; font.pixelSize: 12; color: "#738073" }
                                Repeater {
                                    model: app.job ? app.job.steps : []
                                    ColumnLayout {
                                        required property var modelData
                                        required property int index
                                        Layout.fillWidth: true; spacing: 5
                                        Copy { Layout.fillWidth: true; text: (index + 1) + "   " + modelData.title + (modelData.review ? "   · review checkpoint" : ""); font.weight: Font.DemiBold }
                                        Copy { Layout.leftMargin: 24; Layout.fillWidth: true; text: (modelData.criteria || []).join(" · "); color: "#7d8979"; font.pixelSize: 12 }
                                    }
                                }
                                Copy { visible: app.job && app.job.commands && app.job.commands.length > 0; text: "COMMANDS THIS JOB WILL RUN"; font.pixelSize: 10; color: "#81907c"; font.letterSpacing: 1 }
                                Copy { Layout.fillWidth: true; visible: app.job && app.job.commands && app.job.commands.length > 0; text: app.job && app.job.commands ? app.job.commands.map(function(c) { return JSON.stringify(c) }).join("\n") : ""; font.family: "monospace"; font.pixelSize: 12 }
                                Copy { Layout.fillWidth: true; text: "Only start forms from an agent you trust. Commands can modify files; protected copy is not a security sandbox."; font.pixelSize: 11; color: "#936e40" }
                                ActionButton { text: "Read full plan"; onClicked: fullPlanDialog.open() }
                            }
                        }
                        Paper {
                            visible: !!app.job
                            Layout.fillWidth: true; implicitHeight: setupColumn.implicitHeight + 40
                            ColumnLayout {
                                id: setupColumn; anchors.fill: parent; anchors.margins: 20; spacing: 12
                                RowLayout {
                                    Layout.fillWidth: true
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        Copy { text: "Where are we working?"; font.pixelSize: 18; font.weight: Font.DemiBold }
                                        Copy { Layout.fillWidth: true; text: app.project || "Choose the folder containing your project"; color: "#738073"; font.pixelSize: 12; elide: Text.ElideMiddle; maximumLineCount: 2 }
                                    }
                                    ActionButton { text: "Choose folder"; onClicked: folderDialog.open() }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Switch { id: autoSwitch; checked: app.automatic; onToggled: app.automatic = checked }
                                    Copy { Layout.fillWidth: true; text: "Auto walk  ·  advance verified steps; pause when uncertain"; font.pixelSize: 12 }
                                }
                                RowLayout {
                                    Switch { id: placeSwitch; checked: app.inPlace; onToggled: app.inPlace = checked }
                                    Copy { Layout.fillWidth: true; text: app.inPlace ? "Current folder  ·  edits your selected files directly" : "Protected copy  ·  requires a clean, committed Git project"; color: app.inPlace ? "#a66b35" : "#738073"; font.pixelSize: 12 }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Copy { Layout.fillWidth: true; text: "Nothing runs until you press Start."; color: "#849080"; font.pixelSize: 11 }
                                    ActionButton { text: "Start walk  →"; primary: true; enabled: app.online && !!app.project && !app.active; onClicked: { app.error = ""; app.logs = ""; app.send({op: "start", root: app.project, auto: app.automatic, in_place: app.inPlace}) } }
                                }
                            }
                        }
                        Item { implicitHeight: 10 }
                    }
                }
                ScrollView {
                    visible: app.page === "library" || app.page === "inbox"
                    Layout.fillWidth: true; Layout.fillHeight: true; contentWidth: availableWidth; clip: true
                    ColumnLayout {
                        width: parent.width; spacing: 15
                        Copy { text: app.page === "inbox" ? "A home for your plans." : "Every walk, remembered."; font.pixelSize: 32; font.weight: Font.DemiBold; Layout.fillWidth: true }
                        Copy { Layout.fillWidth: true; text: app.page === "inbox" ? "Save completed forms in your inbox. Select one to review and start.\nDepositing a file does not automatically execute commands." : "Pick up a paused walk or open the results of a finished one."; color: "#738073" }
                        ActionButton { visible: app.page === "inbox"; text: "Open inbox folder  ↗"; onClicked: app.openPath(app.inboxPath) }
                        Copy { visible: (app.page === "library" ? app.runs : app.inbox).length === 0; text: "Nothing here yet. Your next walk starts with a job form."; color: "#738073" }
                        Repeater {
                            model: app.page === "library" ? app.runs : app.inbox
                            Paper {
                                required property var modelData
                                Layout.fillWidth: true; implicitHeight: 84
                                RowLayout {
                                    anchors.fill: parent; anchors.margins: 16; spacing: 12
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        Copy { Layout.fillWidth: true; text: modelData.name; font.weight: Font.DemiBold; maximumLineCount: 1; elide: Text.ElideRight }
                                        Copy { Layout.fillWidth: true; text: app.page === "library" ? (modelData.phase === "reviewing" && modelData.status === "running" ? "Needs review" : modelData.status) + " · " + modelData.step : "Ready to import"; font.pixelSize: 12; color: "#738073" }
                                    }
                                    ActionButton { text: "Open  →"; enabled: !app.active; onClicked: { if (app.page === "library") app.send({op: "load", id: modelData.id}); else app.importFile(modelData.path) } }
                                }
                            }
                        }
                    }
                }
                ScrollView {
                    visible: app.page === "walk"
                    Layout.fillWidth: true; Layout.fillHeight: true; contentWidth: availableWidth; clip: true
                    ColumnLayout {
                        width: parent.width; spacing: 18
                        Copy { Layout.fillWidth: true; text: app.statusText; font.pixelSize: 34; font.weight: Font.DemiBold }
                        Copy { Layout.fillWidth: true; text: app.state ? app.state.name : ""; font.pixelSize: 16; color: "#738073" }
                        Paper {
                            Layout.fillWidth: true; implicitHeight: progressColumn.implicitHeight + 40
                            ColumnLayout {
                                id: progressColumn; anchors.fill: parent; anchors.margins: 20; spacing: 12
                                RowLayout {
                                    Layout.fillWidth: true
                                    Copy { text: app.state ? app.state.history.length + " of " + (app.walkJob ? app.walkJob.steps.length : "?") + " checkpoints finished" : ""; font.weight: Font.DemiBold }
                                    Item { Layout.fillWidth: true }
                                    Copy { text: app.state ? app.state.turns + " model turns" : ""; color: "#849080"; font.pixelSize: 11 }
                                }
                                ProgressBar {
                                    id: walkProgress
                                    Layout.fillWidth: true; from: 0
                                    to: 1
                                    value: app.state && app.walkJob && app.walkJob.steps.length ? app.state.history.length / app.walkJob.steps.length : 0
                                    background: Rectangle { implicitHeight: 10; radius: 5; color: "#e4eadf" }
                                    contentItem: Item {
                                        implicitHeight: 10
                                        Rectangle { width: parent.width * walkProgress.visualPosition; height: parent.height; radius: 5; color: "#467250" }
                                    }
                                }
                                Repeater {
                                    model: app.walkJob ? app.walkJob.steps : []
                                    RowLayout {
                                        required property var modelData
                                        required property int index
                                        Layout.fillWidth: true
                                        readonly property var entry: app.state ? app.state.history.find(function(h) { return h.step === modelData.id }) : null
                                        Copy { text: parent.entry ? (parent.entry.outcome === "passed" ? "✓" : "◇") : app.state && app.state.step === modelData.id ? "●" : "○"; color: parent.entry ? "#467250" : "#98a28e"; Layout.preferredWidth: 22 }
                                        Copy { Layout.fillWidth: true; text: modelData.title; font.weight: app.state && app.state.step === modelData.id ? Font.DemiBold : Font.Normal }
                                        Copy { text: parent.entry ? parent.entry.outcome.replace(/_/g, " ") : app.state && app.state.step === modelData.id ? app.state.phase === "reviewing" ? "review" : "current" : "up next"; font.pixelSize: 11; color: "#849080" }
                                    }
                                }
                            }
                        }
                        Paper {
                            Layout.fillWidth: true; implicitHeight: evidenceColumn.implicitHeight + 40
                            color: app.review ? "#fff9eb" : "#ffffff"
                            ColumnLayout {
                                id: evidenceColumn; anchors.fill: parent; anchors.margins: 20; spacing: 12
                                Copy { text: app.review ? "A hand on the leash." : app.state && app.state.status === "completed" ? "Your results are ready." : "What’s happening"; font.pixelSize: 21; font.weight: Font.DemiBold }
                                Copy { Layout.fillWidth: true; text: app.external ? "This walk is controlled by another window. You can view progress here. Pause and close the other window before resuming here." : app.review ? app.reason : app.state && app.state.status === "completed" ? "Completion: " + (app.state.completion || "").replace(/_/g, " ") + ". Review your workspace before applying changes to the original project." : app.state && app.state.reason ? app.state.reason : "Your local model is working through the current step. Verification runs before the next checkpoint."; color: "#738073" }
                                Copy { visible: !!app.shownResult; Layout.fillWidth: true; text: app.shownResult ? app.shownResult.summary : "" }
                                Repeater {
                                    model: app.shownEvaluation ? app.shownEvaluation.checks : []
                                    Copy { required property var modelData; Layout.fillWidth: true; text: (modelData.pass ? "✓  " : "✕  ") + modelData.id; color: modelData.pass ? "#467250" : "#a63e35"; font.pixelSize: 12 }
                                }
                                RowLayout {
                                    visible: app.review && !app.external
                                    ActionButton { text: "Approve & continue"; primary: true; enabled: !(app.state && app.state.evaluation && app.state.evaluation.checks.some(function(c) { return !c.pass })); onClicked: app.control("approve") }
                                    ActionButton { text: "Retry step"; onClicked: app.control("retry") }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    ActionButton { visible: app.active && !app.external; text: "Pause walk"; onClicked: app.control("pause") }
                                    ActionButton { visible: !app.active && !app.external && app.state && ["completed", "aborted"].indexOf(app.state.status) < 0; text: "Resume walk"; primary: true; onClicked: app.resumeWalk() }
                                    ActionButton { text: app.state && app.state.status === "completed" ? "Open results  ↗" : "Open workspace  ↗"; onClicked: if (app.state) app.openPath(app.state.root) }
                                    Item { Layout.fillWidth: true }
                                    ActionButton { text: app.details ? "Hide details" : "Show details"; onClicked: app.details = !app.details }
                                }
                                Copy { visible: app.details; Layout.fillWidth: true; text: app.state ? "Workspace: " + app.state.root + "\nRun: " + app.state.id + "\n" + app.logs : ""; font.family: "monospace"; font.pixelSize: 11 }
                                ActionButton { visible: app.details && !!app.state; text: "Open saved run log  ↗"; onClicked: if (app.state) app.openPath(Quickshell.env("DOG_WALKER_DATA") || Quickshell.env("HOME") + "/.local/share/dog-walker/runs/" + app.state.id) }
                            }
                        }
                    }
                }
                Copy { Layout.fillWidth: true; text: "LOCAL MODELS  ·  AUTHORED STEPS  ·  VERIFIED CHECKPOINTS"; font.pixelSize: 9; font.letterSpacing: 1.2; color: "#9aa18e" }
            }
        }
        }
        Dialog {
            id: pasteDialog
            anchors.centerIn: parent
            width: Math.min(window.width - 60, 700); height: Math.min(window.height - 60, 530)
            modal: true; title: "Paste a completed job form"
            standardButtons: Dialog.Cancel | Dialog.Ok
            onAccepted: { app.error = ""; app.send({op: "import", text: pastedForm.text}) }
            ScrollView { anchors.fill: parent; TextArea { id: pastedForm; placeholderText: "dog_walker: 1\nname: …\ngoal: …\nsteps: …"; font.family: "monospace"; wrapMode: TextEdit.Wrap } }
        }
        Dialog {
            id: fullPlanDialog
            anchors.centerIn: parent; width: Math.min(window.width - 60, 720); height: Math.min(window.height - 60, 580)
            modal: true; title: "Full job plan"; standardButtons: Dialog.Close
            ScrollView {
                anchors.fill: parent; contentWidth: availableWidth
                Copy { width: parent.width; text: app.job ? "Constraints\n" + (app.job.constraints || []).join("\n") + "\n\n" + app.job.steps.map(function(s) { return s.title + "\n" + (s.prompt || "Saved step prompt is in the run log.") + "\n\nChecks\n" + JSON.stringify(s.checks || [], null, 2) }).join("\n\n──────────\n\n") : "" }
            }
        }
        Dialog {
            id: phoneDialog
            anchors.centerIn: parent; width: Math.min(window.width - 60, 620)
            modal: true; title: "Your walk, within reach"; standardButtons: Dialog.Close
            ColumnLayout {
                width: parent.width; spacing: 12
                Copy { id: phoneInstructions; Layout.fillWidth: true; font.pixelSize: 13 }
                Copy { text: "Private phone address"; font.weight: Font.DemiBold }
                TextField { id: phoneAddress; Layout.fillWidth: true; readOnly: true; selectByMouse: true }
                Copy { text: "Pairing code"; font.weight: Font.DemiBold }
                TextField { id: phoneCode; Layout.fillWidth: true; readOnly: true; selectByMouse: true; font.pixelSize: 24; font.family: "monospace" }
                Copy { Layout.fillWidth: true; text: "Approve, retry, pause, and resume from your phone. Failed checks cannot be approved away. Only your paired Tailscale account can connect."; font.pixelSize: 12; color: "#738073" }
            }
        }
        Dialog {
            id: settingsDialog
            anchors.centerIn: parent; width: Math.min(window.width - 60, 650)
            modal: true; title: "Local model settings"; standardButtons: Dialog.Cancel
            ColumnLayout {
                width: parent.width; spacing: 10
                Copy { Layout.fillWidth: true; text: "Connect a local llama.cpp server with a Codex-compatible Responses API. No cloud addresses are accepted. Model downloads and initial dependency setup are separate."; font.pixelSize: 12 }
                Copy { text: "Model file (.gguf)" }
                TextField { id: modelPath; Layout.fillWidth: true; placeholderText: "/absolute/path/model.gguf" }
                Copy { text: "Local endpoint" }
                TextField { id: endpoint; Layout.fillWidth: true; placeholderText: "http://127.0.0.1:18081/v1" }
                Copy { text: "Codex model catalog (JSON file)" }
                TextField { id: catalog; Layout.fillWidth: true }
                Copy { text: "Model launcher (one argument per line; blank for already running server)"; Layout.fillWidth: true; font.pixelSize: 12 }
                TextArea { id: launcher; Layout.fillWidth: true; implicitHeight: 65; font.family: "monospace" }
                Copy { Layout.fillWidth: true; text: "Prerequisites: " + (app.health.codex ? "Codex ✓  " : "Codex missing  ") + (app.health.worker ? "Model ✓  " : "Model missing  ") + (app.health.catalog ? "Catalog ✓  " : "Catalog missing  ") + (app.health.judge ? "Judge cached ✓" : "Judge not downloaded"); font.pixelSize: 11; color: "#738073" }
                ActionButton { text: "Save local settings"; primary: true; enabled: !app.active; onClicked: app.send({op: "save_settings", settings: {model_path: modelPath.text, endpoint: endpoint.text, catalog: catalog.text, start_command: launcher.text.trim() ? launcher.text.trim().split("\n") : []}}) }
            }
        }
    }
}
