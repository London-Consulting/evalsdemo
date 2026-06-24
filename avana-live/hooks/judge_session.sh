#!/usr/bin/env bash
# SessionEnd hook — auto-run the LLM judge on the session that just ended.
# Reads the current session id from logs/CURRENT, scores it, and appends the
# verdict to logs/verdicts.jsonl. Output/errors go to logs/judge.log.
# Always exits 0 so a judge hiccup never blocks the session from closing.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CUR="$ROOT/logs/CURRENT"
[ -f "$CUR" ] || exit 0
SID="$(basename "$(cat "$CUR")" .jsonl)"        # e.g. session-20260623-203115
python3 "$ROOT/tools/judge.py" --session "$SID" >> "$ROOT/logs/judge.log" 2>&1
exit 0
