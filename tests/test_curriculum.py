"""知识点先修关系与「下一步练什么」的契约测试。"""
import json
import os
import tempfile
import unittest

from lyceum import curriculum


class PrereqDataTest(unittest.TestCase):
    def test_every_edge_points_at_a_real_topic(self):
        topics = curriculum._load_taxonomy_topics()
        for subject, table in curriculum.EDGES.items():
            for topic, prereqs in table.items():
                self.assertIn(topic, topics[subject])
                for p in prereqs:
                    self.assertIn(p, topics[subject])

    def test_the_table_is_not_trivial(self):
        self.assertGreaterEqual(sum(len(v) for v in curriculum.EDGES.values()), 150)
        self.assertEqual(set(curriculum.EDGES), {"数学", "物理", "化学", "英语", "语文", "生物", "历史", "地理"})

    def test_a_cycle_is_refused_at_load_time(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "p.json")
            json.dump({"edges": {"数学": [["有理数", ["整式的加减"]], ["整式的加减", ["有理数"]]]}},
                      open(path, "w", encoding="utf-8"), ensure_ascii=False)
            with self.assertRaises(ValueError):
                curriculum.load_edges(path)

    def test_an_unknown_topic_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "p.json")
            json.dump({"edges": {"数学": [["不存在的知识点", ["有理数"]]]}},
                      open(path, "w", encoding="utf-8"), ensure_ascii=False)
            with self.assertRaises(ValueError):
                curriculum.load_edges(path)


class PrereqChainTest(unittest.TestCase):
    def test_direct_prereqs(self):
        self.assertEqual(curriculum.prereqs("数学", "一元一次方程"), ("整式的加减", "简易方程"))

    def test_chain_is_topological_and_deduplicated(self):
        chain = curriculum.chain("数学", "二次函数")
        self.assertEqual(len(chain), len(set(chain)))
        for t in ("一元二次方程", "一次函数", "平面直角坐标系"):
            self.assertIn(t, chain)
        # 先出现的一定是更基础的
        self.assertLess(chain.index("平面直角坐标系"), chain.index("一次函数"))
        self.assertLess(chain.index("因式分解"), chain.index("一元二次方程"))
        self.assertNotIn("二次函数", chain)

    def test_unknown_topic_has_no_prereqs(self):
        self.assertEqual(curriculum.prereqs("数学", "这个概念不存在"), ())
        self.assertEqual(curriculum.chain("数学", "这个概念不存在"), [])


class RecommendTest(unittest.TestCase):
    def test_weak_prerequisite_wins_over_the_due_topic(self):
        mastery = {("数学", "一元二次方程"): 0.30, ("数学", "因式分解"): 0.42}
        r = curriculum.recommend(mastery, due=[("数学", "一元二次方程")])
        self.assertEqual((r["subject"], r["topic"]), ("数学", "因式分解"))
        self.assertIn("先补这一步", r["reason"])
        self.assertIn("0.42", r["reason"])

    def test_due_topic_when_prereqs_are_solid(self):
        mastery = {("数学", "一元二次方程"): 0.55, ("数学", "因式分解"): 0.91,
                   ("数学", "二次根式"): 0.88}
        r = curriculum.recommend(mastery, due=[("数学", "一元二次方程")])
        self.assertEqual(r["topic"], "一元二次方程")
        self.assertIn("到期复习", r["reason"])

    def test_missing_prerequisite_counts_as_not_mastered(self):
        mastery = {("数学", "一元二次方程"): 0.40}
        r = curriculum.recommend(mastery, due=[("数学", "一元二次方程")])
        self.assertIn(r["topic"], {"因式分解", "二次根式"})
        self.assertIn("还没学过", r["reason"])

    def test_without_due_it_still_repairs_the_prerequisite(self):
        mastery = {("数学", "一元二次方程"): 0.18, ("数学", "因式分解"): 0.775,
                   ("数学", "整式的乘法"): 0.40}
        r = curriculum.recommend(mastery)
        self.assertEqual(r["topic"], "整式的乘法", "应沿先修链往下找到最基础的那一步")
        self.assertIn("先补这一步", r["reason"])

    def test_without_due_it_picks_the_weakest(self):
        mastery = {("数学", "有理数"): 0.70, ("英语", "时态"): 0.35}
        r = curriculum.recommend(mastery)
        self.assertEqual((r["subject"], r["topic"]), ("英语", "时态"))
        self.assertIn("建议先巩固", r["reason"])

    def test_nothing_known_returns_none(self):
        self.assertIsNone(curriculum.recommend({}))

    def test_reason_is_deterministic_for_ties(self):
        mastery = {("数学", "有理数"): 0.50, ("数学", "整式的加减"): 0.50}
        first = curriculum.recommend(mastery)
        second = curriculum.recommend(dict(reversed(list(mastery.items()))))
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
