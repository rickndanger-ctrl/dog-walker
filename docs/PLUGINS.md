# Dog Walker plugin harness preview

Dog Walker exposes named tools through the worker's existing Codex MCP client.
A job requests installed plugin IDs; each run saves its grants, exposes those
tools, records calls, and retains verification and review checkpoints.
Project, browser, and connected tools share this interface. Existing jobs
that omit `plugins` keep their original offline tool set.

## Use the included tools

Put this optional field at the top level of a completed job form:

```yaml
plugins: [project, browser, obsidian]
```

Choose tools the job needs. The desktop's **Read full plan** shows requested
plugins and machine-local settings under Constraints before Start. Import never
starts tools. Close and reopen the app after the current walk finishes to load
updated Python code.

| Plugin | Tools | Boundary |
| --- | --- | --- |
| `project` | `project_map`, `project_search`, `project_read`, `project_list`, `project_git_status`, `project_verify` | Selected workspace; fresh bounded discovery and authored checks in the existing offline sandbox |
| `browser` | `browser_inspect` | Fresh headless Chromium; project HTML or exact configured HTTP(S) origins; no saved accounts, clicks or form submissions |
| `obsidian` | `obsidian_read`, `obsidian_search` | Existing configured Markdown vault, read only; missing mounts fail without a replacement |
| shared | `recommend_tool` | Cached local Laya advice about enabled built-in tools; returns a name or uncertainty and executes nothing |

Browser inspection returns title, visible text, viewport, horizontal overflow,
JavaScript errors and blocked resource origins. This is an inspection adapter.
For navigation/click/form tools or another connected app, install a trusted
stdio MCP plugin with the precise tool allowlist you intend to expose.

Project mapping and search work behind the scenes, with no new settings or
downloads. See [Finding the right project files](PROJECT_CONTEXT.md) for limits
and the tool interface. The small coder is removed; the
[historical helper comparison](BENCHMARK.md) remains available for review.

The browser uses installed Node, Playwright and Chromium; it downloads nothing.
Rick's default module path points to the existing Hermes Army Playwright
installation. Other machines need a manifest pointing to their installed module.
Playwright must support `routeWebSocket` (1.48+) and Chromium's sandbox must work.

## Install or configure plugins

```sh
dog-walker plugins
dog-walker plugin-add /path/to/trusted-plugin.json
```

These commands list or validate/install manifest data. They never start servers
or call tools. Manifests live in `~/.config/dog-walker/plugins/ID.json`;
`DOG_WALKER_PLUGIN_DIR` can select another directory. A manifest with a built-in
ID customizes its settings. New walks see changes; saved grants stay fixed.
Removing a custom manifest removes that plugin for new jobs; removing a
built-in override restores its defaults. A job can request at most one plugin
for each built-in adapter, and multiple custom MCP plugins.

A browser override for a local app:

```json
{
  "id": "browser",
  "name": "Browser inspection",
  "description": "Inspect project HTML and the local app at port 3000.",
  "category": "browser",
  "adapter": "browser",
  "settings": {
    "playwright_module": "/absolute/path/to/node_modules/playwright",
    "origins": ["http://127.0.0.1:3000"]
  }
}
```

Origins are exact scheme/host/port strings, without paths, credentials or
wildcards. The default list is empty: local HTML works, network origins require
configuration. Other origins, non-GET/HEAD requests, service workers and
WebSockets are blocked. Website responses remain untrusted data. JavaScript
executes in the browser; GET endpoints can have side effects, so configure
sites you intend the job to inspect.

Obsidian overrides use `adapter: "obsidian"`, `category: "connected"`, and
`settings: {"root": "/absolute/path/to/the/existing/vault"}`. Reader calls use
relative note paths. Search requires a folder and stops at 20 matches or 500
Markdown files. Rick's default uses the existing SFTP-linked vault at
`~/Documents/Obsidian Vault`; it is not a replacement directory.

A trusted connected service can provide a stdio MCP plugin:

```json
{
  "id": "my-app",
  "name": "My connected app",
  "description": "Read records from the existing local app connector.",
  "category": "connected",
  "adapter": "mcp",
  "settings": {
    "command": "/absolute/path/to/installed-app-mcp-server",
    "args": ["--stdio"],
    "enabled_tools": ["records_read", "records_search"]
  }
}
```

Request `plugins: [my-app]` in the form. Categories are `project`, `browser`, or
`connected`; they do not alter executable behavior. Servers must already be
installed and authenticated through their own local setup. ChatGPT's installed
app connectors and login sessions are not automatically available to this local
worker. This preview supports stdio custom servers; direct HTTP/OAuth management
and an in-app plugin catalog are future work. Keep secrets out of forms and
manifests. Custom MCP servers are trusted code running as the user outside the
worker shell sandbox. A tool allowlist limits exposure, not server behavior.

## Laya's role

Laya produces a typed choice over enabled tool names. The worker reads the
tool's JSON schema, supplies arguments and makes the actual call. Recommendations
below threshold, malformed predictions, missing cached weights or overlong
input return uncertainty. The worker can choose among granted tools using their
descriptions. A recommendation never grants access or accepts failed checks.

This adapter routes among 2–10 built-in tools using short descriptions and the
existing cached judge. External MCP tools are discovered by Codex and are not
included in this first Laya selector. Routing quality on Rick's tasks is
uncalibrated; unit tests verify decision handling, not model accuracy.

## Verify use and try the practice job

```yaml
checks:
- {type: tool_called, tool: project_read, id: source-tool-used}
- {type: no_changes, id: project-unchanged}
```

`tool_called` requires a successful built-in broker receipt from the current
step and turn. Claims, errors or old calls cannot pass it. It proves invocation,
not correctness of the whole task; pair it with actual file/test checks.
Custom MCP activity is captured in Codex's event log; this check currently
covers the built-in broker only.

Use `examples/plugin-harness.dogwalk` with `examples/harness-fixture` in
Protected copy mode after the current walk finishes. It reads project files,
reads/searches the existing vault, inspects `index.html` at phone width,
checks receipts and unchanged files, then asks for review. Missing runtime or
vault access is a blocker. Starting and approving the job are user actions.

## Runtime and verification

The broker uses stdio MCP with newline-delimited JSON-RPC. Per-turn Codex
configuration adds required servers with tool allowlists. Grants are saved in
`plugin-grants.json` in the run folder. Built-in calls log arguments, bounded
results, step, turn and duration as `plugin_tool` events. Paused or previous-turn
servers cannot execute tools. Broker-owned subprocesses have deadlines and
terminate their process groups on cancellation. Project verification retains
protected-file preflight and allowed-file checks.

The tool layer retains the shell sandbox; a protected copy is not an adversarial
code sandbox. Configured browser/connected plugins may access permitted network
resources. Inference remains local, with no cloud fallback; shell and verification
commands remain offline.

Primary references: [Codex MCP configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli),
[MCP tools](https://modelcontextprotocol.io/specification/2025-06-18/server/tools),
[MCP stdio transport](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports),
[Playwright browser contexts](https://playwright.dev/docs/api/class-browsercontext),
and [Laya's typed decisions](https://github.com/NandhaKishorM/laya).
