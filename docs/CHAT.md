# Local chat and work plans

Dog Walk uses the existing local Codex CLI and configured loopback model for conversation and plan building. Chat has a separate configuration under `~/.local/share/dog-walker/chat-codex-home` and uses Codex's **read-only** sandbox. Walk execution keeps its existing workspace-write configuration. Chat does not install packages or silently start jobs.

Choose a project to let the model inspect its files. **Attach** supports multiple selections; dropping files on the composer also attaches them. Use up to six active attachments: at most four PNG/JPEG/WebP images, each under 12 MB, and 48 KB total UTF-8 reference text. Images are copied into the conversation and passed with Codex `--image`; they survive moving or deleting the original. Text/code files are snapshotted. PDF extraction uses the installed `pdftotext`, takes the first 20 pages, and rejects empty or oversized text; scanned pages can be attached as pictures. Audio, video, archives, and binary office documents are not supported in this version.

The configured Ornith model catalog advertises image input, and its vision projector exists on this development machine. Other models need their own working vision runtime. The app reports failed turns without treating a partial response as a completed reply.

For inference only, attached images are decoded and copied into a private `attachments/inference` cache as JPEGs with a 384-pixel longest edge. EXIF orientation is applied, transparency is composited on white, and inputs above 40 megapixels or corrupt/unsupported images are rejected. The saved attachment and its preview remain at their original resolution. This compact copy is intended to keep local vision requests responsive; use a crop or a closer image when small text or fine detail matters.

Chats, references, image snapshots, and turn logs live under `~/.local/share/dog-walker/chats`. They can contain private project content. Removing an attachment takes it out of subsequent model context; saved snapshots remain available for earlier messages. Common credential patterns are redacted from stored text. Recent conversation context is bounded; the model is told when older messages may have been omitted.

**Create a walk** supplies the same official job schema used by imported forms. The model may ask a question instead of producing a plan. A valid plan must explicitly declare allowed files, use only the selected plugins, and include a final review checkpoint. Schema, workflow paths, and installed-plugin validation all run before **Review plan** is available. Invalid drafts retain the conversation and leave any previously imported job untouched.

**Review plan** loads the saved draft into the existing preview. **Start walk** creates the run through the existing `Store` and `Engine`: protected copy/current folder choice, scope checks, verification, retries, and review tokens remain authoritative. A run records the source conversation ID. **Discuss in chat** adds a saved status/result/check snapshot; an unfinished run remains labeled unfinished.

The desktop allows one model operation at a time across its windows. Pause an active walk to chat. **Stop** cancels the current reply and releases its locks. Switching chats and starting a walk are rejected while a reply is running. Closing or crashing saves interrupted state; reopening never automatically repeats a message or launches a draft.

Verification commands:

```sh
.venv/bin/pytest tests/test_chat.py tests/test_vision.py tests/test_desktop.py tests/test_worker.py
.venv/bin/python scripts/chat-ui-smoke.py
```

The QML smoke uses isolated data and inert visual fixtures; it does not press Send/Create/Start or invoke a model. A real local vision ChatWorker/Codex turn completed in 128.28 seconds after image preprocessing, with no tools or walk. Its caption misidentified fine details; this verifies transport and completion, not model accuracy. See `VERIFICATION.md`.


Projects save their names and existing folders in the local library. Add one with **Projects +**, select it to open its latest chat, and use **New chat** to add another conversation to that project. Legacy conversations remain available. Archiving a project preserves its folder and conversations. Project and preference writes are locked across desktop windows.

**Enter** sends; **Shift+Enter** inserts a new line. Acknowledgment from the engine clears the composer only after the message is saved. Keyboard submission follows the same active-walk, offline, size and duplicate-send guards as the Send button.

To use a project without chatting: click **New walk**, drop a folder (or choose **Project folder**), and import its completed `.dogwalk` plan. A folder with one top-level `.dogwalk` plan opens that plan for review automatically. Folders with multiple plans ask you to choose; external symlinked forms are skipped. Selecting a folder and importing the form do not use the local model or start any work. Review the plan and press **Start walk**. Change desktop appearance under **Settings ···**; dark/light mode is saved locally. The phone has its own persistent Light/Dark button.

### Plan formatting

Create a walk supplies the full official form schema and a complete structural example in the prompt, alongside the structured-output API request. This matters because some local Responses servers do not enforce the API schema. Chat snippets are reference material; they are not treated as existing project files.

The controller validates the result before exposing Review plan. If the draft is invalid, it makes one read-only correction request with concise field errors and the original requirements. The corrected draft must pass the same scope, plugin, check and final-review gates. It does not start a walk. A second invalid result stops with a short error rather than dumping the schema or silently accepting an informal plan.

Generated editing plans also reject `no_changes` checks, which compare against the original run baseline and would contradict an edit. The prompt explains passing command gates, protected-file `unchanged` checks, and keeping small edits and their verification in the same step. Imported forms keep their existing contract.

The coding worker also receives its exact five-field completion-report schema and a valid example on every fresh or resumed turn. Invalid reports still pause the run without automatic edit replay; the error names the missing/invalid field without dumping the full schema. An interrupted run requires an explicit retry after reviewing partial work.

A completed worker report that omits only the empty blockers list is canonicalized to blockers=[] and logged. The four work-claim fields must already be present and valid; blocked reports, other omissions, oversized claims and unknown fields remain errors. This neither repeats a worker turn nor changes status/evidence/file claims; authored checks and scope still gate completion.

The saved controller selection owns generated-plan plugin grants. A model may omit selected IDs; Handler retains the exact saved selection. Any model-added unselected ID is rejected. The reviewed form carries a bounded snapshot of completed user/assistant chat references in its first step so a fresh coding session receives the prototype/brief that the plan refers to. Failed drafts and system messages are excluded. This reference is visible in the full plan and compiled into its immutable workflow snapshot; it never expands the file or plugin scope.
