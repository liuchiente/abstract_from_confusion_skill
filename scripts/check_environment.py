#!/usr/bin/env python3
import importlib, sys
mods=['openpyxl','docx','yaml','pypdf']
missing=[]
for m in mods:
    try: importlib.import_module(m)
    except Exception as e: missing.append((m,str(e)))
print('python',sys.version.split()[0])
if sys.version_info < (3, 10):
    print('FAIL Python 3.10 or newer is required')
    raise SystemExit(1)
print('python_minimum PASS (>=3.10)')
for m in mods: print(m,'PASS' if all(x[0]!=m for x in missing) else 'FAIL')
raise SystemExit(1 if missing else 0)
