#!/usr/bin/env python3
"""Dispatch an inventory's eligible source files to AFC format adapters."""
from pathlib import Path
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from afc_card_runtime.common import read_jsonl, write_jsonl

RUNTIME = Path(__file__).resolve().parents[1]
CODE_EXTENSIONS = {'.py', '.pyi', '.js', '.jsx', '.mjs', '.cjs', '.ts', '.tsx', '.java', '.dart', '.php', '.vue', '.html', '.htm', '.css', '.scss', '.kt', '.go', '.rs', '.rb', '.cs', '.cpp', '.c', '.h', '.hpp', '.swift'}
GROUPS = {
    'word': ({'.docx'}, 'parse_word.py'),
    'excel': ({'.xlsx', '.xlsm'}, 'parse_excel.py'),
    'pdf': ({'.pdf'}, 'parse_pdf.py'),
    'code': (CODE_EXTENSIONS, 'parse_code.py'),
    'text': ({'.md', '.markdown', '.txt', '.rst', '.csv', '.json', '.yaml', '.yml', '.xml'}, 'parse_text.py'),
}


def get_sources(eligible, kb_id, catalog_path):
    data = json.loads(Path(eligible).read_text(encoding='utf-8'))
    paths = data.get('paths') if isinstance(data, dict) else data
    if not isinstance(paths, list):
        raise ValueError('eligible source list must contain a paths array')
    sources = [Path(item).expanduser().resolve() for item in paths]
    if any(not path.is_file() for path in sources):
        missing = [str(path) for path in sources if not path.is_file()]
        raise FileNotFoundError('eligible source file is missing: ' + ', '.join(missing[:10]))
    catalog = Path(catalog_path)
    workspace = json.loads(catalog.read_text(encoding='utf-8'))
    if workspace.get('format') != 'afc-workspace-catalog':
        raise ValueError('invalid workspace catalog')
    rows = [row for row in workspace.get('knowledge_bases', []) if row.get('kb_id') == kb_id]
    if len(rows) != 1:
        raise KeyError(f'KB ID not registered exactly once: {kb_id}')
    roots = []
    for item in rows[0].get('source_roots', []):
        path = Path(item).expanduser()
        roots.append(path.resolve() if path.is_absolute() else (catalog.parent / path).resolve())
    for source in sources:
        if not any(source == root or root in source.parents for root in roots):
            raise ValueError(f'eligible file is outside registered roots for {kb_id}: {source}')
    return list(dict.fromkeys(sources)), roots


def main():
    ap = argparse.ArgumentParser(description='Route eligible files to Word, Excel, PDF, text and code parsers.')
    ap.add_argument('--kb-id', required=True)
    ap.add_argument('--eligible-list', required=True, help='inventory candidate/eligible-source-paths.json')
    ap.add_argument('--catalog', help='Workspace catalog; defaults to AFC_PROJECT_ROOT/afc-workspace.json')
    ap.add_argument('--output-dir', required=True)
    ap.add_argument('--media-dir', help='Directory for extracted embedded images')
    ap.add_argument('--pdf-profile', choices=['fast', 'article'], default='fast',
                    help='Opt in to layout-aware PDF block extraction and image Source Units for article/study-guide PDFs.')
    args = ap.parse_args()
    project = Path(os.environ.get('AFC_PROJECT_ROOT') or Path.cwd()).resolve()
    catalog = Path(args.catalog).expanduser() if args.catalog else project / 'afc-workspace.json'
    if not catalog.is_absolute():
        catalog = (project / catalog).resolve()
    sources, roots = get_sources(args.eligible_list, args.kb_id, catalog)
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    media_dir = Path(args.media_dir).expanduser().resolve() if args.media_dir else output_dir / 'source-media'
    media_dir.mkdir(parents=True, exist_ok=True)
    grouped = {key: [] for key in GROUPS}
    unsupported = []
    for path in sources:
        group = next((key for key, (extensions, _) in GROUPS.items() if path.suffix.lower() in extensions), None)
        if group:
            grouped[group].append(path)
        else:
            unsupported.append({'source_file': str(path), 'kind': 'unsupported-file-type',
                                'detail': f'No parser adapter is registered for {path.suffix or "(no extension)"}.'})
    outputs, reports = [], []
    for key, (_, script) in GROUPS.items():
        files = grouped[key]
        if not files:
            continue
        out = output_dir / f'step-card-0-{key}-source-units.jsonl'
        report = output_dir / f'step-card-0-{key}-structure-report.json'
        parser_python = (os.environ.get('AFC_CODE_PYTHON') or sys.executable) if key == 'code' else sys.executable
        command = [parser_python, str(RUNTIME / 'scripts' / script), *map(str, files),
                   '-o', str(out), '--structure-report', str(report)]
        for root in roots:
            command += ['--source-root', str(root)]
        if key in {'word', 'excel'}:
            command += ['--media-dir', str(media_dir)]
        elif key == 'pdf':
            command += ['--profile', args.pdf_profile]
            if args.pdf_profile == 'article':
                command += ['--media-dir', str(media_dir)]
        try:
            subprocess.run(command, check=True, cwd=str(RUNTIME), env={**os.environ, 'AFC_HOME': str(RUNTIME)})
        except subprocess.CalledProcessError:
            # A parser can still emit useful Source Units and a report while
            # reporting unsupported structures; leave the report for review.
            if not out.exists() or not report.exists():
                raise
        outputs.append(out)
        reports.append(report)
    if unsupported:
        report = output_dir / 'step-card-0-unsupported-structure-report.json'
        report.write_text(json.dumps({'report_schema_version': '2', 'parser': 'parse_sources.py',
                                      'files': [], 'parser_gaps': [], 'unsupported_structures': unsupported},
                                     ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        reports.append(report)
    combined = []
    for output in outputs:
        combined.extend(read_jsonl(output))
    combined.sort(key=lambda row: (
        str(row.get('source_path', '')).casefold(), int(row.get('page') or 0),
        int(row.get('block_index') or 0), int(row.get('image_index') or 0),
        str(row.get('source_unit_id', ''))))
    combined_path = output_dir / 'step-card-0-source-units.jsonl'
    write_jsonl(combined_path, combined)
    result = {'kb_id': args.kb_id, 'eligible_files': len(sources),
              'source_units': len(combined), 'parser_outputs': [str(path) for path in outputs],
              'structure_reports': [str(path) for path in reports],
              'unsupported_file_count': len(unsupported), 'combined_output': str(combined_path)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if unsupported else 0


if __name__ == '__main__':
    raise SystemExit(main())
