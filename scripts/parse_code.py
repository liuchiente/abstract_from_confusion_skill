#!/usr/bin/env python3
"""Extract source-preserving code units without importing or executing projects.

Python uses the standard-library AST. Java, Dart, JavaScript/TypeScript, PHP,
HTML templates, Vue single-file components and stylesheets use tree-sitter-language-pack.
"""
from pathlib import Path
import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from afc_card_runtime.common import write_jsonl, source_prefix

RUNTIME = Path(__file__).resolve().parents[1]
CODE_LANGUAGES = {
    '.java': 'java', '.dart': 'dart',
    '.js': 'javascript', '.jsx': 'javascript', '.mjs': 'javascript', '.cjs': 'javascript',
    '.ts': 'typescript', '.tsx': 'tsx', '.php': 'php', '.vue': 'vue',
    '.html': 'html', '.htm': 'html', '.css': 'css', '.scss': 'scss',
}
CODE_EXTENSIONS = {
    '.py', '.pyi', *CODE_LANGUAGES.keys(),
    '.kt', '.go', '.rs', '.rb', '.cs', '.cpp', '.c', '.h', '.hpp', '.swift',
}
CLASS_NODES = {
    'class_declaration', 'interface_declaration', 'enum_declaration',
    'record_declaration', 'annotation_type_declaration', 'class_definition',
    'mixin_declaration', 'extension_declaration', 'trait_declaration',
}
FUNCTION_NODES = {
    'method_declaration', 'constructor_declaration', 'compact_constructor_declaration',
    'method_definition', 'function_declaration', 'generator_function_declaration',
    'function_definition', 'method_signature', 'function_signature',
}
IMPORT_NODES = {
    'import_declaration', 'import_statement', 'import_or_export',
    'namespace_use_declaration', 'use_declaration',
}
CALL_NODES = {
    'method_invocation', 'call_expression', 'function_call_expression',
    'function_call', 'invocation_expression',
}
COMPONENT_NODES = {'template_element', 'script_element', 'style_element'}
STYLE_NODES = {'rule_set', 'rule'}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def files_from(inputs, recursive=True):
    files = []
    for raw in inputs:
        path = Path(raw).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f'source path does not exist: {path}')
        if path.is_file():
            if path.suffix.lower() in CODE_EXTENSIONS:
                files.append(path)
            continue
        iterator = path.rglob('*') if recursive else path.iterdir()
        files.extend(item.resolve() for item in iterator
                     if item.is_file() and item.suffix.lower() in CODE_EXTENSIONS
                     and not any(part.startswith('.') or part in {
                         '__pycache__', 'node_modules', 'vendor', 'dist', 'build',
                     } for part in item.relative_to(path).parts[:-1]))
    return sorted(set(files), key=lambda item: str(item).casefold())


def git_revision(path, cache):
    directory = Path(path).parent
    while True:
        if directory in cache:
            return cache[directory]
        try:
            result = subprocess.run(['git', '-C', str(directory), 'rev-parse', '--show-toplevel'],
                                    check=True, capture_output=True, text=True)
            root = Path(result.stdout.strip()).resolve()
            revision = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'],
                                      check=True, capture_output=True, text=True).stdout.strip()
            cache[directory] = {'repository_root': str(root), 'revision': revision}
            return cache[directory]
        except (subprocess.CalledProcessError, FileNotFoundError):
            if directory.parent == directory:
                cache[directory] = {'repository_root': None, 'revision': None}
                return cache[directory]
            directory = directory.parent


def code_metadata(path, roots, text, language, revision, symbol, kind, start, end,
                  ordinal, value=None, **extra):
    prefix = source_prefix(path, roots)
    qualified = '.'.join(part for part in symbol if part)
    return {
        'source_unit_id': f'{prefix}::CODE::{language}::{kind.upper()}::{qualified}::{ordinal}',
        'source_file': path.name, 'source_path': str(path),
        'kind': 'paragraph', 'parent_kind': 'code-symbol',
        'value': text if value is None else value, 'text': text if value is None else value,
        'source_hash': sha256(path), 'source_language': language,
        'code_symbol': qualified, 'code_symbol_kind': kind,
        'code_line_start': start, 'code_line_end': end,
        'repository_root': revision['repository_root'],
        'repository_revision': revision['revision'], **extra,
    }


