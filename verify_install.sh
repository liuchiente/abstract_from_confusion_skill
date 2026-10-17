#!/usr/bin/env bash
# Verify an AFC Card Experiment installation, for either harness target.
#
#   verify_install.sh [repo] [--target codex|claude|both]
#
# Every check must end in PASS or FAIL and the script must always reach its
# verdict. An earlier version ran the launcher inside a plain assignment under
# `set -e`, so the single most common failure -- a default python3 older than
# 3.10 -- aborted the script after a screen of PASS lines, printed no FAIL and
# no verdict, and left its own `bad 'launcher ...'` branch unreachable.
set -uo pipefail
REPO='.'
TARGET="${AFC_TARGET:-both}"
while [ $# -gt 0 ]; do
  case "$1" in
    --target) TARGET="${2:-}"; shift 2 ;;
    --target=*) TARGET="${1#*=}"; shift ;;
    *) REPO="$1"; shift ;;
  esac
done
REPO="$(cd "$REPO" && pwd)"
HOME_DIR="$REPO/.afc-card-experiment"
PYTHON="${AFC_PYTHON:-python3}"
fail=0
pass() { echo "PASS $1"; }
bad()  { echo "FAIL $1"; fail=1; }

# Which locations this target installs into. Skills are copies of one source, so
# a difference between two installed copies means one was hand-edited.
SKILL_DIRS=(); RULES_FILES=(); MANIFESTS=()
case "$TARGET" in
  codex|both)
    SKILL_DIRS+=("$REPO/.codex/skills" "$REPO/.agents/skills")
    RULES_FILES+=("$REPO/AGENTS.md"); MANIFESTS+=("$REPO/.codex-plugin/plugin.json") ;;
esac
case "$TARGET" in
  claude|both)
    SKILL_DIRS+=("$REPO/.claude/skills")
    RULES_FILES+=("$REPO/CLAUDE.md"); MANIFESTS+=("$REPO/.claude-plugin/plugin.json") ;;
esac
if [ "${#SKILL_DIRS[@]}" -eq 0 ]; then
  echo "verify_install: --target must be codex, claude or both (got: $TARGET)" >&2; exit 2
fi

for s in afc-context afc-cards afc-links afc-boxes afc-domains afc-curate afc-discuss afc-update afc-publish afc-query afc-share afc-validate afc-pipeline afc-workspace; do
  missing=0
  for dir in "${SKILL_DIRS[@]}"; do
    [ -f "$dir/$s/SKILL.md" ] || { bad "skill $s ($dir)"; missing=1; }
  done
  [ "$missing" -eq 1 ] && continue
  first="${SKILL_DIRS[0]}/$s"; differs=0
  for dir in "${SKILL_DIRS[@]}"; do
    diff -r -q "$first" "$dir/$s" >/dev/null 2>&1 || { differs=1; break; }
  done
  if [ "$differs" -eq 1 ]; then
    bad "skill $s differs between installed copies; reinstall to resync"
  else pass "skill $s"; fi
done

for p in check_skill_scope.py sync_skill_metadata.py parse_word.py parse_excel.py parse_pdf.py parse_text.py parse_code.py parse_sources.py prepare_code_parser.py extract_ocr.py apply_visual_extractions.py knowledge_pack.py workspace.py \
         audit_source_structure.py build_context_candidates.py validate_context_selection.py \
         plan_extraction_batches.py merge_extraction_batches.py \
         allocate_ids.py sample_units.py compute_review_metrics.py evaluate_card_health.py \
         record_decision.py record_changes.py validate_schema.py validate_cards.py \
         validate_evidence.py validate_links.py validate_boxes.py validate_coverage.py \
         build_query_index.py ensure_query_index.py query_fast.py resolve_boxes.py \
         run_query_benchmark.py check_pipeline_artifacts.py knowledge_base.py selftest.py; do
  [ -f "$HOME_DIR/scripts/$p" ] && pass "script $p" || bad "script $p"
done

for c in settings.yaml business-contexts.yaml box-taxonomy.yaml knowledge-signals.yaml query-terms.yaml skill-scopes.yaml; do
  [ -f "$HOME_DIR/config/$c" ] && pass "config $c" || bad "config $c"
done

[ -d "$HOME_DIR/schemas" ] && pass 'schemas present' || bad 'schemas'
[ -f "$HOME_DIR/OPERATIONS.md" ] && pass 'operations manual present' || bad 'operations manual'
[ -f "$HOME_DIR/requirements-ocr.txt" ] && pass 'optional OCR requirements present' || bad 'optional OCR requirements'
[ -f "$HOME_DIR/requirements-code.txt" ] && pass 'optional code parser requirements present' || bad 'optional code parser requirements'
[ -d "$HOME_DIR/tests" ] && pass 'tests present' || bad 'tests'
[ -f "$HOME_DIR/templates/afc-scope.md" ] && pass 'Scope template present' || bad 'Scope template'

for f in "${RULES_FILES[@]}"; do
  [ -f "$f" ] && grep -q 'afc:begin' "$f" \
    && pass "$(basename "$f") carries the AFC section" \
    || bad "$(basename "$f") has no AFC section; the agent will not load the AFC rules"
done

for m in "${MANIFESTS[@]}"; do
  [ -f "$m" ] && pass "plugin manifest $(basename "$(dirname "$m")")/$(basename "$m")" \
    || bad "plugin manifest missing: $m"
done

# The launcher is the single path convention; without it every skill command
# fails. Capture its own message: "Python 3.10 or newer is required" is the
# answer the operator needs, not a bare non-zero exit.
launcher_ok=0
if [ -x "$REPO/afc" ]; then
  if resolved="$(cd "$REPO" && ./afc --home 2>&1)"; then
    if [ "$resolved" = "$HOME_DIR" ]; then pass "launcher resolves to $resolved"; launcher_ok=1
    else bad "launcher resolved to $resolved, expected $HOME_DIR"; fi
  else
    bad "launcher ./afc could not resolve the runtime: $resolved"
  fi
else
  bad 'launcher ./afc missing or not executable'
fi

# Settings must be readable by the runtime, not just present on disk. When the
# launcher is broken this cannot run, which is a reported failure, not a skip.
if [ "$launcher_ok" -eq 1 ]; then
  settings_error="$(cd "$REPO" && AFC_HOME="$HOME_DIR" "$PYTHON" -c "
import sys; sys.path.insert(0,'$HOME_DIR')
from afc_card_runtime.config import load_settings
s=load_settings()
assert s.path is not None, 'settings.yaml not found'
assert s.query('top_k'), 'query limits missing'
" 2>&1)" && pass 'settings.yaml is read by the runtime' \
    || bad "settings.yaml is present but the runtime could not read it: $(printf '%s' "$settings_error" | tail -1)"
else
  bad 'settings.yaml could not be checked because the launcher does not run'
fi

# Scope enforcement has to actually refuse something, or it is decoration.
if [ "$launcher_ok" -eq 1 ]; then
  if (cd "$REPO" && AFC_SKILL=afc-validate ./afc allocate_ids.py --help >/dev/null 2>&1); then
    bad 'skill scope is not enforced: afc-validate was allowed to run allocate_ids.py'
  else pass 'skill scope is enforced by the launcher'; fi
fi

if [ "$fail" -eq 0 ]; then
  echo "AFC Card Experiment install verification ($TARGET): PASS"
  echo 'Recommended next: ./afc check_environment.py && ./afc selftest.py'
else
  echo "AFC Card Experiment install verification ($TARGET): FAIL"; exit 1
fi
