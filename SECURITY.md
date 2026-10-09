# Security and offline boundaries

Dog Walker is a local automation tool. A completed form can contain verification commands and instructions that edit files. Only start jobs from agents and sources you trust. Import is inert; Start executes the job. A separate Git worktree protects the original checkout but is not a sandbox or backup of all local files.

Inference endpoints are restricted to HTTP loopback. There is no hosted fallback, and local judge loading disables runtime Hugging Face downloads. Initial dependency/model installation needs internet. The app does not disable the host's network: arbitrary authored commands and worker subprocesses must not be treated as network-isolated merely because inference is local. For a hard offline boundary, run the model server, runner, and tools together in an isolated network namespace as demonstrated by the acceptance harness.

Run logs stay in the local data folder and may contain project text. Common credential patterns are redacted, but this is not a complete secrets scanner. Do not put secrets into forms or publish your run-data folder. Settings and model weights are not included in the repository.

Do not weaken checks or judge thresholds merely to obtain an automatic pass. A response mentioning tests is not test execution evidence. Manual acceptance is recorded separately; failed deterministic checks cannot be approved past the gate.

Optional phone access runs behind Tailscale Serve, accepts only its configured owner identity, and also requires pairing with signed expiring cookies. The HTTP backend listens only on loopback. Trusted local users can control local processes and are outside this authentication boundary. The phone's exact run/review context is validated by the desktop before a decision is accepted, and deterministic checks rerun before advancing. No status, evidence, or action request is cached or queued by the service worker. Private pairing credentials are stored with mode 0600 outside the repository. Do not enable Tailscale Funnel or expose this backend directly.

The file allowlist detects persistent changes to tracked and non-ignored workspace files, including unexpected additions, deletions, renames, and symlink replacement. It does not police ignored files, transient edits later reverted, or activity outside the workspace. Keep protected-file checks and the coding harness's sandbox enabled; this application is not an adversarial-code sandbox.
