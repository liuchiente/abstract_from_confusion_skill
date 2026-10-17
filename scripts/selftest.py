#!/usr/bin/env python3
"""Run the AFC package self-test.

v0.4.1 shipped with no tests at all while advertising regression validation as a
core capability, so defects like the Chinese tokenizer and the self-certifying
parser gate could only be found by hand. `afc-validate` runs this first.
"""
from pathlib import Path
import argparse, subprocess, sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description='Run the AFC package self-test (pytest).')
    ap.add_argument('-k', help='pytest -k expression')
    ap.add_argument('-q', '--quiet', action='store_true')
    ap.add_argument('extra', nargs='*', help='Extra pytest arguments')
    a = ap.parse_args()
    try:
        import pytest  # noqa: F401
    except ImportError:
        print('pytest is not installed. Install the dev extras:\n'
              '  pip install -r requirements-dev.txt', file=sys.stderr)
        return 3
    cmd = [sys.executable, '-m', 'pytest', str(ROOT / 'tests')]
    cmd.append('-q' if a.quiet else '-ra')
    if a.k:
        cmd += ['-k', a.k]
    cmd += a.extra
    return subprocess.run(cmd, cwd=ROOT).returncode


if __name__ == '__main__':
    raise SystemExit(main())
