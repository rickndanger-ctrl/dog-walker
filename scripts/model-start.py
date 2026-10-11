#!/usr/bin/env python3
"""Start a reviewed local main-model runtime with model swap disabled.

Uses the existing launcher and shared switch lock. Reuses a healthy server;
never restarts it automatically or touches its model/vision/template settings.
"""
import fcntl
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

LAUNCHER = Path.home() / 'opt/local-model-runtime/launcher.py'


def no_swap_plan(plan):
    """Add a per-service cgroup policy, preserving every inference argument."""
    result = {**plan, 'start_argv': list(plan['start_argv'])}
    index = result['start_argv'].index('--')
    result['start_argv'].insert(index, '--property=MemorySwapMax=0')
    return result



def vision_plan(plan):
    """Bound CPU vision work unless the reviewed profile already sets a limit."""
    options = {arg.split("=", 1)[0] for arg in plan["server_argv"]}
    if "--image-max-tokens" in options:
        return plan
    extra = ["--image-max-tokens", "512"]
    if "--image-min-tokens" not in options:
        extra += ["--image-min-tokens", "64"]
    return {**plan, "server_argv": [*plan["server_argv"], *extra],
            "start_argv": [*plan["start_argv"], *extra]}

def arguments(argv=None):
    parser = argparse.ArgumentParser(description="Load one reviewed local main model, reusing an idle healthy server.")
    parser.add_argument('--model', choices=('ornith', 'gemma', 'qwen'), default='ornith')
    parser.add_argument('--dry-run', action='store_true')
    return parser.parse_args(argv)


def main():
    args = arguments()
    spec = importlib.util.spec_from_file_location('dogwalk_reviewed_launcher', LAUNCHER)
    if spec is None or spec.loader is None:
        raise RuntimeError('The reviewed local model launcher is missing')
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    plan = vision_plan(no_swap_plan(runtime.build_plan(args.model)))
    if args.dry_run:
        print(json.dumps(plan, indent=2))
        return 0
    lock = Path(os.environ.get('XDG_RUNTIME_DIR', '/tmp')) / f'local-ai-model-switch-{os.getuid()}.lock'
    with lock.open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        runtime.launch(plan)
        # Apply to every reuse, including a service that was still warming.
        # This does not bring previously swapped pages back; diagnostics report
        # those pages separately rather than silently restarting another client.
        result = subprocess.run(['systemctl', '--user', 'set-property', '--runtime',
                                 plan['unit'], 'MemorySwapMax=0'], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError('Could not apply the model no-swap policy: ' + result.stderr.strip())
    print('Local model loaded; warmup is enabled and service swap limit is zero.', flush=True)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(f'Handler model startup: {exc}', file=sys.stderr)
        sys.exit(1)
