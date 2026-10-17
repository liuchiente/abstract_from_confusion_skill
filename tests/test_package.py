"""Package-integrity tests.

v0.4.1 shipped docs and skills referencing paths and flags that did not exist,
schemas nothing read, and a settings file nothing opened. These tests make that
class of defect fail instead of being discovered at runtime.
"""
import json
import os
import py_compile
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ['README.md', 'AGENTS.md', 'RUN_ALL.md', 'MIGRATION.md']

# Installed layout check: the runtime directory holds scripts/, schemas/,
# config/ and tests/, while plugin.json, skills/ and the launcher live beside it
# in the repo. Tests about the package source skip there rather than failing.
IS_SOURCE_TREE = (ROOT / 'plugin.json').exists() and (ROOT / 'skills').is_dir()
source_only = pytest.mark.skipif(
    not IS_SOURCE_TREE,
    reason='package-source layout only; this is an installed runtime directory')


def skill_files():
    return sorted((ROOT / 'skills').glob('*/SKILL.md')) if (ROOT / 'skills').is_dir() else []


def skill_reference_files():
    """A skill's references/ hold real commands, so they are checked like docs."""
    return sorted((ROOT / 'skills').glob('*/references/*.md')) if (ROOT / 'skills').is_dir() else []


def doc_files():
    return ([ROOT / d for d in DOCS if (ROOT / d).exists()]
            + skill_files() + skill_reference_files())


def test_every_script_compiles(tmp_path):
    for script in sorted((ROOT / 'scripts').glob('*.py')):
        py_compile.compile(str(script), cfile=str(tmp_path / (script.stem + '.pyc')), doraise=True)
    for module in sorted((ROOT / 'afc_card_runtime').glob('*.py')):
        py_compile.compile(str(module), cfile=str(tmp_path / (module.stem + '.pyc')), doraise=True)


@source_only
def test_release_payload_excludes_local_work_and_experiments():
    # build_release.py is a source-tree tool; it is not part of an install.
    from build_release import package_files
    assert all(not ({'work', 'experiments'} & set(path.relative_to(ROOT).parts))
               for path in package_files())


