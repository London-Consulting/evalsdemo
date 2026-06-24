#!/usr/bin/env bash
# Stop hook — log Avana's reply (the last assistant message in the transcript).
# Hook JSON arrives on stdin and is passed straight through to Python.
TOOLS="$(cd "$(dirname "${BASH_SOURCE[0]}")/../tools" && pwd)"
sleep 0.4   # let Claude Code flush the final assistant message to the transcript
python3 "$TOOLS/avana.py" hook-reply
exit 0
