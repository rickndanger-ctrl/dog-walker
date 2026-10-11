# Local Responses compatibility bridge

Some local Responses servers accept ordinary function tools but ignore Codex's
MCP namespace envelopes. Dog Walk automatically uses `ResponsesBridge` for
walks with granted plugins. It adapts those
tool definitions for one Codex worker turn: it flattens each namespace tool
into a function name such as `mcp__dogwalker__project_map`, then restores the
namespace and original function name on returned function calls.

The bridge is a temporary loopback HTTP listener on an operating-system
assigned port. It accepts only `POST /v1/responses` and the local runtime's
`GET /v1/models`, `/props`, and `/health` routes (including the `/models` and
`/responses` forms produced when Codex appends routes to a `/v1` base URL). It
validates the upstream endpoint as HTTP on loopback, does not follow redirects,
and sends only JSON content type, accept, host, and content length headers. It
does not forward authorization, cookies, proxy settings, or arbitrary headers.

Request bodies are limited to 16 MiB. The bridge forwards plain function tools
unchanged, rejects malformed namespaces and generated-name collisions, and
rewrites namespaced function-call history into the flat format expected by the
runtime. It restores names on JSON responses and structured SSE events while
passing text deltas through unchanged. SSE is processed one bounded line at a
time; the full stream is never buffered. Upstream connections have a long
per-read timeout for local model prefill, while `close()` immediately shuts
down active sockets so worker cancellation does not wait for that timeout.

The bridge does not start or stop a model service, persist requests, or provide
a cloud fallback. It closes when the turn finishes or is cancelled. The
configured model endpoint and its readiness check remain unchanged; only the
temporary Codex process receives the bridge address.

The pinned runtime's `server_chat_convert_responses_to_chatcmpl` converter
explicitly skips namespace tools. A real Codex request captured against a
scripted local endpoint confirmed that its MCP definitions arrive in namespace
envelopes. `scripts/transport-acceptance.py` checks the complete real Codex,
bridge, MCP server and recorded-receipt path without model inference.

Before coder removal, a `--coder` acceptance also verified an actual helper
call through Codex and the broker. That mode is now removed; its historical
evidence remains in `artifacts/coder-transport-acceptance.json`.

See the [official MCP documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)
for Codex's server configuration. This bridge is local runtime compatibility,
not an OpenAI API service or a change to the shared model installation.
