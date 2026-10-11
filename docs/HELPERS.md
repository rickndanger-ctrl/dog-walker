# Terminal helpers

Open or start a walk. Handler automatically opens two terminal panes: the
selected local model's **Live context** on the left and **Agents** on the right.
Use **Shell**, **Claude**, or **Codex** on the right. Agent tabs stay within that
pane, so switching helpers keeps the local-model context visible. Drag the
divider to adjust the widths. Switching tabs preserves each terminal session.
Reopening the walk reconnects to existing helper sessions without starting a
provider request; missing helpers start only when you click their button.
Closing Handler pauses its worker, while the tmux sessions remain available.

Keep **Review** selected and click **Claude** or **Codex** to review the current step,
code and recent activity while the local model continues. The helper gets a
project snapshot and a custom MCP connection for fresh status and files. Review
mode cannot pause, edit or advance a walk. Saved suggestions stay outside the
project and are not automatically sent to the worker.

Choose **Help**, then click **Claude** or **Codex** for repairs. Handler pauses the
walk before launching the helper. Its MCP tools can edit exact allowlisted files,
run the authored checks, queue advice for the next local-model turn, and
resume/retry the selected walk. Protected inputs cannot be edited. Writes require
the current file hash and the same locks used by the worker. Helpers cannot
approve completion, change checks, switch models or execute arbitrary commands
through this connection. Final approval remains with you.

The Shell tab also provides these shortcuts:

```sh
check-model claude
check-model codex
help-model claude
help-model codex
```

Omitting the provider selects Codex. These commands run the interactive helper
in that shell. The helper starts with a request to inspect the selected walk, so you
can continue with “why is my model stuck?” or “help it finish this step.” The
ordinary shell itself has your normal local permissions; use the helper commands
when you want Handler's scoped MCP controls.

Claude and Codex use their configured CLI account and model. Opening live output
does not call either provider. Launching a helper can send project context to that
provider; it is an explicit user action, separate from local Ornith/Gemma
inference. Existing provider settings and global MCP registrations are not changed.

An interrupted worker turn still requires a retry. A helper can inspect partial
work, queue guidance, resume the walk, and request retry at its fresh checkpoint.
Advice is consumed once for that step; stale advice is archived instead of being
injected into a later step. Verification never manufactures a worker tool receipt
or changes a failed check into an approval.

The integration requires `tmux`, the chosen `claude` or `codex` CLI, and the
repo-local Qt 6 terminal plugin. Install it with:

```sh
.venv/bin/python scripts/install-terminal.py
```

The build needs Git, a C++ compiler, make, Qt 6 development libraries and qmake6.
The launcher supplies the local QML import path; restart Handler after installing.
The plugin is [QMLTermWidget](https://github.com/Swordfish90/qmltermwidget), pinned
to `8913504fa2ebd220ebe7c680c32954e1b3c035c5`. Its GPL and component license files
and authors are preserved under `.runtime/qml/QMLTermWidget`; these licenses are
separate from Handler's license. On Omarchy, both panes read the current generated
Ghostty background, foreground and 16 ANSI colors, plus your Ghostty font and
size. The desktop settings are read only. Colors refresh when Handler starts or
you open a terminal; a new palette name lets existing PTYs adopt updated colors.
The terminal follows Omarchy independently of Handler's light/dark interface.
If no complete native palette is available, the original Corso dark/light palette
is the fallback. External terminal CLI commands remain available on Omarchy.

MCP uses a local stdio subprocess with
isolated Python imports, bound to one saved run and role. It creates no network
listener. Claude's session uses its explicit MCP configuration and read-only
built-in file tools, with hooks disabled. Codex's built-in shell remains in a
read-only sandbox. Application-managed edits go through the scoped controller.

CLI options are checked against the installed clients; Claude's options are also
documented in the [official CLI reference](https://code.claude.com/docs/en/cli-reference).
