#!/usr/bin/env python3
"""Avana trace logger + fake-tool dispatcher.

Subcommands:
  start                      -> begin a new session log, print its path
  msg <role> <text>          -> log a user/assistant message (deduped)
  tool <name> <json-args>    -> log a tool call + a simulated result, print the result JSON
  human <name> <role> <text> -> log a human-agent message (for handoff demos)
  end [summary]              -> log session_end
  view                       -> build logs/_view.js for trace.html (all sessions)

Messages are normally logged automatically by the hooks in .claude/settings.json;
the model only needs to call `tool` when it uses a tool.
"""
import sys, os, json, glob, random, datetime

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS_DIR)
LOGDIR = os.path.join(ROOT, "logs")
CURRENT = os.path.join(LOGDIR, "CURRENT")


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def append(path, obj):
    with open(path, "a") as f:
        f.write(json.dumps(obj) + "\n")


def start_session():
    os.makedirs(LOGDIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(LOGDIR, f"session-{stamp}.jsonl")
    open(CURRENT, "w").write(path)
    append(path, {"t": now(), "type": "system", "kind": "session_start",
                  "text": f"Session started · {stamp}"})
    return path


def current_log():
    if os.path.exists(CURRENT):
        p = open(CURRENT).read().strip()
        if p and os.path.exists(p):
            return p
    return start_session()


ACTIVE_SID = os.path.join(LOGDIR, "ACTIVE_SID")


def _active_sid():
    try:
        return open(ACTIVE_SID).read().strip()
    except Exception:
        return ""


def rotate_if_new(sid):
    """Start a fresh log when Claude Code's session_id changes, so sessions never mix."""
    if not sid or sid == _active_sid():
        return
    start_session()
    os.makedirs(LOGDIR, exist_ok=True)
    with open(ACTIVE_SID, "w") as f:
        f.write(sid)


def last_event(path):
    try:
        lines = [l for l in open(path) if l.strip()]
        return json.loads(lines[-1]) if lines else None
    except Exception:
        return None


def gen(prefix, n=4):
    return f"{prefix}-{random.randint(10 ** (n - 1), 10 ** n - 1)}"


def simulate(name, args):
    lat = random.randint(200, 600)
    if name == "lookup_patient":
        r = {"patient_id": args.get("patient_id") or gen("P", 5), "verified": True,
             "recent_visits": [{"visit_id": "V-20614", "dept": "Cardiology", "date": "2026-06-01"}],
             "_stub": True}
    elif name == "lookup_visit":
        r = {"visit_id": args.get("visit_id", "V-?????"), "dept": "(demo stub)",
             "date": "(demo)", "billing_status": "unknown", "_stub": True}
    elif name == "lookup_staff":
        r = {"staff_id": gen("S"), "name": args.get("name", "(staff)"), "role": "RN",
             "unit": args.get("unit", "-"), "manager": "(manager on file)", "_stub": True}
    elif name == "log_complaint":
        r = {"complaint_id": gen("CMP"), "status": "open", "routed_to": "Patient Experience Team"}
    elif name == "send_compliment":
        r = {"recognition_id": gen("REC"), "routed_to": ["staff member", "their manager"],
             "channels": ["unit_huddle", "recognition_file"]}
    elif name == "escalate_to_billing":
        r = {"ticket_id": gen("BIL"), "sla": "2 business days", "owner": "Billing Resolution"}
    elif name == "escalate_to_human":
        pr = args.get("priority", "normal")
        r = {"handoff_id": gen("H"), "queue": args.get("reason", "general"), "priority": pr,
             "est_wait": "immediate" if pr == "urgent" else "under 1 min"}
    elif name == "schedule_callback":
        r = {"callback_id": gen("CB"), "window": args.get("window", "(tbd)"),
             "topic": args.get("topic", "")}
    else:
        r = {"_stub": True, "echo": args}
    return r, lat


def cmd_msg(role, text):
    path = current_log()
    le = last_event(path)
    if le and le.get("type") == role and le.get("text") == text:
        return  # dedup (Stop hook can fire repeatedly)
    append(path, {"t": now(), "type": role, "text": text})


def cmd_tool(name, args_json):
    path = current_log()
    try:
        args = json.loads(args_json) if args_json else {}
    except Exception:
        args = {"_raw": args_json}
    append(path, {"t": now(), "type": "tool_call", "name": name, "args": args})
    r, lat = simulate(name, args)
    append(path, {"t": now(), "type": "tool_result", "name": name, "status": "ok",
                  "latency_ms": lat, "result": r})
    print(json.dumps(r))


def cmd_human(name, role, text):
    append(current_log(), {"t": now(), "type": "human", "name": name, "role": role, "text": text})


def cmd_end(text=""):
    append(current_log(), {"t": now(), "type": "system", "kind": "session_end",
                           "text": text or "Session ended"})


def cmd_hook_start():
    """SessionStart hook: rotate to a fresh log keyed to this Claude Code session."""
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    rotate_if_new(data.get("session_id"))


def cmd_hook_prompt():
    """UserPromptSubmit hook: read hook JSON from stdin, log the patient message."""
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    rotate_if_new(data.get("session_id"))
    p = (data.get("prompt") or "").strip()
    if p:
        cmd_msg("user", p)


MODEL_PRETTY = {
    "claude-opus-4-8": "Opus 4.8", "claude-opus-4-7": "Opus 4.7", "claude-opus-4-6": "Opus 4.6",
    "claude-sonnet-4-6": "Sonnet 4.6", "claude-sonnet-4-5": "Sonnet 4.5",
    "claude-haiku-4-5": "Haiku 4.5", "claude-fable-5": "Fable 5",
}


def prettify_model(m):
    if not m:
        return "unknown"
    for k, v in MODEL_PRETTY.items():
        if m.startswith(k):
            return v
    return m


def _transcript_dir():
    return os.path.join(os.path.expanduser("~/.claude/projects"), ROOT.replace("/", "-"))


def _newest_transcript():
    """Find the newest Claude Code transcript for this project directory."""
    files = sorted(glob.glob(os.path.join(_transcript_dir(), "*.jsonl")), key=os.path.getmtime)
    return files[-1] if files else None


def _model_map():
    """Map assistant reply text -> model id, across all transcripts for this project."""
    m = {}
    for fp in glob.glob(os.path.join(_transcript_dir(), "*.jsonl")):
        try:
            for line in open(fp):
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                msg = o.get("message") or {}
                if msg.get("role") == "assistant" and msg.get("model"):
                    t = _assistant_text(msg)
                    if t:
                        m[t] = msg["model"]
        except Exception:
            pass
    return m


def relabel_models():
    """Backfill the real model id onto assistant events that don't have one yet."""
    mp = _model_map()
    if not mp:
        return
    for fp in glob.glob(os.path.join(LOGDIR, "session-*.jsonl")):
        out, changed = [], False
        for line in open(fp):
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                out.append(line)
                continue
            if o.get("type") == "assistant" and not o.get("model"):
                mdl = mp.get(o.get("text"))
                if mdl:
                    o["model"] = mdl
                    changed = True
            out.append(json.dumps(o))
        if changed:
            with open(fp, "w") as f:
                f.write("\n".join(out) + "\n")


def _logged_texts(path, role):
    out = set()
    try:
        for l in open(path):
            l = l.strip()
            if not l:
                continue
            o = json.loads(l)
            if o.get("type") == role and o.get("text"):
                out.add(o["text"])
    except Exception:
        pass
    return out


def _assistant_text(msg):
    c = msg.get("content")
    if isinstance(c, list):
        return "".join(b.get("text", "") for b in c
                       if isinstance(b, dict) and b.get("type") == "text").strip()
    if isinstance(c, str):
        return c.strip()
    return ""


def backfill_assistant(transcript_path, session_path=None):
    """Append any assistant replies in the transcript that aren't logged yet.

    Scans the WHOLE transcript (not just the last message) so a missed Stop is
    recovered on the next one. Uses the transcript's own timestamps (converted to
    local time) and dedupes by exact text.
    """
    if not (transcript_path and os.path.exists(transcript_path)):
        return 0
    path = session_path or current_log()
    have = _logged_texts(path, "assistant")
    added = 0
    for line in open(transcript_path):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        msg = obj.get("message") or {}
        if msg.get("role") != "assistant":
            continue
        text = _assistant_text(msg)
        if not text or text in have:
            continue
        ts = obj.get("timestamp")
        try:
            t = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().isoformat(timespec="seconds")
        except Exception:
            t = now()
        append(path, {"t": t, "type": "assistant", "text": text, "model": msg.get("model")})
        have.add(text)
        added += 1
    return added


def cmd_hook_reply():
    """Stop hook: read hook JSON from stdin, backfill assistant replies from the transcript."""
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    rotate_if_new(data.get("session_id"))
    tp = data.get("transcript_path") or _newest_transcript()
    backfill_assistant(tp)


def build_traces():
    """Reconcile logs and return the list of trace objects (shared by `view` and the server)."""
    # Backstop: backfill any assistant replies the Stop hook missed for the current session.
    if os.path.exists(CURRENT):
        backfill_assistant(_newest_transcript(), open(CURRENT).read().strip())
    relabel_models()  # stamp the real model id onto assistant events
    files = sorted(glob.glob(os.path.join(LOGDIR, "session-*.jsonl")))
    traces = []
    for fp in files:
        events = [json.loads(l) for l in open(fp) if l.strip()]
        if len(events) <= 1:
            continue  # skip empty sessions (just a session_start)
        events.sort(key=lambda e: e.get("t", ""))  # chronological, in case of backfill
        # keep session_end as the terminal event even if a pleasantry came after it
        ends = [e for e in events if e.get("type") == "system" and e.get("kind") == "session_end"]
        if ends:
            events = [e for e in events if e not in ends] + ends
        tools = sorted({e["name"] for e in events if e.get("type") == "tool_call"})
        # real model: most recent assistant event that carries one
        model = "unknown"
        for e in events:
            if e.get("type") == "assistant" and e.get("model"):
                model = prettify_model(e["model"])
        base = os.path.basename(fp).replace(".jsonl", "")
        tags = ["live"] + (["human_handoff"] if any(e.get("type") == "human" for e in events) else [])
        traces.append({
            "trace_id": base, "session_id": base, "scenario": "Live chat session",
            "persona": "(captured live via Claude Code)", "channel": "claude_code",
            "model": model, "started_at": events[0]["t"],
            "context": {"summary": "Captured live: you chatting with Avana in Claude Code. "
                                    "Messages logged by hooks; tool calls by the dispatcher.",
                        "patient": {"name": "(live patient)", "patient_id": "-", "verified": False}},
            "outcome": {"status": "live", "tags": tags, "tools_used": tools},
            "events": events})
    return traces


def cmd_view():
    traces = build_traces()
    out = os.path.join(LOGDIR, "_view.js")
    with open(out, "w") as f:
        f.write("window.TRACES = " + json.dumps(traces, indent=2) + ";\n")
        f.write('window.__BUILT = ' + json.dumps(now()) + ';\n')
    print(f"Wrote {out} ({len(traces)} session(s)). "
          f"Open avana-live/trace.html and reload to view.")


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        return
    c = a[0]
    if c == "start":
        print(start_session())
    elif c == "msg":
        cmd_msg(a[1], a[2] if len(a) > 2 else "")
    elif c == "tool":
        cmd_tool(a[1], a[2] if len(a) > 2 else "")
    elif c == "human":
        cmd_human(a[1], a[2], a[3])
    elif c == "end":
        cmd_end(a[1] if len(a) > 1 else "")
    elif c == "hook-start":
        cmd_hook_start()
    elif c == "hook-prompt":
        cmd_hook_prompt()
    elif c == "hook-reply":
        cmd_hook_reply()
    elif c == "view":
        cmd_view()
    else:
        print("unknown subcommand:", c)


if __name__ == "__main__":
    main()
