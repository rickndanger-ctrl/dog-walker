# Dog Walker · official agent handoff

Give your agent this document, the blank form, and your task. The agent should return **one completed `.dogwalk` file**. Import or drop that file into Dog Walker, select your project folder, review it, and press **Start walk**.

## Instructions for the agent

You are preparing an authored offline workflow, not performing it. Fill in `JOB_FORM.dogwalk` using the user's task and actual project facts. Ask for missing facts that materially affect safety or correctness. Do not invent filenames, test commands, installed dependencies, or success evidence. Return YAML only, saved with a `.dogwalk` extension; no Markdown fences. Use `job.schema.json` as the formal contract.

- Replace every ALL_CAPS placeholder. Give the job a short name and a measurable goal. List scope limits and files that must not change.
- Fill `allowed_changes` with exact project-relative files this job may create, edit, rename, or delete. An empty list makes the entire job read only. This gate fingerprints tracked and non-ignored files and rejects persistent changes outside the list, even if the worker claims success. It requires Git, including in current-folder mode. It does not monitor ignored files or files outside the workspace and is not a sandbox. Older forms may omit it, which disables this additional scope gate.
- Use ordered steps, usually inspect → plan → implement → verify → summarize. Each needs a unique `id`, human-readable `title`, full `prompt`, `success_criteria` list, and `checks` list. Prompts are plain text; dollar signs are literal. The selected workspace is supplied by the app, not embedded in the form.
- Checks are authoritative. Supported types: `command` (`argv` array, optional timeout), `file_exists` (`path`), `file_contains` (`path`, `text`), `unchanged` (`path`), `no_changes`, `response_contains` (`text`), and `command_executed` (`text`). Paths must be relative and stay inside the project. Commands run in the workspace without an implicit shell. A response mentioning tests is not proof they passed: use a `command` check to rerun tests.
- Prefer actual file/test checks. `response_contains` is only a text check, not semantic verification. If no reliable check exists, use `checks: []` and `approval: true`; that step will require review. Written success criteria alone are instructions, not automated proof.
- Include a specific correction `retry_prompt` and bounded `max_retries` (default 2). The app automatically appends failed checks and the previous result to correction prompts. Do not tell the worker to skip failures, alter tests to force a pass, install packages, fetch online resources, or modify files outside the selected workspace.
- Optional `questions` use the local Laya judge. It is conservative and not calibrated for every project; uncertainty pauses for review. Do not reduce thresholds merely to make a workflow continue. Prefer `noul` with explicit instructions, `expected: true`, `threshold: 0.85`.
- `mode: auto` advances verified steps; it does not override failed checks, approval gates, or uncertainty. `supervised` asks before advancing. `max_turns` bounds the entire workflow. Branches (`on_pass`, `on_exhausted`) are optional; default sequence is ordered and finishes after the last step. Failed steps cannot transition directly to complete.
- A job file may contain powerful commands. Show the user what will run. Importing never starts commands; the user presses Start. Do not include secrets or absolute machine-specific paths.

## What the user does

1. Click **Agent form** and give your agent the two files plus your task.
2. Save the returned file anywhere, or in `~/Documents/Dog Walker/Inbox`.
3. Open it with Dog Walker, or drag it onto the window. Pasting completed YAML also works.
4. Choose the project folder. **Protected copy** requires a clean, committed Git project; changes stay in a separate workspace. **Current folder** edits the selected files directly and is clearly marked.
5. Review the steps and commands, then Start. When it pauses, read the evidence before approving or retrying. Completed work is opened with **Open results**; original files are not silently replaced.
