#!/usr/bin/env bash
# Install for Claude Code. install.sh does the work; both targets come from the
# same skills, scripts, config and rules template.
set -euo pipefail
exec bash "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/install.sh" "${1:-.}" --target claude
