#!/usr/bin/env python3
"""Behavior tests for the pluggable judge (safety + tone). Stdlib unittest, no deps.

Only the external LLM boundary (_claude / _ollama) is stubbed (so no real LLM call
or API key is needed); the rest — rubric selection, judge(), main()'s arg parsing and
trace loop, verdict parsing — runs for real.

    python3 tools/test_judge.py
"""
import io, json, os, sys, unittest
from unittest import mock

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS)
import judge  # noqa: E402

EVAL_TRACES = os.path.abspath(os.path.join(TOOLS, "..", "..", "eval-traces"))

SAMPLE_TRACE = {
    "trace_id": "t_sample",
    "events": [
        {"t": "1", "type": "user", "text": "I was overcharged and I am furious."},
        {"t": "2", "type": "assistant", "text": "I'm sorry about that — let me help."},
    ],
}


class JudgeSelection(unittest.TestCase):
    def test_tone_judge_sends_the_tone_rubric(self):
        seen = {}

        def fake_claude(prompt, model, scratch, rubric):
            seen["rubric"] = rubric
            return '{"verdict": "pass", "reason": "warm and calm"}'

        with mock.patch.object(judge, "_claude", fake_claude):
            judge.judge(SAMPLE_TRACE, "/tmp", engine="claude", judge_name="tone")
        self.assertEqual(seen["rubric"], judge.JUDGES["tone"])
        self.assertNotEqual(judge.JUDGES["tone"], judge.JUDGES["safety"])

    def test_default_judge_is_safety(self):
        seen = {}

        def fake_claude(prompt, model, scratch, rubric):
            seen["rubric"] = rubric
            return '{"verdict": "pass", "reason": "ok"}'

        with mock.patch.object(judge, "_claude", fake_claude):
            judge.judge(SAMPLE_TRACE, "/tmp", engine="claude")
        self.assertEqual(seen["rubric"], judge.JUDGES["safety"])

    def test_tone_judge_sends_the_tone_rubric_via_ollama(self):
        seen = {}

        def fake_ollama(prompt, model, rubric):
            seen["rubric"] = rubric
            return '{"verdict": "pass", "reason": "warm"}'

        with mock.patch.object(judge, "_ollama", fake_ollama):
            judge.judge(SAMPLE_TRACE, "/tmp", engine="ollama", judge_name="tone")
        self.assertEqual(seen["rubric"], judge.JUDGES["tone"])

    def test_unknown_judge_raises(self):
        with self.assertRaises(KeyError):
            judge.judge(SAMPLE_TRACE, "/tmp", engine="claude", judge_name="bogus")


class VerdictParsing(unittest.TestCase):
    def test_parses_wrapped_json_through_tone_path(self):
        def fake_claude(prompt, model, scratch, rubric):
            return 'sure: {"verdict": "fail", "reason": "cold and dismissive"} done'

        with mock.patch.object(judge, "_claude", fake_claude):
            v = judge.judge(SAMPLE_TRACE, "/tmp", engine="claude", judge_name="tone")
        self.assertEqual(v, {"verdict": "fail", "reason": "cold and dismissive"})


class CliJudgeFlag(unittest.TestCase):
    def _run_main(self, argv):
        seen = {"rubrics": []}

        def fake_claude(prompt, model, scratch, rubric):
            seen["rubrics"].append(rubric)
            return '{"verdict": "pass", "reason": "ok"}'

        with mock.patch.object(judge, "_claude", fake_claude), \
                mock.patch.object(sys, "argv", argv):
            judge.main()
        return seen["rubrics"]

    def test_cli_judge_tone_uses_tone_rubric(self):
        rubrics = self._run_main(
            ["judge.py", "--dir", EVAL_TRACES, "--judge", "tone", "--engine", "claude"])
        self.assertTrue(rubrics)
        self.assertTrue(all(r == judge.JUDGES["tone"] for r in rubrics))

    def test_cli_defaults_to_safety(self):
        rubrics = self._run_main(
            ["judge.py", "--dir", EVAL_TRACES, "--engine", "claude"])
        self.assertTrue(rubrics)
        self.assertTrue(all(r == judge.JUDGES["safety"] for r in rubrics))

    def test_cli_unknown_judge_exits(self):
        with mock.patch.object(sys, "argv",
                               ["judge.py", "--dir", EVAL_TRACES, "--judge", "bogus"]):
            with self.assertRaises(SystemExit):
                judge.main()


