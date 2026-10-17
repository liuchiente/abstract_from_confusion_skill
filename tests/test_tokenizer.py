"""Chinese retrieval regression tests.

These exist because of a v0.4.1 defect: `tokenize()` emitted an unbroken CJK run
of four characters or fewer as a single token, and the FTS expression used exact
terms only. Indexing 「加買失敗」 and querying 「加買」 therefore returned nothing,
while Vietnamese and English were unaffected -- so the failure was invisible to
anyone testing in a space-delimited language.
"""
import re
import sqlite3

from afc_card_runtime.common import (FTS5_RESERVED, TOKENIZER_VERSION, cjk_ngrams,
                                     fts_or_expr, fts_terms, normalize_text, tokenize)


def build_search_text(text):
    """Mirror build_query_index.search_tokens()."""
    text = normalize_text(text).lower()
    codes = re.findall(r'(?<![A-Za-z0-9_])[A-Za-z]{1,8}[0-9]{0,4}(?![A-Za-z0-9_])', text)
    vals = []
    for x in [*tokenize(text), *codes]:
        x = normalize_text(x).replace('"', ' ')
        if x and x not in vals:
            vals.append(x)
    return ' '.join(vals)


def make_index(docs):
    con = sqlite3.connect(':memory:')
    con.execute("CREATE VIRTUAL TABLE t USING fts5(id UNINDEXED, search_text, tokenize='unicode61')")
    for doc_id, text in docs.items():
        con.execute('INSERT INTO t VALUES (?,?)', (doc_id, build_search_text(text)))
    return con


def search(con, query):
    expr = fts_or_expr(fts_terms(query, min_len=2, limit=12))
    if not expr:
        return []
    return [r[0] for r in con.execute('SELECT id FROM t WHERE t MATCH ? ORDER BY bm25(t)', (expr,)).fetchall()]


DOCS = {
    'E1': '加買失敗',
    'E2': '無法加買，請聯繫業務員',
    'E3': 'Tải lên thất bại',
    'E4': '確認頁 Back 返回並保留已輸入資料',
    'E5': 'Component Type = textbox, Max Length = 20',
}


def test_short_chinese_query_finds_short_chinese_value():
    con = make_index(DOCS)
    assert 'E1' in search(con, '加買')
    assert 'E1' in search(con, '失敗')
    assert 'E1' in search(con, '加買失敗')


def test_chinese_query_inside_longer_run():
    con = make_index(DOCS)
    assert 'E4' in search(con, '返回')
    assert 'E4' in search(con, '保留已輸入資料')
    assert 'E4' in search(con, '確認頁')


def test_latin_and_vietnamese_still_work():
    con = make_index(DOCS)
    assert 'E3' in search(con, 'thất bại')
    assert 'E3' in search(con, 'tải')
    assert 'E5' in search(con, 'textbox')
    assert 'E5' in search(con, 'Max Length')


def test_fts_reserved_words_are_never_emitted():
    for word in FTS5_RESERVED:
        assert word not in fts_terms(f'A {word} B')
    # A query written with a bare operator must still be a valid expression.
    con = make_index(DOCS)
    assert search(con, '加買 OR 失敗')


def test_cjk_ngrams_cover_every_substring_of_length_two_or_more():
    run = '保留已輸入資料'
    grams = set(cjk_ngrams(run))
    for n in (2, 3):
        for i in range(len(run) - n + 1):
            assert run[i:i + n] in grams


def test_whole_run_is_emitted_for_exact_match_ranking():
    assert '加買失敗' in tokenize('加買失敗')


def test_single_character_runs_survive():
    assert tokenize('A 的 B') == ['a', '的', 'b']


def test_tokenizer_version_is_declared():
    # ensure_query_index.py rebuilds a stale index by comparing this value;
    # changing tokenize() without bumping it would leave indexes silently wrong.
    assert TOKENIZER_VERSION and TOKENIZER_VERSION.isdigit()


# Golden fingerprint of tokenize() over a fixed corpus, pinned to
# TOKENIZER_VERSION. Changing tokenize() without bumping that version leaves
# every existing query index silently matching against the old segmentation --
# which is how a Vietnamese tokenization regression survived into a built index
# during development of this release. If this test fails because you changed the
# tokenizer deliberately: bump TOKENIZER_VERSION, update the hash below, and
# every index rebuilds on next use.
TOKENIZER_CORPUS = [
    '加買失敗', '無法加買，請聯繫業務員', '確認頁 Back 返回並保留已輸入資料',
    'Tải lên thất bại', 'Sửa đơn và gửi lại', 'Component Type = textbox, Max Length = 20',
    'Return Code E102', 'CA 確認頁 Back 的行為是什麼？', '保單號碼', 'A 的 B',
]
TOKENIZER_FINGERPRINTS = {
    '2': '41867905b04ea4c7e44554414e1624ec2c7ed15f74fd11ee9889cb9d164b8e6e',
}


def test_tokenizer_behaviour_matches_its_declared_version():
    import hashlib
    import json as _json
    blob = _json.dumps([tokenize(x) for x in TOKENIZER_CORPUS], ensure_ascii=False)
    actual = hashlib.sha256(blob.encode('utf-8')).hexdigest()
    expected = TOKENIZER_FINGERPRINTS.get(TOKENIZER_VERSION)
    assert expected is not None, (
        f'TOKENIZER_VERSION {TOKENIZER_VERSION!r} has no recorded fingerprint; '
        f'add {actual!r} to TOKENIZER_FINGERPRINTS')
    assert actual == expected, (
        'tokenize() changed without bumping TOKENIZER_VERSION. Existing query '
        'indexes would keep matching against the old segmentation. Bump the '
        f'version and record the new fingerprint {actual!r}.')


def test_vietnamese_words_are_not_split_on_diacritics():
    # The regression this fingerprint exists to catch: a separate character class
    # for diacritics shredded "tải" into "t"/"ả"/"i".
    assert tokenize('Tải lên thất bại') == ['tải', 'lên', 'thất', 'bại']
    assert tokenize('Sửa đơn và gửi lại') == ['sửa', 'đơn', 'và', 'gửi', 'lại']
