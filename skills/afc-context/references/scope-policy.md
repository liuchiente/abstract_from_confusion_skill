# Scope policy and source boundaries

Read this before the first parse of a run, and whenever a source turns out
to sit outside the roots you were given. Scope decides what is in the run at
all, so getting it wrong is not recoverable later by extracting more.


For a product KB, the source folder is the primary boundary for one product scan. Put
`afc-scope.md` in each product directory and use canonical Scope IDs under
`預設 Scope` and `排除 Scope`. The nearest file applies; a child file replaces
the parent defaults and exclusions. Start from `templates/afc-scope.md` in the
runtime. `無。` is an explicit empty section.

`context.xml` is a mapping only: it maps company-approved Business Context
names/aliases to declared Scope IDs. The existing YAML mapping is also
supported. Neither mapping file selects source directories or defines
exclusions. For a run, use the Scope the user explicitly named; otherwise map a
requested Business Context and intersect it with the directory default; if no
Business Context was named, use the directory default. Apply exclusions after
that resolution. Only an explicit run option
`--override-excluded-scope <ScopeID>` overrides an exclusion.

Always pass the selected source root as `--scope-root` and the prompt's explicit
target as `--target-scope`. Repeat `--scope-root` for overlapping roots so Step 0
records each membership. If a parsed source path is outside all supplied roots,
do not widen the roots to make it eligible; correct the source selection.

A general/reference KB may explicitly use `scope_policy: not-applicable` in the
workspace catalog when product Scope does not apply. This removes only the
product-Scope filter; the registered and selected source folders still define
the scan boundary. Do not infer this policy for a product KB. Use the
`afc-workspace` skill to resolve the KB ID and policy before inventory.
