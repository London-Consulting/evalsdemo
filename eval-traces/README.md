# Avana eval dataset — review & label in the trace viewer

A folder of 20 synthetic Avana conversations (12 with deliberate failures, 8 handled
correctly). You review each one in the **same trace viewer** as the live logs and assign
your own **pass/fail + reason** — the human-labeling step of building evals.

## Layout
- `traces/ev_01.json … ev_20.json` — one conversation per file (same event shape as the
  live logs). Each carries a `suggested` hint (an AI-proposed verdict + reason) you can
  accept or override — it is **not** your label.
- `annotations.json` — **your** labels live here, written by the viewer:
  `{ "ev_08": { "verdict": "fail", "reason": "…", "labeled_at": "…" }, … }`

## Review and label
Just start the viewer — it offers **both** the live demo sessions and this dataset, and
you switch between them with the **source dropdown** in the top-right (no restart):
```bash
cd /Users/elise/Repos/evals/avana-live
python3 tools/serve.py
# open http://127.0.0.1:8787/  → pick "Eval dataset (20)" or "Live sessions" up top
```
(`--dir <folder>` still works to add another dataset to the dropdown.) Each source keeps
its **own** `annotations.json`, so labels never cross between live and dataset.

In the browser:
- The left sidebar lists all 20 traces; the dot shows your label state (`○` unlabeled,
  `✓` pass, `✗` fail).
- Open a trace → a **labeling panel** sits above the conversation: click **Pass** or
  **Fail**, type your reasoning in the box, and **Save label** (written to
  `annotations.json`). **Clear** removes a label.
- The 💡 *Suggested* line offers an AI starting point — **use this** copies it into your
  verdict + reason so you can edit rather than start blank.
- **Patient view** hides tool calls/system events; **View raw JSON** shows the trace.

## The deliberate failures (for reference)
| Trace | Category | What goes wrong |
|---|---|---|
| `ev_01`–`ev_03` | angry_capitulation | escalates on anger alone (no verify/info), or over-promises a fix |
| `ev_04`–`ev_07` | lack_of_context | fabricates prior-chat memory / ticket status, forgets in-session, skips ID verification |
| `ev_08`–`ev_11` | improper_payout | grants refund / waives charge / approves credit / negotiates discount with no authority |
| `ev_12` | medical_advice | gives medication dosing advice |
| `ev_13`–`ev_20` | *_handled_well | the same situations handled correctly (contrast set) |

## Why this matters for evals
Your `annotations.json` becomes the **gold labels** for the eval suite: the `verdict` is
the ground truth a code/LLM-judge eval is scored against, and your `reason` captures the
rationale that turns into the eval's rubric. Point the server at a different `--dir` to
label other datasets (e.g. captured live sessions) the same way.

## Create a judge from these labels
[`judge-creator-prompt.md`](judge-creator-prompt.md) is a teaching template: hand an LLM
your golden annotations and it writes you a judge that reproduces them.

## Run the LLM judge against these labels
`tools/judge.py` scores each trace with an LLM-as-judge (run through Claude Code headless,
so **no API key** is needed) and reports agreement with the gold labels:
```bash
cd /Users/elise/Repos/evals/avana-live
python3 tools/judge.py --dir ../eval-traces          # judge all 20 + score vs gold
```
Gold comes from `annotations.json` (your labels) if present, else each trace's baked-in
`suggested.verdict`. Where the judge and the gold **disagree** is the signal: either the
judge needs a sharper rubric (`RUBRIC` in `judge.py`) or the human label deserves a second
look.
