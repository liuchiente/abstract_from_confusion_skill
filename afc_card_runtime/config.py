"""Single source of truth for AFC runtime settings.

v0.4.1 duplicated every threshold across settings.yaml, each script's argparse
defaults, README.md, AGENTS.md and the SKILL.md files, and no script ever read
settings.yaml. Here the defaults are declared once and settings.yaml overrides
them; every script takes its defaults from this module.
"""
from pathlib import Path
import os

try:
    import yaml
except Exception:  # pragma: no cover - yaml is a hard requirement at runtime
    yaml = None

DEFAULTS = {
    'company_context': './config/company-context.md',
    'business_context_map': './config/business-contexts.yaml',
    'box_taxonomy': './config/box-taxonomy.yaml',
    'knowledge_signals': './config/knowledge-signals.yaml',
    'query_terms': './config/query-terms.yaml',
    'source_paths': ['./input'],
    'source_recursive': True,
    'work_dir': './work',
    'output_dir': './output',
    'unknown_value': '未定義',
    'none_value': '無',

    'default_business_contexts': [],
    'active_scopes': [],
    'context_anchors': [],
    'excluded_scopes': [],
    'context_scope_detection': 'multi',
    # Last-resort structural fallback only. A stronger boundary (document, sheet,
    # heading, table, contiguous region, page) always wins. See afc-context.
    'context_fallback_block_window': 3,

    'source_structure': {
        'audit_required': True,
        'parse_nested_tables': True,
        'extract_text_boxes': True,
        'extract_embedded_images': True,
        'visual_extraction_when_available': False,
        'image_text_pending_is_review': True,
        'unsupported_structure_is_review': True,
    },
    'ocr': {
        'enabled': True,
        'engine': 'tesseract',
        'language': 'chi_tra+eng+vie',
        'min_confidence': 0.75,
        'allow_multimodal_fallback': False,
    },

    'context_knowledge_signals': {
        'enabled': True,
        'recover_within_selected_boundary': True,
        'preserve_literal_knowledge': True,
        'preserve_structured_facts': True,
        'audit_unselected_signal_candidates': True,
        # Generic words ("error", "code", "length") may mark a COLUMN HEADER as
        # signal-bearing, but must not select a content row on their own.
        'generic_terms_select_headers_only': True,
    },

    'query': {
        'mode': 'auto',
        'top_k': 12,
        'candidate_k': 40,
        'rerank_k': 8,
        'link_k': 16,
        'evidence_k': 16,
        'box_expand_k': 12,
        'default_box_hops': 0,
        'max_box_hops': 1,
        'default_card_hops': 0,
        'max_card_hops': 1,
        'max_query_terms': 12,
    },

    'coverage': {
        'ledger_required': True,
        'accounting_required': 1.0,
    },

    'extraction': {
        # Step 1 is written by the model, one ledger row per selected Source
        # Unit, so it is the one step that can run out of context mid-run.
        # plan_extraction_batches.py bounds a batch to this many units and keeps
        # a document section, sheet or table together where it fits.
        'max_units_per_batch': 120,
    },

    'card_health': {
        'saturation_green_lt': 0.02,
        'saturation_yellow_lte': 0.05,
        'novelty_green_lt': 0.02,
        'novelty_yellow_lte': 0.05,
        'atomicity_green_lt': 0.02,
        'atomicity_yellow_lte': 0.05,
        'review_green_lt': 0.02,
        'review_yellow_lte': 0.05,
        'unaccounted_required': 0.0,
        'unsupported_required': 0.0,
        # A rate is only graded when the review sample is large enough for the
        # green threshold to be distinguishable from zero. Below this, the
        # metric reports a count and is graded INSUFFICIENT_SAMPLE.
        'min_sample_for_rate_grading': 30,
    },

    'gold': {
        # Scoring a run against the gold set's known answers. A source string
        # the gold set names must be preserved exactly -- there is no sensible
        # floor below 1.0 for that -- while claim coverage allows for a claim a
        # reviewer later judges not worth a Card.
        'min_literal_preservation': 1.0,
        'min_claim_coverage': 0.9,
    },

    'skill_triggers': {
        # Share of trigger cases that must reach the intended skill. Selection
        # is probabilistic, so this is a floor on observed accuracy, not a
        # promise about any single request.
        'min_accuracy': 0.9,
    },

    'decision': {
        # When Card health is not READY, Step 2 requires a human decision whose
        # recorded health snapshot still matches the current health report.
        'required_when_not_ready': True,
    },

    'artifacts': {
        'field_master_excel': None,
        'card_master_jsonl': './output/knowledge_card_master.jsonl',
        'evidence_master_jsonl': './output/knowledge_evidence.jsonl',
        'card_links_jsonl': './output/knowledge_links.jsonl',
        'card_boxes_jsonl': './output/knowledge_boxes.jsonl',
        'card_box_memberships_jsonl': './output/knowledge_box_memberships.jsonl',
        'box_links_jsonl': './output/knowledge_box_links.jsonl',
        'card_contexts_jsonl': './output/knowledge_contexts.jsonl',
        'query_index_db': './work/query-index/afc-query.db',
        'id_registry': './work/id-registry.jsonl',
        'change_log': './work/knowledge-change-log.jsonl',
    },
}

_MARKERS = ('scripts', 'config')

_version_cache = {}


