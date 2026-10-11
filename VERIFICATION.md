# Verification — 2026-10-08, America/Los_Angeles

## Simplified context and agent panes — 2026-10-09

Opening a walk now prepares an independent persistent context terminal on the
left and a shell on the right. Claude/Codex buttons open helpers in the right
pane; switching agent tabs leaves the left PTY mounted. A draggable divider
adjusts the widths. The Terminal dropdown and nested tmux status bars are removed
from the embedded workspace. Review is the default; Help still pauses before
scoped edits. Saved helper sessions reconnect with an attach-only path that
cannot start a missing provider session or create a new inference request.

Both terminal panes import the current Omarchy Ghostty foreground, background,
normal and bright ANSI palettes and configured font/size. Desktop configuration
is read only. A content-based palette name refreshes existing terminal colors
without replacing the PTY. The terminal follows Omarchy independently of the
app's light/dark interface; Corso remains the fallback on other machines.
PTY startup waits for a usable viewport so initial context is not lost during
split-layout sizing.

Validation: **470 Handler pytest tests passed in 65.37 seconds**, and **32 Qt
test results passed**. New cases verify exact native color/bright-slot imports,
unchanged source settings, theme cache refresh, missing-theme fallback, separate
real context/shell tmux sessions with stable process IDs, and reconnect-only
agent restoration. Qt tests verify right-side agent selection without restarting
left context, explicit Help gating and reachable controls in a small workspace.
Actual QML/Bash renders passed in both app modes at 1280×800 and 720×400.
These results concern Handler; they do not assert that the clipboard project's
own tests pass or that the local model completed its current step.

Deployment paused the active clipboard walk, retained partial backend work and
restored the same run at 1/4 checkpoints. Its workspace fingerprints before and
after the controller restart matched. Existing Claude/Codex terminals reattached
without new provider launches, and the selected Claude Review tab was restored.
The main Ornith service and existing external Claude process retained their
PIDs. The walk was left paused for Resume and explicit Retry; no failed project
check was bypassed and no authored plan was changed.

## Embedded workspace and Markdown briefs — 2026-10-09

Handler now has persistent embedded Live, Shell and Claude/Codex helper tabs,
using a pinned repo-local Qt 6 QMLTermWidget build and a dedicated tmux socket.
Review helpers retain scoped reads; drive helpers still pause before edits.
The New walk composer accepts ordinary Markdown through drop or Attach file,
with an independently chosen Project folder starting in the user's Projects area.
Plain briefs use the existing official schema, repair and review pipeline before
Start. The full brief is installed as a fingerprinted protected reference at
Start, outside the allowed edit scope. Import and planning never execute the walk.

Validation: **466 pytest tests passed in 68.79 seconds** against the staged UI;
the final native regression passed after the last frontend changes. **27 Qt test
results passed**, including actual shell keyboard input, one shell startup across
theme/size changes, Markdown attachment, Enter/Shift+Enter, and visible start
controls in a small window. Isolated tests exercise persistent real tmux shells,
review without pausing, and pause before drive. No cloud helper inference was
submitted during these tests.

`scripts/workspace-ui-smoke.py` renders the actual brief composer and real Bash
terminal in both themes at 1280×800 and 720×400, checks image dimensions and QML
errors, and starts no walk or model. Native integration opens actual Shell/Live
tabs for a disposable completed run; it cleans up only its own tmux sessions.
The complete suite also caught and fixed a legacy Textual timer shutdown race.

Applying the interface paused Rick's clipboard walk on its backend step, retained
partial work, and restored the same saved run at 1/4 checkpoints with an embedded
Live tab and no UI error. File fingerprints before/after the restart were equal.
The Ornith model service and existing Claude process retained their PIDs. The walk
was left paused; an interrupted turn needs Resume and an explicit Retry. This
upgrade does not establish a multi-agent speedup or validate provider reasoning.

## Terminal helpers — 2026-10-09

Added a real Omarchy terminal with a dedicated Handler tmux socket: live activity
and an ordinary workspace shell. The persistent Terminal menu opens it or launches
a user-selected Claude/Codex helper. Review mode exposes only scoped reads and saved
suggestions. Help pauses before launch; its MCP controller gates edits by the
worker/run locks, exact allowlist, protected inputs and current file hash. It can
run unchanged authored checks, queue one-use step guidance and resume/retry, with
no completion approval, arbitrary commands or model-switch tool.

