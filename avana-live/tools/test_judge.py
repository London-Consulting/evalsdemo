#!/usr/bin/env python3
"""Behavior tests for the pluggable judge (safety + tone). Stdlib unittest, no deps.

Only the external LLM boundary (_claude / _ollama) is stubbed (so no real LLM call
or API key is needed); the rest — rubric selection, judge(), main()'s arg parsing and
trace loop, verdict parsing — runs for real.

    python3 tools/test_judge.py
"""
import os, sys, unittest
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
