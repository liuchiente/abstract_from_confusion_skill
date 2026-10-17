"""Article PDF section continuity and coverage grouping regressions."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import parse_pdf


def test_article_heading_context_continues_across_pages(tmp_path, monkeypatch):
    source = tmp_path / 'article.pdf'
    source.write_bytes(b'placeholder')
    output = tmp_path / 'units.jsonl'
    pages = [SimpleNamespace() for _ in range(4)]
    fake_metadata = SimpleNamespace(title='1c38609a-ac8f-413a-b5fb-c51d75c50a4d')
    monkeypatch.setattr(parse_pdf, 'PdfReader', lambda _: SimpleNamespace(pages=pages, metadata=fake_metadata, get_fields=lambda: {}))
    monkeypatch.setattr(parse_pdf, 'page_assets', lambda _: {'images': 0, 'annotations': 0})
    texts = iter([
        ('9.1 Risk\n\nRisk is uncertain.', 'mock'),
        ('9.2 Response\n\nA response reduces the selected threat.', 'mock'),
        ('9.2.1 Owner\n\nAssign a response owner.', 'mock'),
        ('The owner monitors the trigger.', 'mock'),
    ])
    monkeypatch.setattr(parse_pdf, 'extract_page_text', lambda *_: next(texts))
    monkeypatch.setattr(sys, 'argv', [
        'parse_pdf.py', str(source), '--profile', 'article', '-o', str(output),
        '--structure-report', str(tmp_path / 'structure.json'),
    ])

    parse_pdf.main()
    rows = [json.loads(line) for line in output.read_text(encoding='utf-8').splitlines()]
    page_one = next(row for row in rows if row.get('page') == 1 and row.get('heading_level'))
    page_two = next(row for row in rows if row.get('page') == 2 and row.get('heading_level'))
    page_three = next(row for row in rows if row.get('page') == 3 and row.get('heading_level'))
    page_four = next(row for row in rows if row.get('page') == 4)
    assert page_one['section_heading_path'] == ['Document: article', '9.1 Risk']
    assert page_two['section_heading_path'] == ['Document: article', '9.2 Response']
    assert page_three['section_heading_path'] == ['Document: article', '9.2 Response', '9.2.1 Owner']
    assert page_four['section_heading_path'] == ['Document: article', '9.2 Response', '9.2.1 Owner']
    assert page_four['section_key'] == page_three['section_key']


def test_section_metadata_changes_when_heading_path_changes():
    first = parse_pdf.section_metadata(['Chapter 2', '2.1 Risk'])
    second = parse_pdf.section_metadata(['Chapter 2', '2.2 Response'])
    assert first['section_heading_path_text'] == 'Chapter 2 / 2.1 Risk'
    assert first['section_key'] != second['section_key']


def test_coverage_report_groups_review_and_unaccounted_by_section(tmp_path):
    source = tmp_path / 'source.jsonl'
    coverage = tmp_path / 'coverage.jsonl'
    cards = tmp_path / 'cards.jsonl'
    source.write_text('\n'.join([
        json.dumps({'source_unit_id':'u1','selected':True,'kind':'pdf-block','source_file':'a.pdf','source_path':'/a.pdf','section_heading_path':['2.1 Risk'],'section_key':'risk'}),
        json.dumps({'source_unit_id':'u2','selected':True,'kind':'pdf-block','source_file':'a.pdf','source_path':'/a.pdf','section_heading_path':['2.1 Risk'],'section_key':'risk'}),
        json.dumps({'source_unit_id':'u3','selected':True,'kind':'pdf-block','source_file':'a.pdf','source_path':'/a.pdf','section_heading_path':['2.2 Response'],'section_key':'response'}),
    ]) + '\n', encoding='utf-8')
    coverage.write_text(json.dumps({'Source Unit ID':'u1','Disposition':'Review','Review Reason':'待核對來源意義'})+'\n', encoding='utf-8')
    cards.write_text('', encoding='utf-8')
    proc = __import__('subprocess').run([
        sys.executable, str(ROOT / 'scripts' / 'validate_coverage.py'),
        '--source-map', str(source), '--coverage', str(coverage), '--cards', str(cards),
    ], cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 2  # final accounting correctly rejects unassessed units
    report = json.loads(proc.stdout)
    risk = next(row for row in report['by_section'] if row['section_heading_path_text'] == '2.1 Risk')
    response = next(row for row in report['by_section'] if row['section_heading_path_text'] == '2.2 Response')
    assert (risk['selected'], risk['review'], risk['missing']) == (2, 1, 1)
    assert (response['selected'], response['review'], response['missing']) == (1, 0, 1)
