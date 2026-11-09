"""写作分项评分的测试：形式维度必须可复现，模型维度必须显式标注来源。"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lyceum import writing as W  # noqa: E402

EN_GOOD = """Last summer I joined a reading club in our town library. Although I was nervous at first, \
the members were friendly and encouraging.

Every Saturday we read a short story and discussed it together. For example, we talked about why \
the main character made that choice. Therefore, I learned to explain my ideas with reasons.

In conclusion, the club changed the way I read. I now notice details that I used to skip, and I \
write better stories myself."""

ZH_GOOD = """去年秋天，我第一次参加了学校的朗读比赛。

起初我只是站在台下看别人，心里想：他们怎么一点都不紧张。后来老师鼓励我报名，我便每天中午到空教室练十分钟。

虽然最后只拿了三等奖，但我发现自己不再害怕开口。因此，这次比赛成了我这一年的转折点。总之，勇敢一点，收获往往比想象的多。"""


class FeatureTest(unittest.TestCase):
    def test_english_words_and_chinese_chars(self):
        self.assertEqual(W.features("I love reading books.", "英语")["units"], 4)
        self.assertEqual(W.features("我爱读书。", "语文")["units"], 4)

    def test_paragraph_and_sentence_counting(self):
        f = W.features(EN_GOOD, "英语")
        self.assertEqual(f["paragraphs"], 3)
        self.assertGreaterEqual(f["sentences"], 5)
        self.assertGreater(f["connectives"], 2)


class RuleScoreTest(unittest.TestCase):
    def test_a_short_piece_loses_length_points_with_evidence(self):
        dims, _ = W.rule_dimensions("I like it.", "英语", "middle")
        length = next(d for d in dims if d["key"] == "length")
        self.assertLess(length["score"], 12)
        self.assertIn("%", length["evidence"])

    def test_one_paragraph_is_called_out(self):
        dims, _ = W.rule_dimensions("I like reading. It is fun. We read every day.", "英语", "middle")
        structure = next(d for d in dims if d["key"] == "structure")
        self.assertLessEqual(structure["score"], 10)
        self.assertIn("一段", structure["evidence"])

    def test_no_connectives_scores_zero(self):
        dims, _ = W.rule_dimensions("I read. I write. I sleep.", "英语", "middle")
        self.assertEqual(next(d for d in dims if d["key"] == "cohesion")["score"], 0)

    def test_a_good_essay_scores_well_on_form(self):
        r = W.review(EN_GOOD, "英语", "middle")
        self.assertGreaterEqual(r["total"], 70)
        self.assertEqual(r["coverage"], "仅形式维度")

    def test_chinese_targets_are_longer(self):
        r = W.review(ZH_GOOD, "语文", "middle")
        self.assertEqual(len(r["dims"]), 4)
        self.assertGreater(r["features"]["units"], 60)

    def test_total_is_the_sum_and_max_matches(self):
        r = W.review(ZH_GOOD, "语文", "middle")
        self.assertEqual(r["total"], sum(d["score"] for d in r["dims"]))
        self.assertEqual(r["max"], 25 * len(r["dims"]))

    def test_empty_text_is_zero_and_says_so(self):
        r = W.review("", "语文", "middle")
        self.assertEqual(r["total"], 0)
        self.assertIn("没有内容可评", r["notes"])

    def test_scoring_is_deterministic(self):
        a = W.review(ZH_GOOD, "语文", "middle")
        b = W.review(ZH_GOOD, "语文", "middle")
        self.assertEqual(a, b)


class ModelPathTest(unittest.TestCase):
    def fake_chat(self, payload):
        def chat(*a, **k):
            return json.dumps(payload, ensure_ascii=False) if isinstance(payload, dict) else payload
        return chat

    def test_model_dimensions_are_labeled_and_merge(self):
        chat = self.fake_chat({"dims": [{"key": "content", "score": 20, "reason": "第三段回应了题目"},
                                        {"key": "language", "score": 18, "reason": "两处时态不一致"}]})
        r = W.review(ZH_GOOD, "语文", "middle", task="记一次比赛", chat=chat, use_model=True)
        self.assertEqual(len(r["dims"]), 6)
        self.assertEqual({d["source"] for d in r["dims"]}, {"rule", "model"})
        self.assertEqual(r["coverage"], "形式 + 内容")
        self.assertEqual(r["total"], sum(d["score"] for d in r["dims"]))

    def test_broken_model_output_falls_back_to_rules(self):
        r = W.review(ZH_GOOD, "语文", "middle", chat=self.fake_chat("不是 JSON"), use_model=True)
        self.assertEqual(len(r["dims"]), 4)
        self.assertTrue(any("模型评分失败" in n for n in r["notes"]))
        self.assertEqual(r["coverage"], "仅形式维度")

    def test_missing_dimension_is_rejected(self):
        chat = self.fake_chat({"dims": [{"key": "content", "score": 20, "reason": "x"}]})
        r = W.review(ZH_GOOD, "语文", "middle", chat=chat, use_model=True)
        self.assertEqual(len(r["dims"]), 4)
        self.assertTrue(any("维度不完整" in n for n in r["notes"]))

    def test_scores_are_clamped(self):
        chat = self.fake_chat({"dims": [{"key": "content", "score": 99, "reason": "x"},
                                        {"key": "language", "score": -5, "reason": "y"}]})
        r = W.review(ZH_GOOD, "语文", "middle", chat=chat, use_model=True)
        model = [d for d in r["dims"] if d["source"] == "model"]
        self.assertEqual([d["score"] for d in model], [25, 0])

    def test_model_is_off_by_default(self):
        def boom(*a, **k):
            raise AssertionError("默认不应调用模型")
        r = W.review(EN_GOOD, "英语", "middle", chat=boom)
        self.assertEqual(len(r["dims"]), 4)
        self.assertTrue(any("未启用模型" in n for n in r["notes"]))


if __name__ == "__main__":
    unittest.main()
