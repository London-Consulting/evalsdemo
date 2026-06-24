#!/usr/bin/env bash
# UserPromptSubmit hook — log the patient's message to the trace.
# Hook JSON arrives on stdin and is passed straight through to Python.
TOOLS="$(cd "$(dirname "${BASH_SOURCE[0]}")/../tools" && pwd)"
python3 "$TOOLS/avana.py" hook-prompt
exit 0
