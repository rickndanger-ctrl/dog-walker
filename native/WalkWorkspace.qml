pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root

    Layout.fillWidth: true
    Layout.fillHeight: true
    Layout.minimumHeight: 0

    property var controller: null
    readonly property var walkState: controller ? controller.state : null
    readonly property var job: controller ? controller.walkJob : null
    readonly property var steps: job && job.steps ? job.steps : []
    readonly property int completedSteps: walkState && walkState.history ? walkState.history.length : 0
    readonly property string statusLabel: !walkState ? "No walk selected"
        : controller.external ? "Open in another window"
        : controller.review ? "Needs your review"
        : walkState.status === "completed" ? "Walk complete"
        : walkState.status === "aborted" ? "Walk stopped"
        : walkState.status === "paused" ? "Walk paused"
        : walkState.phase === "evaluating" ? "Checking the work"
        : "Working through the plan"

    ColumnLayout {
        anchors.fill: parent
        spacing: 8

        // Status and progress occupy the top line. Actions wrap independently
        // so review controls remain reachable in a narrow tiled window.
        ColumnLayout {
            Layout.fillWidth: true
            Layout.minimumHeight: 0
            spacing: 5

            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: 36
                spacing: 10

                Rectangle {
                    Layout.preferredWidth: 8
                    Layout.preferredHeight: 8
                    radius: 4
                    color: Theme.text
                    Layout.alignment: Qt.AlignVCenter
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 7
                        Copy {
                            Layout.fillWidth: true
                            text: root.walkState ? root.walkState.name : root.statusLabel
                            font.pixelSize: 15
                            font.weight: Font.DemiBold
                            maximumLineCount: 1
                            elide: Text.ElideRight
                        }
                        Copy {
                            visible: !!root.walkState
                            text: root.statusLabel
                            color: Theme.muted
                            font.pixelSize: 14
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        ProgressBar {
                            id: walkProgress
                            Layout.fillWidth: true
                            implicitHeight: 5
                            from: 0
                            to: 1
                            value: root.steps.length ? Math.min(1, root.completedSteps / root.steps.length) : 0
                            background: Rectangle { radius: 3; color: Theme.border }
                            contentItem: Item {
                                Rectangle {
                                    width: parent.width * walkProgress.visualPosition
                                    height: parent.height
                                    radius: 3
                                    color: Theme.text
                                }
                            }
                        }
                        Copy {
                            text: root.walkState
                                ? root.completedSteps + " / " + (root.steps.length || "?") + " steps"
                                : ""
                            color: Theme.muted
                            font.pixelSize: 14
                        }
                        Copy {
                            visible: !!root.controller.review && !!root.controller.reason
                            Layout.maximumWidth: 190
                            text: root.controller.review ? root.controller.reason : ""
                            color: Theme.muted
                            font.pixelSize: 14
                            maximumLineCount: 1
                            elide: Text.ElideRight
                        }
                    }
                }
            }

            Flow {
                Layout.fillWidth: true
                Layout.minimumHeight: implicitHeight
                spacing: 6

                ActionButton {
                    visible: root.controller && root.controller.active && !root.controller.external
                    text: "Pause"
                    implicitHeight: 32
                    leftPadding: 12; rightPadding: 12
                    onClicked: root.controller.control("pause")
                }
                ActionButton {
                    visible: root.controller && !root.controller.active && !root.controller.external
                        && root.walkState && ["completed", "aborted"].indexOf(root.walkState.status) < 0
                    text: "Resume"
                    implicitHeight: 32
                    leftPadding: 12; rightPadding: 12
                    primary: true
                    onClicked: root.controller.resumeWalk()
                }
                ActionButton {
                    visible: root.controller && root.controller.review && !root.controller.external
                    text: "Retry"
                    implicitHeight: 32
                    leftPadding: 12; rightPadding: 12
                    onClicked: root.controller.control("retry")
                }
                ActionButton {
                    visible: root.controller && root.controller.review && !root.controller.external
                    text: "Approve"
                    implicitHeight: 32
                    leftPadding: 12; rightPadding: 12
                    primary: true
                    enabled: !(root.walkState && root.walkState.evaluation
                        && root.walkState.evaluation.checks.some(function(check) { return !check.pass }))
                    onClicked: root.controller.control("approve")
                }
                ActionButton {
                    visible: !!root.walkState
                    text: root.controller.details ? "Hide" : "Details"
                    implicitHeight: 32
                    leftPadding: 12; rightPadding: 12
                    onClicked: root.controller.details = !root.controller.details
                }
                ActionButton {
                    visible: !!root.walkState && (root.walkState.status === "completed" || !!root.controller.shownResult)
                    text: "Open results"
                    implicitHeight: 32
                    leftPadding: 12; rightPadding: 12
                    onClicked: root.controller.openPath(root.walkState.root)
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: root.controller && root.controller.details ? 98 : 0
            visible: root.controller && root.controller.details
            color: Theme.surface
            border.color: Theme.border
            radius: 6
            clip: true

            RowLayout {
                anchors.fill: parent
                anchors.margins: 10
                spacing: 14

                ScrollView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    contentWidth: availableWidth
                    ColumnLayout {
                        width: parent.width
                        spacing: 2
                        Repeater {
                            model: root.steps
                            RowLayout {
                                id: stepRow
                                required property var modelData
                                required property int index
                                Layout.fillWidth: true
                                spacing: 6
                                Copy {
                                    Layout.preferredWidth: 18
                                    text: root.walkState && root.walkState.history
                                        && root.walkState.history.some(function(entry) { return entry.step === stepRow.modelData.id }) ? "✓"
                                        : root.walkState && root.walkState.step === stepRow.modelData.id ? "●" : "○"
                                    font.pixelSize: 14
                                    color: Theme.muted
                                }
                                Copy {
                                    Layout.fillWidth: true
                                    text: (stepRow.index + 1) + ". " + stepRow.modelData.title
                                    maximumLineCount: 1
                                    elide: Text.ElideRight
                                    font.pixelSize: 14
                                }
                            }
                        }
                    }
                }

                Rectangle { Layout.preferredWidth: 1; Layout.fillHeight: true; color: Theme.border }

                ColumnLayout {
                    Layout.preferredWidth: Math.max(180, parent.width * 0.36)
                    Layout.fillHeight: true
                    spacing: 3
                    Copy {
                        visible: !!root.controller.reason
                        Layout.fillWidth: true
                        text: root.controller.review ? root.controller.reason : ""
                        font.pixelSize: 14
                        maximumLineCount: 2
                        elide: Text.ElideRight
                    }
                    Copy {
                        visible: !!root.controller.shownResult
                        Layout.fillWidth: true
                        text: root.controller.shownResult ? root.controller.shownResult.summary : ""
                        font.pixelSize: 14
                        maximumLineCount: 2
                        elide: Text.ElideRight
                    }
                    Copy {
                        visible: !!root.controller.shownEvaluation
                        Layout.fillWidth: true
                        text: root.controller.shownEvaluation
                            ? root.controller.shownEvaluation.checks.map(function(check) {
                                return (check.pass ? "✓ " : "✕ ") + check.id
                            }).join("   ") : ""
                        color: Theme.muted
                        font.pixelSize: 14
                        maximumLineCount: 2
                        elide: Text.ElideRight
                    }
                    Copy {
                        Layout.fillWidth: true
                        text: root.walkState ? "Workspace: " + root.walkState.root + "   ·   Run: " + root.walkState.id : ""
                        color: Theme.muted
                        font.pixelSize: 14
                        maximumLineCount: 1
                        elide: Text.ElideMiddle
                    }
                    Copy {
                        visible: !!root.controller.logs
                        Layout.fillWidth: true
                        text: String(root.controller.logs || "").split("\n").slice(-2).join("   ")
                        color: Theme.muted
                        font.pixelSize: 14
                        maximumLineCount: 1
                        elide: Text.ElideRight
                    }
                }
            }
        }

        AgentWorkspace { controller: root.controller }
    }
}
