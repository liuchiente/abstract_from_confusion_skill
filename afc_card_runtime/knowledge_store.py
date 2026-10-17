"""Portable release store and human-reviewed change workflow."""

from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone

from .config import package_version

from .common import read_jsonl, write_jsonl

DATASETS = {
    'cards': ('knowledge_card_master.jsonl', 'Card ID'),
    'evidence': ('knowledge_evidence.jsonl', 'Evidence ID'),
    'links': ('knowledge_links.jsonl', 'Link ID'),
    'boxes': ('knowledge_boxes.jsonl', 'Box ID'),
    'memberships': ('knowledge_box_memberships.jsonl', 'Membership ID'),
    'box_links': ('knowledge_box_links.jsonl', 'Box Link ID'),
    'contexts': ('knowledge_contexts.jsonl', 'Context ID'),
    'coverage': ('source_unit_coverage.jsonl', 'Source Unit ID'),
    'domains': ('knowledge_domains.jsonl', 'Domain Key'),
    'source_catalog': ('source_catalog.jsonl', 'Membership ID'),
    'scope_attributions': ('knowledge_scope_attributions.jsonl', 'Attribution Key'),
}


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def atomic_json(path, value):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix='.' + target.name + '.', dir=str(target.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(temporary), str(target))
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def atomic_jsonl(path, rows):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix='.' + target.name + '.', dir=str(target.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(temporary), str(target))
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def load_json(path, default=None):
    p = Path(path)
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else default


def init_store(root, kb_id, name=None, runtime_version=None, scope_policy='product'):
    root = Path(root).expanduser().resolve()
    if root.exists() and any(root.iterdir()):
        raise FileExistsError('Knowledge Base root is not empty: ' + str(root))
    for directory in ('identity', 'releases', 'runs', 'history', 'indexes'):
        (root / directory).mkdir(parents=True, exist_ok=True)
    atomic_json(root / 'manifest.json', {
        'format': 'afc-knowledge-base', 'format_version': '1.0',
        'kb_id': kb_id, 'name': name or kb_id,
        'scope_policy': scope_policy,
        'created_at': utc_now(), 'runtime_version': runtime_version or package_version(),
        'current_release': None,
    })
    atomic_json(root / 'CURRENT.json', {'release_id': None, 'updated_at': utc_now()})
    for rel in ('identity/id-registry.jsonl', 'history/knowledge-change-log.jsonl',
                'history/review-decisions.jsonl'):
        path = root / rel
        if not path.exists():
            atomic_jsonl(path, [])
    return root


def current_release(root, allow_empty=False):
    root = Path(root).expanduser().resolve()
    pointer = load_json(root / 'CURRENT.json', {}) or {}
    release_id = pointer.get('release_id')
    if not release_id:
        if allow_empty:
            return None
        raise ValueError('Knowledge Base has no accepted release yet: ' + str(root))
    release = root / 'releases' / release_id
    if not release.is_dir():
        raise FileNotFoundError('CURRENT.json points to a missing release: ' + str(release))
    return release


def entity_key(dataset, row):
    if dataset == 'scope_attributions':
        return row.get('Attribution Key') or (str(row.get('Card ID', '')) + '::' + str(row.get('Scope ID', '')))
    return row.get(DATASETS[dataset][1])


def entity_map(dataset, rows):
    result = {}
    for row in rows:
        key = entity_key(dataset, row)
        if key:
            if key in result and canonical_json(result[key]) != canonical_json(row):
                raise ValueError(f'duplicate {dataset} key with conflicting rows: {key}')
            result[key] = row
    return result


def empty_release_datasets(release_dir):
    release_dir.mkdir(parents=True, exist_ok=True)
    for filename, _key in DATASETS.values():
        path = release_dir / filename
        if not path.exists():
            atomic_jsonl(path, [])