Validation: full pytest suite 435 passed in 36.24 seconds; native rendering plus
helper tests passed after moving the menu into the header. An additional actual
verification regression detected a protected-file change without changing saved
evaluation or advancing the walk. The final focused helper suite passed 17 tests.
Qt keyboard/drop tests passed 19 including setup/cleanup. Real isolated stdio MCP
initialize, tools/list and handler_status succeeded against Rick's paused walk.
Codex parsed the generated per-session MCP configuration as enabled stdio;
Claude's generated launch arguments parsed successfully without inference.

Live desktop verification: Handler restored the clipboard walk at 1/4 checkpoints,
paused on backend after its 3600-second timeout, with no UI error. The Terminal
button is visible in the small tiled window. A real Ghostty client attached to the
dedicated tmux session, showing live output and Bash in the saved workspace.
No Claude/Codex model turn was submitted during these checks. Their end-to-end
reasoning and tool-use behavior remains to be exercised by a user-launched helper;
this does not establish a model speedup. No project files or authored checks in
Rick's live walk were changed by this integration.

## Current harness verification — 2026-10-09

### Small coder removal and model guidance

Rick requested removing the small coder. Its active plugin and broker, helper
library and startup/probe utilities, and the 1,117,320,768-byte Qwen model file
are removed. The separate transient service is inactive and had no persistent
unit. New coder grants are rejected; historical grants remain readable but
cannot expose the coder tool, forward its service environment or execute it.
Saved chat selections omit the retired tool without rewriting old history.
Historical pilot records remain; live pilot runs/resumes are disabled before
any inference. Current full suite: **339 passed in 34.73 seconds**. Retired
feature tests were replaced with removal checks. The remaining scripted Codex
transport acceptance passed, using project_map and no model inference.

The main runtime remains healthy with PID 196000 and zero process swap. Laya
remains installed. A three-task local CPU timing probe took 6.669 seconds cold
and 0.436/0.428 seconds warm, choosing the expected map/search/verify options.
All stayed below the current confidence threshold and correctly returned
review. This is exploratory timing, not evidence of a general speedup or
validated routing accuracy. `artifacts/laya-routing-probe.json` records it.

Gemma 4's installed weight, catalog entry and launcher dry run were verified.
`artifacts/gemma-worker-profile.json` is validated and ready to review; current
worker settings remain Ornith. No live Gemma Dog Walk or model switching was
performed. See [model and speed guidance](docs/MODEL_STRATEGY.md) for the proposed
Laya role and Gemma settings. The following coder sections are historical.

### Project context and actual model tool access

Before coder removal, the full suite passed **370 tests**. Coverage included fresh project
mapping and literal search, safe file opens, Git ignore rules, bounded structured
results, isolated benchmark scoring, helper cleanup on interruption, and streamed
namespace compatibility including cancellation after response headers.

Investigation found the pinned local Responses converter discarded Codex's MCP
namespace envelopes. Dog Walk now translates them into ordinary function tools
for granted walks and restores namespaced calls in streamed responses and request
history. It uses a temporary loopback listener per turn; the shared model service,
configured endpoint, readiness checks, tool grants and sandbox remain unchanged.

`scripts/transport-acceptance.py` passed with real Codex and the actual MCP broker
against a scripted local provider: two Responses requests, successful audited
`project_map` call, completed controller verification, and unchanged original.
This test performs no model inference. A separate live Ornith walk subsequently
recorded a successful `project_map` receipt through the same transport.

The `--coder` transport acceptance also passed: three scripted main Responses
requests, successful project-map and real `local_coder_suggest` receipts,
unchanged fixture, and advice marked untrusted/unapplied/unverified. It performed
actual helper inference and no main-model inference. The main runtime retained
PID 196000, and the helper was stopped after the check. The coder's MCP process
now receives only the two desktop-session environment names needed for its user
service; values never enter configuration arguments or saved grants.

The six-task helper pilot uses `artifacts/context-helper-pilot-final`. Earlier
`context-helper-pilot-live` (overlapping app checks), `context-helper-pilot-clean`
(before namespace compatibility), and `context-helper-pilot` (missing helper
service environment) are preserved separately and excluded from the comparison.
They provide no evidence of a helper speedup.

