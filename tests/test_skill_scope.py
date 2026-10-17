"""A skill must not do the next step's work.

Every SKILL.md ended with a boundary written as prose addressed to a model, and
a skill that drifted across it (afc-query rebuilding an index, afc-discuss
publishing, afc-validate repairing what it inspected) produced a plausible
result with no trace of the step it skipped. config/skill-scopes.yaml turns that
boundary into a declaration the `afc` launcher enforces; these tests keep the
declaration, the enforcement and what each SKILL.md documents in agreement.
"""
from pathlib import Path
import json
import os
import re
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from afc_card_runtime.skill_scope import ScopeError, load_scopes, subcommand_of  # noqa: E402

SCOPES = load_scopes(home=ROOT)
IS_SOURCE_TREE = (ROOT / 'skills').is_dir()
source_only = pytest.mark.skipif(not IS_SOURCE_TREE, reason='package-source layout only')


def skill_dirs():
    return sorted(p for p in (ROOT / 'skills').glob('*') if (p / 'SKILL.md').is_file()) \
        if IS_SOURCE_TREE else []


def documented_commands(skill_dir):
    """(script, subcommand) for every ./afc call in a skill and its references."""
    files = [skill_dir / 'SKILL.md', *sorted(skill_dir.glob('references/*.md'))]
    found = set()
    for path in files:
        text = path.read_text(encoding='utf-8')
        for block in re.findall(r'```bash\n(.*?)```', text, re.S):
            for line in block.replace('\\\n', ' ').splitlines():
                match = re.search(r'\./afc\s+([a-z0-9_]+\.py)\s*(.*)$', line)
                if not match:
                    continue
                args = [a for a in match.group(2).split() if a != '\\']
                found.add((match.group(1), subcommand_of(match.group(1), args, SCOPES)))
    return found


# --- the manifest covers the package -------------------------------------

@source_only
def test_every_skill_has_a_declared_scope():
    declared = set(SCOPES.skills)
    on_disk = {p.name for p in skill_dirs()}
    assert on_disk - declared == set(), (
        f'skills with no entry in config/skill-scopes.yaml: {sorted(on_disk - declared)}. '
        'An undeclared skill is unenforced.')
    assert declared - on_disk == set(), (
        f'manifest entries with no skill: {sorted(declared - on_disk)}')


@source_only
def test_every_script_has_a_declared_change_class():
    on_disk = {p.name for p in (ROOT / 'scripts').glob('*.py')}
    undeclared = sorted(on_disk - set(SCOPES.scripts))
    assert not undeclared, (
        f'scripts with no change class in config/skill-scopes.yaml: {undeclared}. '
        'Without one the launcher cannot tell whether a skill may run it.')


@source_only
@pytest.mark.parametrize('skill_dir', skill_dirs(), ids=lambda p: p.name)
def test_a_skill_documents_only_commands_inside_its_own_scope(skill_dir):
    name = skill_dir.name
    violations = []
    for script, subcommand in sorted(documented_commands(skill_dir)):
        try:
            SCOPES.check(name, script, subcommand)
        except ScopeError as exc:
            violations.append(f'{script} {subcommand or ""}'.strip() + f' — {exc}')
    assert not violations, (
        f'{name}/SKILL.md documents commands outside its declared scope:\n  '
        + '\n  '.join(violations)
        + '\n\nEither the skill is reaching into another step, or the manifest is '
          'missing something the skill legitimately owns. Fix whichever is wrong.')


@source_only
@pytest.mark.parametrize('skill_dir', skill_dirs(), ids=lambda p: p.name)
def test_the_generated_boundary_matches_the_manifest(skill_dir):
    text = (skill_dir / 'SKILL.md').read_text(encoding='utf-8')
    assert '<!-- afc:scope:begin -->' in text, (
        f'{skill_dir.name}/SKILL.md has no generated Scope section; run '
        './afc sync_skill_metadata.py --write')
    skill = SCOPES.skill(skill_dir.name)
    assert f'AFC_SKILL={skill_dir.name}' in text
    assert f'may cause **{skill["mutation"]}** changes' in text
    for item in skill.get('out_of_scope') or []:
        assert item in text, f'{skill_dir.name} does not state its boundary: {item!r}'


@source_only
def test_the_skills_are_in_sync_with_the_manifest():
    proc = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'sync_skill_metadata.py'),
                           '--root', str(ROOT)],
                          capture_output=True, text=True, cwd=ROOT)
    assert proc.returncode == 0, (
        'skills disagree with config/skill-scopes.yaml. Run '
        './afc sync_skill_metadata.py --write\n' + proc.stdout + proc.stderr)