def validate_release(release_dir, evidence_required_card_ids=None):
    """Schema and cross-reference gate before an accepted release is activated."""
    try:
        import jsonschema
    except ImportError as exc:
        raise RuntimeError('jsonschema is required to publish a Knowledge Base release') from exc
    root = Path(__file__).resolve().parents[1]
    schema_kinds = {
        'cards': 'knowledge-card.schema.json',
        'evidence': 'evidence-record.schema.json',
        'links': 'knowledge-link.schema.json',
        'boxes': 'knowledge-box.schema.json',
        'memberships': 'box-membership.schema.json',
        'box_links': 'box-link.schema.json',
        'contexts': 'context-block.schema.json',
        'coverage': 'card-coverage.schema.json',
        'scope_attributions': 'knowledge-scope-attribution.schema.json',
        'domains': 'semantic-domain.schema.json',
    }
    records = {}
    for dataset, (filename, _key) in DATASETS.items():
        path = Path(release_dir) / filename
        rows = read_jsonl(path) if path.exists() else []
        records[dataset] = rows
        entity_map(dataset, rows)
        schema_name = schema_kinds.get(dataset)
        if not schema_name:
            continue
        schema_path = root / 'schemas' / schema_name
        if not schema_path.exists():
            raise FileNotFoundError('release validator schema is missing: ' + str(schema_path))
        validator = jsonschema.Draft202012Validator(json.loads(schema_path.read_text(encoding='utf-8')))
        for index, row in enumerate(rows, 1):
            error = next(validator.iter_errors(row), None)
            if error:
                raise ValueError(f'{filename} row {index} fails {schema_name}: {error.message}')

    card_ids = {str(row.get('Card ID')) for row in records['cards'] if row.get('Card ID')}
    domains_by_key = {str(row.get('Domain Key')): row for row in records['domains'] if row.get('Domain Key')}
    domain_keys = {key for key, row in domains_by_key.items() if row.get('Status', 'Active') in {'Active', 'Deprecated'}}
    for key, row in domains_by_key.items():
        missing_parents = set(row.get('Parent Keys') or []) - set(domains_by_key)
        if missing_parents:
            raise ValueError(f"Semantic Domain {key} points to unknown parents: " + ', '.join(sorted(missing_parents)))
    visiting, visited = set(), set()
    def visit_domain(key):
        if key in visiting:
            raise ValueError('Semantic Domain hierarchy contains a cycle at ' + key)
        if key in visited:
            return
        visiting.add(key)
        for parent in domains_by_key.get(key, {}).get('Parent Keys') or []:
            visit_domain(parent)
        visiting.remove(key)
        visited.add(key)
    for domain_key in domains_by_key:
        visit_domain(domain_key)
    for row in records['cards']:
        missing_domains = set(row.get('Semantic Domain Keys') or []) - domain_keys
        if missing_domains:
            raise ValueError('Card references unknown Semantic Domain Keys: ' + ', '.join(sorted(missing_domains)))
    evidence_ids = {str(row.get('Evidence ID')) for row in records['evidence'] if row.get('Evidence ID')}
    box_ids = {str(row.get('Box ID')) for row in records['boxes'] if row.get('Box ID')}
    attr_keys = set()
    for row in records['scope_attributions']:
        key = str(row.get('Card ID')) + '::' + str(row.get('Scope ID'))
        if key in attr_keys:
            raise ValueError('duplicate Card/Scope attribution: ' + key)
        attr_keys.add(key)
        if row.get('Card ID') not in card_ids:
            raise ValueError('Scope Attribution points to unknown Card ID: ' + str(row.get('Card ID')))
        missing = set(row.get('Evidence IDs') or []) - evidence_ids
        if missing:
            raise ValueError('Scope Attribution points to unknown Evidence IDs: ' + ', '.join(sorted(missing)))
    for row in records['cards']:
        refs = set(row.get('Evidence Record IDs') or [])
        card_type = str(row.get('Card Type') or '')
        if (card_type not in {'Concept', 'Context'} and not refs
                and (evidence_required_card_ids is None
                     or str(row.get('Card ID')) in evidence_required_card_ids)):
            raise ValueError('source-derived Card must reference at least one Evidence Record: '
                             + str(row.get('Card ID')))
        missing = refs - evidence_ids
        if missing:
            raise ValueError('Card points to unknown Evidence IDs: ' + ', '.join(sorted(missing)))
    for row in records['links']:
        for field in ('Source Card ID', 'Target Card ID'):
            if row.get(field) and row[field] not in card_ids:
                raise ValueError('Card Link points to unknown Card ID: ' + str(row[field]))
    for row in records['memberships']:
        if row.get('Card ID') not in card_ids or row.get('Box ID') not in box_ids:
            raise ValueError('Box Membership points to an unknown Card or Box ID')
    for row in records['box_links']:
        if row.get('Source Box ID') not in box_ids or row.get('Target Box ID') not in box_ids:
            raise ValueError('Box Link points to an unknown Box ID')
    return {'datasets': {key: len(value) for key, value in records.items()}, 'card_count': len(card_ids),
            'evidence_count': len(evidence_ids), 'box_count': len(box_ids)}