The final pilot completed all **12 walks** in 49.3 minutes, with no app test
suite running alongside it. Main-only: **5/6** repairs passed code/scope checks
and completed, median **254.4 seconds**. Helper enabled: **6/6** repairs passed
code/scope checks, but only **4/6** walks completed, median **275.1 seconds**;
two paused because the main model returned malformed completion text. The
main-only navigation walk stopped before editing and failed its code check.
Of six helper-enabled walks, four called the coder: three calls succeeded,
one timed out, and two walks skipped it. Those missed calls mean the helper arm
is a test of the current harness with the tool available, not six successful
uses of helper advice.

Every file-scope and original-preservation check passed. There were no helper
cleanup errors, and sampled main-model swap stayed zero. Peak sampled combined
RSS was 27.88 GiB main-only and 29.08 GiB with the helper. The main runtime
retained PID 196000 and returned to healthy idle state; the helper was inactive
after the pilot. The saved Desk Notes job remained paused at three turns.

The helper remains opt-in. One run per small task does not establish a general
quality or speed benefit, and shorter failed walks can affect median time.
See the [portable results](docs/verification/helper-pilot.json) and local
`artifacts/context-helper-pilot-final/REPORT.md` / `results.json`. The final
report separates code checks from workflow completion and includes review
reasons recovered from the saved controller state; timings and scores are
unchanged.

After the pilot and report clarification, the complete suite passed again:
**370 passed in 46.43 seconds**. Python compilation and `git diff --check` also
passed. The idle native app was reopened with the updated backend and connected
to the same saved chat without a QML load error. The saved Desk Notes state
file's SHA-256 stayed unchanged across reopening; main PID and zero process
swap were rechecked, and the helper remained inactive.

The earlier sandbox limitations below are historical. An earlier full-suite run passed **328 tests** with no thread shim or deselected test; the latest total is 370 above. Coverage includes locked project/preference persistence, legacy chats, direct folder setup and bundled-plan auto-review, frozen grants, stopped/stale callers, real subprocess JSONL handling, private image preprocessing, model identity/health readiness, scoped credential forwarding, and bounded local coder suggestions.

Additional real runtime checks:

- **Qt keyboard tests:** four behavior cases (six Qt test lifecycle results) pass for Enter send, Shift+Enter newline, saving/acknowledgment, duplicate sends, active-walk/offline and size guards. `qmltestrunner -input tests/qml` uses the actual ChatPane.
- **Native UI:** `scripts/chat-ui-smoke.py --theme dark` and `--theme light` render welcome, conversation, tools, plan review and 900×620 compact views. No QML load/type/binding errors. Chat transcript boxes removed; theme contrast checked in both modes.
- **Phone browser:** real sandboxed Chromium at 390px verifies dark/light toggle, persisted choice, button contrast, no horizontal overflow and no walk/pair actions. Existing phone authorization and pairing remain unchanged.
- **Connectors:** actual stdio MCP initialize/tools-list for pinned Firecrawl 3.29.1 and Microsoft Playwright 0.0.83. Live Firecrawl search worked without an account key in its limited keyless mode. A local Playwright fixture passed navigation, typing, clicking and closing. No whole-desktop input connector is enabled.
- **Small coder:** official 1.5B Qwen Q4_K_M weights verified against pinned HF size/SHA-256; fully RAM-loaded CPU service showed zero swap. A real `local_coder_suggest` broker call in an isolated temporary job lazily started the model and returned advice marked untrusted/unapplied/unverified; workspace files were unchanged. Helper stopped after testing. One simple repair sample measured 17.16 generated tokens/s; this is not a general quality or speedup benchmark.
- **Main model:** zero-swap service startup retained the reviewed Ornith, vision projector, template, context and cache settings. Healthy loaded identity and zero process VmSwap verified before work. After vision the process reported about 25.0 GiB RSS and zero swap. CPU vision defaults to a bounded image-token budget and a private 384px inference copy; original uploads/previews remain intact.
- **Full rendered app walk:** `scripts/desktop_acceptance.py --plain-project --phone` invoked actual QML button handlers. A real three-turn Codex/Ornith job repaired an ordinary project in a protected copy, passed three unchanged tests and allowed-file checks, paused/reopened without replay, rejected stale/duplicate phone approvals, and completed after an explicit scripted test-harness phone review. The original folder/test file remained unchanged and no Git remotes were added. This run used local inference, but was not a separate external-network-namespace acceptance.
- **Actual local vision chat:** `scripts/chat-acceptance.py` passed an uploaded image through the real ChatWorker/Codex route and completed with no tools or walk. After preprocessing it took 128.28 seconds. The model caption was imperfect: it misnamed the breed and described floppy ears despite the cropped-ear logo. This verifies image transport and turn completion, not caption accuracy. Earlier full-size tests timed out; those isolated requests were cleaned up and the model was returned to a healthy ready state.