@source_only
@pytest.mark.parametrize('skill_dir', skill_dirs(), ids=lambda p: p.name)
def test_allowed_tools_match_the_manifest(skill_dir):
    skill = SCOPES.skill(skill_dir.name)
    declared = skill.get('allowed_tools')
    assert declared, f'{skill_dir.name} declares no allowed_tools'
    head = (skill_dir / 'SKILL.md').read_text(encoding='utf-8').split('---')[1]
    line = re.search(r'(?m)^allowed-tools:\s*(.+)$', head)
    assert line, f'{skill_dir.name}/SKILL.md frontmatter has no allowed-tools'
    assert [t.strip() for t in line.group(1).split(',')] == list(declared)


# --- the rules themselves -------------------------------------------------

@source_only
def test_a_read_only_skill_cannot_reach_a_mutating_command():
    for name in ('afc-validate', 'afc-discuss'):
        assert SCOPES.skill(name)['mutation'] == 'read-only'
        for script, subcommand in (('allocate_ids.py', None), ('parse_word.py', None),
                                   ('knowledge_base.py', 'publish'),
                                   ('knowledge_base.py', 'stage'),
                                   ('ensure_query_index.py', None)):
            with pytest.raises(ScopeError):
                SCOPES.check(name, script, subcommand)


@source_only
def test_the_release_boundary_is_held_by_the_skills_that_own_it():
    release_owners = {n for n in SCOPES.skills
                      if SCOPES.skill(n)['mutation'] == 'release'}
    assert release_owners == {'afc-update', 'afc-workspace', 'afc-share'}, (
        f'skills allowed to change the persistent Knowledge Base: {sorted(release_owners)}. '
        'Publishing belongs to the governed change path, not to a pipeline step.')
    for name in sorted(set(SCOPES.skills) - release_owners):
        with pytest.raises(ScopeError):
            SCOPES.check(name, 'knowledge_base.py', 'publish')


@source_only
def test_the_orchestrator_borrows_step_scopes_but_not_the_release_boundary():
    # afc-pipeline runs each step through that step's skill, so a step command
    # is in scope; publishing is not, however the pipeline is invoked.
    SCOPES.check('afc-pipeline', 'parse_word.py', None)
    SCOPES.check('afc-pipeline', 'allocate_ids.py', None)
    with pytest.raises(ScopeError):
        SCOPES.check('afc-pipeline', 'knowledge_base.py', 'publish')


@source_only
def test_an_unknown_class_is_treated_as_the_strongest():
    from afc_card_runtime.skill_scope import Scopes
    scopes = Scopes({'change_classes': ['read-only', 'work', 'release'],
                     'scripts': {'typo.py': 'raed-only'},
                     'skills': {'s': {'mutation': 'read-only', 'scripts': ['typo.py']}}})
    with pytest.raises(ScopeError):
        scopes.check('s', 'typo.py')


# --- enforcement through the launcher -------------------------------------

def run_afc(*args, skill=None):
    env = {'AFC_PYTHON': sys.executable, 'AFC_HOME': str(ROOT),
           'PATH': os.environ.get('PATH', '/usr/bin:/bin')}
    if skill is not None:
        env['AFC_SKILL'] = skill
    return subprocess.run(['bash', str(ROOT / 'afc'), *args],
                          capture_output=True, text=True, cwd=ROOT, env=env)


@source_only
def test_the_launcher_refuses_an_out_of_scope_command_and_names_the_owner():
    proc = run_afc('allocate_ids.py', '--help', skill='afc-validate')
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert 'out of scope for afc-validate' in proc.stderr
    assert 'afc-cards' in proc.stderr, 'the refusal must name the skill that owns it'

    allowed = run_afc('validate_schema.py', '--help', skill='afc-validate')
    assert allowed.returncode == 0, allowed.stderr


@source_only
def test_a_subcommand_outside_a_skills_narrowing_is_refused():
    refused = run_afc('knowledge_base.py', 'publish', '--kb-root', '/tmp/nope',
                      '--run-id', 'r', skill='afc-discuss')
    assert refused.returncode == 3, refused.stdout + refused.stderr
    assert 'limited to' in refused.stderr and 'afc-update' in refused.stderr


