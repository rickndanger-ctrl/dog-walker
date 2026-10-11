# Web and browser connectors

The optional connectors use the app's existing stdio MCP plugin harness. Install
the exact pinned official packages and register their manifests with:

```sh
bash scripts/install-connectors.sh
```

The packages live under `$XDG_DATA_HOME/dog-walker/tools` (normally
`~/.local/share/dog-walker/tools`). The manifests go to the user plugin folder.
The script requires Node 20+, npm, `dog-walker` on `PATH`, and an installed
Chromium or Chrome executable. It does not sign in to sites, copy browser data,
or run a job.

Request these plugins explicitly in a workflow:

```yaml
plugins: [firecrawl, playwright-browser]
```

`firecrawl` runs the official `firecrawl-mcp` stdio server. Without an API key,
the manifest enables keyless search and scrape, which are rate-limited by
Firecrawl. To register the full allowlist (search, scrape, map, crawl, and
developer search), set `FIRECRAWL_API_KEY` in the environment and rerun the
installer. The script checks only whether the variable is set; it never prints
or stores its value. The manifest stores only that variable's name. Dog Walker
forwards it only to this server when the plugin is requested, never stores the
key in the manifest or run grant. Firecrawl results are external content and
must be treated as untrusted source material. Authenticated calls can use
Firecrawl credits.

`playwright-browser` runs Microsoft's Playwright MCP against a fresh isolated,
headless Chromium context. Its enabled tools navigate pages, inspect accessible
content, click and type. The isolated context does not load saved browser
accounts or retain cookies after close. Page scripts and network requests can
still interact with the pages opened by the agent; use it only for sites the
job is allowed to access. The connector is browser-only; it does not control
the Linux desktop or native applications.

For direct whole-desktop control, Clawd Cursor is an alternative MCP server.
Its upstream documentation supports Linux Wayland, but requires AT-SPI,
Tesseract, and synthetic input via `ydotool` plus its daemon for mouse control;
`wtype` provides keyboard input only. This installation does not enable Clawd
Cursor. Add it only after installing and configuring its Wayland input
prerequisites and reviewing the broad desktop-control grant for the job.

The source packages are pinned at `firecrawl-mcp@3.29.1`,
`@playwright/mcp@0.0.83`. Update the pins only after reviewing the upstream
release and changing the manifests' enabled tool names to match the current
`tools/list` contract.

Upstream references:

- [Firecrawl MCP server](https://github.com/firecrawl/firecrawl-mcp-server)
- [Firecrawl MCP package registry manifest](https://github.com/firecrawl/firecrawl-mcp-server/blob/main/server.json)
- [Microsoft Playwright MCP](https://github.com/microsoft/playwright-mcp)
- [Clawd Cursor](https://github.com/AmrDab/clawdcursor)
