# Local model readiness and memory diagnostics

Dog Walker checks the configured local model endpoint before a worker turn.
`dog_walker.runtime.verify_runtime(model_path, endpoint, emit, cancel=None)`
requires the endpoint's `/props` model path to match the configured model
file and `/health` to report `status: ok`. If health includes slot counts, at
least one slot must be idle. It returns
`ready: true` and `fully_loaded: true` only after both checks pass. The request
timeout is bounded to 0.1–5 seconds (2 seconds by default); proxy settings are
ignored, redirects are rejected, and the endpoint must be plain HTTP on
loopback. A missing, loading, unhealthy, busy, or mismatched service returns
`ready: false`, so the caller can stop before inference.

On Linux, the module finds a process whose command line names both the model
path and endpoint port, then reports that process's `/proc/PID/status` RSS,
swap, and locked-memory values. It also reports system `MemAvailable` and swap
use. These are memory diagnostics, not proof that the runtime placed every
model tensor in physical RAM. A nonzero server `VmSwap` produces a speed warning
but does not make an already healthy and correctly identified server fail
readiness. New service launches can enforce a zero-swap policy separately.

The optional `probe_file_cache(path)` uses Linux `mincore` as a read-only check
of a backing file's page-cache residency. `verify_runtime(...,
include_file_cache=True)` can attach the same measurement for the model and a
unique adjacent `mmproj-*.gguf` projector. The result is explicitly named
`model_file_cache`; it does not describe tensors copied or repacked into the
model server process. No file reads or preloading are used for readiness. This
avoids caching a second 21.7 GB copy of weights when the runtime has repacked
them into its own anonymous process memory.

## Current machine observation

The existing Ornith endpoint reported the configured 35B model at 65,536
context and `/health` returned `ok` with one idle slot. A read-only page-cache
probe of its 21.7 GB GGUF found about 658 MB (3.03%) resident in the file cache.
At the same time the `llama-server` process reported about 24.8 GiB RSS, 713 MiB
`VmSwap`, and zero locked memory; system `MemAvailable` was about 15.0 GiB.
This confirms why file-cache residency and runtime process residency must be
reported separately. The server already performs its default startup warmup;
its pinned help says `--no-warmup` disables that behavior.

The process's `Max locked memory` limit is 8 MiB, far below this model's
working set, so `--mlock` cannot be treated as a way to keep all server pages
resident with the current service limits. The runtime helper does not alter
resource limits, enable swap, change launcher arguments, or restart the model.

## Verification

Tests use a fake loopback OpenAI-compatible server and small temporary model
files. They verify identity, readiness, cancellation, timeout bounds, redirect
rejection, process-memory reporting, and the read-only nature of the optional
file-cache probe:

```sh
.venv/bin/python -m pytest -q tests/test_runtime.py
```

References: Linux [`mincore(2)`](https://www.man7.org/linux/man-pages/man2/mincore.2.html)
reports whether backing pages are resident; Linux [`/proc/meminfo`](https://www.man7.org/linux/man-pages/man5/proc_meminfo.5.html)
defines `MemAvailable`; the [llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
documents startup warmup and model loading options.


## Dog Walk startup policy (2026-10-09)

The app's default launcher is `scripts/model-start.py`. It imports the existing reviewed local-model launcher, retains its shared switch lock and exact Ornith/vision/template/cache arguments, and adds `MemorySwapMax=0` to new service starts. It also defaults dynamic-resolution vision to 64–512 image tokens on this CPU runtime, respecting an explicitly configured maximum in the reviewed profile. The original attachment remains unchanged; the model processes a bounded representation. Fine detail and text recognition may need a closer image crop. It also applies that limit after reusing or waiting for an existing service. The normal server startup warmup remains enabled. An existing service with swapped pages is reported honestly and is never automatically interrupted by the app.

During this authorized upgrade, all desktop, chat and run locks were confirmed idle, then Ornith was reloaded once with the zero-swap policy. Its post-start report showed the expected model, healthy idle slot, about 22.2 GiB RSS, and **zero process VmSwap**. The subsequent real three-turn protected-copy walk passed its checks and final paired-phone review, then reopened without replaying a completed turn. GPU offload was not increased: this machine has a 2 GiB GPU and uses the reviewed CPU runtime. Zero swap is a residency policy, not a benchmark or a claim of complete GPU placement.

Worker and chat readiness now invoke this diagnostic after the configured startup command finishes. Walk event logs record `model_ready` metadata before inference. `artifacts/model-residency.json` contains the local reload observation; later memory use can differ.

After the final optimized vision test, the main process reported about 25.0 GiB RSS and zero VmSwap. Private 384px JPEG inference copies also bound image workload even for projectors that ignore dynamic image-token settings; originals and previews remain unchanged.
