# 0.2.0 · Native desktop preview

- Native Quickshell/QML desktop with job import, readable plan preview, project chooser, progress, review controls, saved walks, and inbox.
- Official single-file `.dogwalk` form, agent handoff, JSON Schema, completed example, bounded retries, and literal-dollar prompts.
- Application-menu launcher, icon, double-click file association, singleton window, and optional Omarchy bar-launcher prototype.
- Machine-local model settings accepting only loopback HTTP endpoints. The model, launcher, and Codex catalog are configurable rather than tied to one user's absolute paths.
- MIT-licensed source. No bundled weights, cloud API, or Jev adapter.
- A single Markdown-fenced worker result is accepted with the same strict JSON Schema and independent checks; ambiguous or incomplete results still pause.
- Terminal resume mode changes respect run locks.

This is a source-install preview for the current Quickshell-based Omarchy environment. It is not an official Omarchy package or a universal local-model connector. The first tested worker is Ornith via a patched local llama.cpp Responses API and Codex CLI. Models without a compatible tool-calling/Responses endpoint have not been verified.

Existing engine offline acceptance remains documented in `VERIFICATION.md`. Desktop additions are covered by deterministic bridge tests and an actual offscreen QML import/render smoke test. A fresh real-model job through the desktop has not yet been completed; it is a remaining integration acceptance item, not an automated-test claim. The conservative local semantic judge may require frequent human review.
