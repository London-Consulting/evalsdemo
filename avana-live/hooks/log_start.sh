#!/usr/bin/env bash
# SessionStart hook — rotate to a fresh log keyed to this Claude Code session.
# Hook JSON (incl. session_id) arrives on stdin and is passed through to Python.
TOOLS="$(cd "$(dirname "${BASH_SOURCE[0]}")/../tools" && pwd)"
python3 "$TOOLS/avana.py" hook-start
exit 0
