# Security and offline boundaries

Dog Walker is a local automation tool. A completed form can contain verification commands and instructions that edit files. Only start jobs from agents and sources you trust. Import is inert; Start executes the job. A separate local copy protects the original project folder but is not a sandbox or backup of all local files. Its starting Git history has no remotes; the source repository metadata is excluded.

Inference endpoints are restricted to HTTP loopback. There is no hosted fallback, and local judge loading disables runtime Hugging Face downloads. Initial dependency/model installation needs internet. Worker tools explicitly use the workspace sandbox with network access disabled. Authored verification commands run under `codex sandbox -P :workspace`; missing sandbox support fails the check rather than running it unprotected. Tests needing network connections, including local TCP servers, will fail under this policy. The app does not disable the host's network: its model API and phone service remain separate processes with their own loopback/private-network roles. For a hard offline boundary, run the model server, runner, and tools together in an isolated network namespace as demonstrated by the acceptance harness.

Run logs stay in the local data folder and may contain project text. Common credential patterns are redacted, but this is not a complete secrets scanner. Do not put secrets into forms or publish your run-data folder. Settings and model weights are not included in the repository.

Do not weaken checks or judge thresholds merely to obtain an automatic pass. A response mentioning tests is not test execution evidence. Manual acceptance is recorded separately; failed deterministic checks cannot be approved past the gate.

Optional phone access runs behind Tailscale Serve, accepts only its configured owner identity, and also requires pairing with signed expiring cookies. The HTTP backend listens only on loopback. Trusted local users can control local processes and are outside this authentication boundary. The phone's exact run/review context is validated by the desktop before a decision is accepted, and deterministic checks rerun before advancing. No status, evidence, or action request is cached or queued by the service worker. Private pairing credentials are stored with mode 0600 outside the repository. Do not enable Tailscale Funnel or expose this backend directly.

The file allowlist detects persistent changes to tracked and non-ignored workspace files, including unexpected additions, deletions, renames, and symlink replacement. It does not police ignored files, transient edits later reverted, or activity outside the workspace. Keep protected-file checks and the coding harness's sandbox enabled; this application is not an adversarial-code sandbox.

Git setup and initial baseline commits are local controller operations. Protected copies exclude source Git metadata, hooks, and remotes. Current-folder mode preserves existing repository configuration but adds local history when it is missing. Publishing credentials and SSH agent variables are removed from child environments, global Git credential configuration is disabled there, and worker instructions prohibit remotes, pushes, and publication. Verified sandbox tests demonstrate local writes working while socket creation and a Git push to a reachable test HTTP server are denied. This is the installed Codex sandbox boundary, not a guarantee against a sandbox escape or privileged local software.


Optional job-scoped plugins expose only requested tool sets through MCP. Built-in
readers bound paths to the selected workspace or configured existing vault.
Browser inspection uses a fresh profile and exact configured origins; the
default origin list is empty. Tool calls are recorded and successful built-in
receipts can be required at checkpoints. Laya recommendations are advisory and
cannot grant tools or override checks. Custom stdio MCP servers are trusted
user-installed code outside the shell sandbox, so review their implementations
and expose only needed tools. Connected tools do not inherit ChatGPT app
credentials. See [plugin boundaries and configuration](docs/PLUGINS.md).

Chat uses a separate local Codex home and the read-only sandbox. Project selection
guides what the model should read; it is not a hard read-access boundary for the
shell. Chat instructions prohibit unrelated folders and credential files. No
plugin process is launched merely by choosing tools or generating a draft.
Generated forms must pass the existing schema/workflow/grant validation, declare
allowed changes, and retain a final review checkpoint. Start and all subsequent
verification/review decisions use the existing engine.

Conversations and attached text/images are saved locally and can contain private
information. Text credential redaction does not sanitize pixels in photographs.
Removing an active attachment excludes it from future model input, while earlier
message snapshots remain saved. See [chat limits and storage](docs/CHAT.md).

## Optional hosted decision routing

Handler defaults to local Laya for bounded read-only project preparation. A separately configured, explicitly enabled TypeSafe Jev connection can send up to 4,000 characters of the task prompt and finite routing options to the official provider. Key setup and synthetic testing alone do not enable this. The owner-only key file is outside the project, excluded from chat/form exports, and not forwarded to Codex or plugins. The client disables proxies and redirects, limits responses and socket wait time, and exposes sanitized errors. Provider uncertainty/errors return to the main worker with its original grants; provider decisions never authorize writes or pass verification checks. Main-model generation remains local. The private setup terminal explains data transfer before enabling real-work routing.
