"""构造样例与校准摘要的离线测试：不调用模型。"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import calibrate_topic as C  # noqa: E402

DATA = os.path.join(ROOT, "tests", "fixtures", "topic-cases.jsonl")


class DatasetTest(unittest.TestCase):
    def test_cases_load_and_are_balanced(self):
        cases = C.load_cases(DATA)
        self.assertGreaterEqual(len(cases), 20)
        counts = {}
        for c in cases:
            counts[c["expect"]] = counts.get(c["expect"], 0) + 1
        self.assertEqual(set(counts), set(C.LABELS))
        self.assertGreaterEqual(min(counts.values()), 5)

    def test_no_duplicate_texts_and_all_have_sources(self):
        cases = C.load_cases(DATA)
        texts = [c["text"] for c in cases]
        self.assertEqual(len(texts), len(set(texts)))
        for c in cases:
            self.assertIn(c.get("label_source", "constructed"), ("constructed", "human"))
            self.assertTrue(c["text"].strip())
            self.assertTrue(c["task"].strip())

    def test_bad_line_is_reported_not_skipped(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as fh:
            fh.write(json.dumps({"task": "x", "text": "y", "expect": "great"}) + "\n")
            path = fh.name
        try:
            with self.assertRaises(ValueError) as ctx:
                C.load_cases(path)
            self.assertIn("expect", str(ctx.exception))
        finally:
            os.unlink(path)


class SummaryTest(unittest.TestCase):
    def test_accuracy_matrix_and_recall(self):
        rows = [{"task": "a", "expect": "on_topic", "got": "on_topic", "evidence": "e", "evidence_ok": True, "latency": 2},
                {"task": "b", "expect": "off_topic", "got": "partial", "evidence": "e", "evidence_ok": False, "latency": 4},
                {"task": "c", "expect": "partial", "got": "partial", "evidence": "", "latency": 3}]
        s = C.summarize(rows)
        self.assertEqual(s["n"], 3)
        self.assertEqual(s["ok"], 2)
        self.assertEqual(s["accuracy"], 0.667)
        self.assertEqual(s["matrix"]["off_topic"], {"partial": 1})
        self.assertEqual(s["per_label"]["on_topic"]["recall"], 1.0)
        self.assertEqual(s["per_label"]["off_topic"]["recall"], 0.0)
        self.assertEqual(s["evidence_rate"], 0.5)
        self.assertEqual(s["latency_avg"], 3.0)
        self.assertEqual(s["mismatches"][0]["task"], "b")

    def test_errors_count_as_misses(self):
        s = C.summarize([{"task": "a", "expect": "on_topic", "got": None, "why": "模型判断失败"}])
        self.assertEqual(s["accuracy"], 0.0)
        self.assertEqual(s["matrix"]["on_topic"], {"error": 1})

    def test_dry_run_does_not_need_a_model(self):
        self.assertEqual(C.main(["--dry"]), 0)


if __name__ == "__main__":
    unittest.main()
