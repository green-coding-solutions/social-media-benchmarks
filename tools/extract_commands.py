#!/usr/bin/env python3
"""Extracts the playwright commands from a usage scenario, in flow order, as JSON.

Feeds tools/run_locally.js, which replays them against a live browser so a scenario can
be checked without waiting on a full GMT measurement run.

Non-secret GMT variables can be substituted on the way through, since the scenario is
still a template at this point:

Usage: python3 tools/extract_commands.py usage_scenario_x_smoke.yml [__GMT_VAR_X__=value ...]
"""
import json
import sys
from pathlib import Path

import yaml


def main():
    path = Path(sys.argv[1])
    text = path.read_text()
    for pair in sys.argv[2:]:
        key, _, value = pair.partition('=')
        text = text.replace(key, value)

    loader = yaml.SafeLoader
    for tag in ('!include-gmt-helper', '!include'):
        loader.add_constructor(tag, lambda l, n: {})
    doc = yaml.load(text, Loader=loader)

    out = []
    for step in doc.get('flow', []):
        for i, cmd in enumerate(step.get('commands', [])):
            if cmd['type'] == 'playwright':
                out.append({'step': step['name'], 'idx': i, 'js': cmd['command'].strip()})
            elif cmd['command'].strip().startswith('sleep '):
                out.append({'step': step['name'], 'idx': i, 'sleep': int(cmd['command'].split()[1])})
    json.dump(out, sys.stdout)


if __name__ == '__main__':
    main()
