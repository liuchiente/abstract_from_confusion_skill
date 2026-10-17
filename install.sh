#!/usr/bin/env bash
# Install AFC Card Experiment into a repository, for Codex, Claude Code, or both.
#
# One source, two targets. The skills, scripts, config and rules are the same
# files for both harnesses; only where they are installed differs, and that
# mapping lives in `target_paths` below. Keeping two copies of the package was
# the alternative, and this package's own history is the argument against it:
# every drift defect it has fixed came from one fact stated in two places.
#
# v0.4.1 rewrote every SKILL.md during install to patch up two incompatible path
# conventions. That rewriting is gone: the skills call the `afc` launcher, which
# locates the runtime itself, so the files are copied verbatim and what you
# review is what runs.
#
#   install.sh [repo] [--target codex|claude|both]
#
set -euo pipefail

REPO='.'
TARGET="${AFC_TARGET:-both}"
while [ $# -gt 0 ]; do
  case "$1" in
    --target) TARGET="${2:-}"; shift 2 ;;
    --target=*) TARGET="${1#*=}"; shift ;;
    -h|--help)
      echo "usage: install.sh [repo] [--target codex|claude|both]"; exit 0 ;;
    *) REPO="$1"; shift ;;
  esac
done
case "$TARGET" in
  codex|claude|both) ;;
  *) echo "install.sh: --target must be codex, claude or both (got: $TARGET)" >&2; exit 2 ;;
esac

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$REPO" && pwd)"
VERSION="$(cat "$ROOT/VERSION")"
HOME_DIR="$REPO/.afc-card-experiment"
PYTHON="${AFC_PYTHON:-python3}"
mkdir -p "$HOME_DIR"

# Runtime assets are versioned and safe to replace.
for item in scripts schemas tests afc_card_runtime templates requirements.txt requirements-ocr.txt requirements-code.txt requirements-dev.txt \
            VERSION README.md AGENTS.md RUN_ALL.md MIGRATION.md OPERATIONS.md; do
  [ -e "$ROOT/$item" ] || continue
  rm -rf "$HOME_DIR/$item"
  cp -R "$ROOT/$item" "$HOME_DIR/$item"
done

# The launcher lives at the repo root so every skill can call `./afc <script>`.
cp "$ROOT/afc" "$REPO/afc"
chmod +x "$REPO/afc"

