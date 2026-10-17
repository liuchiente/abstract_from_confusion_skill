#!/usr/bin/env python3
"""Pre-download AFC's selected tree-sitter grammars for offline scans."""
from pathlib import Path
import argparse
import json
import os
import sys

RUNTIME = Path(__file__).resolve().parents[1]
LANGUAGES = ['java', 'dart', 'javascript', 'typescript', 'tsx', 'php', 'html', 'vue', 'css', 'scss']


def main():
    ap = argparse.ArgumentParser(description='Prepare local parsers for Java, Dart, JS/TS, PHP, HTML, Vue and CSS/SCSS.')
    ap.add_argument('--cache-dir', help='Base directory for grammar cache; defaults to <AFC_HOME>/cache/code-parsers')
    args = ap.parse_args()
    if sys.version_info < (3, 10):
        ap.error('code parser support requires Python 3.10 or newer; set AFC_PYTHON to that interpreter')
    try:
        from tree_sitter_language_pack import PackConfig, cache_dir, configure, download
    except ImportError as exc:
        ap.error('install requirements-code.txt into this Python environment first: ' + str(exc))
    cache = args.cache_dir or os.environ.get('AFC_CODE_PARSER_CACHE') or str(RUNTIME / 'cache' / 'code-parsers')
    configure(PackConfig(cache_dir=cache))
    count = download(LANGUAGES)
    print(json.dumps({'status': 'ready', 'languages': LANGUAGES,
                      'cached_language_count': count, 'cache_dir': cache_dir()},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
