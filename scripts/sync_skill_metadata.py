#!/usr/bin/env python3
"""Generate each skill's boundary section and tool declaration from the manifest.

A boundary that lives in two places drifts. `config/skill-scopes.yaml` is the one
place: the `afc` launcher enforces it, and this script writes the same facts into
every SKILL.md — the `allowed-tools` frontmatter key a Claude harness reads, and
a generated Scope section stating what the skill may run and what it hands off.

  sync_skill_metadata.py            report what is out of sync (exit 2 if any)
  sync_skill_metadata.py --write    bring the skills into sync

The test suite runs the check, so editing the manifest without regenerating, or
editing a generated block by hand, fails instead of quietly disagreeing with
what the launcher enforces.
"""
from pathlib import Path
import argparse
import difflib
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from afc_card_runtime.config import find_afc_home
from afc_card_runtime.skill_scope import load_scopes

BEGIN = '<!-- afc:scope:begin -->'
END = '<!-- afc:scope:end -->'
GENERATED_BY = 'scripts/sync_skill_metadata.py'


def scope_section(name, skill, scopes):
    own = sorted(set(skill.get('scripts') or []))
    limits = skill.get('subcommands') or {}
    delegates = skill.get('delegates') or []
    lines = [
        BEGIN,
        f'<!-- Generated from config/skill-scopes.yaml by {GENERATED_BY}.',
        '     Edit the manifest, not this block: the `afc` launcher enforces the',
        '     manifest, so a hand-edited copy here would only disagree with it. -->',
        '',
        '## Scope',
        '',
        f'This skill may cause **{skill.get("mutation")}** changes. Set',
        f'`AFC_SKILL={name}` while following it: the `afc` launcher then refuses any',
        'command outside the scope below and names the skill that owns it.',
        '',
        'Commands this skill may run:',
        '',
    ]
    for script in own:
        limit = limits.get(script)
        suffix = f' — only `{", ".join(limit)}`' if limit else ''
        lines.append(f'- `{script}`{suffix}')
    if delegates:
        lines += [
            '',
            'It also runs each step through that step\'s own skill, so it may use their',
            'commands while `AFC_SKILL` names the step being followed: '
            + ', '.join(f'`{d}`' for d in delegates) + '.',
        ]
    out_of_scope = skill.get('out_of_scope') or []
    handoff = skill.get('handoff') or {}
    if out_of_scope:
        lines += ['', 'Not this skill\'s job:', '']
        for item in out_of_scope:
            owner = handoff.get(item, 'another skill')
            # Only a skill name is code; "the user" and the like are prose.
            owner = f'`{owner}`' if re.fullmatch(r'afc-[a-z-]+', owner) else owner
            lines.append(f'- {item} → {owner}')
    lines += [
        '',
        f'`./afc --scope {name}` prints this boundary.',
        END,
    ]
    return '\n'.join(lines) + '\n'


def frontmatter_with_tools(text, skill):
    """Keep `allowed-tools` in the frontmatter equal to the manifest."""
    tools = skill.get('allowed_tools')
    if not tools:
        return text
    rendered = 'allowed-tools: ' + ', '.join(tools)
    match = re.match(r'^---\n(.*?)\n---\n', text, re.DOTALL)
    if not match:
        return text
    body = match.group(1)
    if re.search(r'(?m)^allowed-tools:.*$', body):
        new_body = re.sub(r'(?m)^allowed-tools:.*$', rendered, body)
    else:
        # After description, so name/description stay the first keys a harness reads.
        new_body = body.rstrip('\n') + '\n' + rendered
    return text[:match.start()] + f'---\n{new_body}\n---\n' + text[match.end():]


def rendered(path, name, skill, scopes):
    text = path.read_text(encoding='utf-8')
    text = frontmatter_with_tools(text, skill)
    section = scope_section(name, skill, scopes)
    if BEGIN in text:
        start = text.index(BEGIN)
        end = text.index(END) + len(END)
        return text[:start] + section.rstrip('\n') + text[end:]
    return text.rstrip('\n') + '\n\n' + section


def main():
    ap = argparse.ArgumentParser(
        description='Sync each SKILL.md with config/skill-scopes.yaml.')
    ap.add_argument('--write', action='store_true', help='Rewrite the skills in place')
    ap.add_argument('--root', help='Package root (defaults to the AFC home)')
    a = ap.parse_args()

    root = Path(a.root) if a.root else find_afc_home()
    scopes = load_scopes(home=root)
    skills_dir = root / 'skills'
    if not skills_dir.is_dir():
        print(f'sync_skill_metadata: no skills/ under {root}', file=sys.stderr)
        return 2

    changed, missing = [], []
    for path in sorted(skills_dir.glob('*/SKILL.md')):
        name = path.parent.name
        skill = scopes.skill(name)
        if skill is None:
            missing.append(name)
            continue
        current = path.read_text(encoding='utf-8')
        target = rendered(path, name, skill, scopes)
        if current == target:
            continue
        changed.append(name)
        if a.write:
            path.write_text(target, encoding='utf-8')
        else:
            diff = difflib.unified_diff(current.splitlines(True), target.splitlines(True),
                                        f'{name}/SKILL.md', f'{name}/SKILL.md (from manifest)')
            sys.stdout.writelines(diff)

    declared = set(scopes.skills)
    on_disk = {p.parent.name for p in skills_dir.glob('*/SKILL.md')}
    orphan_entries = sorted(declared - on_disk)

    if missing:
        print(f'skills with no entry in skill-scopes.yaml: {missing}', file=sys.stderr)
    if orphan_entries:
        print(f'manifest entries with no skill: {orphan_entries}', file=sys.stderr)
    if a.write:
        print(f'synced {len(changed)} skill(s): {", ".join(changed) or "none"}')
    elif changed:
        print(f'\nout of sync: {", ".join(changed)}. Run: ./afc sync_skill_metadata.py --write',
              file=sys.stderr)
    else:
        print('every skill matches config/skill-scopes.yaml')
    return 2 if (changed and not a.write) or missing or orphan_entries else 0


if __name__ == '__main__':
    raise SystemExit(main())
