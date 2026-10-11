# Handler model roles

Updated 2026-10-10. The small coder is removed. Qwen 3.8 27B, Ornith and Gemma 4 are the main-model choices for chat, vision and coding. Local Laya prepares optional read-only project context; TypeSafe Jev is an optional hosted decision provider.

## Main model picker

Choose **Qwen 3.8 27B**, **Ornith**, or **Gemma 4** in the chat header or New walk model picker. Selection saves the next request's connection; it does not load or stop a server by itself. The next chat or walk uses the reviewed launcher, shared switch lock, warmup, zero service swap policy and server identity/readiness checks. The launcher reuses the matching healthy server and refuses to stop the other model while it is processing a request. Keep one main model loaded on this machine.

Qwen uses `Qwen3.8-27B-UD-Q4_K_XL.gguf`, its `mmproj-F16.gguf` projector and `http://127.0.0.1:18080/v1`. Handler's existing chat and coding worker request non-thinking mode through Codex; the reviewed Qwen launcher supplies its non-thinking sampling settings (temperature 0.7, top-p 0.8, top-k 20, min-p 0, presence penalty 1.5). Handler does not substitute a separate model or start one merely when the picker changes.

The picker is unavailable while this window is working; another chat/walk's worker lease also blocks configuration changes. Missing model/projector/runtime files or catalog entries disable the corresponding profile. Custom connections remain available under **Settings → Model settings → Advanced connection**. Existing `dog-walker` commands, provider/session identifiers, data paths and `.dogwalk` forms remain compatible with the Handler name.

Both startup plans were dry-run validated. The current Ornith server remained at PID 196000. No live Gemma coding walk was run during this upgrade; the Gemma profile and reviewed startup plan are ready, but those checks are not a claim of measured Gemma coding quality.

## Read-only preparation

Before a walk's worker turn, the controller may ask a process-wide cached local Laya judge to choose `project_map`, `project_search`, or no extra context. Only an explicitly frozen project grant allows these reads. Search requires one safe filename explicitly supplied in backticks. The router cannot execute tests, edit files, grant tools, or satisfy `tool_called` checks on the worker's behalf.

The router requires at least 0.85 support and a valid finite probability distribution. Uncertain choices, provider errors, missing judges and scan errors continue with the original main-model prompt and tools. Fresh context is labeled as untrusted data and capped at 6,000 characters. Cancellation waits for the routing thread before releasing the run lease. Actual verification and authored review gates remain authoritative.

This can reduce repeated context-planning turns; it does not increase Ornith/Gemma's token generation speed. No end-to-end walk speedup has been measured for this new preparation path. The earlier three-task Laya probe recorded a cold first call of 6.669 seconds and warm calls of 0.436/0.428 seconds, with all support values below threshold. That probe used different examples and is not directly comparable to the Jev sample below.

## Optional Jev testing

Enter the key in a private terminal, never in a chat or exported plan:

```bash
cd ~/Projects/dog-walker
bash scripts/jev-test-setup.sh
```

The setup stores an owner-only key at `~/.config/dog-walker/jev.json`. It then sends three fixed synthetic tasks and saves the result to `artifacts/jev-routing-probe.json`. Saving/testing the key does **not** enable Jev for actual work. `TYPESAFE_API_KEY` can also supply a test key without a stored key. No API key is included in reports or worker/plugin configuration.

To enable optional Jev preparation for walks, run:

```bash
.venv/bin/python scripts/configure-jev.py --enable
```

The command explains that up to 4,000 characters of task text and routing options will be sent to TypeSafe, then asks for an explicit opt-in. To return to local Laya, use `--disable`. Main-model inference stays local in both cases. A Jev timeout, malformed result or uncertain answer falls back to the main worker rather than adding a second decision-provider call.

The adapter pins `jev-1.13.0`, uses the official HTTPS endpoint, disables proxies/redirects, applies a five-second socket timeout and caps responses at 64 KiB. The request uses the provider's typed Choice interface. [TypeSafe API](https://docs.typesafe.ai/api)

On this machine the initial three synthetic requests took 0.191, 0.175 and 0.199 seconds. Choices matched the three expected labels; support was 0.53, 0.90 and 1.0, so the first must fall back. Reported input usage was 1,093 tokens total. At the published $0.042 per million input tokens with output free, estimated cost was $0.000045906. This is a connectivity/timing sample, not an accuracy benchmark or evidence of faster completed walks. [TypeSafe pricing](https://docs.typesafe.ai/models)

An additional actual-controller test on a temporary public toy fixture selected `project_search` with support 1.0 in 0.195 seconds. The returned context was labeled as untrusted data and the fixture remained unchanged. This used the testing-only Jev client and did not enable hosted routing for real work. Evidence: `artifacts/jev-controller-acceptance.json`.