def package_version(home=None):
    """The runtime version, read from VERSION rather than restated in code.

    It is stamped into immutable release manifests, so a copy in a source file
    would silently outlive the release it describes.
    """
    root = Path(home).resolve() if home else find_afc_home()
    key = str(root)
    if key not in _version_cache:
        path = root / 'VERSION'
        _version_cache[key] = path.read_text(encoding='utf-8').strip() if path.exists() \
            else 'unknown'
    return _version_cache[key]


def _looks_like_home(p: Path) -> bool:
    return all((p / m).is_dir() for m in _MARKERS)


def find_afc_home(start=None):
    """Locate the AFC runtime root.

    Order: $AFC_HOME, an installed `.afc-card-experiment/` beside the caller,
    then the package root inferred from this file. Works in both the development
    layout (runtime at repo root) and the installed layout.
    """
    env = os.environ.get('AFC_HOME')
    if env:
        p = Path(env).expanduser()
        if _looks_like_home(p):
            return p.resolve()
    here = Path(start).resolve() if start else Path.cwd()
    for base in [here, *here.parents]:
        cand = base / '.afc-card-experiment'
        if _looks_like_home(cand):
            return cand.resolve()
        if _looks_like_home(base):
            return base.resolve()
    pkg_root = Path(__file__).resolve().parents[1]
    return pkg_root


def _deep_merge(base, override):
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


# Legacy v0.4.1 flat keys accepted for backward compatibility, mapped to their
# v0.5.0 nested home. Listed so an unmigrated settings.yaml keeps working.
_LEGACY_KEYS = {
    'query_mode': ('query', 'mode'),
    'query_top_k': ('query', 'top_k'),
    'query_candidate_k': ('query', 'candidate_k'),
    'query_rerank_k': ('query', 'rerank_k'),
    'query_link_k': ('query', 'link_k'),
    'query_evidence_k': ('query', 'evidence_k'),
    'query_box_expand_k': ('query', 'box_expand_k'),
    'query_default_box_hops': ('query', 'default_box_hops'),
    'query_max_box_hops': ('query', 'max_box_hops'),
    'query_default_card_hops': ('query', 'default_card_hops'),
    'query_max_card_hops': ('query', 'max_card_hops'),
    'coverage_ledger_required': ('coverage', 'ledger_required'),
    'coverage_accounting_required': ('coverage', 'accounting_required'),
    'context_neighbor_window': ('context_fallback_block_window',),
    'field_master_excel': ('artifacts', 'field_master_excel'),
    'card_master_jsonl': ('artifacts', 'card_master_jsonl'),
    'evidence_master_jsonl': ('artifacts', 'evidence_master_jsonl'),
    'card_links_jsonl': ('artifacts', 'card_links_jsonl'),
    'card_boxes_jsonl': ('artifacts', 'card_boxes_jsonl'),
    'card_box_memberships_jsonl': ('artifacts', 'card_box_memberships_jsonl'),
    'box_links_jsonl': ('artifacts', 'box_links_jsonl'),
    'card_contexts_jsonl': ('artifacts', 'card_contexts_jsonl'),
    'query_index_db': ('artifacts', 'query_index_db'),
}


class Settings:
    def __init__(self, data, home, path=None, migrated=None):
        self.data = data
        self.home = Path(home)
        self.path = Path(path) if path else None
        self.migrated_legacy_keys = migrated or []

    def get(self, dotted, default=None):
        node = self.data
        for part in dotted.split('.'):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def resolve(self, dotted, default=None):
        """Resolve a configured path against the AFC home directory."""
        val = self.get(dotted, default)
        if val in (None, ''):
            return None
        p = Path(str(val)).expanduser()
        return p if p.is_absolute() else (self.home / p).resolve()

    def query(self, key):
        return self.get(f'query.{key}', DEFAULTS['query'][key])

    def card_health(self, key):
        return self.get(f'card_health.{key}', DEFAULTS['card_health'][key])

    def __repr__(self):
        return f'Settings(home={self.home}, path={self.path})'


_cache = {}


def load_settings(path=None, home=None, use_cache=True):
    home = Path(home).resolve() if home else find_afc_home()
    cfg_path = Path(path).resolve() if path else (home / 'config' / 'settings.yaml')
    # The persistent Knowledge Base root changes the ID registry/change-log
    # destinations even when the runtime settings file is the same.
    key = (str(cfg_path), str(home), os.environ.get('AFC_KB_ROOT'))
    if use_cache and key in _cache:
        return _cache[key]
    raw = {}
    if cfg_path.exists():
        if yaml is None:
            raise RuntimeError('PyYAML is required to read settings.yaml')
        raw = yaml.safe_load(cfg_path.read_text(encoding='utf-8')) or {}
    migrated = []
    for legacy, target in _LEGACY_KEYS.items():
        if legacy in raw:
            node = raw
            for part in target[:-1]:
                node = node.setdefault(part, {})
            node.setdefault(target[-1], raw[legacy])
            migrated.append(legacy)
    data = _deep_merge(DEFAULTS, raw)
    kb_root = os.environ.get('AFC_KB_ROOT')
    if kb_root:
        identity_path = (Path(kb_root).expanduser().resolve() / 'identity' / 'id-registry.jsonl')
        data.setdefault('artifacts', {})['id_registry'] = str(identity_path)
    s = Settings(data, home, cfg_path if cfg_path.exists() else None, migrated)
    if use_cache:
        _cache[key] = s
    return s
