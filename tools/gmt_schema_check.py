#!/usr/bin/env python3
"""Validates the scenarios against GMT's own SchemaChecker, before a run.

validate_scenarios.py checks what this repo controls. This checks what GMT will accept:
it resolves the !include-gmt-helper partial, reproduces the compose-file merge and
flow-prepend handling from lib/scenario_runner.py, substitutes credential-shaped values,
and then runs the real schema checker over the result.

Usage: GMT_DIR=/path/to/green-metrics-tool python3 tools/gmt_schema_check.py
"""
import os
import re
import sys
from pathlib import Path

import yaml

GMT = Path(os.environ.get('GMT_DIR', Path.home() / 'code/green-metrics-tool'))
sys.path.insert(0, str(GMT))
ROOT = Path(__file__).parent.parent

# Deliberately awkward values: a leading @ and a password full of YAML indicators, since
# GMT substitutes these into the file as raw text before it is parsed.
VARS = {
    '__GMT_VAR_SECRET_USERNAME__': '@Handle1985',
    # Synthetic, but the same shape as a generated password: YAML indicators throughout.
    '__GMT_VAR_SECRET_PASSWORD__': '%pass!word#with:colons-and@at',
    '__GMT_VAR_INSTANCE__': 'mastodon.social',
    # LinkedIn cannot be logged into unattended - see README. This is the li_at cookie.
    '__GMT_VAR_SECRET_SESSION__': 'AQEDAT-fake-session-value-for-schema-check-only',
}


def make_loader():
    class Loader(yaml.SafeLoader):
        pass

    def helper(loader, node):
        name = loader.construct_scalar(node)
        if not re.fullmatch(r'gmt-playwright(?:-headful)?(?:-with-cache)?\.yml', name):
            raise ValueError(f'GMT would reject this include: {name}')
        return yaml.load((GMT / 'templates/partials' / name).read_text(), make_loader())

    Loader.add_constructor('!include-gmt-helper', helper)
    return Loader


def merge_dicts(d1, d2):
    """Mirrors lib/scenario_runner.py."""
    if isinstance(d1, dict):
        for k, v in d2.items():
            if k in d1 and isinstance(v, dict) and isinstance(d1[k], dict):
                merge_dicts(d1[k], v)
            else:
                d1[k] = v
        return d1
    return d2


def main():
    from lib.schema_checker import SchemaChecker

    failed = False
    for path in sorted(ROOT.glob('usage_scenario_*.yml')):
        text = path.read_text()
        for key, value in VARS.items():
            text = text.replace(key, value)
        if left := re.findall(r'^(?![\s]*#).*__GMT_VAR_\w+__', text, re.MULTILINE):
            print(f'FAIL {path.name}: unreplaced {left}')
            failed = True
            continue

        obj = yaml.load(text, make_loader())
        new_dict = {}
        for k, v in obj['compose-file'].items():
            if k in obj:
                new_dict[k] = merge_dicts(v, obj[k])
            else:
                obj[k] = v
        del obj['compose-file']
        obj.update(new_dict)
        obj['flow-prepend'].extend(obj['flow'])
        obj['flow'] = obj['flow-prepend']
        del obj['flow-prepend']

        try:
            SchemaChecker(validate_compose_flag=True).check_usage_scenario(obj)
        except Exception as exc:  # noqa: BLE001 - surface whatever GMT objects to
            print(f'FAIL {path.name}: {exc}')
            failed = True
            continue

        env = obj['services']['gmt-playwright-nodejs']['environment']
        launch = next(c['command'] for f in obj['flow']
                      for c in f.get('commands', []) if 'gmt-playwright-ipc.js' in c['command'])
        smoke = path.stem.endswith('_smoke')
        problems = []
        if env.get('GMT_SM_USERNAME') != VARS['__GMT_VAR_SECRET_USERNAME__']:
            problems.append(f'username mangled: {env.get("GMT_SM_USERNAME")!r}')
        if env.get('GMT_SM_PASSWORD') != VARS['__GMT_VAR_SECRET_PASSWORD__']:
            problems.append(f'password mangled: {env.get("GMT_SM_PASSWORD")!r}')
        if ('--headless false' if smoke else '--headless true') not in launch:
            problems.append('wrong headless mode for this profile')
        if smoke and '/tmp/.X11-unix:/tmp/.X11-unix' not in obj['services']['gmt-playwright-nodejs'].get('volumes', []):
            problems.append('smoke scenario is missing the X11 mount')
        if problems:
            failed = True
            print(f'FAIL {path.name}: {"; ".join(problems)}')
        else:
            mode = 'headful' if smoke else 'headless'
            print(f'  ok {path.name}: {len(obj["flow"])} steps, {mode}, credentials intact')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