@pytest.mark.parametrize('doc', doc_files(), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_referenced_scripts_exist(doc):
    text = doc.read_text(encoding='utf-8')
    referenced = set(re.findall(r'\./afc\s+([a-z0-9_]+\.py)', text))
    missing = [s for s in sorted(referenced) if not (ROOT / 'scripts' / s).exists()]
    assert not missing, f'{doc.name} references missing scripts: {missing}'


@pytest.mark.parametrize('doc', doc_files(), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_referenced_config_files_exist(doc):
    text = doc.read_text(encoding='utf-8')
    referenced = set(re.findall(r'config/([a-z0-9._-]+\.(?:yaml|md))', text))
    missing = []
    for name in sorted(referenced):
        if (ROOT / 'config' / name).exists():
            continue
        # A reference may legitimately name the working copy of a shipped example.
        stem, _, ext = name.rpartition('.')
        if (ROOT / 'config' / f'{stem}.example.{ext}').exists():
            continue
        missing.append(name)
    assert not missing, f'{doc.name} references missing config: {missing}'


@pytest.mark.parametrize('skill', skill_files(), ids=lambda p: p.parent.name)
def test_skills_use_the_launcher_not_a_relative_script_path(skill):
    text = skill.read_text(encoding='utf-8')
    assert '../../scripts/' not in text, (
        'skills must call ./afc <script>, not a path relative to the skill directory; '
        'that convention is what required the installer to rewrite every SKILL.md')
    assert 'python ../../' not in text


@pytest.mark.parametrize('skill', skill_files(), ids=lambda p: p.parent.name)
def test_skills_declare_a_name_and_description(skill):
    text = skill.read_text(encoding='utf-8')
    assert text.startswith('---\n'), f'{skill} has no frontmatter'
    head = text.split('---', 2)[1]
    assert re.search(r'^name:\s*\S+', head, re.M), f'{skill} has no name'
    desc = re.search(r'^description:\s*(.+)$', head, re.M)
    assert desc and len(desc.group(1)) > 40, f'{skill} has no usable description'


def test_every_schema_is_valid_json_schema():
    jsonschema = pytest.importorskip('jsonschema')
    for path in sorted((ROOT / 'schemas').glob('*.json')):
        schema = json.loads(path.read_text(encoding='utf-8'))
        jsonschema.Draft202012Validator.check_schema(schema)


def test_validate_schema_knows_every_shipped_schema():
    sys.path.insert(0, str(ROOT / 'scripts'))
    spec = (ROOT / 'scripts' / 'validate_schema.py').read_text(encoding='utf-8')
    declared = set(re.findall(r"\('([a-z0-9-]+\.schema\.json)'", spec))
    on_disk = {p.name for p in (ROOT / 'schemas').glob('*.json')}
    unused = on_disk - declared
    assert not unused, (
        f'schemas nothing validates against: {sorted(unused)}. '
        'v0.4.1 shipped 13 unused schemas; add it to validate_schema.KINDS.')
    assert not (declared - on_disk), f'validate_schema references missing schemas: {sorted(declared - on_disk)}'


@source_only
def test_the_launcher_resolves_the_runtime():
    proc = subprocess.run(['bash', str(ROOT / 'afc'), '--home'],
                          capture_output=True, text=True, cwd=ROOT)
    assert proc.returncode == 0, proc.stderr
    assert Path(proc.stdout.strip()) == ROOT


def test_requirements_cover_what_the_code_imports():
    reqs = (ROOT / 'requirements.txt').read_text(encoding='utf-8').lower()
    # jsonschema was shipped unused-and-undeclared in v0.4.1.
    for pkg in ('openpyxl', 'python-docx', 'pyyaml', 'pypdf', 'jsonschema'):
        assert pkg in reqs, f'{pkg} is imported by the package but not declared'


@source_only
def test_plugin_version_matches_version_file():
    version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
    for rel in ('plugin.json', '.codex-plugin/plugin.json', '.claude-plugin/plugin.json'):
        data = json.loads((ROOT / rel).read_text(encoding='utf-8'))
        assert data['version'] == version, f'{rel} says {data["version"]}, VERSION says {version}'


# --- Artifact chain -------------------------------------------------------
#
# v0.8.6 documented three Step 0 inputs that no documented command produced:
# the audit read a merged `step-card-0-source-units.jsonl` that only
# build_context_candidates.py writes (under a different name), and the OCR
# enrichment wrote `step-card-0-source-map-enriched.jsonl` while the next step
# read `step-card-0-word-source-units-enriched.jsonl` -- so recognized image
# text silently never reached Card extraction. Checking that referenced scripts
# and config files exist did not catch it, because every script and flag was
# real; only the work/ artifact names were out of step.

# Flags whose value is written by the command rather than read by it.
WRITER_FLAGS = {'-o', '--output', '--json-output', '--report', '--structure-report',
                '--verdict-template', '--template', '--log', '--append-history', '--cards-output',
                '--evidence-output', '--output-dir'}
# Scripts where another flag also names an output.
EXTRA_WRITER_FLAGS = {'ensure_query_index.py': {'--db'}, 'record_decision.py': {'--decision'}}

# Artifacts the reasoning model writes itself, or that come from an earlier run
# or an accepted release. No command produces them, by design.
MODEL_AUTHORED_ARTIFACTS = {
    'work/step-card-0-contexts.jsonl',
    'work/step-card-1-cards.jsonl',
    'work/step-card-1-evidence.jsonl',
    'work/step-card-1-coverage.jsonl',
    'work/step-card-1-reconciled-cards.jsonl',
    'work/step-card-2-cards-with-concepts.jsonl',
    'work/step-card-2-links.jsonl',
    'work/step-card-3-boxes.jsonl',
    'work/step-card-3-box-memberships.jsonl',
    'work/step-card-3-box-links.jsonl',
    'work/step-card-4-master.jsonl',
    'work/step-card-4-evidence.jsonl',
    'work/previous/step-card-1-cards.jsonl',
    'work/previous/step-card-1-evidence.jsonl',
    'work/query-runs/baseline.json',
    'work/release-decisions.jsonl',
    'output/knowledge_card_master.jsonl',
    'output/knowledge_evidence.jsonl',
    'output/knowledge_links.jsonl',
    'output/knowledge_boxes.jsonl',
    'output/knowledge_box_memberships.jsonl',
    'output/knowledge_box_links.jsonl',
    'output/knowledge_contexts.jsonl',
    'output/knowledge_domains.jsonl',
    'output/insurance_field_knowledge.xlsx',
}

ARTIFACT_PATH = re.compile(
    r'(?<![\w./-])((?:work|output)/[A-Za-z0-9._${}/,-]*\.(?:jsonl|json|xlsx|db|sqlite))')


def afc_commands(text):
    """Yield (script, argument string) for each ./afc call in a bash fence."""
    for block in re.findall(r'```bash\n(.*?)```', text, re.S):
        for line in block.replace('\\\n', ' ').splitlines():
            match = re.search(r'\./afc\s+([a-z0-9_]+\.py)\s*(.*)$', line)
            if match:
                yield match.group(1), match.group(2)


def expand_braces(token):
    inner = re.search(r'\{([^{}]*,[^{}]*)\}', token)
    if not inner:
        return [token]
    return [out for part in inner.group(1).split(',')
            for out in expand_braces(token[:inner.start()] + part + token[inner.end():])]


def as_pattern(path):
    """A documented output may interpolate a shell variable (…-$p-report.json)."""
    parts = re.split(r'(\$\{?\w+\}?)', path)
    return re.compile(''.join(r'[^/\s]*' if p.startswith('$') else re.escape(p)
                              for p in parts) + r'\Z')


def documented_artifacts():
    produced, consumed = [], {}
    for doc in doc_files():
        for script, arguments in afc_commands(doc.read_text(encoding='utf-8')):
            writers = WRITER_FLAGS | EXTRA_WRITER_FLAGS.get(script, set())
            tokens = arguments.split()
            for index, token in enumerate(tokens):
                flag, _, inline = token.partition('=')
                if flag not in writers:
                    continue
                value = inline or (tokens[index + 1] if index + 1 < len(tokens) else '')
                for path in expand_braces(value.strip('\'"')):
                    if ARTIFACT_PATH.fullmatch(path):
                        produced.append(path)
            for raw in ARTIFACT_PATH.findall(arguments):
                for path in expand_braces(raw):
                    consumed.setdefault(path, set()).add(doc.relative_to(ROOT).as_posix())
    return produced, consumed


@source_only
def test_every_documented_input_artifact_is_produced_somewhere():
    produced, consumed = documented_artifacts()
    patterns = [as_pattern(path) for path in produced]
    unresolved = {
        path: sorted(docs) for path, docs in sorted(consumed.items())
        if '$' not in path
        and path not in MODEL_AUTHORED_ARTIFACTS
        and not any(pattern.match(path) for pattern in patterns)
    }
    assert not unresolved, (
        'documented commands read artifacts that no documented command writes: '
        f'{unresolved}. Either fix the filename so it matches the step that '
        'produces it, or add it to MODEL_AUTHORED_ARTIFACTS when the model '
        'writes it by hand.')


@source_only
def test_the_ocr_enrichment_reaches_card_extraction():
    """The enriched map must be what Context selection reads, not a dead end.

    The chain spans afc-context's SKILL.md and its references/, so both are read
    here: moving a command into a reference file must not break the chain.
    """
    skill_dir = ROOT / 'skills' / 'afc-context'
    text = '\n'.join(path.read_text(encoding='utf-8') for path in
                     [skill_dir / 'SKILL.md', *sorted(skill_dir.glob('references/*.md'))])
    enriched = set()
    for script, arguments in afc_commands(text):
        if script != 'apply_visual_extractions.py':
            continue
        tokens = arguments.split()
        for index, token in enumerate(tokens):
            if token in {'-o', '--output'} and index + 1 < len(tokens):
                enriched.add(tokens[index + 1])
    assert enriched, 'afc-context documents no apply_visual_extractions.py output'
    consumers = [arguments for script, arguments in afc_commands(text)
                 if script == 'build_context_candidates.py']
    assert consumers, 'afc-context documents no build_context_candidates.py call'
    for path in sorted(enriched):
        assert any(path in arguments for arguments in consumers), (
            f'{path} is enriched with OCR text but never read by '
            'build_context_candidates.py, so the recognized image text cannot '
            'reach Evidence or Cards')


# --- Install and verification layer --------------------------------------
#
# The AFC rules used to be copied to .afc-card-experiment/AGENTS.md, a path no
# harness reads, so an installed repository ran with no AFC rules at all. And
# verify_codex_install.sh ran the launcher in a bare assignment under `set -e`,
# so an old default python3 aborted it after a screen of PASS lines, with no
# FAIL and no verdict.

@source_only
def test_the_installer_puts_the_rules_where_each_harness_reads_them():
    installer = (ROOT / 'install.sh').read_text(encoding='utf-8')
    assert (ROOT / 'templates' / 'afc-rules.md').is_file(), 'the rules section is missing'
    # Codex reads AGENTS.md, Claude Code reads CLAUDE.md, both at the repo root.
    # A copy inside the runtime directory is never loaded.
    for rules_file in ('$REPO/AGENTS.md', '$REPO/CLAUDE.md'):
        assert rules_file in installer, f'install.sh never writes {rules_file}'
    assert 'afc:begin' in installer and 'afc:end' in installer, (
        'the merged section needs delimiters so an upgrade replaces it in place')
    assert 'templates/afc-rules.md' in installer, (
        'both targets must fill their rules file from the one template')


@source_only
def test_the_rules_section_points_at_every_skill():
    section = (ROOT / 'templates' / 'afc-rules.md').read_text(encoding='utf-8')
    missing = [skill.parent.name for skill in skill_files()
               if skill.parent.name not in section]
    assert not missing, f'the installed rules section names no entry point for: {missing}'


@source_only
def test_the_rules_section_tells_the_agent_to_declare_its_skill():
    # Scope enforcement only runs when AFC_SKILL is set, so the rules must say so.
    section = (ROOT / 'templates' / 'afc-rules.md').read_text(encoding='utf-8')
    assert 'export AFC_SKILL=' in section and '--scope' in section


@source_only
@pytest.mark.parametrize('wrapper,target', [('install_codex.sh', 'codex'),
                                            ('install_claude.sh', 'claude'),
                                            ('verify_codex_install.sh', 'codex')])
def test_the_target_wrappers_delegate_to_one_implementation(wrapper, target):
    text = (ROOT / wrapper).read_text(encoding='utf-8')
    assert f'--target {target}' in text, f'{wrapper} must pass --target {target}'
    base = 'verify_install.sh' if wrapper.startswith('verify') else 'install.sh'
    assert base in text, f'{wrapper} must delegate to {base} rather than duplicating it'


@source_only
def test_verification_always_reaches_a_verdict():
    verify = (ROOT / 'verify_install.sh').read_text(encoding='utf-8')
    assert 'set -euo pipefail' not in verify, (
        'a checklist must not abort on the first failing check: `set -e` made '
        'the launcher check exit before printing FAIL or a verdict')
    assert re.search(r'if\s+resolved="\$\(.*--home', verify), (
        'run the launcher inside an if-condition so its failure is reported, '
        'not fatal')
    # Every check path has to end in pass or bad, including the ones that
    # previously could not run at all.
    assert 'could not be checked because the launcher does not run' in verify


@source_only
def test_every_plugin_manifest_says_the_same_thing():
    rels = ('plugin.json', '.codex-plugin/plugin.json', '.claude-plugin/plugin.json')
    manifests = {rel: json.loads((ROOT / rel).read_text(encoding='utf-8')) for rel in rels}
    distinct = {json.dumps(m, sort_keys=True) for m in manifests.values()}
    assert len(distinct) == 1, (
        f'plugin manifests have drifted: {manifests}. One package, one description: '
        'change plugin.json and copy it to both harness manifests.')


@source_only
def test_settings_comments_do_not_restate_the_version():
    header = (ROOT / 'config' / 'settings.yaml').read_text(encoding='utf-8').split('\n\n')[0]
    version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
    stale = re.findall(r'v\d+\.\d+\.\d+', header)
    assert not [v for v in stale if v != 'v' + version], (
        f'settings.yaml header names {stale} while VERSION says {version}; '
        'a version in a comment goes stale unnoticed')


# --- Progressive disclosure ------------------------------------------------
#
# A step's SKILL.md is read in full whenever that step runs. afc-cards and
# afc-context had grown past 20 KB each -- roughly 25-30 k tokens of
# instructions for one pipeline run before any source was read -- with no way to
# load only the part in hand. Reference-shaped material (worked examples,
# per-source-type playbooks, command cookbooks, verdict vocabularies) now lives
# in each skill's references/, pointed at from the step that needs it.

SKILL_BUDGET_BYTES = 20_000


@source_only
@pytest.mark.parametrize('skill', skill_files(), ids=lambda p: p.parent.name)
def test_a_skill_stays_within_its_instruction_budget(skill):
    size = len(skill.read_bytes())
    assert size <= SKILL_BUDGET_BYTES, (
        f'{skill.parent.name}/SKILL.md is {size} bytes. Move reference-shaped '
        f'material into {skill.parent.name}/references/ and point at it from the '
        'step that needs it, rather than growing what every run must read.')


@source_only
@pytest.mark.parametrize('skill', skill_files(), ids=lambda p: p.parent.name)
def test_every_reference_file_is_reachable_from_its_skill(skill):
    references = sorted(skill.parent.glob('references/*.md'))
    if not references:
        pytest.skip('no reference files')
    text = skill.read_text(encoding='utf-8')
    orphans = [r.name for r in references if f'references/{r.name}' not in text]
    assert not orphans, (
        f'{skill.parent.name} has reference files nothing points at: {orphans}. '
        'An unreferenced file is content the agent will never load.')


@source_only
@pytest.mark.parametrize('skill', skill_files(), ids=lambda p: p.parent.name)
def test_a_skill_does_not_point_at_a_missing_reference(skill):
    text = skill.read_text(encoding='utf-8')
    named = set(re.findall(r'references/([A-Za-z0-9._-]+\.md)', text))
    missing = sorted(n for n in named if not (skill.parent / 'references' / n).is_file())
    assert not missing, f'{skill.parent.name}/SKILL.md points at missing references: {missing}'


@source_only
def test_the_launcher_does_not_turn_an_option_value_into_a_path(tmp_path):
    """`--target-scope CA` must stay `CA` even when ./CA exists.

    The launcher absolutises arguments that name an existing path so they
    survive its cd into the runtime. "Exists in the current directory" alone is
    not enough to decide that an argument is a path: run from a directory that
    holds a product folder named CA, `--target-scope CA` became
    /abs/path/CA and was recorded as the run's Scope.
    """
    (tmp_path / 'CA').mkdir()
    units = tmp_path / 'units.jsonl'
    units.write_text(json.dumps({'source_unit_id': 'a.docx::B1::P1', 'kind': 'paragraph',
                                 'value': 'CA 加買規則', 'source_file': 'a.docx'}) + '\n',
                     encoding='utf-8')
    report = tmp_path / 'report.json'
    proc = subprocess.run(
        ['bash', str(ROOT / 'afc'), 'build_context_candidates.py', 'units.jsonl',
         '--target-scope', 'CA', '-o', str(tmp_path / 'out.jsonl'), '--report', str(report)],
        capture_output=True, text=True, cwd=tmp_path,
        env={'AFC_PYTHON': sys.executable, 'AFC_HOME': str(ROOT),
             'PATH': os.environ.get('PATH', '/usr/bin:/bin')})
    assert proc.returncode == 0, proc.stderr
    scopes = json.loads(report.read_text(encoding='utf-8'))['target_scopes']
    assert scopes == ['CA'], f'the launcher rewrote the Scope value: {scopes}'

    # A bare file name as an option value is still a path and must survive the cd.
    audit = tmp_path / 'audit.json'
    proc = subprocess.run(
        ['bash', str(ROOT / 'afc'), 'audit_source_structure.py', '--source-map', 'units.jsonl',
         '--json-output', str(audit)],
        capture_output=True, text=True, cwd=tmp_path,
        env={'AFC_PYTHON': sys.executable, 'AFC_HOME': str(ROOT),
             'PATH': os.environ.get('PATH', '/usr/bin:/bin')})
    assert proc.returncode == 0, proc.stderr
    assert json.loads(audit.read_text(encoding='utf-8'))['summary']['source_units'] == 1, (
        'a bare existing file passed to an option was not absolutised, so the '
        'script looked for it inside the runtime instead'
    )


@source_only
def test_draft_schema_validation_separates_placeholder_ids_from_real_errors(tmp_path):
    """Before allocate_ids.py every record fails the ID pattern, which made it
    impossible to schema-check a batch: the real errors arrived buried in one
    pattern complaint per record."""
    cards = tmp_path / 'step-card-1-cards.jsonl'
    good = {'Card ID': 'CARD-P7f-B001-004', 'Card Type': 'Rule', 'Concept Key': 'k',
            'Title': 'T', 'Content': 'C', 'Source': 'a.docx', 'Source Location': 'S',
            'Evidence Record IDs': ['EVD-P7f-B001-001']}
    bad = {**good, 'Card ID': 'CARD-P7f-B001-005', 'Card Type': 'NotAType'}
    cards.write_text(''.join(json.dumps(r) + '\n' for r in (good, bad)), encoding='utf-8')

    def run(*extra):
        proc = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'validate_schema.py'),
                               *extra, str(cards)],
                              capture_output=True, text=True, cwd=ROOT,
                              env={'AFC_HOME': str(ROOT), 'PATH': os.environ.get('PATH', '')})
        return json.loads(proc.stdout)

    final = run()
    draft = run('--draft')
    assert final['total_errors'] > draft['total_errors'], (
        'draft mode must not treat an unallocated ID as a schema error')
    assert draft['placeholder_ids'] >= 2 and draft['mode'] == 'draft'
    # The genuine mistake still fails, or draft mode would be a way to skip review.
    assert draft['status'] == 'FAIL'
    assert any('Card Type' in e['path'] for r in draft['results'] for e in r['errors'])


