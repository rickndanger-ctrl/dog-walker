#!/usr/bin/env bash
set -euo pipefail

data_root="${XDG_DATA_HOME:-$HOME/.local/share}/dog-walker/tools"
config_tmp="$(mktemp -d)"
trap 'rm -rf "$config_tmp"' EXIT

mkdir -p "$data_root/firecrawl" "$data_root/playwright"
npm install --prefix "$data_root/firecrawl" --save-exact firecrawl-mcp@3.29.1
npm install --prefix "$data_root/playwright" --save-exact @playwright/mcp@0.0.83

firecrawl_bin="$data_root/firecrawl/node_modules/.bin/firecrawl-mcp"
playwright_bin="$data_root/playwright/node_modules/.bin/playwright-mcp"
chromium_bin="$(command -v chromium || command -v google-chrome-stable || command -v google-chrome || true)"
if [[ -z "$chromium_bin" ]]; then
  printf '%s\n' 'A system Chromium/Chrome executable is required for the isolated browser connector.' >&2
  exit 1
fi
firecrawl_auth_mode="keyless"
if [[ -n "${FIRECRAWL_API_KEY:-}" ]]; then
  firecrawl_auth_mode="authenticated"
fi

python - "$config_tmp" "$firecrawl_bin" "$playwright_bin" "$chromium_bin" "$firecrawl_auth_mode" <<'PY'
import json
import pathlib
import sys

target = pathlib.Path(sys.argv[1])
firecrawl, playwright, chromium, auth_mode = sys.argv[2:]
manifests = {
    "firecrawl": {
        "id": "firecrawl", "name": "Firecrawl web research",
        "description": ("Search and scrape web sources through the official Firecrawl MCP server in rate-limited keyless mode." if auth_mode == "keyless" else
                        "Search, map, crawl, scrape, and search developer sources through the official Firecrawl MCP server."),
        "category": "connected", "adapter": "mcp",
        "settings": {
            "command": firecrawl, "args": [],
            "enabled_tools": (["firecrawl_search", "firecrawl_scrape"] if auth_mode == "keyless" else
                              ["firecrawl_search", "firecrawl_scrape", "firecrawl_map", "firecrawl_crawl", "firecrawl_developer_search"]),
            "env_vars": ["FIRECRAWL_API_KEY"],
        },
    },
    "playwright-browser": {
        "id": "playwright-browser", "name": "Isolated browser control",
        "description": "Navigate and interact with a fresh isolated headless Chromium session. No saved browser accounts.",
        "category": "connected", "adapter": "mcp",
        "settings": {
            "command": playwright,
            "args": ["--isolated", "--headless", "--browser=chromium", f"--executable-path={chromium}"],
            "enabled_tools": ["browser_navigate", "browser_snapshot", "browser_click", "browser_type", "browser_press_key", "browser_close"],
        },
    },
}
for ident, manifest in manifests.items():
    (target / f"{ident}.json").write_text(json.dumps(manifest, indent=2) + "\n")
PY

dog-walker plugin-add "$config_tmp/firecrawl.json"
dog-walker plugin-add "$config_tmp/playwright-browser.json"
printf 'Installed pinned MCP packages under %s and registered manifests.\n' "$data_root"
