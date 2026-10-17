"""Deterministic Card / Evidence identity and ID allocation.

v0.4.1 only validated the ID *format* (`CARD-\\d{6}`, `EVD-\\d{6}`) and left the
numbering to the model, while Card delta, rerun novelty, Gold regression and
`afc-curate`'s "never renumber" rule all assumed the IDs were stable. This
module makes identity a pure function of content and keeps a registry on disk,
so the same source fact gets the same ID on every rerun.
"""
from pathlib import Path
import hashlib
import json
import re

from .common import normalize_text, read_jsonl

CARD_PREFIX = 'CARD'
EVIDENCE_PREFIX = 'EVD'
ID_WIDTH = 6
ID_RE = {
    CARD_PREFIX: re.compile(r'^CARD-\d{6}$'),
    EVIDENCE_PREFIX: re.compile(r'^EVD-\d{6}$'),
}


def _norm_list(v):
    if v is None:
        return []
    if isinstance(v, (list, tuple, set)):
        vals = [normalize_text(x) for x in v]
    else:
        vals = [normalize_text(v)]
    return sorted({x for x in vals if x})


def _canonical(value):
    """Stable, order-insensitive JSON form used for hashing."""
    if isinstance(value, dict):
        return {k: _canonical(value[k]) for k in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonical(x) for x in value]
    return normalize_text(value) if value is not None else ''


