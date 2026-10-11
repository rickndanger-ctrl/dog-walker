#!/usr/bin/env python3
"""Render actual QML with inert fixture data. Never starts a model or a walk."""
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
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/chat-ui")
    parser.add_argument("--theme", choices=["dark", "light"], default="dark")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    outputs = [str((args.output / (name + ".png")).resolve()) for name in ("welcome", "conversation", "tools", "plan", "compact")]
    with tempfile.TemporaryDirectory(prefix="dogwalk-ui-") as temporary:
        scratch = Path(temporary)
        native = scratch / "native"
        shutil.copytree(args.native, native)
        # The bridge uses a throwaway data folder. Fixture messages are visual
        # examples only; this harness never presses Send, Create, or Start.
        portrait = (native / "cane-corso.png").as_uri()
        fixture = {"id": "visual-example", "title": "Build a simple local notes app", "project": "/example/notes",
                   "attachments": [{"id": "image", "name": "reference.png", "kind": "image", "preview": portrait}],
                   "draft": {"id": "visual-plan"}, "selected_plugins": ["project", "browser", "obsidian"],
                   "messages": [{"id": "1", "role": "user", "status": "complete", "text": "Build a local notes app. Keep the interface clean."},
                                {"id": "2", "role": "assistant", "status": "complete", "text": "We can build it in three steps: inspect the project, implement the notes view, and verify that notes survive a restart. Your original project can stay in a protected copy."},
                                {"id": "3", "role": "assistant", "status": "complete", "text": "Your plan is ready. Review the allowed files and checks before starting.", "draft_id": "visual-plan"}]}
        import sys
        sys.path.insert(0, str(ROOT))
        from dog_walker.forms import parse_form, preview
        job = preview(parse_form((ROOT / "examples/discount.dogwalk").read_text()))
        shell = native / "shell.qml"
        qml = shell.read_text()
        qml = qml.replace("Theme.dark = m.theme !== \"light\"", "Theme.dark = " + ("true" if args.theme == "dark" else "false"), 1)
        test = '''
    property int testFrame: 0
    property bool testCapturing: false
    property int testTicks: 0
    Timer {
        interval: 400; running: true; repeat: true
        onTriggered: {
            app.testTicks++
            if (app.testTicks > 75) { console.error("UI test timed out"); Qt.quit(); return }
            if (!app.online || !app.chat || app.testCapturing) return
            app.testCapturing = true
            if (app.testFrame === 1) { app.projects = [{id: "notes", name: "Desk Notes", root: "/example/notes", available: true}]; }
            if (app.testFrame === 1) app.acceptMessage({type: "chat", chat: FIXTURE, busy: false, progress: ""})
            if (app.testFrame === 2) app.page = "tools"
            if (app.testFrame === 3) { app.job = JOB; app.project = "/example/notes"; app.page = "new" }
            Qt.callLater(function() { canvas.grabToImage(function(result) {
                if (!result.saveToFile(OUTPUTS[app.testFrame])) console.error("Capture failed")
                app.testFrame++; app.testCapturing = false
                if (app.testFrame === OUTPUTS.length) { console.log("CHAT_UI_PASS"); Qt.quit() }
            }) })
        }
    }
'''.replace("FIXTURE", json.dumps(fixture)).replace("JOB", json.dumps(job)).replace("OUTPUTS", json.dumps(outputs[:4]))
        qml = qml.replace("    Process {", test + "    Process {", 1)
        shell.write_text(qml)
        runtime = scratch / "runtime"
        runtime.mkdir(mode=0o700)
        env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QPA_PLATFORMTHEME": "none",
               "QT_QUICK_BACKEND": "software", "QT_QUICK_CONTROLS_STYLE": "Basic", "DISPLAY": "", "WAYLAND_DISPLAY": "",
               "XDG_RUNTIME_DIR": str(runtime), "DOG_WALKER_APP_ROOT": str(ROOT), "DOG_WALKER_DATA": str(scratch / "data"),
               "DOG_WALKER_INBOX": str(scratch / "inbox"), "DOG_WALKER_OPEN_FILE": ""}
        result = subprocess.run(["quickshell", "-n", "-p", str(native)], env=env, capture_output=True, text=True, timeout=40)
        log = result.stdout + result.stderr
        compact = scratch / "compact"
        shutil.copytree(args.native, compact)
        compact_qml = (compact / "shell.qml").read_text().replace("Theme.dark = m.theme !== \"light\"", "Theme.dark = " + ("true" if args.theme == "dark" else "false"), 1).replace("implicitWidth: 1120; implicitHeight: 780", "implicitWidth: 900; implicitHeight: 620")
        compact_timer = '''
    Timer { interval: 1200; running: true; repeat: false
        onTriggered: canvas.grabToImage(function(result) {
            result.saveToFile(COMPACT_OUTPUT); console.log("COMPACT_UI_PASS"); Qt.quit()
        })
    }
'''.replace("COMPACT_OUTPUT", json.dumps(outputs[-1]))
        (compact / "shell.qml").write_text(compact_qml.replace("    Process {", compact_timer + "    Process {", 1))
        small = subprocess.run(["quickshell", "-n", "-p", str(compact)], env=env, capture_output=True, text=True, timeout=15)
        log += small.stdout + small.stderr
        (args.output / "qml.log").write_text(log)
        failures = [line for line in log.splitlines() if any(t in line for t in
                    ("TypeError", "ReferenceError", "Binding loop", "Failed to load configuration", "Invalid property", "Unable to assign", "Cannot assign", "Capture failed"))]
        if result.returncode or small.returncode or "CHAT_UI_PASS" not in log or "COMPACT_UI_PASS" not in log or failures or any(not Path(p).is_file() for p in outputs):
            raise SystemExit("QML smoke failed:\n" + log)
        if struct.unpack(">II", Path(outputs[-1]).read_bytes()[16:24]) != (900, 620):
            raise SystemExit("The compact view did not resize to 900×620")
        print("PASS: five QML views, including 900×620; inert fixtures, no model or walk. " + str(args.output))


if __name__ == "__main__":
    main()