Reproduction commands:

```sh
.venv/bin/python -m pytest -q
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software QT_QUICK_CONTROLS_STYLE=Basic /usr/lib/qt6/bin/qmltestrunner -input tests/qml
.venv/bin/python scripts/chat-ui-smoke.py --theme dark
.venv/bin/python scripts/chat-ui-smoke.py --theme light --output artifacts/chat-ui-light
node scripts/phone-ui-smoke.cjs
# Opt-in isolated live-model checks; run only when no user walk/chat is active:
.venv/bin/python scripts/desktop_acceptance.py --plain-project --phone
.venv/bin/python scripts/chat-acceptance.py
```

Local evidence: `artifacts/desktop-acceptance.json`, `artifacts/chat-acceptance.json`, `artifacts/model-residency.json`, UI screenshots and QML logs. Tests do not approve or replay Rick's saved Desk Notes job.


Dog Walker v0.3.0 is a native desktop source-install preview with an optional private phone companion. Run `dog-walker` to open the desktop, or `dog-walker demo` for the terminal coding fixture.

- **178 automated tests pass**, including the real offscreen QML import/render smoke test, engine recovery, official forms, strict worker-result parsing, run locks, phone authentication and request rejection, command cancellation, and file-scope enforcement. Fifty seeded adversarial worker scenarios claim success while independently checked files may fail; failed checks never complete those walks.
- A fresh real Ornith job through the rendered desktop imported the official form without executing it, inspected a disposable project, fixed only `calc.py`, and passed all three project tests. Its exact file allowlist and protected test-file checks passed; the original checkout remained unchanged.
- That desktop run paused at its authored approval checkpoint, closed and reopened, and completed after a paired HTTP test client approved the fresh review through the real QML/Python broker. Stale and duplicate approvals were rejected. It stayed at **three worker turns**, without replay or test-harness result-format recovery. The final approval was explicitly scripted for testing; this is not a claim of unattended completion.
- The actual private Tailscale HTTPS service passed certificate validation and mobile browser checks using iPhone 13 and Pixel 7 Chromium emulation: pairing, secure session cookies, no horizontal overflow, service-worker registration, offline action disabling, reconnect, and no cached API responses or JavaScript errors. Rick separately confirmed successful pairing on his physical phone. Rick subsequently completed the practice walk with both review decisions recorded as phone approvals. Physical installation and browser-specific Safari behavior remain unverified.
- Regression checks cover persistent edits/additions/deletions/renames and symlink replacement outside an exact file allowlist, protected-file failure before any verification command, changes during a live review, and cancellation of command descendants before unlocking. This does not establish safety against arbitrary hostile code.
- A fresh real-model desktop run started from an ordinary folder without Git, used an independent local baseline without remotes, corrected one inspection-detail failure, and completed four worker turns with all three fixture tests passing. Pause/close/reopen replayed no turn; paired HTTP approval succeeded and stale/duplicate decisions were rejected. The original folder stayed unchanged and without Git. This used a scripted test approval and a network-connected host with sandboxed commands, not a new hard-offline namespace test.
- New regressions verify ordinary and empty folders, dirty/untracked source files, original-folder preservation, copies without remotes/hooks, automatic local history, removal of publishing credentials, denied socket creation, denied Git push to a reachable HTTP test server, sandbox-argument isolation, and fail-closed verification when Codex is missing.
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
- [Ordinary-folder and local-only integration summary](docs/verification/plain-folder-acceptance.json)
- [Private HTTPS mobile browser summary](docs/verification/phone-browser-acceptance.json)
- Full event logs remain private in the local run-data folder; they are not published.

Runtime uses local Ornith weights, pinned CPU dependencies, and Laya checkpoint `e929ae5cf69bc34259cd2f95c9e91145b818b1f0`. The application contains no hosted Jev adapter or cloud fallback.

The fresh desktop/phone test used loopback inference on a network-connected host. The earlier engine acceptance above used a hard offline namespace. These are separate boundaries. This preview has been exercised on the development Omarchy machine; general model compatibility, all phones, and long-running production reliability have not been established. Written criteria and semantic judgments do not replace project-specific tests or human review.


