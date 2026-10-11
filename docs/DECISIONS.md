# Handler Decisions

Open **Handler Decisions** in the Omarchy application launcher, or run `handler decide`.
The terminal menu keeps Laya loaded between requests. Finish pasted input with a dot on its own line.

```sh
handler decide triage "Fix the failing login test today; done when tests pass"
handler decide context --file task.txt --json
printf '%s\n' 'All tests passed, but deployment is blocked.' | handler decide review --criterion 'Tests passed' --criterion 'Deployment completed'
handler decide context "Investigate the login failure" --backend jev
handler decide triage "Implement the specified change" --handoff
```

Laya runs locally using the existing pinned weights. Jev is hosted: selecting it explicitly sends the supplied text and preset questions to TypeSafe using the existing private credentials. This does not enable Jev routing elsewhere in Handler. Missing credentials produce an error; there is no automatic backend fallback.

Triage scores urgency and clarity on a displayed 0–2 scale and selects a next step. Context selection recommends what Qwen should inspect; it reads no project files. Review accepts up to eight individual acceptance criteria and evaluates supplied evidence. Scores can be fractional expected values. Displayed confidence is support from the answer distribution, not a calibrated correctness guarantee. Values below .85 require review. Invalid responses are marked invalid.

Input is limited to 12,000 characters and Laya's smaller token budget; shorten oversized evidence rather than truncating away blockers. The pinned Laya checkpoint warns that some heads are uncalibrated. Keep that warning in mind when interpreting results; these presets need calibration against real labeled tasks.

Qwen handoff requires an explicit selection. It starts a separate interactive Pi session with tools, context-file loading, and session persistence disabled. It carries the supplied task and advisory decisions and asks Qwen to propose next steps. This harness does not run checks or modify projects. It stores no task history.

## Verification — 2026-10-10

Full Handler suite: 486 tests passed in 39.68 seconds; final decision-specific suite: 13 passed. Desktop entry passed desktop-file validation and the launch command opened a Ghostty window. Qwen handoff arguments are covered by a mocked subprocess test and checked against Pi's installed CLI help; no live Qwen generation was performed for this change.

Live three-preset Laya probe: 6.247 seconds cold triage, .366 seconds warm context selection, .562 seconds warm completion review. All results were below .85 and marked review. One completion answer was tentative but inconsistent with explicit passing-test evidence, reinforcing advisory use. An explicit synthetic Jev context probe selected tests with support 1.0 in .217 seconds. These measurements are exploratory, not accuracy benchmarks. Existing Jev routing was already enabled and was left unchanged; the new decision CLI nevertheless defaults to local Laya.

## DeepSeek Harness tool

Both `dsh-qwen` and `dsh-ornith` default minimal profiles include the local stdio MCP server `python -m dog_walker.decision_mcp`. Restart an already running harness and open a new session to load it. Models see `mcp__handler__decide`, with arguments `preset` (triage/context/review), `evidence` (short supplied text), and optional `criteria` (required for review). It returns the same structured advisory results as the terminal. Laya stays loaded within that MCP process after the first call.

The tool description and MCP instructions encourage proactive use for bounded decisions while skipping trivial tasks and extended reasoning. Calls are chosen by the main model, not forced on every turn. The MCP tool exposes only local Laya: models cannot select Jev, access files, run commands, or start another model through it. Existing explicit Jev CLI use remains available. Backups of both harness patches are saved as `web-local.patch.before-decisions.yml` beside the active patches.

Integration verification: 63 focused tests passed, both `dsh-* --check` commands passed, and the harness's installed MCP SDK successfully initialized, discovered, and called the actual local server. The synthetic context call selected tests at .6832 support and returned review in 5.955 seconds cold. Autonomous tool selection by the main models was not benchmarked.
