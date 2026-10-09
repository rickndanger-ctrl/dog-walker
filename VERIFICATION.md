# Verification — 2026-10-08, America/Los_Angeles

Dog Walker v0.2.0 is a native desktop source-install preview. Run `dog-walker` to open the desktop, or `dog-walker demo` for the terminal coding fixture.

- 58 automated tests pass: the original engine checks plus official-form validation, desktop import/review/recovery, a rendered offscreen QML window, fenced-result schema validation, and prevention of mode changes to a locked run through the terminal CLI.
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
- Full event logs remain private in the local run-data folder; they are not published.

Runtime uses local Ornith weights, pinned CPU dependencies, and Laya checkpoint `e929ae5cf69bc34259cd2f95c9e91145b818b1f0`. The application contains no hosted Jev adapter or cloud fallback.
