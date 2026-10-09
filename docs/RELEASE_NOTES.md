# 0.3.0 · Desktop and private phone preview

Dog Walker now has an optional installable phone companion over private Tailscale HTTPS. Pair from the desktop to monitor progress and evidence, approve or retry a checkpoint, pause, and resume. The computer retains control of the worker and saved-run locks.

- Exact run/review IDs reject stale and duplicate approvals. Deterministic checks run again before advancement, including when files change during review.
- Official forms declare an exact file allowlist. Persistent changes outside it block advancement; protected-file failures prevent verification commands from running.
- Pausing verification terminates its command group and waits before releasing the run lock.
- A complete worker JSON result may arrive inside a single Markdown/tool envelope. Parsing still enforces the strict result schema and rejects ambiguous, truncated, or unrelated text.
- Workflow validation rejects unknown fields and invalid transitions; local settings expand home-directory paths. Native completed walks retain their final summary and checks.
- Phone access requires the configured Tailscale owner plus pairing, signed 12-hour secure cookies, origin and CSRF checks. Offline actions are disabled; evidence and requests are never cached or queued.

**Verification:** 167 automated tests pass. A fresh three-turn Ornith job through the rendered native desktop passed all three project tests, preserved the original checkout and protected tests, reopened without replay, and completed through a scripted paired-phone HTTP approval. Stale and duplicate approvals failed. The real private HTTPS service passed iPhone/Android Chromium emulation checks, and Rick confirmed physical-phone pairing. See [the verification record](https://github.com/rickndanger-ctrl/dog-walker/blob/main/VERIFICATION.md) for evidence and boundaries.

This is an MIT-licensed source-install preview for Quickshell-based Omarchy, with no bundled worker weights or hosted fallback. The tested worker is Ornith through a compatible local Responses API and Codex CLI. Other models, physical-phone approvals/installations, Safari behavior, and long-running production reliability remain unverified. The optional Omarchy bar widget has manifest validation only. The conservative semantic judge may require frequent human review; authored checks remain essential. File allowlists and protected worktrees are not an adversarial-code sandbox.

The earlier engine acceptance used a hard offline namespace. Phone monitoring requires a network connection and was verified separately. Source, setup instructions, official form, schema, agent handoff, and completed example are included.