class LayaEngine(unittest.TestCase):
    """Only the HTTP call to the Laya server is stubbed."""

    def _run(self, probs_by_label, judge_name="safety"):
        seen = {}
        labels = list(judge.LAYA_QUESTIONS[judge_name])

        def fake_urlopen(req, timeout=None):
            seen["request"] = json.loads(req.data)
            answers = {"q%d" % i: {"type": "noul", "noul": probs_by_label.get(label, 0.0)}
                       for i, label in enumerate(labels)}
            return io.BytesIO(json.dumps({"answers": answers}).encode())

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            v = judge.judge(SAMPLE_TRACE, "/tmp", engine="laya", judge_name=judge_name)
        return v, seen["request"]

    def test_sends_one_yes_no_question_per_rule_for_the_chosen_judge(self):
        _, req = self._run({}, judge_name="tone")
        sent = [q["instructions"] for q in req["questions"].values()]
        self.assertEqual(sent, list(judge.LAYA_QUESTIONS["tone"].values()))
        self.assertTrue(all(q["type"] == "noul" for q in req["questions"].values()))
        self.assertEqual(req["model"], judge.LAYA_MODEL)
        self.assertIn("PATIENT: I was overcharged", req["state"])

    def test_fails_on_any_violation_at_threshold_and_names_the_worst(self):
        v, _ = self._run({"gave medical advice": 0.79, "invented facts": judge.LAYA_THRESHOLD})
        self.assertEqual(v, {"verdict": "fail", "reason": "gave medical advice (0.79)"})

    def test_passes_when_every_violation_is_below_threshold(self):
        v, _ = self._run({"invented facts": 0.3})
        self.assertEqual(v["verdict"], "pass")
        self.assertIn("invented facts 0.30", v["reason"])

    def test_judge_without_a_question_set_is_refused(self):
        with mock.patch.dict(judge.JUDGES, {"custom": "some rubric"}):
            with self.assertRaises(ValueError):
                judge.judge(SAMPLE_TRACE, "/tmp", engine="laya", judge_name="custom")

    def test_unreachable_server_gives_a_readable_error(self):
        import urllib.error
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            with self.assertRaisesRegex(RuntimeError, "Laya not reachable"):
                judge.judge(SAMPLE_TRACE, "/tmp", engine="laya")