# Preserve user configuration on upgrade; new defaults land beside it as
# examples. skill-scopes.yaml is deliberately NOT in this list: it declares what
# each installed skill may run, so preserving an old copy would refuse commands
# the new skills document. It is package structure, like schemas/, and is
# replaced with the rest of the runtime.
mkdir -p "$HOME_DIR/config"
for f in "$ROOT"/config/*; do
  [ -f "$f" ] || continue
  name="$(basename "$f")"
  if [ ! -e "$HOME_DIR/config/$name" ]; then
    cp "$f" "$HOME_DIR/config/$name"
  else
    case "$name" in
      settings.yaml|company-context.md|business-contexts.yaml|box-taxonomy.yaml|knowledge-signals.yaml|query-terms.yaml|query-cases.yaml)
        base="${name%.*}"; ext="${name##*.}"
        cp "$f" "$HOME_DIR/config/${base}.v${VERSION}.example.${ext}" ;;
      *) cp "$f" "$HOME_DIR/config/$name" ;;
    esac
  fi
done

# Every skill and document writes extracted media to work/source-media.
mkdir -p "$HOME_DIR/work/query-runs" "$HOME_DIR/work/query-index" "$HOME_DIR/work/delta" \
         "$HOME_DIR/work/source-media" "$HOME_DIR/output" "$HOME_DIR/input"

install_skills_into() {
  local parent="$1"; mkdir -p "$parent"
  for d in "$ROOT"/skills/afc-*; do
    [ -d "$d" ] || continue
    name="$(basename "$d")"; target="$parent/$name"
    rm -rf "$target"; mkdir -p "$target"; cp -R "$d"/. "$target"/
  done
  echo "  skills  -> $parent"
}

install_manifest_into() {
  local source="$1" dest="$2"
  [ -f "$source" ] || return 0
  mkdir -p "$(dirname "$dest")"
  cp "$source" "$dest"
  echo "  plugin  -> $dest"
}

# The agent's rules have to live where the harness looks for them: AGENTS.md for
# Codex, CLAUDE.md for Claude Code, both at the repo root. An earlier version
# copied the package's own AGENTS.md into the runtime directory, a path no
# harness reads, so an installed repo ran with no AFC rules at all. One template
# fills both files; the block is delimited and replaced in place on upgrade,
# leaving whatever the repo already had in that file untouched.
install_rules_into() {
  local dest="$1"
  local section="$ROOT/templates/afc-rules.md"
  [ -f "$section" ] || return 0
  local begin='<!-- afc:begin -->'
  local end='<!-- afc:end -->'
  local staged="$HOME_DIR/.afc-rules-section.md"
  {
    printf '%s\n' "$begin"
    printf '<!-- Installed by install.sh v%s. Edit templates/afc-rules.md in the AFC package, not here: this block is replaced on upgrade. -->\n\n' "$VERSION"
    cat "$section"
    printf '%s\n' "$end"
  } > "$staged"
  if [ -f "$dest" ] && grep -qF "$begin" "$dest"; then
    "$PYTHON" - "$dest" "$staged" <<'PYMERGE'
import re, sys
target, section = sys.argv[1], sys.argv[2]
with open(target, encoding='utf-8') as f:
    text = f.read()
with open(section, encoding='utf-8') as f:
    block = f.read().rstrip('\n')
text = re.sub(r'<!-- afc:begin -->.*?<!-- afc:end -->', lambda _: block, text,
              count=1, flags=re.DOTALL)
with open(target, 'w', encoding='utf-8') as f:
    f.write(text)
PYMERGE
    echo "  rules   -> $dest (updated in place)"
  else
    if [ -f "$dest" ] && [ -s "$dest" ]; then printf '\n' >> "$dest"; fi
    cat "$staged" >> "$dest"
    echo "  rules   -> $dest"
  fi
  rm -f "$staged"
}

# Where each harness looks. This is the only place the two targets differ.
target_paths() {
  case "$1" in
    codex)
      # Codex reads .codex/skills; .agents/skills is the AGENTS.md-convention
      # location other harnesses look in. Both are copies of skills/ in this
      # package, replaced whole on every install, and the verifier fails if they
      # differ -- so edit the package, never an installed copy.
      SKILL_DIRS=("$REPO/.codex/skills" "$REPO/.agents/skills")
      RULES_FILE="$REPO/AGENTS.md"
      MANIFEST_SOURCE="$ROOT/.codex-plugin/plugin.json"
      MANIFEST_DEST="$REPO/.codex-plugin/plugin.json" ;;
    claude)
      SKILL_DIRS=("$REPO/.claude/skills")
      RULES_FILE="$REPO/CLAUDE.md"
      MANIFEST_SOURCE="$ROOT/.claude-plugin/plugin.json"
      MANIFEST_DEST="$REPO/.claude-plugin/plugin.json" ;;
  esac
}

INSTALLED=()
for one in codex claude; do
  case "$TARGET" in
    both) ;;
    "$one") ;;
    *) continue ;;
  esac
  target_paths "$one"
  echo "$one:"
  for dir in "${SKILL_DIRS[@]}"; do install_skills_into "$dir"; done
  install_manifest_into "$MANIFEST_SOURCE" "$MANIFEST_DEST"
  install_rules_into "$RULES_FILE"
  INSTALLED+=("$one")
done

cat <<MSG

AFC Card Experiment v$VERSION installed for: ${INSTALLED[*]}
  runtime : $HOME_DIR
  launcher: $REPO/afc        (try: ./afc --home, ./afc --list, ./afc --scope afc-cards)

Existing settings/company-context/taxonomy/signal files were preserved when
present; new defaults are beside them as *.v$VERSION.example.*. The skill scope
manifest is package structure and was replaced.
Knowledge data is kept in a separate Knowledge Base directory. This installer
does not move or rewrite existing Knowledge Base data; use OPERATIONS.md to
register existing Knowledge Bases and MIGRATION.md for version upgrades.

Next:
  "$PYTHON" -m pip install -r "$HOME_DIR/requirements.txt"
  # For local OCR: install Tesseract + language packs, then "$PYTHON" -m pip install -r "$HOME_DIR/requirements-ocr.txt"
  # Optional Java/Dart/JS/TS/PHP parsing: install requirements-code.txt with the AFC Python 3.10+ interpreter
  ./afc check_environment.py
  "$PYTHON" -m pip install -r "$HOME_DIR/requirements-dev.txt" && ./afc selftest.py   # optional but recommended
  bash "$ROOT/verify_install.sh" "$REPO" --target $TARGET

Read $HOME_DIR/OPERATIONS.md for multi-KB setup, scanning, updates, queries,
portable packs, and OCR-first setup. See MIGRATION.md for version upgrades.

Then start a NEW session from inside $REPO
MSG
