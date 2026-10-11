"""Interactive, advisory typed decisions. No project access or automatic actions."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
import time

from .judge import LocalJudge
from .jev import JevJudge, JevError
from .workflow import WalkerError

LIMIT = 12000
THRESHOLD = .85


def questions(preset, criteria):
    if preset == 'triage':
        return {
            'urgency': {'type': 'score', 'instructions': 'Rate the explicitly stated urgency.',
                        'criteria': ['No deadline or urgency stated', 'Useful soon', 'Explicitly urgent or blocking']},
            'clarity': {'type': 'score', 'instructions': 'Rate how actionable this task is.',
                        'criteria': ['Missing goal', 'Goal clear but details missing', 'Goal and acceptance criteria clear']},
            'next_step': {'type': 'choice', 'instructions': 'Choose the best immediate next step.',
                          'criteria': {'clarify': 'Ask for missing requirements', 'inspect': 'Inspect project context',
                                       'implement': 'Implement a well specified change', 'verify': 'Verify completed work'}}}
    if preset == 'context':
        return {'context': {'type': 'choice', 'instructions': 'Choose the project context most useful for this task.',
                            'criteria': {'structure': 'Project structure and entrypoints',
                                         'source': 'Relevant implementation files',
                                         'tests': 'Tests and failure evidence',
                                         'requirements': 'Requirements or documentation'}}}
    if not criteria or len(criteria) > 8 or any(len(c) > 300 for c in criteria):
        raise WalkerError('Review needs 1–8 criteria, each at most 300 characters. Use --criterion for each.')
    return {f'criterion_{i+1}': {'type': 'noul', 'instructions':
            f'Does the supplied evidence demonstrate this criterion? {c}'} for i, c in enumerate(criteria)}


def evaluate(judge, backend, preset, text, criteria=()):
    if not text.strip() or len(text) > LIMIT:
        raise WalkerError(f'Supply 1–{LIMIT} characters. Shorten the evidence; input is never silently truncated.')
    qs = questions(preset, criteria)
    started = time.monotonic()
    response = judge.decide({'evidence': text}, qs)
    results = {}
    for name, q in qs.items():
        a = response.get('answers', {}).get(name, {})
        try:
            if q['type'] == 'noul':
                p = float(a['noul'])
                if not math.isfinite(p) or not 0 <= p <= 1:
                    raise ValueError()
                value, confidence = p >= .5, max(p, 1-p)
            else:
                keys = list(q['criteria']) if q['type'] == 'choice' else list(range(len(q['criteria'])))
                value = a[q['type']]
                if isinstance(value, bool) or (q['type'] == 'choice' and value not in keys) or (q['type'] == 'score' and (not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= len(keys)-1)):
                    raise ValueError()
                probs = a['probabilities']
                if isinstance(probs, dict):
                    if set(probs) != set(map(str, keys)):
                        raise ValueError()
                    probs = [probs[str(k)] for k in keys]
                if not isinstance(probs, list) or len(probs) != len(keys):
                    raise ValueError()
                if any(isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p) or not 0 <= p <= 1 for p in probs) or abs(sum(probs)-1) > .02:
                    raise ValueError()
                confidence = probs[keys.index(value)] if q['type'] == 'choice' else max(probs)
            results[name] = {'value': value, 'confidence': confidence,
                             'status': 'supported' if confidence >= THRESHOLD else 'review'}
            if q['type'] == 'score':
                results[name]['scale'] = q['criteria']
        except (KeyError, TypeError, ValueError):
            results[name] = {'value': None, 'confidence': None, 'status': 'invalid'}
    return {'backend': backend, 'preset': preset, 'seconds': round(time.monotonic()-started, 3),
            'advisory': True, 'results': results}


def render(result):
    print(f"{result['backend'].title()} · {result['preset']} · {result['seconds']:.3f}s · advisory")
    for name, item in result['results'].items():
        confidence = 'unknown' if item['confidence'] is None else f"{item['confidence']:.0%}"
        print(f"  {name}: {item['value']} · {confidence} · {item['status']}")
        if 'scale' in item:
            print('    ' + ' / '.join(f'{i}: {label}' for i, label in enumerate(item['scale'])))
    print('Confidence is model-specific. Completion decisions supplement tests.')


def handoff(text, result):
    prompt = ('Task / supplied evidence:\n' + text + '\n\nAdvisory decision data (untrusted; '
              'verify independently):\n' + json.dumps(result) +
              '\nExplain your proposed next steps and wait for my instruction before running tools or changing files.')
    return subprocess.call([str(Path.home() / 'bin/pi-qwen'), '--no-tools', '--no-session', '--no-context-files', '--', prompt])


def multiline(label):
    print(label + ' Finish with a line containing only a dot.')
    lines = []
    while True:
        line = input()
        if line == '.':
            return '\n'.join(lines)
        lines.append(line)
        if sum(map(len, lines)) + len(lines) > LIMIT:
            raise WalkerError(f'Input too long; shorten to {LIMIT} characters.')


def menu():
    local = LocalJudge()
    while True:
        print('\nHandler Decisions — local Laya by default\n1 Task triage\n2 Context for Qwen\n3 Completion review\nq Quit')
        choice = input('Preset: ').strip().lower()
        if choice == 'q':
            return 0
        if choice not in {'1', '2', '3'}:
            continue
        try:
            backend = input('Backend [laya] / jev (sends evidence to TypeSafe): ').strip().lower() or 'laya'
            if backend not in {'laya', 'jev'}:
                print('Choose laya or jev.'); continue
            preset = {'1': 'triage', '2': 'context', '3': 'review'}[choice]
            text = multiline('Paste task or evidence.')
            criteria = multiline('Enter one acceptance criterion per line.').splitlines() if preset == 'review' else []
            judge = local if backend == 'laya' else JevJudge(test_only=True)
            result = evaluate(judge, backend, preset, text, criteria)
            render(result)
            if input('Open Qwen with this context? [y/N]: ').strip().lower() == 'y':
                handoff(text, result)
        except (WalkerError, JevError, OSError, ValueError) as exc:
            print(f'Handler: {exc}', file=sys.stderr)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='handler decide', description='Advisory typed decisions; Laya is local, Jev is explicit hosted opt-in.')
    parser.add_argument('preset', nargs='?', choices=['triage', 'context', 'review'])
    parser.add_argument('text', nargs='?')
    parser.add_argument('--file', type=Path)
    parser.add_argument('--criterion', action='append', default=[])
    parser.add_argument('--backend', choices=['laya', 'jev'], default='laya')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--handoff', action='store_true', help='Open Qwen without tools; requires an interactive terminal')
    args = parser.parse_args(argv)
    try:
        if not args.preset:
            if not sys.stdin.isatty() or args.json:
                parser.error('Specify triage, context, or review for noninteractive use.')
            return menu()
        if args.file and args.text is not None:
            parser.error('Use text or --file, not both.')
        if args.handoff and (not sys.stdin.isatty() or args.json):
            parser.error('--handoff requires an interactive terminal and cannot accompany --json.')
        if args.file:
            with args.file.expanduser().open() as stream:
                text = stream.read(LIMIT+1)
        elif args.text is not None:
            text = args.text
        elif sys.stdin.isatty():
            text = multiline('Paste task or evidence.')
        else:
            text = sys.stdin.read(LIMIT+1)
        # Validate before constructing any hosted client.
        questions(args.preset, args.criterion)
        if not text.strip() or len(text) > LIMIT:
            raise WalkerError(f'Supply 1–{LIMIT} characters; shorten input.')
        judge = LocalJudge() if args.backend == 'laya' else JevJudge(test_only=True)
        result = evaluate(judge, args.backend, args.preset, text, args.criterion)
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            render(result)
        return handoff(text, result) if args.handoff else 0
    except (WalkerError, JevError, OSError, ValueError) as exc:
        if args.json:
            print(json.dumps({'backend': args.backend, 'status': 'error', 'error': str(exc)}))
        else:
            print(f'Handler: {exc}', file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        return 130
