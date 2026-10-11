# Small coder removed

Rick requested removal on 2026-10-09. Dog Walk no longer lists or executes the
`local-coder` adapter. Its broker integration, startup/probe utilities, and
Qwen2.5-Coder 1.5B model file have been removed. The separate transient service
is inactive; no persistent service was installed.

Historical grants and reports remain readable for audit. They cannot expose
`local_coder_suggest` or start a helper. New plans requesting the retired adapter
must remove it before starting. The historical paired pilot remains in
[BENCHMARK.md](BENCHMARK.md) and `verification/helper-pilot.json`.

Ornith and Gemma remain separate main-model choices. Local Laya is retained for
bounded decisions and advisory tool recommendations. See
[model and speed guidance](MODEL_STRATEGY.md).