@source_only
def test_the_query_fast_path_keeps_its_fallback():
    """A shortcut through the planner must not become a shortcut past sufficiency."""
    text = (ROOT / 'skills' / 'afc-query' / 'SKILL.md').read_text(encoding='utf-8')
    assert 'Fast path' in text, 'afc-query documents no fast path for a plain lookup'
    fast = text[text.index('Fast path'):text.index('## 1. Normalize the question')]
    for required in ('Fall back', 'insufficient'):
        assert required in fast, (
            f'the fast path does not say when to {required.lower()}; without that it is '
            'just a licence to answer from the first retrieval')


@source_only
def test_the_version_is_read_from_the_version_file_not_restated_in_code():
    """runtime_version is stamped into immutable release manifests.

    A literal in a source file outlives the release it describes, and 0.8.6 was
    still being written into stores after the package had moved on.
    """
    from afc_card_runtime.config import package_version
    version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
    assert package_version(home=ROOT) == version

    offenders = []
    for path in sorted((ROOT / 'scripts').glob('*.py')) + \
            sorted((ROOT / 'afc_card_runtime').glob('*.py')):
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if line.lstrip().startswith('#') or '"""' in line:
                continue  # rationale may name the version a defect was fixed in
            if re.search(r'''["']v?\d+\.\d+(\.\d+)?["']''', line) and \
                    re.search(r'(?i)version', line):
                offenders.append(f'{path.name}:{number}: {line.strip()}')
    allowed = ('schema_version', 'format_version', 'TOKENIZER_VERSION', 'tokenizer_version',
               'report_schema_version', 'audit_schema_version', 'plan_schema_version',
               'index_schema_version', 'PACK_VERSION')
    offenders = [o for o in offenders if not any(a in o for a in allowed)]
    assert not offenders, (
        'a package version literal in code:\n  ' + '\n  '.join(offenders)
        + '\nUse afc_card_runtime.config.package_version() so VERSION stays the one place.')


@source_only
def test_the_readme_title_matches_the_version():
    """A README headed with an old version is the first thing a reader distrusts."""
    version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
    first = (ROOT / 'README.md').read_text(encoding='utf-8').splitlines()[0]
    assert first.strip() == f'# AFC Card Experiment v{version}', (
        f'README starts with {first!r} but VERSION says {version}')
