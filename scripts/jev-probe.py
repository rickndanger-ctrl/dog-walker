#!/usr/bin/env python3
"""Optionally probe Jev with synthetic, public routing examples only."""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dog_walker.jev import (INPUT_COST_PER_MILLION, MODEL_ID, JevJudge,
                            estimate_input_tokens, has_key)

CRITERIA = {
    "project_map": "Inspect a bounded project file map.",
    "project_search": "Search one explicitly named filename.",
    "none": "Do not add project context.",
}
PROBES = (
    ("A public toy app needs its startup file located.", "project_map"),
    ("A public toy app asks to find the file `widget.py`.", "project_search"),
    ("A public toy app asks a general greeting with no file context needed.", "none"),
)


def arguments(argv=None):
    parser = argparse.ArgumentParser(description="Send three synthetic public routing probes to Jev.")
    parser.add_argument("--run", action="store_true", help="make the three real HTTPS requests")
    return parser.parse_args(argv)


def confidence(answer, choice):
    if choice not in CRITERIA:
        return None
    route = answer.get("answers", {}).get("route", {})
    probabilities = route.get("probabilities", {})
    if isinstance(probabilities, dict):
        value = probabilities.get(choice)
    elif isinstance(probabilities, list):
        value = probabilities[list(CRITERIA).index(choice)] if len(probabilities) == len(CRITERIA) else None
    else:
        value = None
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def main(argv=None):
    args = arguments(argv)
    if not args.run:
        print("No request sent. Pass --run to send three synthetic public toy tasks.")
        return 0
    try:
        if not has_key():
            print("No Jev API key is available; no request sent.", file=sys.stderr)
            return 1
        # This bypass is limited to the explicitly invoked probe, whose three
        # payloads below are synthetic public examples rather than task text.
        judge = JevJudge(test_only=True)
        reports = []
        for task, expected in PROBES:
            state = {"task_data": task}
            questions = {"route": {"type": "choice", "instructions":
                "Choose the best optional read-only context decision for this synthetic public toy task.",
                "criteria": CRITERIA}}
            estimated_tokens = estimate_input_tokens(state, questions)
            started = time.monotonic()
            answer = judge.decide(state, questions)
            elapsed = time.monotonic() - started
            route = answer.get("answers", {}).get("route", {})
            choice = route.get("choice") if route.get("choice") in CRITERIA else "unknown"
            input_tokens = answer.get("usage", {}).get("input_tokens") or answer.get("usage", {}).get("prompt_tokens")
            token_source = "api" if isinstance(input_tokens, int) and not isinstance(input_tokens, bool) else "estimate"
            if token_source == "estimate":
                input_tokens = estimated_tokens
            reports.append({"expected": expected, "choice": choice, "confidence": confidence(answer, choice),
                            "elapsed_seconds": round(elapsed, 3), "input_tokens": input_tokens,
                            "input_tokens_source": token_source,
                            "estimated_input_cost_usd": round(input_tokens * INPUT_COST_PER_MILLION / 1_000_000, 9)})
        print(json.dumps({"model": MODEL_ID, "probes": reports,
                          "estimated_input_cost_total_usd": round(
                              sum(row["estimated_input_cost_usd"] for row in reports), 9),
                          "output_cost_usd": 0}, indent=2))
        return 0
    except Exception:
        # Do not print provider errors, response bodies, request data, or credentials.
        print("Jev probe failed; response details are hidden and no request data was logged.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
