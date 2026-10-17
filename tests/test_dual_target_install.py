"""One source, two harnesses.

The package installs into a Codex repo and a Claude Code repo from the same
skills, scripts, config and rules template. A second copy of the package would
have been the alternative, and this package's history is the argument against
it: its drift defects all came from one fact stated in two places. These tests
install for real and compare what each target gets.
"""
from pathlib import Path
import filecmp
import json
import os
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
IS_SOURCE_TREE = (ROOT / 'install.sh').is_file() and (ROOT / 'skills').is_dir()
source_only = pytest.mark.skipif(not IS_SOURCE_TREE, reason='package-source layout only')

SKILL_NAMES = sorted(p.parent.name for p in (ROOT / 'skills').glob('*/SKILL.md')) \
    if (ROOT / 'skills').is_dir() else []


def install(repo, target):
    env = {'AFC_PYTHON': sys.executable, 'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
           'HOME': str(repo)}
    proc = subprocess.run(['bash', str(ROOT / 'install.sh'), str(repo), '--target', target],
                          capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout


def verify(repo, target):
    env = {'AFC_PYTHON': sys.executable, 'PATH': os.environ.get('PATH', '/usr/bin:/bin')}
    return subprocess.run(['bash', str(ROOT / 'verify_install.sh'), str(repo),
                           '--target', target],
                          capture_output=True, text=True, env=env)


@source_only
@pytest.mark.parametrize('target,skills_dir,rules,manifest', [
    ('codex', '.codex/skills', 'AGENTS.md', '.codex-plugin/plugin.json'),
    ('claude', '.claude/skills', 'CLAUDE.md', '.claude-plugin/plugin.json'),
])
def test_each_target_installs_where_its_harness_looks(tmp_path, target, skills_dir,
                                                      rules, manifest):
    install(tmp_path, target)
    for name in SKILL_NAMES:
        assert (tmp_path / skills_dir / name / 'SKILL.md').is_file(), \
            f'{name} missing from {skills_dir}'
    assert 'afc:begin' in (tmp_path / rules).read_text(encoding='utf-8'), (
        f'{rules} has no AFC section, so the {target} harness loads no AFC rules')
    assert (tmp_path / manifest).is_file()
    assert (tmp_path / 'afc').is_file() and os.access(tmp_path / 'afc', os.X_OK)
    assert (tmp_path / '.afc-card-experiment' / 'config' / 'skill-scopes.yaml').is_file(), \
        'without the scope manifest nothing is enforced'
    assert verify(tmp_path, target).returncode == 0


@source_only
def test_both_targets_install_byte_identical_skills(tmp_path):
    install(tmp_path, 'both')
    for name in SKILL_NAMES:
        codex = tmp_path / '.codex/skills' / name
        for other in (tmp_path / '.agents/skills' / name, tmp_path / '.claude/skills' / name):
            diff = filecmp.dircmp(codex, other)
            assert not (diff.left_only or diff.right_only or diff.diff_files), (
                f'{name} differs between {codex} and {other}: '
                f'{diff.left_only} {diff.right_only} {diff.diff_files}. '
                'Both targets must come from the same source files.')


@source_only
def test_both_rules_files_carry_the_same_section(tmp_path):
    install(tmp_path, 'both')
    section = (ROOT / 'templates' / 'afc-rules.md').read_text(encoding='utf-8').strip()
    for rules in ('AGENTS.md', 'CLAUDE.md'):
        text = (tmp_path / rules).read_text(encoding='utf-8')
        assert section in text, f'{rules} does not carry templates/afc-rules.md verbatim'
    assert json.loads((tmp_path / '.codex-plugin/plugin.json').read_text(encoding='utf-8')) == \
        json.loads((tmp_path / '.claude-plugin/plugin.json').read_text(encoding='utf-8'))


@source_only
def test_installing_one_target_leaves_the_other_alone(tmp_path):
    install(tmp_path, 'codex')
    assert not (tmp_path / 'CLAUDE.md').exists()
    assert not (tmp_path / '.claude').exists()
    install(tmp_path, 'claude')
    assert (tmp_path / 'CLAUDE.md').is_file() and (tmp_path / 'AGENTS.md').is_file()


@source_only
def test_reinstalling_keeps_the_repos_own_rules_and_replaces_only_the_block(tmp_path):
    own = '# My project\n\nHouse rules that must survive an upgrade.\n'
    (tmp_path / 'CLAUDE.md').write_text(own, encoding='utf-8')
    install(tmp_path, 'claude')
    install(tmp_path, 'claude')
    text = (tmp_path / 'CLAUDE.md').read_text(encoding='utf-8')
    assert text.startswith(own), 'the repo\'s own rules were not preserved'
    assert text.count('<!-- afc:begin -->') == 1, 'an upgrade appended a second AFC section'


@source_only
def test_an_unknown_target_is_refused(tmp_path):
    env = {'AFC_PYTHON': sys.executable, 'PATH': os.environ.get('PATH', '/usr/bin:/bin')}
    proc = subprocess.run(['bash', str(ROOT / 'install.sh'), str(tmp_path),
                           '--target', 'gemini'], capture_output=True, text=True, env=env)
    assert proc.returncode == 2 and 'codex, claude or both' in proc.stderr


@source_only
def test_scope_enforcement_survives_installation(tmp_path):
    """The guard has to work from the installed runtime, not just in this tree."""
    install(tmp_path, 'claude')
    env = {'AFC_PYTHON': sys.executable, 'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
           'AFC_SKILL': 'afc-query'}
    refused = subprocess.run(['bash', str(tmp_path / 'afc'), 'parse_word.py', '--help'],
                             capture_output=True, text=True, cwd=tmp_path, env=env)
    assert refused.returncode == 3, refused.stdout + refused.stderr
    assert 'afc-context' in refused.stderr
    env['AFC_SKILL'] = 'afc-context'
    allowed = subprocess.run(['bash', str(tmp_path / 'afc'), 'parse_word.py', '--help'],
                             capture_output=True, text=True, cwd=tmp_path, env=env)
    assert allowed.returncode == 0, allowed.stderr


@source_only
def test_upgrading_replaces_the_scope_manifest_but_keeps_user_config(tmp_path):
    """skill-scopes.yaml declares what the installed skills may run.

    Preserving a user's old copy on upgrade would refuse commands the new skills
    document, so it is package structure like schemas/, not configuration.
    Settings the user owns must still survive.
    """
    install(tmp_path, 'claude')
    config = tmp_path / '.afc-card-experiment' / 'config'
    (config / 'settings.yaml').write_text('query:\n  top_k: 99\n', encoding='utf-8')
    (config / 'skill-scopes.yaml').write_text('version: 1\nskills: {}\n', encoding='utf-8')

    install(tmp_path, 'claude')

    assert 'top_k: 99' in (config / 'settings.yaml').read_text(encoding='utf-8'), (
        'the upgrade overwrote the user\'s settings.yaml')
    scopes = (config / 'skill-scopes.yaml').read_text(encoding='utf-8')
    assert 'afc-cards' in scopes, (
        'the upgrade kept a stale scope manifest; the new skills would be refused '
        'commands they document')
    assert (config / f'settings.v{(ROOT / "VERSION").read_text().strip()}.example.yaml').is_file()
