#!/usr/bin/env bash
# Install for Codex. Kept so existing instructions keep working; install.sh does
# the work and also installs for Claude Code with --target claude or both.
set -euo pipefail
exec bash "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/install.sh" "${1:-.}" --target codex