def normalize_migrated_null_fields(release_dir):
    """Drop optional v0.5 nulls where the v0.6 schema defines a non-null type."""
    root = Path(__file__).resolve().parents[1]
    schema_kinds = {
        'cards': 'knowledge-card.schema.json', 'evidence': 'evidence-record.schema.json',
        'links': 'knowledge-link.schema.json', 'boxes': 'knowledge-box.schema.json',
        'memberships': 'box-membership.schema.json', 'box_links': 'box-link.schema.json',
        'contexts': 'context-block.schema.json', 'coverage': 'card-coverage.schema.json',
    }
    changes = []
    for dataset, schema_name in schema_kinds.items():
        filename = DATASETS[dataset][0]
        path = Path(release_dir) / filename
        if not path.exists():
            continue
        schema = load_json(root / 'schemas' / schema_name, {}) or {}
        properties = schema.get('properties') or {}
        required = set(schema.get('required') or [])
        rows = read_jsonl(path)
        changed = False
        for index, row in enumerate(rows, 1):
            for field in list(row):
                if row[field] is not None or field not in properties:
                    continue
                field_type = properties[field].get('type')
                nullable = field_type is None or field_type == 'null' or (isinstance(field_type, list) and 'null' in field_type)
                if nullable:
                    continue
                if field in required:
                    raise ValueError(f'{filename} row {index} has null required field {field!r}; migration will not alter it')
                del row[field]
                changed = True
                changes.append({'dataset': dataset, 'row': index, 'field': field})
        if changed:
            atomic_jsonl(path, rows)
    return {'removed_optional_null_count': len(changes), 'fields': changes}


def release_hashes(release_dir):
    out = {}
    for dataset, (filename, _key) in DATASETS.items():
        path = Path(release_dir) / filename
        if path.exists():
            out[dataset] = sha256_file(path)
    return out


def verify_release(release_dir):
    """Validate a portable release and confirm its canonical files stayed intact."""
    release_dir = Path(release_dir)
    manifest = load_json(release_dir / 'release-manifest.json', {}) or {}
    expected = manifest.get('dataset_sha256')
    if not isinstance(expected, dict):
        raise ValueError('release manifest has no dataset hashes: ' + str(release_dir))
    actual = release_hashes(release_dir)
    if actual != expected:
        changed = sorted(set(actual) | set(expected))
        changed = [name for name in changed if actual.get(name) != expected.get(name)]
        raise ValueError('release files do not match the published hashes: ' + ', '.join(changed))
    required_evidence = set(manifest.get('evidence_required_card_ids') or [])
    return {
        'hashes': actual,
        'validation': validate_release(release_dir, evidence_required_card_ids=required_evidence),
    }


def next_release_id(root):
    ids = []
    for path in (Path(root) / 'releases').glob('release-*'):
        try:
            ids.append(int(path.name.split('-', 1)[1]))
        except (ValueError, IndexError):
            continue
    return 'release-{0:06d}'.format(max(ids or [0]) + 1)


def publish_pointer(root, release_id):
    root = Path(root)
    atomic_json(root / 'CURRENT.json', {'release_id': release_id, 'updated_at': utc_now()})
    manifest = load_json(root / 'manifest.json', {}) or {}
    manifest['current_release'] = release_id
    manifest['updated_at'] = utc_now()
    atomic_json(root / 'manifest.json', manifest)


def backup_current_pointer(root):
    pointer = load_json(Path(root) / 'CURRENT.json', {}) or {}
    return pointer.get('release_id')


def make_scope_attributions(cards, run_id, accepted_legacy=False):
    rows = []
    for card in cards:
        singular = card.get('Scope')
        plural = card.get('Scopes')
        values = []
        product_context = card.get('Product Context')
        legacy_values = ([singular] if isinstance(singular, str) else (singular or []))
        legacy_values += plural if isinstance(plural, list) else []
        if product_context:
            legacy_values += product_context if isinstance(product_context, list) else [x.strip() for x in str(product_context).replace('，', ',').split(',')]
        for value in legacy_values:
            value = str(value or '').strip()
            if value and value not in values:
                values.append(value)
        source_scope_fields = [field for field in ('Scope', 'Scopes', 'Product Context') if card.get(field) is not None]
        field_sets = []
        for field in source_scope_fields:
            raw = card.get(field)
            raw_values = raw if isinstance(raw, list) else [x.strip() for x in str(raw).replace('，', ',').split(',')]
            field_sets.append({str(x).strip() for x in raw_values if str(x).strip()})
        conflict = bool(field_sets and any(value_set != field_sets[0] for value_set in field_sets[1:]))
        for scope_id in values:
            key = str(card.get('Card ID', '')) + '::' + scope_id
            rows.append({
                'Attribution Key': key,
                'Card ID': card.get('Card ID'), 'Scope ID': scope_id,
                'Attribution Basis': 'Legacy Card Scope',
                'Evidence IDs': list(dict.fromkeys(card.get('Evidence Record IDs') or [])),
                'Source Context IDs': [],
                'Status': 'Needs Review' if conflict else ('Confirmed' if accepted_legacy else 'Candidate'),
                'Run ID': run_id,
                'Source Card Fields': source_scope_fields,
                'Notes': 'Legacy Scope/Scopes values conflict; inspect before confirmation.' if conflict else 'Imported from v0.5 Card scope field; confirm applicability during review.',
            })
    return rows