@source_only
def test_no_skill_means_no_enforcement():
    """A direct operator command still works; the guard is for a skill run."""
    proc = run_afc('validate_schema.py', '--help')
    assert proc.returncode == 0, proc.stderr
    unknown = run_afc('validate_schema.py', '--help', skill='afc-not-a-skill')
    assert unknown.returncode == 3 and 'unknown skill' in unknown.stderr


@source_only
def test_the_launcher_prints_a_skills_scope():
    proc = run_afc('--scope', 'afc-discuss')
    assert proc.returncode == 0, proc.stderr
    assert 'read-only' in proc.stdout and 'afc-update' in proc.stdout


# --- descriptions are the first boundary ---------------------------------
#
# A harness picks a skill from its description, so that is the earliest place to
# keep a skill out of its neighbour's work -- and the place a user's own words
# have to land. This team works in Chinese; descriptions written only in AFC's
# internal English vocabulary left afc-query, afc-discuss, afc-domains,
# afc-workspace and afc-share competing for the same requests.

CJK = re.compile(r'[㐀-䶿一-鿿]')


def description_of(skill_dir):
    head = (skill_dir / 'SKILL.md').read_text(encoding='utf-8').split('---')[1]
    match = re.search(r'(?m)^description:\s*(.+)$', head)
    assert match, f'{skill_dir.name} has no description'
    return match.group(1).strip()


@source_only
@pytest.mark.parametrize('skill_dir', skill_dirs(), ids=lambda p: p.name)
def test_a_description_carries_the_words_a_user_would_type(skill_dir):
    description = description_of(skill_dir)
    assert len(description) > 80, 'too thin to distinguish this skill from its siblings'
    assert CJK.search(description), (
        f'{skill_dir.name} has no Chinese trigger words. The sources, the config and '
        'the users are Chinese; an English-only description competes badly for a '
        'Chinese request.')


@source_only
@pytest.mark.parametrize('skill_dir', skill_dirs(), ids=lambda p: p.name)
def test_a_description_says_what_it_is_not_for(skill_dir):
    """The overlap between neighbouring skills is resolved here, not guessed at."""
    description = description_of(skill_dir)
    name = skill_dir.name
    others = sorted(n for n in SCOPES.skills if n != name)
    assert any(other in description for other in others) or 'never' in description.lower(), (
        f'{name} does not say what it is not for. Name the sibling that owns the '
        'neighbouring work, so a harness choosing between them has something to go on.')


@source_only
def test_no_two_skills_claim_the_same_work_in_the_same_words():
    descriptions = {d.name: description_of(d) for d in skill_dirs()}
    assert len(set(descriptions.values())) == len(descriptions), 'duplicate descriptions'
    # The opening clause is what a harness weighs most; two skills must not share it.
    openings = {}
    for name, description in descriptions.items():
        opening = description.split('.')[0].strip().lower()
        openings.setdefault(opening, []).append(name)
    clashes = {k: v for k, v in openings.items() if len(v) > 1}
    assert not clashes, f'skills opening with the same claim: {clashes}'


# --- one current behaviour, not a version matrix --------------------------

@source_only
@pytest.mark.parametrize('skill_dir', skill_dirs(), ids=lambda p: p.name)
def test_a_skill_states_one_current_behaviour(skill_dir):
    """A version-conditional clause makes the agent decide which release it is.

    Past-tense rationale ("v0.4.1 let the model number IDs, which is why...")
    explains a rule and stays. "For v0.7, use..." asks the reader to work out
    which version applies to them, in a package that is exactly one version.
    """
    files = [skill_dir / 'SKILL.md', *sorted(skill_dir.glob('references/*.md'))]
    offenders = []
    for path in files:
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            conditional = re.search(
                r'(?i)(\bfor\s+(a\s+|persistent\s+)?v0\.\d'      # "For v0.7, use..."
                r'|\bin\s+(a\s+|persistent\s+)v0\.\d'            # "In persistent v0.6..."
                r'|\bin\s+v0\.\d\s*,)', line)                     # "In v0.6, Scope comes..."
            if conditional or re.search(r'^#+ .*v0\.\d', line):
                offenders.append(f'{path.relative_to(skill_dir.parent)}:{number}: {line.strip()}')
    assert not offenders, (
        'version-conditional clauses in ' + skill_dir.name + ':\n  ' + '\n  '.join(offenders)
        + '\n\nState the current behaviour, or the real condition '
          '("with a persistent Knowledge Base"), not a release number.')
