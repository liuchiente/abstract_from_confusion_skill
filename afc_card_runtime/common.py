from pathlib import Path
import json, os, re

# CJK ranges used for n-gram segmentation. SQLite FTS5 `unicode61` treats an
# unbroken CJK run as ONE token, so Chinese recall depends entirely on AFC
# emitting its own overlapping n-grams on BOTH the index and the query side.
CJK_RANGE = r'㐀-䶿一-鿿豈-﫿぀-ヿ'
# Latin letters, digits and Latin-script diacritics (Vietnamese included) form a
# SINGLE class: splitting them apart shreds "tải" into "t"/"ả"/"i".
_TOKEN_RE = re.compile(r'[A-Za-zÀ-ỹ0-9_]+|[' + CJK_RANGE + r']+', re.UNICODE)
_CJK_ONLY_RE = re.compile(r'^[' + CJK_RANGE + r']+$')

# FTS5 treats these bare words as operators. They must never be emitted as a term.
FTS5_RESERVED = {'and', 'or', 'not', 'near'}

# Query-side noise words. Applied symmetrically to index and query so they
# cancel out; they only exist to keep BM25 from ranking on interrogatives.
STOPWORDS = {'哪些', '是否', '有哪', '可以', '什麼', '如何', '相關', '哪些限制'}

# Longest CJK run emitted verbatim as an exact-match term alongside its n-grams.
MAX_WHOLE_RUN = 12

# Bump whenever tokenize() changes shape. A query index built by an older
# tokenizer cannot be matched against terms from a newer one, and source hashes
# alone would not notice -- the index would just quietly under-retrieve.
TOKENIZER_VERSION = '2'


def read_jsonl(path):
    p = Path(path)
    if not p.exists():
        return []
    out = []
    with p.open('r', encoding='utf-8') as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError(f'{path}:{lineno}: invalid JSON line: {e}') from e
    return out


def write_jsonl(path, rows):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('w', encoding='utf-8') as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')


def write_json(path, obj):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')
    return p


def read_json(path, default=None):
    if not path:
        return default
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding='utf-8'))


def normalize_text(v):
    if v is None:
        return ''
    return re.sub(r'\s+', ' ', str(v)).strip()


def cjk_ngrams(run, sizes=(2, 3)):
    """Overlapping n-grams for one unbroken CJK run.

    Every substring of length >= min(sizes) is reachable, so a short query term
    always has an index counterpart. This is the fix for the v0.4.1 failure where
    querying 「加買」 could not retrieve an Evidence Record reading 「加買失敗」.
    """
    out = []
    for n in sizes:
        if len(run) < n:
            continue
        out.extend(run[i:i + n] for i in range(len(run) - n + 1))
    return out


def tokenize(text):
    """Segment text into FTS terms.

    Latin/digit/Vietnamese words are kept whole. CJK runs always produce
    2-grams and 3-grams, plus the whole run (up to MAX_WHOLE_RUN) so that an
    exact phrase still scores higher than its fragments. Single-character runs
    are emitted as-is; callers decide whether to keep 1-char terms.
    """
    text = normalize_text(text).lower()
    out = []
    for part in _TOKEN_RE.findall(text):
        if _CJK_ONLY_RE.match(part):
            if len(part) == 1:
                out.append(part)
                continue
            out.extend(cjk_ngrams(part))
            if len(part) <= MAX_WHOLE_RUN:
                out.append(part)
        else:
            out.append(part)
    return [x for x in dict.fromkeys(out) if x and x not in STOPWORDS]


def fts_terms(text, min_len=2, limit=None):
    """Tokens safe to place inside an FTS5 MATCH expression."""
    vals = []
    for t in tokenize(text):
        t = normalize_text(t).replace('"', '')
        if len(t) < min_len:
            continue
        if t in FTS5_RESERVED:
            continue
        if t not in vals:
            vals.append(t)
    return vals[:limit] if limit else vals


def fts_or_expr(terms):
    """OR-join already-sanitised terms. Returns None when there is nothing to match."""
    safe = [normalize_text(t).replace('"', '') for t in terms or []]
    safe = [t for t in safe if t and t not in FTS5_RESERVED]
    return ' OR '.join('"' + t + '"' for t in safe) if safe else None


def source_prefix(file_path, roots=None):
    """Stable Source Unit ID prefix for a source file.

    The prefix uses a shared namespace across every containing registered root.
    This preserves relative paths while preventing identical paths in separate
    source folders from receiving the same ID.
    """
    fp = Path(file_path).resolve()
    normalized_roots = []
    for raw in roots or []:
        root = Path(raw).resolve()
        root = root.parent if root.is_file() else root
        if root not in normalized_roots:
            normalized_roots.append(root)
    candidates = []
    for root in normalized_roots:
        try:
            candidates.append((fp.relative_to(root), root))
        except ValueError:
            continue
    candidates.sort(key=lambda item: (len(item[0].parts), item[0].as_posix().casefold()))
    if not candidates:
        return Path(fp.name).as_posix()
    legacy_rel = candidates[0][0]
    collision = any(
        (other / legacy_rel).resolve() != fp and (other / legacy_rel).is_file()
        for other in normalized_roots
    )
    if collision:
        # Keep existing IDs for ordinary files; add the shared-root prefix only
        # when another registered root has the same relative path.
        try:
            common = Path(os.path.commonpath([str(root) for root in normalized_roots]))
        except ValueError:  # roots can live on separate Windows drive letters
            root = candidates[0][1]
            root_prefix = root.as_posix().replace(':', '').strip('/')
            return (Path(root_prefix) / legacy_rel).as_posix()
        return fp.relative_to(common).as_posix()
    rel = legacy_rel
    return rel.as_posix()