def refresh_legacy_scope_attributions(cards, scope_rows, run_id):
    """Refresh auto-derived scope rows from the current Card scope fields."""
    explicit = [row for row in scope_rows
                if row.get('Attribution Basis') != 'Legacy Card Scope']
    refreshed = make_scope_attributions(cards, run_id)
    return explicit + refreshed


def reconstruct_v05_id_registry(source_root, release_dir, run_id):
    """Rebuild current v0.5 ID bindings when a packaged work registry is absent.

    Current Cards/Evidence retain their IDs and get their content identities.
    A high-water mark is recovered from available output/work JSONL references
    so later allocations do not reuse an observed number. Missing historical
    identity history cannot be reconstructed and is returned as a limitation.
    """
    from .ids import CARD_PREFIX, EVIDENCE_PREFIX, ID_RE, card_identity, evidence_identity

    source_root = Path(source_root)
    release_dir = Path(release_dir)
    identity_functions = {
        'cards': (CARD_PREFIX, 'Card ID', card_identity),
        'evidence': (EVIDENCE_PREFIX, 'Evidence ID', evidence_identity),
    }
    registry = {}
    by_identity = {}
    max_seen = {CARD_PREFIX: 0, EVIDENCE_PREFIX: 0}
    for dataset, (prefix, id_field, identity_fn) in identity_functions.items():
        path = release_dir / DATASETS[dataset][0]
        for row in read_jsonl(path) if path.exists() else []:
            record_id = str(row.get(id_field) or '')
            if not ID_RE[prefix].fullmatch(record_id):
                raise ValueError(f'cannot reconstruct registry: invalid {id_field} {record_id!r}')
            identity = identity_fn(row)
            prior_id = by_identity.get((prefix, identity))
            if prior_id and prior_id != record_id:
                raise ValueError(f'cannot reconstruct registry: duplicate {prefix} identity on {prior_id} and {record_id}')
            prior_identity = registry.get((prefix, record_id), {}).get('identity')
            if prior_identity and prior_identity != identity:
                raise ValueError(f'cannot reconstruct registry: {record_id} has conflicting current identities')
            by_identity[(prefix, identity)] = record_id
            registry[(prefix, record_id)] = {
                'prefix': prefix, 'id': record_id, 'identity': identity,
                'first_run': row.get('First Seen Run'),
                'last_run': row.get('Last Seen Run'),
                'note': 'Current binding reconstructed from the accepted v0.5 master; prior identity history unavailable.',
            }
            max_seen[prefix] = max(max_seen[prefix], int(record_id.rsplit('-', 1)[1]))

    # Search only established Card/Evidence outputs and run datasets, not raw
    # source-unit text, which may contain strings that resemble AFC IDs.
    reference_files = list((source_root / 'output').glob('*.jsonl'))
    work = source_root / 'work'
    for pattern in ('*cards*.jsonl', '*evidence*.jsonl', '*knowledge-change*.jsonl'):
        reference_files.extend(work.glob(pattern))
    reference_files.extend((work / 'delta').rglob('*.jsonl') if (work / 'delta').is_dir() else [])
    reference_files = sorted({p.resolve() for p in reference_files if p.is_file()})
    patterns = {
        CARD_PREFIX: re.compile(r'^CARD-(\d{6})$'),
        EVIDENCE_PREFIX: re.compile(r'^EVD-(\d{6})$'),
    }
    id_fields = {
        'Card ID': CARD_PREFIX, 'Card IDs': CARD_PREFIX,
        'Source Card ID': CARD_PREFIX, 'Target Card ID': CARD_PREFIX,
        'Related Card IDs': CARD_PREFIX, 'Superseded By': CARD_PREFIX,
        'Supersedes': CARD_PREFIX,
        'Evidence ID': EVIDENCE_PREFIX, 'Evidence IDs': EVIDENCE_PREFIX,
        'Evidence Record IDs': EVIDENCE_PREFIX,
    }

    def observe_references(value):
        if isinstance(value, dict):
            object_prefix = {'Card': CARD_PREFIX, 'Evidence': EVIDENCE_PREFIX}.get(value.get('Object Type'))
            for field, item in value.items():
                prefix = id_fields.get(field)
                if field == 'Object ID':
                    prefix = object_prefix
                if prefix:
                    items = item if isinstance(item, list) else [item]
                    for candidate in items:
                        match = patterns[prefix].fullmatch(str(candidate or ''))
                        if match:
                            max_seen[prefix] = max(max_seen[prefix], int(match.group(1)))
                observe_references(item)
        elif isinstance(value, list):
            for item in value:
                observe_references(item)

    for path in reference_files:
        with path.open('r', encoding='utf-8') as stream:
            for line in stream:
                try:
                    observe_references(json.loads(line))
                except json.JSONDecodeError:
                    continue

    reserved_high_watermarks = {}
    for prefix, maximum in max_seen.items():
        if not maximum:
            continue
        high_id = f'{prefix}-{maximum:06d}'
        if (prefix, high_id) not in registry:
            identity = hashlib.sha256(('v05-reconstructed-high-watermark:' + high_id).encode('utf-8')).hexdigest()
            registry[(prefix, high_id)] = {
                'prefix': prefix, 'id': high_id, 'identity': identity,
                'first_run': None, 'last_run': run_id,
                'note': 'Reserved v0.5 high-water mark; original record was not present in the accepted master.',
            }
            reserved_high_watermarks[prefix] = high_id

    rows = [registry[key] for key in sorted(registry, key=lambda item: (item[0], int(item[1].rsplit('-', 1)[1])))]
    return rows, {
        'method': 'reconstructed-from-current-master-and-observed-jsonl-ids',
        'registry_row_count': len(rows),
        'reserved_high_watermarks': reserved_high_watermarks,
        'scanned_reference_files': len(reference_files),
        'limitation': 'Missing historical identity_history and unreferenced deleted IDs cannot be recovered without the original registry.',
    }