class MegaEvalEngines(unittest.TestCase):
    """Jev / Ollama System 1 / baseline and the cost maths. Only HTTP and the CLI are stubbed."""

    def _fake_system1(self, seen, prob=0.9, usage=None):
        def fake_urlopen(req, timeout=None):
            seen["url"], seen["body"] = req.full_url, json.loads(req.data)
            seen["auth"] = req.get_header("Authorization")
            answers = {q: {"type": "noul", "noul": prob} for q in seen["body"]["questions"]}
            return io.BytesIO(json.dumps({"answers": answers, "usage": usage or {}}).encode())
        return fake_urlopen

    def test_jev_gets_the_same_questions_as_laya_plus_model_and_key(self):
        seen = {}
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "k123"}), \
                mock.patch("urllib.request.urlopen", self._fake_system1(seen)):
            judge.judge(SAMPLE_TRACE, "/tmp", engine="jev")
        laya_req = judge.build_request(SAMPLE_TRACE, "laya")
        self.assertEqual(seen["url"], judge.JEV_URL)
        self.assertEqual(seen["body"]["questions"], laya_req["body"]["questions"])
        self.assertEqual(seen["body"]["model"], judge.JEV_MODEL)
        self.assertEqual(seen["auth"], "Bearer k123")

    def test_jev_request_shown_in_the_viewer_masks_the_key(self):
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "k123"}):
            shown = json.dumps(judge.build_request(SAMPLE_TRACE, "jev"))
        self.assertNotIn("k123", shown)

    def test_jev_without_a_key_is_a_readable_error(self):
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}):
            with self.assertRaisesRegex(RuntimeError, "No Jev key"):
                judge.judge(SAMPLE_TRACE, "/tmp", engine="jev")

    def test_jev_cost_counts_input_tokens_only(self):
        seen = {}
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "k"}), \
                mock.patch("urllib.request.urlopen",
                           self._fake_system1(seen, usage={"input_tokens": 1_000_000, "output_tokens": 500})):
            d = judge.judge_detailed(SAMPLE_TRACE, "/tmp", engine="jev")
        self.assertAlmostEqual(d["cost_usd"], judge.JEV_PRICE_IN)

    def test_ollama_system1_models_use_systemone_with_the_same_questions(self):
        seen = {}
        with mock.patch("urllib.request.urlopen", self._fake_system1(seen, prob=0.1)):
            v = judge.judge(SAMPLE_TRACE, "/tmp", engine="ollama-s1", model="nimble:9b")
        self.assertTrue(seen["url"].endswith("/v1/systemone"))
        self.assertEqual(seen["body"]["model"], "nimble:9b")
        self.assertEqual(seen["body"]["questions"], judge.build_request(SAMPLE_TRACE, "laya")["body"]["questions"])
        self.assertEqual(v["verdict"], "pass")
        self.assertTrue(judge.is_ollama_system1("tev1:4b"))
        self.assertFalse(judge.is_ollama_system1("qwen3:32b"))

    def test_baseline_always_fails_and_costs_nothing(self):
        d = judge.judge_detailed(SAMPLE_TRACE, "/tmp", engine="baseline")
        self.assertEqual((d["verdict"], d["cost_usd"], d["tokens_in"]), ("fail", 0.0, 0))

    def test_claude_cost_is_tokens_times_list_price(self):
        def fake_claude(prompt, model, scratch, rubric):
            return {"text": '{"verdict": "pass", "reason": "ok"}', "tokens_in": 1000, "tokens_out": 100, "raw": ""}
        with mock.patch.object(judge, "_claude", fake_claude):
            d = judge.judge_detailed(SAMPLE_TRACE, "/tmp", engine="claude", model="claude-opus-5-5")
        _, pin, pout = judge.CLAUDE_MODELS["claude-opus-5-5"]
        self.assertAlmostEqual(d["cost_usd"], (1000 * pin + 100 * pout) / 1e6)
        self.assertEqual(judge.cost_usd("ollama", "qwen3:32b", 10**6, 10**6), 0.0)


class MegaRunner(unittest.TestCase):
    """The server-side mega eval runner: runs every engine over every trace, times each engine,
    and saves the run. Uses the no-model baseline so nothing external is called."""

    def test_runs_all_traces_times_each_engine_and_saves(self):
        import importlib.util, tempfile, time
        spec = importlib.util.spec_from_file_location("serve", os.path.join(TOOLS, "serve.py"))
        serve = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(serve)
        with tempfile.TemporaryDirectory() as runs:
            serve.RUNS = runs
            src = {"id": "eval-traces", "dir": EVAL_TRACES}
            jid = serve.start_mega(src, "safety", [{"engine": "baseline", "model": "", "label": "Always fail"}])
            for _ in range(100):
                st = serve.mega_status(jid)
                if st["finished"]:
                    break
                time.sleep(0.05)
            self.assertTrue(st["finished"])
            self.assertEqual(st["done"], st["total"])
            self.assertEqual(len(st["results"]["baseline|"]), st["total"])
            self.assertIn("wall_ms", st["timing"]["baseline|"])
            self.assertTrue(os.path.exists(os.path.join(runs, st["saved_id"] + ".json")))

    def test_local_engines_share_one_lane_with_laya_first(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("serve", os.path.join(TOOLS, "serve.py"))
        serve = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(serve)
        self.assertTrue(serve._is_local({"engine": "laya"}))
        self.assertTrue(serve._is_local({"engine": "ollama-s1"}))
        self.assertFalse(serve._is_local({"engine": "jev"}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
