#!/usr/bin/env bash
# Verify a Codex installation. Kept so existing instructions keep working;
# verify_install.sh does the work and also verifies Claude Code installs.
set -euo pipefail
exec bash "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/verify_install.sh" "${1:-.}" --target codex