class PythonSymbolVisitor(ast.NodeVisitor):
    def __init__(self, path, roots, lines, digest, revision):
        self.path, self.roots, self.lines = path, roots, lines
        self.digest, self.revision = digest, revision
        self.records, self.scope, self.ordinal = [], [], {}

    def visit_ClassDef(self, node):
        self._symbol(node, 'class')
        self.scope.append(node.name)
        for child in node.body:
            self.visit(child)
        self.scope.pop()

    def visit_FunctionDef(self, node):
        self._symbol(node, 'function')
        self.scope.append(node.name)
        for child in node.body:
            self.visit(child)
        self.scope.pop()

    def visit_AsyncFunctionDef(self, node):
        self._symbol(node, 'async-function')
        self.scope.append(node.name)
        for child in node.body:
            self.visit(child)
        self.scope.pop()

    def _symbol(self, node, symbol_kind):
        name = '.'.join([*self.scope, node.name])
        self.ordinal[name] = self.ordinal.get(name, 0) + 1
        start = min([node.lineno, *[getattr(item, 'lineno', node.lineno)
                                   for item in getattr(node, 'decorator_list', [])]])
        end = getattr(node, 'end_lineno', None) or node.lineno
        source = ''.join(self.lines[start - 1:end])
        imports, calls = python_imports_and_calls(node)
        row = code_metadata(self.path, self.roots, source, 'python', self.revision,
                            [name], symbol_kind, start, end, self.ordinal[name],
                            code_docstring=ast.get_docstring(node, clean=False),
                            code_imports=imports, code_calls=calls)
        # Preserve the v0.8 Source Unit IDs for Python so existing inventories
        # do not see a parser refactor as a new identity scheme.
        row['source_unit_id'] = f'{source_prefix(self.path, self.roots)}::SYMBOL::{name}::{self.ordinal[name]}'
        row['block_index'] = len(self.records) + 1
        row['paragraph_style'] = 'Code ' + symbol_kind
        row['source_hash'] = self.digest
        self.records.append(row)


def python_imports_and_calls(node):
    imports, calls = [], []
    for child in ast.walk(node):
        if isinstance(child, ast.Import):
            imports.extend(item.name for item in child.names)
        elif isinstance(child, ast.ImportFrom):
            imports.append('.' * (child.level or 0) + (child.module or ''))
        elif isinstance(child, ast.Call):
            target = child.func
            if isinstance(target, ast.Name):
                calls.append(target.id)
            elif isinstance(target, ast.Attribute):
                chain, base = [target.attr], target.value
                while isinstance(base, ast.Attribute):
                    chain.append(base.attr); base = base.value
                if isinstance(base, ast.Name):
                    chain.append(base.id)
                calls.append('.'.join(reversed(chain)))
    return sorted(set(imports)), sorted(set(calls))


def parse_python(path, roots, text, revision):
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    lines = text.splitlines(keepends=True)
    prefix = source_prefix(path, roots)
    module = {
        'source_unit_id': f'{prefix}::MODULE', 'source_file': path.name,
        'source_path': str(path), 'kind': 'paragraph', 'parent_kind': 'code-module',
        'value': text, 'text': text, 'block_index': 0, 'paragraph_style': 'Code module',
        'source_hash': digest, 'source_language': 'python', 'code_symbol': path.stem,
        'code_symbol_kind': 'module', 'code_line_start': 1, 'code_line_end': len(lines),
        'repository_root': revision['repository_root'], 'repository_revision': revision['revision'],
    }
    try:
        tree = ast.parse(text, filename=str(path), type_comments=True)
    except SyntaxError as exc:
        module.update({'code_parse_status': 'SYNTAX_ERROR', 'code_parse_error': str(exc)})
        return [module], [{'source_file': str(path), 'kind': 'python-syntax-error',
                           'line': exc.lineno, 'detail': str(exc)}]
    visitor = PythonSymbolVisitor(path, roots, lines, digest, revision)
    visitor.visit(tree)
    return [module, *visitor.records], []


