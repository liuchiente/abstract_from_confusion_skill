#!/usr/bin/env python3
"""Decide whether the skill being followed may run a command.

The `afc` launcher calls this before every run when AFC_SKILL is set. It exits
0 when the command is inside that skill's declared scope and 3 with an
explanation naming the owning skill when it is not. With AFC_SKILL unset there
is nothing to enforce, so it exits 0.

`--explain <skill>` prints a skill's declared scope, which is also what the
generated boundary section in its SKILL.md states.
"""
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from afc_card_runtime.skill_scope import ScopeError, load_scopes, subcommand_of

EXIT_OUT_OF_SCOPE = 3


def main():
    ap = argparse.ArgumentParser(
        description="Check a command against the active skill's declared scope.")
    ap.add_argument('--skill', default='', help='Usually $AFC_SKILL; empty means no enforcement')
    ap.add_argument('--script', help='The script about to run, e.g. parse_word.py')
    ap.add_argument('--explain', metavar='SKILL', help='Print this skill\'s declared scope')
    ap.add_argument('--json', action='store_true')
    # The script's own arguments follow a literal `--`. They are opaque payload
    # here, so they are split off before parsing rather than fed to argparse,
    # which would reject the inner command's flags as unknown.
    argv = sys.argv[1:]
    script_args = []
    if '--' in argv:
        cut = argv.index('--')
        argv, script_args = argv[:cut], argv[cut + 1:]
    a = ap.parse_args(argv)
    a.args = script_args
    scopes = load_scopes()

    if a.explain:
        skill = scopes.skill(a.explain)
        if skill is None:
            print(f'check_skill_scope: unknown skill: {a.explain}', file=sys.stderr)
            return 2
        allowed = sorted(scopes.allowed_scripts(a.explain) or [])
        out = {
            'skill': a.explain,
            'mutation': skill.get('mutation'),
            'scripts': allowed,
            'subcommands': skill.get('subcommands') or {},
            'delegates': skill.get('delegates') or [],
            'out_of_scope': skill.get('out_of_scope') or [],
            'handoff': skill.get('handoff') or {},
            'declared_in': str(scopes.path) if scopes.path else None,
        }
        print(json.dumps(out, ensure_ascii=False, indent=2) if a.json
              else '\n'.join([f'{a.explain}: may cause {out["mutation"]} changes',
                              '  scripts: ' + ', '.join(allowed),
                              *(f'  not its job: {x}  -> {out["handoff"].get(x, "another skill")}'
                                for x in out['out_of_scope'])]))
        return 0

    if not a.skill:
        return 0
    if not a.script:
        ap.error('--script is required unless --explain is used')
    try:
        scopes.check(a.skill, a.script, subcommand_of(a.script, a.args, scopes))
    except ScopeError as exc:
        print(f'afc: out of scope for {a.skill}.\n  {exc}', file=sys.stderr)
        return EXIT_OUT_OF_SCOPE
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
