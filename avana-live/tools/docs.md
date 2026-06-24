# Noridoc: tools

Path: @/avana-live/tools

### Overview
- The Python backend for the Avana demo: a fake-tool dispatcher + trace logger, an LLM-as-judge, a local trace-viewer server, and the judge's unit tests.
- Turns live Claude Code chat sessions (where the model role-plays "Avana") into structured traces, then scores those traces with a selectable LLM judge.
- The judge is pluggable: a named-rubric registry (`JUDGES`) is the single extension point that feeds the CLI, the HTTP API, and the browser viewer alike.

### How it fits into the larger codebase
- This folder is the engine behind the role-play harness defined one level up in [avana-live/CLAUDE.md](../CLAUDE.md) and wired by [avana-live/.claude/settings.json](../.claude/settings.json). Claude Code loads the persona, and the shell hooks in [avana-live/hooks/](../hooks) call into `avana.py` to log every turn.
- `avana.py` is the producer of trace data; `judge.py` and `serve.py` are its two consumers. Both import `avana.py` dynamically (see below) rather than as a package, so this folder has no `__init__.py` and is not meant to be installed.
- The viewer UI is the sibling [avana-live/trace.html](../trace.html), a single static page that `serve.py` serves and talks to over a tiny JSON API (`/data`, `/engines`, `/judges`, `/judge`, `/annotate`).
- The bundled eval dataset and gold labels live outside this folder in [eval-traces/](../../eval-traces) (trace `*.json` files plus `annotations.json`); `judge.py --dir` and `serve.py --dir` both point at it. User-facing usage is documented in [avana-live/README.md](../README.md) and [eval-traces/README.md](../../eval-traces/README.md) — this doc covers the internals, not the workflow.
- The `SessionEnd` hook [avana-live/hooks/judge_session.sh](../hooks/judge_session.sh) invokes `judge.py --session` so every finished chat is auto-graded into `logs/verdicts.jsonl` with no human in the loop.

### Core Implementation
- **`avana.py`** — entry point for the model's tool calls (`tool`/`human`/`end`) and for building traces. It simulates tool results (ticket ids, SLAs, handoff ids) and appends events to `logs/session-*.jsonl`, and `build_traces()` reconciles those logs into trace objects. Every trace shares one event shape (`user` / `assistant` / `human` / `tool_call` / `tool_result`), which is the contract `transcript()` and the viewer rely on.
- **`judge.py`** — the LLM-as-judge. Key structure:
  - `JUDGES = {"safety": SAFETY_RUBRIC, "tone": TONE_RUBRIC}` is the registry; `DEFAULT_JUDGE = "safety"`; `RUBRIC = SAFETY_RUBRIC` is a back-compat alias.
  - `judge(t, scratch, engine="claude", model=None, judge_name=DEFAULT_JUDGE)` looks the rubric up via `JUDGES[judge_name]`, renders the trace with `transcript()`, dispatches to one engine, and parses the verdict.
  - Two engine backends both take the rubric as a parameter: `_claude(prompt, model, scratch, rubric)` (Claude Code headless, no API key, run from a scratch cwd) and `_ollama(prompt, model, rubric)` (local HTTP).
  - `main()` is the CLI: `--judge`, `--engine`, `--model`, `--dir`, `--session`, validating `--judge` against `JUDGES` before running.
- **`serve.py`** — a stdlib HTTP server for [trace.html](../trace.html). Loads `avana.py` and `judge.py` via `importlib`, exposes the JSON API, and persists manual labels to `<dir>/annotations.json` via `POST /annotate`. `/judges` returns `list(judge.JUDGES)`; `/judge` reads engine/model/judge query params and delegates straight to `judge.judge(...)`.
- **`test_judge.py`** — stdlib `unittest`. Stubs only the LLM boundary (`_claude` / `_ollama`); everything else (rubric selection, `judge()`, `main()`, verdict parsing) runs for real against the [eval-traces](../../eval-traces) dataset.

### Things to Know
- **The registry is the only extension point.** Adding a key to `JUDGES` in `judge.py` makes a new judge appear automatically in the CLI (`--judge`), the `/judges` endpoint, and the viewer's **Judge:** dropdown — no other file needs editing. This fan-out is the reason all three layers read the registry instead of hardcoding names.
- **Engine is orthogonal to judge.** Any judge runs over any engine; the rubric is threaded through both `_claude` and `_ollama` so the two axes (which LLM vs. which rubric) compose freely.
- **Output contract is fixed:** every judge must return exactly `{"verdict": "pass"|"fail", "reason": "<one sentence>"}`. `judge()` slices from the first `{` to the last `}` to tolerate models that wrap the JSON in prose, so rubrics must keep that single-object shape.
- **Gold labels are safety-oriented.** Scoring "agreement with gold" only makes sense for the `safety` judge; the `tone` judge produces real verdicts but the bundled gold in `annotations.json` / each trace's `suggested.verdict` is not tone-labeled, so its agreement number is not meaningful until tone gold is hand-labeled.
- **`RUBRIC` is a deliberate alias, not dead code.** It preserves the pre-registry name (`judge.RUBRIC`) for any caller that imported the single default rubric before judges were named.
- **Dynamic loading, not imports.** `serve.py` (and `judge.py` for `avana`) load sibling modules with `importlib.util` from an absolute path so the tools work when run as loose scripts from any cwd; there is intentionally no package layout.
- **The judge must not inherit Avana's persona.** `_claude` runs in a throwaway scratch dir (`tempfile.mkdtemp`) so the headless judge does not pick up [avana-live/CLAUDE.md](../CLAUDE.md) and start role-playing as Avana instead of evaluating it.
- An unknown `judge_name` raises `KeyError` at the `JUDGES[...]` lookup; callers guard against this up front — `main()` exits with a message and `serve.py`'s `/judge` returns HTTP 400.

Created and maintained by Nori.
