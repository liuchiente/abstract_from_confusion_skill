# AFC scope for this directory

This file describes the product scope of source files in this directory.
The closest `afc-scope.md` to a file applies; a child file replaces the parent
file's defaults and exclusions for files beneath that child directory.

## 預設 Scope

- `<canonical_scope_id>` — Optional product scope code, such as `CA`.

## 排除 Scope

- 無。

Use canonical Scope IDs in both sections. `無。` means the section has no
entries. A run's explicit `--target-scope` can override the directory default;
an exclusion still blocks that Scope unless the run explicitly names it with
`--override-excluded-scope`.
