# Historical helper benchmark

This page records the design and results of a preliminary pilot that compared
six small coding tasks with the main worker alone and with the local coder
adviser enabled. The optional local coder has since been retired, so the live
benchmark is disabled. Existing pilot results remain available for review.

The task set covers a bug fix, boundary behavior, a multi-file change, a
regression test, repository navigation, and a behavior-preserving refactor. Each
task runs twice against fresh copies of the same fixture. Condition order
alternates by task. Both conditions use Dog Walker's regular Engine and
controller checks, a four-turn total, and a ten-minute trial cap. The visible
baseline test runs inside each walk; exact allowed-file scope is checked by the
Engine. Separate controller-only acceptance checks are kept outside the trial
workspaces.

Create the historical disposable fixtures and workflows without contacting a
model:

```bash
python scripts/benchmark-pilot.py --dry-run --output /tmp/dog-walker-pilot
```

The live `--run` and `--run --resume` modes now stop with a clear message before
contacting either model. `--dry-run` remains available for reviewing the
disposable fixtures.

The historical report separates passing code/scope checks from completed-and-
correct walks, then shows median time, total pilot time, and peak sampled memory
in GiB. A repair can pass its checks while the walk pauses for a malformed
completion response. Review reasons make that distinction explicit. It also
lists each outcome, turn count, helper calls and errors, memory samples, and
token use when the worker event stream supplies it. Missing token counts stay
`null`. Sampling can miss short peaks. Results are preliminary and need
repeated runs before a product decision.

The 2026-10-09 pilot completed 12 walks. Main-only completed 5/6 correctly;
helper-enabled completed 4/6 correctly, although its repairs passed all six
code/scope checks. The helper was actually called in four of its six walks,
with three successful suggestions and one timeout. See
[recorded results](verification/helper-pilot.json) and `VERIFICATION.md` for
timing, memory and interpretation limits.