def validate_registry_against_release(registry_rows, release_dir):
    """Ensure the v0.5 identity registry covers every imported stable ID."""
    from .ids import CARD_PREFIX, EVIDENCE_PREFIX, card_identity, evidence_identity

    registry_by_id = {str(row.get('id')): row for row in registry_rows if row.get('id')}
    if len(registry_by_id) != len(registry_rows):
        raise ValueError('ID registry contains missing or duplicate ID rows')
    identity_to_id = {}
    for row in registry_rows:
        key = (row.get('prefix'), row.get('identity'))
        previous = identity_to_id.get(key)
        if previous and previous != row.get('id'):
            raise ValueError('ID registry maps one identity to multiple IDs: ' + str(key))
        identity_to_id[key] = row.get('id')
    try:
        import jsonschema
    except ImportError as exc:
        raise RuntimeError('jsonschema is required to validate the ID registry') from exc
    schema_path = Path(__file__).resolve().parents[1] / 'schemas' / 'id-registry.schema.json'
    validator = jsonschema.Draft202012Validator(load_json(schema_path, {}))
    for index, row in enumerate(registry_rows, 1):
        error = next(validator.iter_errors(row), None)
        if error:
            raise ValueError(f'ID registry row {index} fails schema: {error.message}')
    functions = {
        'cards': (CARD_PREFIX, 'Card ID', card_identity),
        'evidence': (EVIDENCE_PREFIX, 'Evidence ID', evidence_identity),
    }
    for dataset, (prefix, id_field, identity_fn) in functions.items():
        path = Path(release_dir) / DATASETS[dataset][0]
        for row in read_jsonl(path) if path.exists() else []:
            record_id = str(row.get(id_field) or '')
            registered = registry_by_id.get(record_id)
            if not registered or registered.get('prefix') != prefix:
                raise ValueError(f'ID registry does not contain imported {id_field}: {record_id}')
            if registered.get('identity') != identity_fn(row):
                raise ValueError(f'ID registry identity does not match imported {id_field}: {record_id}')
    return {'registry_ids': len(registry_rows), 'status': 'valid'}


