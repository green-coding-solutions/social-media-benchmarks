#!/usr/bin/env python3
"""Static checks for the usage scenarios in this repo.

Three failure modes here only show up at measurement time, minutes into a run, which
is an expensive way to find a typo. So we check them up front:

1. Single quotes in a `type: playwright` command. GMT ships those commands through
   `bash -ec "echo '<command>' > /tmp/playwright-ipc-commands"` (lib/scenario_runner.py),
   and a single quote terminates that shell quote and corrupts whatever reaches the browser.
2. The shell round trip itself: run the real `bash -ec "echo ..."` and confirm what comes
   out the far end is byte-identical to what went in, after the .trim() the IPC applies.
3. JS syntax, parsed in exactly the `(async () => { ... })()` wrapper the IPC evals.
4. Hostile credentials. GMT substitutes __GMT_VAR_*__ into the file as raw text *before*
   the YAML is parsed, so a password starting with @ or %, or containing a quote or a
   colon, is a YAML syntax error rather than a password. We substitute deliberately nasty
   values and assert they survive the parse byte for byte.

Plus the ordinary structural checks: GMT's flow-name pattern, unique step names, and
custom_metrics declarations matching the gmtNote() calls that emit them.

Run:  python3 validate_scenarios.py
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
# GMT's own pattern for a flow name, from lib/schema_checker.py
FLOW_NAME_RE = re.compile(r'^[\.\s0-9a-zA-Z_\(\)-]+$')
GMT_VAR_RE = re.compile(r'__GMT_VAR_\w+__')
NOTE_RE = re.compile(r'gmtNote\(\s*"([A-Za-z0-9_-]+)"')

SYNTAX_JS = """
const cmds = require(process.argv[2]);
let fails = 0;
for (const c of cmds) {
  try { new Function(`return (async () => { ${c.js} })()`); }
  catch (e) { fails++; console.log(`  ${c.file} [${c.step}] #${c.idx}: ${e.message}`); }
}
process.exit(fails ? 1 : 0);
"""


# Every YAML indicator character that has bitten a config file at some point, plus a
# leading @ (the shape of an X handle) and a bare integer.
HOSTILE = [
    "@Handle1985",
    "%pass!word#with:colons",
    "a-b\"c\\d $e {f} [g] ,h",
    "*anchor &ref !tag >fold |pipe",
    "- leading dash",
    "12345",
]


def credential_round_trip(path):
    """Substitute nasty credentials the way GMT does and check they survive the parse."""
    text = path.read_text()
    variables = sorted(set(GMT_VAR_RE.findall(text)))
    mapping = {v: HOSTILE[i % len(HOSTILE)] for i, v in enumerate(variables)}

    substituted = text
    for var, value in mapping.items():
        substituted = substituted.replace(var, value)

    loader = yaml.SafeLoader
    for tag in ('!include-gmt-helper', '!include'):
        loader.add_constructor(tag, lambda l, n: {})
    try:
        doc = yaml.load(substituted, Loader=loader)
    except yaml.YAMLError as exc:
        detail = str(exc).replace('\n', ' ')
        return [f'a credential broke the YAML parse: {detail}']

    env = doc.get('services', {}).get('gmt-playwright-nodejs', {}).get('environment', {})
    errors = []
    for key, got in env.items():
        expected = [v for var, v in mapping.items() if v == got]
        if not isinstance(got, str):
            errors.append(f'env var {key} parsed as {type(got).__name__}, not str: {got!r}')
        elif not expected:
            errors.append(f'env var {key} was mangled: got {got!r}, expected one of {list(mapping.values())}')
    if not env:
        errors.append('no environment block found on gmt-playwright-nodejs')
    return errors


def browser_mode(path):
    """Smoke scenarios are headful for debugging; measurement scenarios are headless."""
    text = path.read_text()
    smoke = path.stem.endswith('_smoke')
    want_launch = '--headless false' if smoke else '--headless true'
    want_helper = ('gmt-playwright-headful-with-cache.yml' if smoke
                   else 'gmt-playwright-with-cache.yml')
    errors = []
    if want_launch not in text:
        errors.append(f'expected the IPC to launch with {want_launch}')
    if f'!include-gmt-helper {want_helper}' not in text:
        errors.append(f'expected compose-file to include {want_helper}')
    return errors


def load(path):
    loader = yaml.SafeLoader
    for tag in ('!include-gmt-helper', '!include'):
        loader.add_constructor(tag, lambda l, n: {})
    return yaml.load(path.read_text(), Loader=loader)


def check(path, collected):
    errors = []
    doc = load(path)

    declared = set(doc.get('custom_metrics', {}))
    emitted = set()
    seen = set()

    for step in doc.get('flow', []) + doc.get('flow-prepend', []):
        name = step['name']
        if not FLOW_NAME_RE.fullmatch(name):
            errors.append(f"flow name {name!r} does not match GMT's allowed pattern")
        if name in seen:
            errors.append(f"duplicate flow name {name!r}")
        seen.add(name)

        for i, cmd in enumerate(step.get('commands', [])):
            if cmd['type'] != 'playwright':
                continue
            body = cmd['command']
            emitted |= set(NOTE_RE.findall(body))

            if "'" in body:
                bad = [l.strip() for l in body.splitlines() if "'" in l]
                errors.append(f"[{name}] playwright command #{i} contains a single quote: {bad}")
                continue

            shell = cmd.get('shell', 'sh')
            escaped = body.replace("'", "\\'")
            out = subprocess.run([shell, '-ec', f"echo '{escaped}' > /dev/stdout"],
                                 capture_output=True, text=True, check=False)
            if out.returncode != 0:
                errors.append(f"[{name}] command #{i} broke the shell round trip: {out.stderr.strip()}")
            elif out.stdout.strip() != body.strip():
                errors.append(f"[{name}] command #{i} was mangled by the shell round trip")
            else:
                collected.append({'file': path.name, 'step': name, 'idx': i, 'js': out.stdout.strip()})

    for metric in sorted(emitted - declared):
        errors.append(f"gmtNote() emits {metric!r} but it is not declared under custom_metrics")
    for metric in sorted(declared - emitted):
        errors.append(f"custom_metric {metric!r} is declared but never emitted")

    errors.extend(credential_round_trip(path))
    errors.extend(browser_mode(path))

    variables = sorted(set(GMT_VAR_RE.findall(path.read_text())))
    return errors, variables, len(doc.get('flow', []))


def syntax_check(collected):
    """Parse every command the way gmt-playwright-ipc.js evals it."""
    if not shutil.which('node'):
        print('note: node not found, skipping the JS syntax pass')
        return []
    with tempfile.TemporaryDirectory() as tmp:
        cmds = Path(tmp) / 'cmds.json'
        script = Path(tmp) / 'syntax.js'
        cmds.write_text(json.dumps(collected))
        script.write_text(SYNTAX_JS)
        out = subprocess.run(['node', str(script), str(cmds)],
                             capture_output=True, text=True, check=False)
        return [l for l in out.stdout.splitlines() if l.strip()]


def main():
    files = sorted(ROOT.glob('usage_scenario_*.yml'))
    if not files:
        print('no usage scenarios found')
        return 1

    collected = []
    failed = False
    for path in files:
        errors, variables, steps = check(path, collected)
        print(f"{'FAIL' if errors else '  ok':>4}  {path.name}  ({steps} steps)  "
              f"vars: {', '.join(variables) or '-'}")
        for e in errors:
            failed = True
            print(f"        {e}")

    problems = syntax_check(collected)
    if problems:
        failed = True
        print('FAIL  javascript syntax')
        for p in problems:
            print(p)
    else:
        print(f"  ok  shell round trip and JS syntax ({len(collected)} playwright commands)")

    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