def node_text(node, raw):
    return raw[node.start_byte:node.end_byte].decode('utf-8', errors='replace')


def first_name(node, raw):
    for field in ('name', 'function'):
        value = node.child_by_field_name(field)
        if value is not None and field == 'name':
            return node_text(value, raw).strip()
    for candidate in walk_nodes(node):
        if candidate is not node:
            value = candidate.child_by_field_name('name')
            if value is not None:
                return node_text(value, raw).strip()
    for candidate in walk_nodes(node):
        if candidate.type in {'identifier', 'type_identifier', 'property_identifier', 'tag_name', 'name'}:
            return node_text(candidate, raw).strip()
    return node.type


def walk_nodes(node):
    yield node
    for child in node.children:
        for descendant in walk_nodes(child):
            yield descendant


def function_variable(node):
    if node.type != 'variable_declarator':
        return False
    value = node.child_by_field_name('value')
    return value is not None and value.type in {'arrow_function', 'function_expression', 'function'}


def node_end(node, raw):
    end = node.end_point.row + 1
    if node.type in {'method_signature', 'function_signature'} and node.parent is not None:
        siblings = node.parent.children
        try:
            index = siblings.index(node)
        except ValueError:
            index = -1
        if index >= 0 and index + 1 < len(siblings) and siblings[index + 1].type in {
            'function_body', 'block', 'function_expression_body',
        }:
            end = siblings[index + 1].end_point.row + 1
    return end


def declaration_kind(node, language):
    if node.type == 'function_signature' and node.parent is not None and node.parent.type == 'method_signature':
        return None
    if node.type in CLASS_NODES:
        return node.type.removesuffix('_declaration').removesuffix('_definition')
    if node.type in FUNCTION_NODES or function_variable(node):
        if node.type in {'method_declaration', 'method_definition', 'method_signature'}:
            return 'method'
        if node.type in {'constructor_declaration', 'compact_constructor_declaration'}:
            return 'constructor'
        if function_variable(node):
            return 'function'
        return 'function'
    if language == 'html' and node.type == 'element':
        return 'html-element'
    if language == 'vue' and node.type in COMPONENT_NODES:
        return 'vue-' + node.type.replace('_element', '')
    if language in {'css', 'scss'} and node.type in STYLE_NODES:
        return 'style-rule'
    if node.type in IMPORT_NODES:
        return 'import'
    return None


def collect_calls(node, raw):
    calls = []
    for candidate in walk_nodes(node):
        if candidate.type not in CALL_NODES:
            continue
        target = (candidate.child_by_field_name('name') or
                  candidate.child_by_field_name('function') or
                  candidate.child_by_field_name('method'))
        if target is None and candidate.children:
            target = candidate.children[0]
        if target is not None:
            calls.append(node_text(target, raw).strip())
    return sorted(set(item for item in calls if item))[:100]