## Plugin harness preview — 2026-10-09

The new local plugin layer supports named project, browser-inspection and
connected-vault adapters plus trusted custom stdio MCP manifests. Jobs opt in
with plugin IDs, grants are saved per run, and tool_called checks require an
actual successful built-in receipt from the current step and turn. The native
QML source was not changed or restarted during the active Desk Notes walk.

Validation in this Codex session:

- 66 targeted tests passed across test_plugins.py, test_worker.py,
  test_forms.py, test_workflow.py and test_cli.py. These cover real stdio
  initialize/list/call round trips, actual project/Git/vault-fixture reads,
  grant freezing, disabled/stale tools, path escapes, disconnect handling,
  Laya response handling, subprocess cancellation, and Chromium resource
  policy executed in Node without launching the browser.
- 24 existing engine/desktop logic tests passed using an in-process serial
  adapter for asyncio.to_thread. Threaded subprocess scheduling stalls in
  this session's sandbox. The previously identified real child-pipe smoke
  test was excluded because its child does not inherit that adapter; this
  is not a claim of passing the complete existing desktop suite.
- The installed Codex 0.162.0 CLI accepted the generated per-run MCP overrides
  and listed the required dogwalker stdio server with the expected interpreter,
  isolated helper and run-directory arguments. This checks configuration,
  not a real model's tool selection.
- A broker smoke test read the actual connected vault's
  Mission-Control/AGENT_SHARED_MEMORY.md (2,656 characters) and a real
  practice-project README. It performed no vault writes.
- The practice form validates. A copy was deposited inertly in
  ~/Documents/Dog Walker/Inbox/Try plugin harness.dogwalk with an ordinary
  ~/Documents/Dog Walker/Harness Test Project folder; no walk was started
  and no Git repository was initialized there.
- JavaScript syntax validation and git diff --check passed.

Limits: Chromium's real launch failed inside this session's sandbox with
shutdown: Operation not permitted. Browser rendering therefore remains
unverified on the normal desktop. No real-model plugin walk or actual Laya
routing-quality evaluation was run, to avoid competing with or changing the
active Desk Notes job. Laya tests use fixture answers to verify advisory
behavior and uncertainty handling. Custom connected services need separately
installed/authenticated stdio servers; direct HTTP/OAuth management and an
in-app plugin catalog are not included in this initial preview.

See docs/PLUGINS.md and examples/plugin-harness.dogwalk for the reviewable
implementation and a first real-desktop acceptance walk.

## 2026-10-09 — Dog Walk chat, vision attachments, and monochrome interface

The display name is now Dog Walk. Commands, Python package/IPC identifiers,
settings/run paths, inbox, and phone pairing remain compatible. Rick chose a
clean black-and-white interface, heavy headings, hard edges, and a Cane Corso
portrait instead of the paw. The generated asset and prompt are in
native/cane-corso.png and docs/LOGO.md. It was copied unchanged into the project
and into the existing phone icon routes; there is no in-app cloud image service.

- **114 targeted tests passed**, with one existing child-pipe test deselected,
  across chat, plugins, worker, desktop, engine, forms, workflow, and CLI. As in
  the preceding harness checks, this sandbox needs an ephemeral serial adapter
  for asyncio.to_thread; production code retains normal asynchronous dispatch.
- Chat tests cover persisted messages, interrupted/crashed replies without
  replay, cross-window locks, cancellation before and after task start, stale
  IDs, attachment bounds, durable image snapshots, and actual local PDF text
  extraction through pdftotext.
- A real executable subprocess fixture exercises the Codex JSONL adapter,
  complete/error turns, explicit read-only CLI configuration, --image forwarding,
  and the -- delimiter that keeps stdin's '-' out of the image argument list.
  These are protocol tests; the fixture does not claim model vision accuracy.
  The installed Codex CLI also accepted the separate chat configuration and
  listed no configured MCP servers; choosing plan tools does not launch them.
- Generated drafts use the official schema/compiler. Tests reject path escapes,
  missing allowed-file declarations, changed plugin grants, and missing final
  review. Valid drafts remain inert until reviewed and explicitly started.
- A chat-generated plan was started through the existing Store/Engine with a
  fixture worker, passed real file/scope checks in a protected copy, required
  a fresh review approval, completed without modifying the original project,
  and returned its actual status/check snapshot to chat.
