# Avana — patient-experience eval demo

A self-contained demo of running a Claude Code agent **in character** as a customer-facing
assistant, capturing every session as a structured trace, and reviewing/labeling those
traces in a local viewer — the human-labeling step of building evals.

Everything lives in [`avana-live/`](avana-live/):

- **In-character agent** — Claude Code runs as *Avana*, the patient-experience assistant
  for a fictional health system, taking real (simulated) tool actions.
- **Automatic tracing** — hooks log each session to `avana-live/logs/*.jsonl`.
- **Trace viewer + labeler** — `tools/serve.py` serves a browser viewer where you inspect
  each conversation, switch between data sources, and assign pass/fail labels with reasons.
- **LLM-as-judge** — `tools/judge.py` scores traces against Avana's behavior spec and
  reports agreement with the human labels. Runs through Claude Code headless (no API key).

A labeled eval dataset lives alongside in [`eval-traces/`](eval-traces/) (20 conversations
with seeded failures) — the judge scores ~95% agreement with its gold labels.

## Quick start

```bash
cd avana-live
# 1. Chat with Avana: launch Claude Code inside avana-live/ and talk to it as a patient.
# 2. Review the captured sessions:
python3 tools/serve.py
# open http://127.0.0.1:8787/   (use 127.0.0.1, not localhost)
```

See [`avana-live/README.md`](avana-live/README.md) for the full walkthrough and the
prompt-iteration loop, and [`avana-live/CLAUDE.md`](avana-live/CLAUDE.md) for Avana's
behavior spec.