def stage_proposals(base_dir, candidate_dir, run_dir, run_id, dataset_names=None):
    base_dir = Path(base_dir) if base_dir else None
    candidate_dir = Path(candidate_dir).resolve()
    run_dir = Path(run_dir).resolve()
    candidate_dir.mkdir(parents=True, exist_ok=True)
    if base_dir is None:
        base_dir = Path('/nonexistent')
    incoming = {}
    for dataset, (filename, _key) in DATASETS.items():
        if dataset_names and dataset not in dataset_names:
            continue
        path = candidate_dir / filename
        if path.exists():
            incoming[dataset] = read_jsonl(path)
    if 'cards' in incoming:
        incoming['scope_attributions'] = refresh_legacy_scope_attributions(
            incoming['cards'], incoming.get('scope_attributions', []), run_id)
    if not incoming:
        raise ValueError('candidate directory contains no recognized AFC JSONL datasets: ' + str(candidate_dir))
    proposals = []
    candidate_snapshot = run_dir / 'candidate'
    candidate_snapshot.mkdir(parents=True, exist_ok=True)
    for dataset, (filename, _key) in DATASETS.items():
        if dataset not in incoming:
            continue
        proposed = entity_map(dataset, incoming[dataset])
        base_path = base_dir / filename
        old = entity_map(dataset, read_jsonl(base_path) if base_path.exists() else [])
        atomic_jsonl(candidate_snapshot / filename, incoming[dataset])
        for key, row in sorted(proposed.items()):
            before = old.get(key)
            if (dataset == 'scope_attributions' and before
                    and before.get('Status') == 'Confirmed' and row.get('Status') == 'Candidate'):
                old_basis = {k: v for k, v in before.items() if k not in {'Status', 'Run ID'}}
                new_basis = {k: v for k, v in row.items() if k not in {'Status', 'Run ID'}}
                if canonical_json(old_basis) == canonical_json(new_basis):
                    continue
            if before is not None and canonical_json(before) == canonical_json(row):
                continue
            proposals.append({
                'Proposal ID': dataset + ':' + str(key),
                'Dataset': dataset,
                'Object ID': str(key),
                'Change Type': 'Added' if before is None else 'Updated',
                'Previous Value': before,
                'Proposed Value': row,
                'Run ID': run_id,
            })
    if 'cards' in incoming and 'scope_attributions' in incoming and base_dir.exists():
        card_ids = {str(row.get('Card ID')) for row in incoming['cards'] if row.get('Card ID')}
        old_scope_rows = entity_map('scope_attributions', read_jsonl(base_dir / DATASETS['scope_attributions'][0]))
        new_scope_keys = {entity_key('scope_attributions', row) for row in incoming['scope_attributions']}
        for key, before in sorted(old_scope_rows.items()):
            card_id = str(before.get('Card ID') or '')
            if card_id not in card_ids or key in new_scope_keys or before.get('Status') == 'Retired':
                continue
            proposed = dict(before)
            proposed['Status'] = 'Retired'
            proposed['Run ID'] = run_id
            proposed['Notes'] = 'Scope no longer appears in the candidate Card; retirement requires explicit human acceptance.'
            proposals.append({
                'Proposal ID': 'scope_attributions:' + str(key),
                'Dataset': 'scope_attributions', 'Object ID': str(key),
                'Change Type': 'Scope Retirement Candidate',
                'Previous Value': before, 'Proposed Value': proposed, 'Run ID': run_id,
            })
    registry = candidate_dir / 'id-registry.jsonl'
    if registry.exists():
        atomic_jsonl(candidate_snapshot / 'id-registry.jsonl', read_jsonl(registry))
    atomic_jsonl(run_dir / 'proposals.jsonl', proposals)
    atomic_jsonl(run_dir / 'decisions.jsonl', [])
    manifest = load_json(run_dir / 'run-manifest.json', {}) or {}
    manifest.update({'run_id': run_id, 'status': 'awaiting_review', 'proposal_count': len(proposals),
                     'base_release_id': Path(base_dir).name if Path(base_dir).exists() else None,
                     'candidate_datasets': sorted(incoming)})
    atomic_json(run_dir / 'run-manifest.json', manifest)
    return proposals


def append_decisions(run_dir, entries):
    """Record one explicit decision per proposal, validating all of them first.

    A release needs a decision for every staged proposal, and recording them one
    process at a time rewrote decisions.jsonl per call. This appends a batch in
    a single atomic write, and either every entry is valid or nothing is
    written -- a half-recorded review is worse than none.
    """
    run_dir = Path(run_dir)
    proposals = read_jsonl(run_dir / 'proposals.jsonl')
    by_id = {row.get('Proposal ID'): row for row in proposals}
    prepared, seen = [], set()
    for entry in entries:
        proposal_id = entry['proposal_id']
        decision = entry['decision']
        if decision not in {'accept', 'reject', 'defer'}:
            raise ValueError(f'decision must be accept, reject, or defer: {proposal_id} has {decision!r}')
        if proposal_id in seen:
            raise ValueError('the same proposal was decided twice in one batch: ' + proposal_id)
        if proposal_id not in by_id:
            raise KeyError('proposal does not exist: ' + proposal_id)
        seen.add(proposal_id)
        prepared.append({
            'Proposal ID': proposal_id, 'Decision': decision,
            'Reviewer': entry.get('reviewer') or '', 'Rationale': entry.get('rationale') or '',
            'Decided At': utc_now(),
            'Proposal SHA256': sha256_text(canonical_json(by_id[proposal_id])),
        })
    decisions_path = run_dir / 'decisions.jsonl'
    atomic_jsonl(decisions_path, read_jsonl(decisions_path) + prepared)
    return prepared


