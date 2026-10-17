#!/usr/bin/env python3
"""Parse Markdown, plain text, HTML, CSV, and lightweight config files."""
from pathlib import Path
import argparse
import csv
import hashlib
from html.parser import HTMLParser
import json
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from afc_card_runtime.common import source_prefix, write_jsonl

EXTENSIONS = {'.md', '.markdown', '.txt', '.rst', '.html', '.htm', '.csv', '.json', '.yaml', '.yml', '.xml'}
BLOCK_TAGS = {'p', 'div', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'section', 'article', 'br'}


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks, self.current = [], []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in BLOCK_TAGS:
            self.flush()

    def handle_endtag(self, tag):
        if tag.lower() in BLOCK_TAGS:
            self.flush()

    def handle_data(self, data):
        value = data.strip()
        if value:
            self.current.append(value)

    def flush(self):
        text = ' '.join(self.current).strip()
        if text:
            self.blocks.append(text)
        self.current = []


def list_files(inputs, recursive):
    result = []
    for raw in inputs:
        path = Path(raw).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f'source path does not exist: {path}')
        if path.is_file():
            if path.suffix.lower() in EXTENSIONS:
                result.append(path)
        else:
            paths = path.rglob('*') if recursive else path.iterdir()
            result.extend(item.resolve() for item in paths
                          if item.is_file() and item.suffix.lower() in EXTENSIONS
                          and not any(part.startswith('.') for part in item.relative_to(path).parts[:-1]))
    return sorted(set(result), key=lambda item: str(item).casefold())


def main():
    ap = argparse.ArgumentParser(description='Extract ordered text, markup, CSV and config Source Units.')
    ap.add_argument('inputs', nargs='+')
    ap.add_argument('-o', '--output', required=True)
    ap.add_argument('--structure-report')
    ap.add_argument('--source-root', action='append', default=[])
    ap.add_argument('--no-recursive', action='store_true')
    args = ap.parse_args()
    rows, file_reports = [], []
    for path in list_files(args.inputs, not args.no_recursive):
        raw = path.read_bytes()
        text = raw.decode('utf-8-sig', errors='replace')
        digest = hashlib.sha256(raw).hexdigest()
        prefix = source_prefix(path, args.source_root or args.inputs)
        if path.suffix.lower() == '.csv':
            units = []
            for row_number, cells in enumerate(csv.reader(text.splitlines()), 1):
                if not any(str(cell).strip() for cell in cells):
                    continue
                units.append({'kind': 'table-row', 'row': row_number,
                              'cells': [{'column': i + 1, 'value': value} for i, value in enumerate(cells)],
                              'value': ' | '.join(cells)})
        else:
            if path.suffix.lower() in {'.html', '.htm'}:
                parser = VisibleText()
                parser.feed(text); parser.close(); parser.flush()
                chunks = parser.blocks
            elif path.suffix.lower() in {'.md', '.markdown'}:
                chunks = [part.strip() for part in re.split(r'\n\s*\n', text) if part.strip()]
            elif path.suffix.lower() in {'.json', '.yaml', '.yml', '.xml'}:
                chunks = [text] if text.strip() else []
            else:
                chunks = [part.strip() for part in re.split(r'\n\s*\n', text) if part.strip()]
            units = [{'kind': 'paragraph', 'block_index': i, 'value': chunk, 'text': chunk}
                     for i, chunk in enumerate(chunks)]
        for index, unit in enumerate(units, 1):
            rows.append({
                'source_unit_id': f'{prefix}::TXT{index:06d}',
                'source_file': path.name, 'source_path': str(path),
                'source_hash': digest, 'source_language': 'unknown',
                'encoding': 'utf-8', 'structure_path_text': f'Block {index}',
                **unit,
            })
        file_reports.append({'source_file': str(path), 'discovered': {'blocks': len(units)},
                             'extracted': {'blocks': len(units)}})
    write_jsonl(args.output, rows)
    if args.structure_report:
        Path(args.structure_report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.structure_report).write_text(json.dumps({
            'report_schema_version': '2', 'parser': 'parse_text.py',
            'files': file_reports, 'parser_gaps': [], 'unsupported_structures': [],
            'summary': {'files': len(file_reports), 'source_units': len(rows)},
        }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'files_parsed': len(file_reports), 'source_units': len(rows),
                      'output': args.output}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
