# Verification — 2026-10-08, America/Los_Angeles

Dog Walker v0.3.0 is a native desktop source-install preview with an optional private phone companion. Run `dog-walker` to open the desktop, or `dog-walker demo` for the terminal coding fixture.

- **167 automated tests pass**, including the real offscreen QML import/render smoke test, engine recovery, official forms, strict worker-result parsing, run locks, phone authentication and request rejection, command cancellation, and file-scope enforcement. Fifty seeded adversarial worker scenarios claim success while independently checked files may fail; failed checks never complete those walks.
- A fresh real Ornith job through the rendered desktop imported the official form without executing it, inspected a disposable project, fixed only `calc.py`, and passed all three project tests. Its exact file allowlist and protected test-file checks passed; the original checkout remained unchanged.
- That desktop run paused at its authored approval checkpoint, closed and reopened, and completed after a paired HTTP test client approved the fresh review through the real QML/Python broker. Stale and duplicate approvals were rejected. It stayed at **three worker turns**, without replay or test-harness result-format recovery. The final approval was explicitly scripted for testing; this is not a claim of unattended completion.
- The actual private Tailscale HTTPS service passed certificate validation and mobile browser checks using iPhone 13 and Pixel 7 Chromium emulation: pairing, secure session cookies, no horizontal overflow, service-worker registration, offline action disabling, reconnect, and no cached API responses or JavaScript errors. Rick separately confirmed successful pairing on his physical phone. Physical-phone approvals, installation, and Safari behavior remain unverified.
- Regression checks cover persistent edits/additions/deletions/renames and symlink replacement outside an exact file allowlist, protected-file failure before any verification command, changes during a live review, and cancellation of command descendants before unlocking. This does not establish safety against arbitrary hostile code.
- The installed application-menu entry and `.dogwalk` file association were checked. The development machine's Super + Alt + D shortcut is present, and Hyprland reports no configuration errors.
- The optional bar-widget manifest passes `omarchy plugin validate omarchy-plugin`. This is manifest validation; the widget remains a prototype.

The original engine's offline acceptance:

- Its 31 engine/interface tests cover authored retries and exhaustion, saved-session recovery without duplicate turns, rechecking changed files on resume, branch/skip recording, protected files, malformed/truncated JSONL, worker timeout termination, run locks, and dashboard approve/edit/pause controls. They remain part of the current suite.
- A real five-step Codex-on-Ornith run inspected a disposable buggy project, planned its fix, changed `calc.py`, ran three tests, and summarized the result. All three tests passed; the original checkout and protected test file were preserved.
- Ornith, Codex tools, Dog Walker, and the Laya judge ran inside a Linux network namespace with no external routes. An outbound connection to `1.1.1.1:443` failed. The model endpoint was loopback inside that same namespace.
- Four deterministic checkpoints advanced automatically. The final semantic checkpoint returned probability 0.6722 against threshold 0.85 and paused correctly.
- A second isolated offline test resumed the saved run, rechecked the project, recorded a scripted test-harness approval for the final checkpoint, and completed with `with_manual_acceptance`. No worker turn was replayed; the run contains five turns in one Codex session.
- The 32-case synthetic judge diagnostic reported zero false passes, 28 reviews, four negative decisions, and no positive automatic decisions. These observations do not establish general judge accuracy. No thresholds were fitted; semantic judgments are conservative and deterministic checks remain authoritative.

Evidence:

- [Offline run summary](docs/verification/offline-acceptance.json)
- [Offline resume and completion summary](docs/verification/offline-resume-acceptance.json)
- [Local judge diagnostic](docs/verification/judge-diagnostic.json)
- [Fresh desktop and phone-approval summary](docs/verification/desktop-acceptance.json)
- [Private HTTPS mobile browser summary](docs/verification/phone-browser-acceptance.json)
- Full event logs remain private in the local run-data folder; they are not published.

Runtime uses local Ornith weights, pinned CPU dependencies, and Laya checkpoint `e929ae5cf69bc34259cd2f95c9e91145b818b1f0`. The application contains no hosted Jev adapter or cloud fallback.

The fresh desktop/phone test used loopback inference on a network-connected host. The earlier engine acceptance above used a hard offline namespace. These are separate boundaries. This preview has been exercised on the development Omarchy machine; general model compatibility, all phones, and long-running production reliability have not been established. Written criteria and semantic judgments do not replace project-specific tests or human review.