def append_decision(run_dir, proposal_id, decision, reviewer, rationale):
    return append_decisions(run_dir, [{'proposal_id': proposal_id, 'decision': decision,
                                       'reviewer': reviewer, 'rationale': rationale}])[0]


def accept_run(root, run_dir, run_id, quality_override_by=None, quality_override_rationale=None):
    root = Path(root).resolve()
    run_dir = Path(run_dir).resolve()
    proposals = read_jsonl(run_dir / 'proposals.jsonl')
    decisions = read_jsonl(run_dir / 'decisions.jsonl')
    latest = {}
    for row in decisions:
        latest[row.get('Proposal ID')] = row
    pending = [p['Proposal ID'] for p in proposals if p['Proposal ID'] not in latest]
    if pending:
        raise ValueError('every proposal needs an explicit accept/reject/defer decision; pending: ' + ', '.join(pending[:20]))
    stale = [p['Proposal ID'] for p in proposals
             if latest[p['Proposal ID']].get('Proposal SHA256') != sha256_text(canonical_json(p))]
    if stale:
        raise ValueError('proposal content changed after review or lacks a content-bound decision; restage and review again: '
                         + ', '.join(stale[:20]))
    base = current_release(root, allow_empty=True)
    run_manifest = load_json(run_dir / 'run-manifest.json', {}) or {}
    if run_manifest.get('run_id') and run_manifest['run_id'] != run_id:
        raise ValueError(f"run id mismatch: requested {run_id!r}, run manifest says {run_manifest['run_id']!r}")
    expected_base = run_manifest.get('base_release_id')
    actual_base = base.name if base else None
    if expected_base != actual_base:
        raise ValueError(f'base release changed while reviewing: expected {expected_base!r}, current {actual_base!r}; stage again')
    quality = run_manifest.get('card_health') or {}
    health_path = run_dir / 'card-health.json'
    if not health_path.is_file():
        raise ValueError('staged run has no bound Card health report; restage with --health-report')
    health = load_json(health_path, {}) or {}
    health_status = str(health.get('overall_status') or '').upper()
    actual_health_hash = sha256_file(health_path)
    if quality.get('sha256') != actual_health_hash or quality.get('overall_status') != health_status:
        raise ValueError('Card health report changed after staging; restage and review the current report')
    if health_status != 'READY':
        if not quality_override_by or not quality_override_rationale:
            raise ValueError(
                f'Card health is {health_status or "UNKNOWN"}; publish is blocked. '
                'A separate explicit quality-risk acknowledgement is required: '
                '--accept-quality-risk-by and --quality-risk-rationale. '
                'A decision to continue to Links does not satisfy this release gate.'
            )

    release_id = next_release_id(root)
    release_dir = root / 'releases' / release_id
    release_dir.mkdir(parents=True, exist_ok=False)
    history_paths = [root / 'history' / 'review-decisions.jsonl',
                     root / 'history' / 'knowledge-change-log.jsonl',
                     root / 'identity' / 'id-registry.jsonl']
    old_histories = {path: (path.read_bytes() if path.exists() else None) for path in history_paths}
    old_manifest = load_json(root / 'manifest.json', {}) or {}
    pointer_flipped = False
    try:
        if base:
            for child in base.iterdir():
                if child.is_file() and child.name != 'release-manifest.json':
                    shutil.copy2(str(child), str(release_dir / child.name))
        empty_release_datasets(release_dir)
        accepted = [p for p in proposals if latest[p['Proposal ID']]['Decision'] == 'accept']
        accepted_by_dataset = {}
        for proposal in accepted:
            accepted_by_dataset.setdefault(proposal['Dataset'], {})[proposal['Object ID']] = proposal['Proposed Value']
        for dataset, rows_by_id in accepted_by_dataset.items():
            filename, _key = DATASETS[dataset]
            existing_rows = entity_map(dataset, read_jsonl(release_dir / filename))
            if dataset == 'scope_attributions':
                for row in rows_by_id.values():
                    if row.get('Status') in {'Candidate', 'Needs Review'}:
                        row['Status'] = 'Confirmed'
            if dataset == 'domains':
                for row in rows_by_id.values():
                    if row.get('Status') == 'Candidate':
                        row['Status'] = 'Active'
                        row['Created In Release'] = release_id
            existing_rows.update(rows_by_id)
            values = [existing_rows[key] for key in sorted(existing_rows)]
            atomic_jsonl(release_dir / filename, values)

        evidence_required_card_ids = set()
        for proposal in accepted:
            if proposal.get('Dataset') != 'cards':
                continue
            proposed_card = proposal.get('Proposed Value') or {}
            if str(proposed_card.get('Card Type') or '') not in {'Concept', 'Context'}:
                evidence_required_card_ids.add(str(proposal.get('Object ID')))
        validation = validate_release(
            release_dir, evidence_required_card_ids=evidence_required_card_ids)

        candidate = run_dir / 'candidate'
        id_registry = candidate / 'id-registry.jsonl'
        if id_registry.exists():
            persisted_registry_path = root / 'identity' / 'id-registry.jsonl'
            persisted_registry = read_jsonl(persisted_registry_path)
            new_registry = read_jsonl(id_registry)
            by_id = {(str(row.get('prefix')), str(row.get('id'))): row for row in persisted_registry}
            for row in new_registry:
                key = (str(row.get('prefix')), str(row.get('id')))
                old = by_id.get(key)
                if old and old.get('identity') != row.get('identity'):
                    history = {item.get('identity') for item in row.get('identity_history') or []}
                    if old.get('identity') not in history:
                        raise ValueError('ID registry identity changed without a recorded identity_history entry: ' + str(key))
                by_id[key] = row
            atomic_jsonl(persisted_registry_path, [by_id[key] for key in sorted(by_id)])
        decisions_for_run = [row for row in decisions if row.get('Proposal ID') in latest]
        history_decisions = read_jsonl(root / 'history' / 'review-decisions.jsonl')
        atomic_jsonl(root / 'history' / 'review-decisions.jsonl', history_decisions + decisions_for_run)
        changes = read_jsonl(root / 'history' / 'knowledge-change-log.jsonl')
        change_number = max([
            int(str(row.get('Change ID', '')).split('-')[-1])
            for row in changes if str(row.get('Change ID', '')).startswith('CHG-')
            and str(row.get('Change ID', '')).split('-')[-1].isdigit()
        ] or [0])
        change_rows = []
        for proposal in accepted:
            decision = latest[proposal['Proposal ID']]
            change_number += 1
            change_rows.append({
                'Change ID': 'CHG-{0:06d}'.format(change_number),
                'Change Type': proposal['Change Type'], 'Dataset': proposal['Dataset'],
                'Object ID': proposal['Object ID'], 'Run ID': run_id,
                'Previous Value': proposal.get('Previous Value'),
                'Current Value': proposal.get('Proposed Value'),
                'Decision': decision['Decision'], 'Reviewer': decision['Reviewer'],
                'Rationale': decision['Rationale'], 'Release ID': release_id,
            })
        atomic_jsonl(root / 'history' / 'knowledge-change-log.jsonl', changes + change_rows)
        manifest = {
            'release_id': release_id, 'kb_id': (load_json(root / 'manifest.json', {}) or {}).get('kb_id'),
            'schema_version': '1.0', 'runtime_version': package_version(),
            'parent_release_id': actual_base, 'run_id': run_id, 'accepted_at': utc_now(),
            'proposal_count': len(proposals), 'accepted_count': len(accepted),
            'rejected_count': sum(1 for p in proposals if latest[p['Proposal ID']]['Decision'] == 'reject'),
            'deferred_count': sum(1 for p in proposals if latest[p['Proposal ID']]['Decision'] == 'defer'),
            'evidence_required_card_ids': sorted(evidence_required_card_ids),
            'card_health': {
                'overall_status': health_status,
                'health_report_sha256': actual_health_hash,
                'quality_risk_accepted_by': quality_override_by if health_status != 'READY' else None,
                'quality_risk_rationale': quality_override_rationale if health_status != 'READY' else None,
            },
            'validation': validation,
            'dataset_sha256': release_hashes(release_dir),
        }
        atomic_json(release_dir / 'release-manifest.json', manifest)
        new_manifest = dict(old_manifest)
        new_manifest['current_release'] = release_id
        new_manifest['updated_at'] = utc_now()
        atomic_json(root / 'manifest.json', new_manifest)
        try:
            atomic_json(root / 'CURRENT.json', {'release_id': release_id, 'updated_at': utc_now()})
            pointer_flipped = True
        except Exception:
            atomic_json(root / 'manifest.json', old_manifest)
            raise
        run_manifest.update({'status': 'published', 'published_release_id': release_id,
                             'published_at': utc_now()})
        atomic_json(run_dir / 'run-manifest.json', run_manifest)
    except Exception:
        if not pointer_flipped:
            for path, contents in old_histories.items():
                if contents is None:
                    if path.exists(): path.unlink()
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(contents)
            atomic_json(root / 'manifest.json', old_manifest)
            shutil.rmtree(release_dir, ignore_errors=True)
        raise
    return release_id