- **Five actual QML views rendered** using isolated data: welcome, conversation
  with a reviewable plan/image chip, tools, plan preview, and a fresh 900×620
  window. PNG dimensions verify the smaller view. No QML type/reference/binding
  errors occurred. The smoke never presses Send, Create, or Start. Captures and
  logs are in artifacts/chat-ui; README's desktop image is the new welcome view.
- All QML/CSS color literals are grayscale. The installed launcher reads
  Dog Walk and points directly to the Cane Corso PNG; its prior desktop entry
  was backed up. No keybinding, pairing credential, or saved-run JSON was changed.

Live model/vision inference remains unverified in this session: a direct local
endpoint readiness probe returned Operation not permitted. The installed model
catalog advertises image input and the Ornith vision-projector file exists.
Quickshell's IPC socket is also denied by this sandbox; offscreen rendering works
and connects to the real desktop JSON-line bridge. Normal desktop reopen and a
real-model picture/chat-to-plan walk are the remaining runtime acceptance checks.
Earlier real-model workflow evidence remains recorded above; it is not evidence
for these new chat turns.

## 2026-10-09 — Handler, model picker and optional decision routing

Renamed visible native/phone/launcher surfaces to Handler, retained the Corso logo, removed large slogans and empty-chat hero decoration, and folded advanced connection fields away. Internal commands, IPC, data and form identifiers remain compatible. The chat model picker saves Ornith/Gemma profiles without starting services, rejects missing files/catalog entries and environment overrides, and respects both local task guards and the shared worker lease. Main-model startup preserves the reviewed inference configuration and switch/idle guard; both startup profiles were dry-run checked.

Added cached controller-side Laya preparation restricted to explicitly granted map/search reads. Context is fresh, bounded and labeled as untrusted data; uncertain/error choices retain the original worker flow. Preparation cannot fabricate tool receipts or pass authored checks. Added optional pinned TypeSafe Jev adapter with owner-only key setup, explicit real-work opt-in, sanitized errors, socket timeout and bounded HTTPS responses. Testing-only setup sends fixed synthetic tasks without enabling hosted routing for work.

Validation: 387 pytest cases passed in 35.88 seconds. Native dark/light smoke each passed five views including 900×620; Qt keyboard checks passed 6/6; phone Chromium smoke passed. Scripted actual Codex/MCP transport completed with two fake-provider requests and a real successful project_map receipt, original fixture unchanged; neither main-model nor decision-model inference was needed for that transport check. One initial chat integration test accidentally loaded Laya and hit its short fixture timeout; the test now explicitly injects a skipped route, with separate router/controller tests covering the real integration boundaries.

A real Jev connectivity probe sent three fixed synthetic examples after Rick privately entered the key. Times were 191/175/199 ms; all choices matched the expected labels, but support 0.53 on the first remained below the 0.85 routing threshold. Total API-reported input usage 1,093 tokens; estimated cost at the official price $0.000045906. Jev remains disabled for actual work. These three examples do not establish routing accuracy or an end-to-end walk speedup. No live Gemma coding walk was run.

Handler reopened with the same saved chat, idle and connected. Ornith stayed healthy at PID 196000. The paused Desk Notes state remained byte-identical (SHA256 `6bbf74e22cb3470905e915398d942acd838c3a81b4f934a792f2bece32c851b6`). Private API keys and runtime artifacts are excluded from source control.

A separate real hosted controller acceptance used only a temporary synthetic public project and an explicitly testing-only Jev client. The actual `route_context` selected project_search at support 1.0, returned labeled context in 195 ms, and left the fixture unchanged. No main-model generation or real project content was involved. Evidence: `artifacts/jev-controller-acceptance.json`.

## 2026-10-09 — Create a walk and new-folder selection

Fixed native chat-folder selection: Qt sends file URLs, which the desktop now normalizes with local_path before validating the directory. New empty folders and names containing spaces/Unicode are accepted; sidebar project creation accepts the same file-URL format. Create a walk is available from an existing user conversation without a chosen folder and opens the folder chooser rather than silently disabling itself. Its busy, empty-request and message-length guards remain intact.

