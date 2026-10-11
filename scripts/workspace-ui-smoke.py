#!/usr/bin/env python3
"""Render brief setup and a real local terminal, without model calls or walks."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import struct
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--native", type=Path, default=ROOT / "native")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/workspace-ui")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="handler-render-") as temporary:
        scratch = Path(temporary)
        rc = scratch / "terminal.bashrc"
        rc.write_text("PS1='handler $ '\nprintf '\\033[33mHandler terminal\\033[0m\\n\\033[34mReady\\033[0m · \\033[36mShell\\033[0m · \\033[35mAgents\\033[0m\\n\\n'\n")
        (scratch / ".runtime").symlink_to(ROOT / ".runtime", target_is_directory=True)
        # Supply visual fixture data only. No send/create/start/helper action.
        probe = r'''
    property int renderFrame: 0
    property int renderStage: 0
    property int renderTicks: 0
    Timer {
        interval: 350; running: true; repeat: true
        onTriggered: {
            if (++app.renderTicks > 100) { console.error("Render timed out"); Qt.quit(); return }
            if (!app.online) return
            if (app.renderStage === 0) {
                Theme.dark = app.renderFrame < 2
                if (app.renderFrame % 2 === 0) {
                    app.page = "new"; app.job = null
                    app.project = "/home/example/Projects/notes"
                    app.brief = {id: "visual-brief", title: "Build a notes app", source: "brief.md"}
                } else {
                    app.page = "walk"
                    app.state = {id: "visual-walk", name: "Notes app", status: "completed", step: "complete", history: [{step: "build"}], root: "/example/notes"}
                    app.walkJob = {steps: [{id: "build", title: "Build and test"}]}
                    app.active = false; app.external = false; app.review = false
                    if (!app.terminals.length) {
                        app.acceptMessage({type: "terminal_ready", terminal: {
                            id: "visual-context", run_id: "visual-walk", kind: "context", label: "Live context",
                            program: "/bin/sh", args: ["-c", "printf 'Step: Build and test\\n\\nReading project files…\\nWriting the notes view…\\nRunning persistence checks…\\n\\nAll checks passed.\\n'; read hold"], cwd: WORKDIR
                        }})
                        app.acceptMessage({type: "terminal_ready", terminal: {
                        id: "visual-shell", run_id: "visual-walk", label: "Shell", program: "/bin/bash",
                        args: ["--noprofile", "--rcfile", RCFILE, "-i"], cwd: WORKDIR
                        }})
                    }
                }
                app.renderStage = 1
            } else if (app.renderStage === 1) {
                app.renderStage = 2
                canvas.grabToImage(function(result) {
                    if (!result.saveToFile(OUTPUTS[app.renderFrame])) console.error("Capture failed")
                    if (++app.renderFrame === OUTPUTS.length) { console.log("WORKSPACE_UI_PASS"); Qt.quit() }
                    else app.renderStage = 0
                })
            }
        }
    }
'''.replace("WORKDIR", json.dumps(str(scratch))).replace("RCFILE", json.dumps(str(rc)))
        env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": "",
               "QT_QUICK_BACKEND": "software", "QT_QUICK_CONTROLS_STYLE": "Basic",
               "QML_IMPORT_PATH": str(ROOT / ".runtime/qml"), "DOG_WALKER_APP_ROOT": str(ROOT),
               "DOG_WALKER_DATA": str(scratch / "data"), "DOG_WALKER_INBOX": str(scratch / "inbox"),
               "DOG_WALKER_OPEN_FILE": "", "PS1": "handler $ "}
        logs = []
        for size, dimensions in (("wide", (1280, 800)), ("compact", (720, 400))):
            native = scratch / size / "native"
            shutil.copytree(args.native, native)
            (native.parent / ".runtime").symlink_to(ROOT / ".runtime", target_is_directory=True)
            outputs = [str((args.output / f"{theme}-{view}-{size}.png").resolve())
                       for theme in ("dark", "light") for view in ("brief", "terminal")]
            shell = native / "shell.qml"
            qml = shell.read_text().replace("implicitWidth: 1280; implicitHeight: 800",
                                           f"implicitWidth: {dimensions[0]}; implicitHeight: {dimensions[1]}")
            shell.write_text(qml.replace("    Process {", probe.replace("OUTPUTS", json.dumps(outputs)) + "    Process {", 1))
            result = subprocess.run(["quickshell", "-n", "-p", str(native)], env=env,
                                    capture_output=True, text=True, timeout=40)
            log = result.stdout + result.stderr
            logs.append(log)
            (args.output / "qml.log").write_text("\n".join(logs))
            failures = ("TypeError", "ReferenceError", "Binding loop", "Failed to load configuration",
                        "Unable to assign", "Cannot assign", "Capture failed", "Render timed out", "not found")
            if result.returncode or "WORKSPACE_UI_PASS" not in log or any(f in log for f in failures):
                raise SystemExit("Workspace render failed:\n" + log)
            for path in outputs:
                if not Path(path).is_file() or Path(path).stat().st_size < 3000:
                    raise SystemExit(f"Missing or empty render: {path}")
                if struct.unpack(">II", Path(path).read_bytes()[16:24]) != dimensions:
                    raise SystemExit(f"Incorrect render dimensions: {path}")
        print("Rendered brief setup and real shell in dark/light at 1280×800 and 720×400.")


if __name__ == "__main__":
    main()