def _digest(parts):
    blob = json.dumps(_canonical(parts), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()


STRUCTURED_FIELDS = (
    'Original Name', 'Original Description', 'Original Message', 'Original Component Type',
    'Original Code', 'Original Value', 'Original Label', 'Original Placeholder',
    'Original Required', 'Original Max Length', 'Original Min Length', 'Original Format',
    'Original Validation Message', 'Original Error Message', 'Original Option Values',
    'Original Function Code',
)


def evidence_identity(rec):
    """Identity of a source-preserving Evidence Record.

    Keyed on WHERE the fact came from plus WHAT the fact literally is. Card
    reinterpretation therefore cannot move an Evidence ID, and re-extracting the
    same row reuses it.
    """
    structured = {k: rec.get(k) for k in STRUCTURED_FIELDS if rec.get(k) not in (None, '', [])}
    extra = rec.get('Structured Facts')
    return _digest({
        'kind': 'evidence',
        'source': normalize_text(rec.get('Source')),
        'source_location': normalize_text(rec.get('Source Location')),
        'source_unit_ids': _norm_list(rec.get('Source Unit IDs')),
        'evidence_kind': normalize_text(rec.get('Evidence Kind')),
        'evidence_mode': normalize_text(rec.get('Evidence Mode')),
        # Original Text is compared verbatim apart from whitespace collapsing.
        'original_text': normalize_text(rec.get('Original Text')),
        'source_language': normalize_text(rec.get('Source Language')),
        'structured': structured,
        'structured_facts': extra if isinstance(extra, (dict, list)) else normalize_text(extra),
    })


def card_claim_key(rec):
    """The part of a Card's identity that names *which* claim it is.

    `Concept Key` is the stable choice: it survives rewording. `Claim Key` lets a
    Step 1 run deliberately distinguish several claims extracted from one source
    coordinate. Falling back to `Title` works but makes the identity
    wording-sensitive, so callers should surface that as a warning.
    """
    for field in ('Claim Key', 'Concept Key'):
        v = normalize_text(rec.get(field))
        if v:
            return v, field
    return normalize_text(rec.get('Title')), 'Title'


def card_identity(rec):
    """Identity of a normalized Knowledge Card.

    Keyed on the claim's addressable coordinates plus its claim key, not on its
    prose. A genuinely different claim (new scope, new context, different
    evidence basis) gets a new ID; rewording an existing one does not, provided
    the Card carries a Concept Key / Claim Key.
    """
    concept, _ = card_claim_key(rec)
    return _digest({
        'kind': 'card',
        'card_type': normalize_text(rec.get('Card Type')),
        'concept': concept,
        'scope': _norm_list(rec.get('Scope') or rec.get('Scopes') or rec.get('Product Context')),
        'context': normalize_text(rec.get('Context')),
        'source': normalize_text(rec.get('Source')),
        'evidence': _norm_list(rec.get('Evidence Record IDs')),
        'source_unit_ids': _norm_list(rec.get('Source Unit IDs')),
    })


IDENTITY_FN = {CARD_PREFIX: card_identity, EVIDENCE_PREFIX: evidence_identity}


class IdRegistry:
    """Append-only identity -> ID map persisted as JSONL.

    Rows: {"prefix","id","identity","first_run","last_run","note"}.
    Retired identities are kept so their numbers are never reused.
    """

    def __init__(self, path):
        self.path = Path(path)
        self.rows = []
        self.by_identity = {}
        self.by_id = {}
        self._max = {CARD_PREFIX: 0, EVIDENCE_PREFIX: 0}
        self.load()

    def load(self):
        for row in read_jsonl(self.path):
            prefix = row.get('prefix')
            ident = row.get('identity')
            rid = row.get('id')
            if not (prefix and ident and rid):
                continue
            self.rows.append(row)
            self.by_identity[(prefix, ident)] = rid
            self.by_id[rid] = row
            try:
                n = int(str(rid).split('-')[-1])
            except ValueError:
                continue
            self._max[prefix] = max(self._max.get(prefix, 0), n)
        return self

    def allocate(self, prefix, identity, run_id=None, note=None):
        key = (prefix, identity)
        if key in self.by_identity:
            rid = self.by_identity[key]
            row = self.by_id[rid]
            if run_id:
                row['last_run'] = run_id
            return rid, False
        self._max[prefix] = self._max.get(prefix, 0) + 1
        rid = f'{prefix}-{self._max[prefix]:0{ID_WIDTH}d}'
        row = {'prefix': prefix, 'id': rid, 'identity': identity,
               'first_run': run_id, 'last_run': run_id, 'note': note}
        self.rows.append(row)
        self.by_identity[key] = rid
        self.by_id[rid] = row
        return rid, True

    def rebind(self, prefix, existing_id, identity, run_id=None):
        """Move a known ID onto a new identity (a reworded but same claim).

        Returns False when the ID is unknown, belongs to another prefix, or the
        target identity is already taken by a different ID.
        """
        row = self.by_id.get(existing_id)
        if not row or row.get('prefix') != prefix:
            return False
        if self.by_identity.get((prefix, identity)) not in (None, existing_id):
            return False
        old = row.get('identity')
        if old == identity:
            return True
        self.by_identity.pop((prefix, old), None)
        history = row.setdefault('identity_history', [])
        history.append({'identity': old, 'run': run_id})
        row['identity'] = identity
        if run_id:
            row['last_run'] = run_id
        self.by_identity[(prefix, identity)] = existing_id
        return True

    def resolve_id(self, prefix, record, run_id=None, claimed_id=None, reserved=None):
        """Allocate, reuse or rebind in one step.

        Resolution order:
          1. the identity is already registered -> reuse that ID (`reused`);
          2. the record carries a live registry ID that nothing else claimed in
             this run -> rebind it (`rebound`), preserving continuity across a
             rewording;
          3. otherwise mint a new ID (`new`).
        """
        identity = IDENTITY_FN[prefix](record)
        known = self.by_identity.get((prefix, identity))
        if known:
            row = self.by_id[known]
            if run_id:
                row['last_run'] = run_id
            return known, 'reused', identity
        claimed = normalize_text(claimed_id or record.get('Card ID' if prefix == CARD_PREFIX else 'Evidence ID'))
        if claimed and ID_RE[prefix].match(claimed) and claimed not in (reserved or set()):
            if self.rebind(prefix, claimed, identity, run_id=run_id):
                return claimed, 'rebound', identity
        rid, _ = self.allocate(prefix, identity, run_id=run_id)
        return rid, 'new', identity

    def allocate_for(self, prefix, record, run_id=None, note=None):
        return self.allocate(prefix, IDENTITY_FN[prefix](record), run_id=run_id, note=note)

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('w', encoding='utf-8') as f:
            for row in self.rows:
                f.write(json.dumps(row, ensure_ascii=False) + '\n')
        return self.path

    def stats(self):
        return {p: self._max.get(p, 0) for p in (CARD_PREFIX, EVIDENCE_PREFIX)}