Validation: 61 focused Python chat/project/desktop tests passed, including three new picker regressions. Nine Qt keyboard/button tests passed, including actual mouse clicks for missing-folder selection and drafting from existing messages with an empty composer. Both native theme smoke tests passed all five views. Compile/diff checks passed. Waited for Gemma's active reply to finish before reopening the backend; selected Rick's existing /home/rickom1/Projects/to-do-list folder in the current chat, preserving all eight messages byte-for-byte. The paused Desk Notes state remains unchanged. Gemma stayed healthy and idle; no plan was generated or walk started by this fix.

## 2026-10-09 — Local plan and completion-report contracts

Reproduced Gemma returning an informal plan with description/commands and missing required form fields. Create a walk now supplies the full current schema and a valid structural example in text, as well as the CLI schema. Invalid drafts receive one bounded read-only format repair and still pass the exact plugin, scope, compiler and final-review gates. Generated editing plans reject contradictory no_changes gates, which compare against the original run baseline. Errors name missing/invalid fields instead of dumping schemas. Chat code snippets are explicitly reference material, not saved project files.

A live fixture then exposed the same local structured-output gap in completion reports: Gemma omitted blockers. The worker now appends its exact five-field schema and a valid example on each fresh/resumed turn. Invalid completion reports still pause without automatic edit replay. Removed the engine's pseudo-JSON shape in favor of the worker's valid contract.

Validation: 399 pytest tests passed in 36.23 seconds, including draft correction bounds, plugin-grant preservation, contradictory-check rejection, exact completion examples, concise invalid reports and no automatic worker replay. The scripted actual Desktop/Engine/Store flow passed with real sandboxed unittest checking, protected-copy scope checks, final approval and results recovery. This scripted flow does not establish real model success.

Handler was reopened under the shared idle lease, with the same ten saved chat messages restored and /home/rickom1/Projects/to-do-list still selected. Gemma service PID292787 was not restarted. The paused Desk Notes state remained byte-identical with SHA256 6bbf74e22cb3470905e915398d942acd838c3a81b4f934a792f2bece32c851b6. No user project was edited or user plan started.

Completed the real Gemma fixture after adding narrow completion canonicalization: only a completed report missing its empty blockers list receives blockers=[]. All four work-claim fields must already validate; blocked reports and all other malformed claims remain errors. The worker logs normalization, retains raw output, and does not replay edits. Final validation: 406 pytest tests passed in 35.58 seconds, including a normalized completed report failing an actual missing-output gate rather than bypassing it.

Live evidence: artifacts/harness-flow-acceptance-recover-report.json, retained fixture artifacts/harness-live-cu1ns8sp. Actual local Gemma ChatWorker drafted the form; actual CodexWorker inspected files, changed only todo.py, reproduced the existing failing test, and ran two passing tests after its fix. Handler then ran the authored unittest command and scope checks, reached final test-only approval, completed the protected-copy run, and reopened results into the isolated chat with no additional worker turn. Original fixture and protected test bytes stayed unchanged. The first coding inspection had required one explicitly authorized test-only retry; the successful editing turn's recorded report was subsequently parsed by the new production canonicalizer and resumed at evaluation, with raw answer and original tool records retained. This verifies recovery and component integration; it was not a single fresh uninterrupted run after the final patch. Gemma drafted two steps despite the one-step request, so request adherence and performance are not established by this fixture. Plugins were not granted in this live fixture; their separate tests remain recorded above.

The final backend reload restored the same saved chat, ten messages and selected to-do-list folder; reopening updates chat metadata timestamps. Gemma stayed at PID292787. The original paused Desk Notes state remained byte-identical. No user project, user run or API key was changed.

## 2026-10-09 — Create a walk selected-tools mismatch

Rick's actual retry failed because Gemma returned plugins=[project] while the controller selection was [project,browser,obsidian]. The controller now owns that selection: omitted selected tools are retained, and unselected additions are still rejected. Added a bounded, reviewed first-step chat reference so the fresh coding worker receives the actual prototype rather than an unresolved instruction to use conversation history. Missing/oversized references cannot bypass schema or scope checks.

Validation: 409 pytest tests passed in 36.98 seconds. Recovered Rick's latest saved real Gemma draft with the new validator and reference transfer under the shared idle lease, retained all existing messages, and saved a new reviewable form with provenance linking to the original model turn. No model regeneration or user-project edit was needed. Handler reopened with the same selected to-do-list folder. The native Review plan screen was visually verified in artifacts/create-walk-recovered.png; it displayed Initialize Checklist Project and the correct project folder. No walk was started by the recovery. Evidence: artifacts/selected-tools-recovery.json.
