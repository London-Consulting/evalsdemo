#!/usr/bin/env python3
"""Local server for the Avana trace viewer + manual labeling.

Point it at any folder of traces and review/label them in the browser:

    python3 tools/serve.py                       # live avana-live logs (default)
    python3 tools/serve.py --dir /path/to/dataset  # a folder of *.json traces

A data folder is either:
  * the live logs dir (contains session-*.jsonl) — traces are built/reconciled, OR
  * a dataset dir containing trace files as *.json (optionally in a traces/ subfolder).

Your pass/fail labels, reasons, and tags are saved to <dir>/annotations.json via POST
/annotate, so the viewer is a real eval-authoring tool: you judge each trace, write up
why, and tag/categorize it. Tags start from the trace's auto tags and are editable; your
saved tags override them. Nothing is written back to the trace files themselves.
"""
import json, os, sys, glob, importlib.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
PORT = int(os.environ.get("AVANA_PORT", "8787"))
LOGS = os.path.join(ROOT, "logs")

_spec = importlib.util.spec_from_file_location("avana", os.path.join(TOOLS, "avana.py"))
avana = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(avana)


def _arg_dirs():
    dirs = []
    for i, a in enumerate(sys.argv):
        if a == "--dir" and i + 1 < len(sys.argv):
            dirs.append(os.path.abspath(sys.argv[i + 1]))
    env = os.environ.get("AVANA_DATA_DIR")
    if env:
        dirs.append(os.path.abspath(env))
    return dirs


def build_sources():
    """Ordered list of {id,label,dir} the viewer can switch between in the UI.

    Always offers the live logs; auto-includes the bundled eval dataset and any
    folder passed via --dir / $AVANA_DATA_DIR — so a bare `serve.py` shows both."""
    srcs, seen = [], set()

    def add(sid, label, d):
        d = os.path.abspath(d)
        if d in seen or not os.path.isdir(d):
            return
        seen.add(d)
        srcs.append({"id": sid, "label": label, "dir": d})

    add("live", "Live sessions", LOGS)
    for d in _arg_dirs():
        add(os.path.basename(d) or "dataset", os.path.basename(d) or "dataset", d)
    add("eval-traces", "Eval dataset", os.path.join(os.path.dirname(ROOT), "eval-traces"))
    return srcs


SOURCES = build_sources()
SOURCES_BY_ID = {s["id"]: s for s in SOURCES}


def resolve(sid):
    return SOURCES_BY_ID.get(sid) or SOURCES[0]


def annot_path(d):
    return os.path.join(d, "annotations.json")


def load_annotations(d):
    try:
        return json.load(open(annot_path(d)))
    except Exception:
        return {}


def save_annotation(d, tid, verdict, reason, tags=None):
    a = load_annotations(d)
    tags = [t for t in (tags or []) if t]      # drop blanks
    if verdict is None and not reason and not tags:
        a.pop(tid, None)                       # clearing a label
    else:
        a[tid] = {"verdict": verdict, "reason": reason or "", "tags": tags,
                  "labeled_at": avana.now()}
    os.makedirs(d, exist_ok=True)
    with open(annot_path(d), "w") as f:
        json.dump(a, f, indent=2)
    return a.get(tid)


def _trace_files(d):
    files = [f for f in glob.glob(os.path.join(d, "*.json"))
             if os.path.basename(f) != "annotations.json"]
    files += glob.glob(os.path.join(d, "traces", "*.json"))
    return sorted(files)


def build(d):
    files = _trace_files(d)
    if files:                                  # dataset mode: load *.json traces
        traces = []
        for f in files:
            try:
                traces.append(json.load(open(f)))
            except Exception:
                pass
    elif os.path.abspath(d) == LOGS:           # live mode: build from session logs
        traces = avana.build_traces()
    else:
        traces = []
    ann = load_annotations(d)
    for t in traces:
        t["annotation"] = ann.get(t.get("trace_id"), {"verdict": None, "reason": "", "tags": []})
    return traces


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _source(self):
        q = parse_qs(urlparse(self.path).query)
        return resolve((q.get("source") or [None])[0])

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/trace.html"):
            try:
                with open(os.path.join(ROOT, "trace.html"), "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            except Exception as e:
                self._send(500, str(e), "text/plain")
            return
        if path == "/sources":
            try:
                out = [{"id": s["id"], "label": s["label"], "dir": s["dir"],
                        "count": len(build(s["dir"]))} for s in SOURCES]
                self._send(200, json.dumps({"sources": out}), "application/json")
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}), "application/json")
            return
        if path == "/data":
            try:
                s = self._source()
                payload = {"traces": build(s["dir"]), "built": avana.now(),
                           "dir": s["dir"], "source": s["id"], "labeling": True}
                self._send(200, json.dumps(payload), "application/json")
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}), "application/json")
            return
        self._send(404, "not found", "text/plain")

    def do_POST(self):
        if urlparse(self.path).path != "/annotate":
            self._send(404, "not found", "text/plain")
            return
        try:
            s = self._source()
            n = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(n) or "{}")
            saved = save_annotation(s["dir"], body.get("trace_id"), body.get("verdict"),
                                    body.get("reason"), body.get("tags"))
            self._send(200, json.dumps({"ok": True, "annotation": saved}), "application/json")
        except Exception as e:
            self._send(500, json.dumps({"ok": False, "error": str(e)}), "application/json")


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Avana trace viewer at http://127.0.0.1:{PORT}/   <-- use this exact URL")
    print(f"  (avoid http://localhost — it may resolve to IPv6 ::1 and fail with ERR_ADDRESS_INVALID)")
    print(f"  sources (switch in the top-right dropdown):")
    for s in SOURCES:
        print(f"    • {s['label']:<14} {s['dir']}")
    print("  Ctrl-C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
        srv.shutdown()


if __name__ == "__main__":
    main()
