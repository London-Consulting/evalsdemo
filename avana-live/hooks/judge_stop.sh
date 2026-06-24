#!/usr/bin/env bash
# Stop hook (DEMO) — after each assistant reply, run the judge on the current session and
# surface the verdict to the user via systemMessage. Wired to Stop *for visibility*: it
# fires every turn and slows the session, so it is NOT where you'd judge in production
# (use SessionEnd or an offline run for that). The message itself says so.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CUR="$ROOT/logs/CURRENT"
[ -f "$CUR" ] || exit 0
SID="$(basename "$(cat "$CUR")" .jsonl)"
# --hook makes judge.py print ONE {"systemMessage": ...} JSON line, which Claude Code shows.
python3 "$ROOT/tools/judge.py" --session "$SID" --hook
exit 0
