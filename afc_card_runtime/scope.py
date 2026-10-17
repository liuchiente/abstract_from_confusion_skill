"""Scope mapping and directory-local boundary support for AFC v0.8.5."""

from pathlib import Path
import hashlib
import re
import xml.etree.ElementTree as ET

import yaml

from .common import normalize_text


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _unique(values):
    out = []
    seen = set()
    for value in values:
        value = normalize_text(value)
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            out.append(value)
    return out


def load_business_context_map(path):
    """Load the YAML v0.5 map or the mapping-only XML contract."""
    if not path:
        return []
    source = Path(path).expanduser()
    if not source.exists():
        raise FileNotFoundError('Business Context map does not exist: ' + str(source))
    if source.suffix.lower() == '.xml' or source.name.lower().endswith('.xml.example'):
        root = ET.parse(str(source)).getroot()
        if root.tag != 'context-map':
            raise ValueError('context.xml root must be <context-map>')
        declared = {
            normalize_text(node.attrib.get('id'))
            for node in root.findall('./scopes/scope')
            if normalize_text(node.attrib.get('id'))
        }
        rows = []
        for item in root.findall('./business-contexts/business-context'):
            context = normalize_text(item.attrib.get('name') or item.attrib.get('id'))
            if not context:
                continue
            aliases = [context]
            aliases.extend(normalize_text(x.text) for x in item.findall('./aliases/alias'))
            scopes = [normalize_text(x.attrib.get('id')) for x in item.findall('./maps-to/scope-ref')]
            unknown = [scope for scope in scopes if scope and scope not in declared]
            if unknown:
                raise ValueError('context.xml maps to undeclared Scope IDs: ' + ', '.join(unknown))
            rows.append({
                'context': context,
                'aliases': _unique(aliases),
                'scopes': _unique(scopes),
                'description': normalize_text(item.findtext('description')),
            })
        return rows

    data = yaml.safe_load(source.read_text(encoding='utf-8')) or {}
    rows = []
    for item in data.get('business_contexts', []) or []:
        context = normalize_text(item.get('context'))
        if not context:
            continue
        rows.append({
            'context': context,
            'aliases': _unique([context, *(item.get('aliases') or [])]),
            'scopes': _unique(item.get('scopes') or []),
            'description': normalize_text(item.get('description')),
        })
    return rows


def resolve_business_context_map(path, requested):
    requested_keys = {normalize_text(x).casefold() for x in requested or [] if normalize_text(x)}
    rows = load_business_context_map(path)
    if not requested_keys:
        return {'contexts': [], 'aliases': [], 'scopes': [], 'matches': []}
    matches = []
    for row in rows:
        if requested_keys.intersection(
            {row['context'].casefold(), *(x.casefold() for x in row['aliases'])}
        ):
            matches.append(row)
    contexts = _unique(row['context'] for row in matches)
    aliases = _unique(alias for row in matches for alias in row['aliases'])
    scopes = _unique(scope for row in matches for scope in row['scopes'])
    return {'contexts': contexts, 'aliases': aliases, 'scopes': scopes, 'matches': matches}


_SECTION_NAMES = {
    'default': {'預設scope', '預設範圍', 'default scopes', 'default scope'},
    'excluded': {'排除scope', '排除範圍', 'excluded scopes', 'excluded scope'},
}
_NORMALIZED_SECTION_NAMES = {
    key: {re.sub(r'\s+', '', value).casefold() for value in names}
    for key, names in _SECTION_NAMES.items()
}
_SCOPE_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')