def parse_tree_source(path, roots, raw, text, language, revision, parser):
    tree = parser.parse(raw)
    if tree is None:
        return [], [{'source_file': str(path), 'kind': 'parse-failed',
                     'detail': f'{language} parser returned no syntax tree'}]
    prefix = source_prefix(path, roots)
    digest = hashlib.sha256(raw).hexdigest()
    lines = text.splitlines(keepends=True)
    records = [{
        'source_unit_id': f'{prefix}::MODULE', 'source_file': path.name,
        'source_path': str(path), 'kind': 'paragraph', 'parent_kind': 'code-module',
        'value': text, 'text': text, 'block_index': 0, 'paragraph_style': 'Code module',
        'source_hash': digest, 'source_language': language,
        'code_symbol': path.stem, 'code_symbol_kind': 'module',
        'code_line_start': 1, 'code_line_end': len(lines),
        'repository_root': revision['repository_root'], 'repository_revision': revision['revision'],
    }]
    ordinal, emitted = {}, set()

    def visit(node, scope):
        kind = declaration_kind(node, language)
        if kind:
            name = first_name(node, raw)
            if kind == 'import':
                name = node_text(node, raw).strip().replace('\n', ' ')[:240]
            qualified = [*scope, name]
            key = (node.start_byte, node.end_byte, kind)
            if key not in emitted:
                emitted.add(key)
                qualified_name = '.'.join(part for part in qualified if part)
                ordinal[qualified_name] = ordinal.get(qualified_name, 0) + 1
                start = node.start_point.row + 1
                end = node_end(node, raw)
                start = max(1, min(start, len(lines) or 1))
                end = max(start, min(end, len(lines) or start))
                source = node_text(node, raw)
                records.append({
                    'source_unit_id': f'{prefix}::SYMBOL::{language}::{qualified_name}::{ordinal[qualified_name]}',
                    'source_file': path.name, 'source_path': str(path),
                    'kind': 'paragraph', 'parent_kind': 'code-symbol',
                    'value': source, 'text': source, 'block_index': len(records),
                    'paragraph_style': 'Code ' + kind,
                    'source_hash': digest, 'source_language': language,
                    'code_symbol': qualified_name, 'code_symbol_kind': kind,
                    'code_line_start': start, 'code_line_end': end,
                    'code_imports': [source] if kind == 'import' else [],
                    'code_calls': collect_calls(node, raw),
                    'code_parse_has_errors': bool(node.has_error),
                    'repository_root': revision['repository_root'],
                    'repository_revision': revision['revision'],
                })
            next_scope = [*scope, name] if kind in CLASS_NODES or kind in {'class', 'interface', 'enum', 'trait', 'mixin', 'extension', 'record'} else scope
        else:
            next_scope = scope
        for child in node.children:
            visit(child, next_scope)

    visit(tree.root_node, [])
    unsupported = []
    if tree.root_node.has_error:
        unsupported.append({'source_file': str(path), 'kind': 'syntax-error-nodes',
                            'detail': f'{language} tree contains error or missing nodes; emitted units require review'})
    return records, unsupported


def parse_vue(path, roots, raw, text, revision, get_parser):
    parser = get_parser('vue')
    tree = parser.parse(raw)
    if tree is None:
        return [], [{'source_file': str(path), 'kind': 'parse-failed', 'detail': 'vue parser returned no syntax tree'}]
    records, issues = parse_tree_source(path, roots, raw, text, 'vue', revision, parser)
    # Vue's grammar represents SFC script contents as raw_text. Parse each script
    # body with its declared dialect so Ionic Vue components expose symbols too.
    for node in walk_nodes(tree.root_node):
        if node.type != 'script_element':
            continue
        raw_node = next((item for item in node.children if item.type == 'raw_text'), None)
        if raw_node is None:
            continue
        opening = raw[node.start_byte:raw_node.start_byte].decode('utf-8', errors='replace')
        lang = 'typescript' if ('lang="ts' in opening or "lang='ts" in opening) else 'javascript'
        body = raw[raw_node.start_byte:raw_node.end_byte]
        body_text = body.decode('utf-8', errors='replace')
        script_parser = get_parser(lang)
        script_rows, script_issues = parse_tree_source(
            path, roots, body, body_text, lang, revision, script_parser,
        )
        line_offset = raw[:raw_node.start_byte].count(b'\n')
        for row in script_rows[1:]:
            row['source_unit_id'] = row['source_unit_id'].replace('::SYMBOL::', '::VUE-SCRIPT::', 1)
            row['code_line_start'] += line_offset
            row['code_line_end'] += line_offset
            row['code_symbol_kind'] = 'vue-script-' + row['code_symbol_kind']
            row['value'] = row['text']
            records.append(row)
        issues.extend(script_issues)
    return records, issues


def parse_other(path, roots, raw, text, language, revision):
    try:
        from tree_sitter_language_pack import PackConfig, configure, get_parser
    except Exception as exc:
        module = raw_module(path, text, roots, language, revision)
        return [module], [{'source_file': str(path), 'kind': 'code-parser-runtime-unavailable',
                           'detail': 'Install requirements-code.txt with Python 3.10+ and set AFC_CODE_PYTHON. ' + str(exc)}]
    cache = os.environ.get('AFC_CODE_PARSER_CACHE') or str(RUNTIME / 'cache' / 'code-parsers')
    try:
        configure(PackConfig(cache_dir=cache))
        parser = get_parser(language)
        if language == 'vue':
            return parse_vue(path, roots, raw, text, revision, get_parser)
        return parse_tree_source(path, roots, raw, text, language, revision, parser)
    except Exception as exc:
        module = raw_module(path, text, roots, language, revision)
        return [module], [{'source_file': str(path), 'kind': 'code-grammar-unavailable',
                           'detail': f'{language} grammar could not be loaded from the local parser cache: {exc}'}]


def raw_module(path, text, roots, language, revision):
    lines = text.splitlines(keepends=True)
    return {
        'source_unit_id': f'{source_prefix(path, roots)}::MODULE', 'source_file': path.name,
        'source_path': str(path), 'kind': 'paragraph', 'parent_kind': 'code-module',
        'value': text, 'text': text, 'block_index': 0, 'paragraph_style': 'Code module',
        'source_hash': sha256(path), 'source_language': language,
        'code_symbol': path.stem, 'code_symbol_kind': 'module',
        'code_line_start': 1, 'code_line_end': len(lines),
        'repository_root': revision['repository_root'], 'repository_revision': revision['revision'],
        'code_parse_status': 'RAW_SOURCE_ONLY',
    }


def parse_file(path, roots, revisions):
    raw = path.read_bytes()
    text = raw.decode('utf-8-sig', errors='replace')
    revision = git_revision(path, revisions)
    if path.suffix.lower() in {'.py', '.pyi'}:
        rows, issues = parse_python(path, roots, text, revision)
        return rows, 'python', issues
    language = CODE_LANGUAGES.get(path.suffix.lower())
    if not language:
        return ([raw_module(path, text, roots, 'unknown', revision)],
                'unsupported-language', [{'source_file': str(path), 'kind': 'unsupported-language',
                                           'detail': f'{path.suffix} has no structural adapter in this release'}])
    rows, issues = parse_other(path, roots, raw, text, language, revision)
    return rows, language, issues


def main():
    ap = argparse.ArgumentParser(description='Extract Python, Java, Dart, JS/TS, PHP, HTML, Vue and style code units without executing source code.')
    ap.add_argument('inputs', nargs='+', help='Code files or source directories')
    ap.add_argument('-o', '--output', required=True)
    ap.add_argument('--structure-report', help='Optional source structure report JSON')
    ap.add_argument('--source-root', action='append', default=[], help='Stable source boundary used for path-based Source Unit IDs')
    ap.add_argument('--no-recursive', action='store_true')
    args = ap.parse_args()
    if sys.version_info < (3, 10):
        ap.error('AFC requires Python 3.10 or newer')
    rows, issues, reports = [], [], []
    files = files_from(args.inputs, recursive=not args.no_recursive)
    revisions = {}
    language_counts = {}
    for path in files:
        parsed, language, file_issues = parse_file(path, args.source_root or args.inputs, revisions)
        rows.extend(parsed)
        issues.extend(file_issues)
        language_counts[language] = language_counts.get(language, 0) + 1
        reports.append({'source_file': str(path), 'language': language,
                        'source_units': len(parsed), 'syntax_issues': len(file_issues)})
    write_jsonl(args.output, rows)
    if args.structure_report:
        Path(args.structure_report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.structure_report).write_text(json.dumps({
            'report_schema_version': '2', 'parser': 'parse_code.py',
            'files': reports, 'parser_gaps': [], 'unsupported_structures': issues,
            'summary': {'files_parsed': len(files), 'source_units': len(rows),
                        'languages': language_counts, 'review_items': len(issues)},
        }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'files_parsed': len(files), 'source_units': len(rows),
                      'languages': language_counts, 'unsupported_or_review_items': issues,
                      'output': args.output}, ensure_ascii=False, indent=2))
    return 1 if issues else 0


if __name__ == '__main__':
    raise SystemExit(main())