def parse_scope_metadata(path):
    """Read explicit Markdown sections; unknown text is ignored, not guessed."""
    source = Path(path)
    sections = {'default': [], 'excluded': []}
    current = None
    for raw in source.read_text(encoding='utf-8-sig').splitlines():
        heading = re.match(r'^\s*#{1,6}\s+(.+?)\s*$', raw)
        if heading:
            heading_text = normalize_text(heading.group(1)).strip('`').rstrip(':：。')
            normalized = re.sub(r'\s+', '', heading_text).casefold()
            current = next((key for key, names in _NORMALIZED_SECTION_NAMES.items() if normalized in names), None)
            continue
        if current is None:
            continue
        item = re.match(r'^\s*[-*+]\s+(.+?)\s*$', raw)
        if not item:
            continue
        value = item.group(1).strip()
        code = re.match(r'^`([^`]+)`', value)
        if code:
            value = code.group(1).strip()
        else:
            value = re.split(r'\s+[—–-]\s+|\s*[:：]\s*|\s{2,}', value, maxsplit=1)[0].strip()
        value = value.rstrip('。.;；,，')
        if value.casefold() in {'無', 'none', 'nil', 'n/a', '<canonical_scope_id>'}:
            continue
        if not _SCOPE_ID.fullmatch(value):
            raise ValueError(f'{source}: invalid Scope ID in {current} section: {value!r}')
        sections[current].append(value)
    return {
        'default_scopes': _unique(sections['default']),
        'excluded_scopes': _unique(sections['excluded']),
        'path': str(source.resolve()),
        'sha256': sha256_file(source),
    }


def _nearest_scope_file(file_path):
    path = Path(file_path).expanduser()
    if not path.is_absolute():
        path = path.resolve()
    directory = path if path.is_dir() else path.parent
    while True:
        candidate = directory / 'afc-scope.md'
        if candidate.is_file():
            return candidate
        if directory.parent == directory:
            return None
        directory = directory.parent


def source_memberships(file_path, roots=None):
    """Keep one row per selected path membership, including overlapping roots."""
    path = Path(file_path).expanduser()
    if not path.is_absolute():
        path = path.resolve()
    else:
        path = path.resolve()
    roots = [Path(root).expanduser().resolve() for root in (roots or [])]
    matching = []
    for root in roots:
        try:
            relative = path.relative_to(root) if root.is_dir() else Path(path.name)
        except ValueError:
            continue
        scope_file = _nearest_scope_file(path)
        metadata = parse_scope_metadata(scope_file) if scope_file else {
            'default_scopes': [], 'excluded_scopes': [], 'path': None, 'sha256': None,
        }
        matching.append({
            'root': str(root),
            'relative_path': relative.as_posix(),
            'scope_metadata': metadata,
        })
    # A supplied set of source roots is a boundary. A parsed path that is not
    # beneath any one of them must fail closed instead of inheriting a Scope
    # from an unrelated ancestor directory.
    if not matching and roots:
        return []
    if not matching:
        scope_file = _nearest_scope_file(path)
        metadata = parse_scope_metadata(scope_file) if scope_file else {
            'default_scopes': [], 'excluded_scopes': [], 'path': None, 'sha256': None,
        }
        matching.append({
            'root': None,
            'relative_path': path.name,
            'scope_metadata': metadata,
        })
    return matching


def resolve_membership_scopes(metadata, requested_scopes=None, mapped_scopes=None,
                              global_excluded=None, override_exclusions=None):
    """Resolve the run boundary while keeping local exclusions authoritative."""
    local_defaults = metadata.get('default_scopes') or []
    local_excluded = metadata.get('excluded_scopes') or []
    requested = _unique(requested_scopes or [])
    mapped = _unique(mapped_scopes or [])
    if requested:
        targets = requested
        target_basis = 'Prompt'
    elif mapped:
        targets = [s for s in mapped if not local_defaults or s.casefold() in {x.casefold() for x in local_defaults}]
        target_basis = 'Business Context mapping'
    else:
        targets = list(local_defaults)
        target_basis = 'Directory default' if targets else 'Unresolved'

    excluded = _unique([*(global_excluded or []), *local_excluded])
    overrides = {x.casefold() for x in _unique(override_exclusions or [])}
    blocked = [s for s in targets if s.casefold() in {x.casefold() for x in excluded} and s.casefold() not in overrides]
    allowed = [s for s in targets if s not in blocked]
    status = 'eligible' if allowed else ('excluded' if targets else 'needs-scope')
    if allowed and blocked:
        status = 'partially-excluded'
    applied_overrides = [s for s in targets if s.casefold() in overrides and s.casefold() in {x.casefold() for x in excluded}]
    return {
        'target_scopes': targets,
        'allowed_scopes': allowed,
        'excluded_scopes': excluded,
        'blocked_scopes': blocked,
        'override_scopes': applied_overrides,
        'target_basis': target_basis,
        'status': status,
    }
