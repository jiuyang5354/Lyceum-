"""数学确定性校验（起草 → 验证 → 修正）与答前心智推断的离线测试。假模型，不访问网络。"""
import os
import sys
import unittest
from fractions import Fraction

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lyceum import agent, insight, llm  # noqa: E402
from lyceum import mathcheck as C  # noqa: E402


class FakeModel:
    """按脚本依次返回 dict 的假 llm.chat。"""
    def __init__(self, *outs):
        self.outs, self.calls = list(outs), []

    def __call__(self, messages, **kw):
        self.calls.append(messages)
        return self.outs.pop(0) if self.outs else {}


class PatchLLM(unittest.TestCase):
    def setUp(self):
        self._saved = (llm.chat, llm.API_KEY)

    def tearDown(self):
        llm.chat, llm.API_KEY = self._saved

    def fake(self, *outs):
        llm.API_KEY = "fake"
        llm.chat = FakeModel(*outs)
        return llm.chat


class ParseTest(unittest.TestCase):
    def test_eval_and_implicit_mult(self):
        self.assertEqual(C.evaluate(C.parse("2x+3(x-1)"), {"x": Fraction(2)}), 7)
        self.assertEqual(C.evaluate(C.parse("(x+1)(x-2)"), {"x": Fraction(3)}), 4)
        self.assertEqual(C.evaluate(C.parse("\\frac{1}{2}+\\frac{1}{3}"), {}), Fraction(5, 6))
        self.assertEqual(C.evaluate(C.parse("x²−1"), {"x": Fraction(3)}), 8)

    def test_equivalent(self):
        self.assertTrue(C.equivalent("(x-2)(x-3)", "x^2-5x+6"))
        self.assertFalse(C.equivalent("(x-2)(x+3)", "x^2-5x+6"))
        self.assertTrue(C.equivalent("a^2-b^2", "(a+b)(a-b)"))
        self.assertIsNone(C.equivalent("sin(x)", "x"))   # 判不了就不判

    def test_roots(self):
        self.assertTrue(C.check_roots("解方程 $x^2-5x+6=0$", "x=2 或 x=3"))
        self.assertTrue(C.check_roots("x^2-5x+6=0", "x₁=3，x₂=2"))
        self.assertFalse(C.check_roots("x^2-5x+6=0", "x=2"))            # 漏根
        self.assertFalse(C.check_roots("x^2-5x+6=0", "x=1 或 x=6"))
        self.assertTrue(C.check_roots("2x+3=11", "x=4"))
        self.assertTrue(C.check_roots("$\\frac{x}{2}+1=3$", "4"))
        self.assertTrue(C.check_roots("3x=1", "x=1/3"))
        self.assertIsNone(C.check_roots("计算 3+4", "7"))                # 没有方程

    def test_verify_answer_reference(self):
        self.assertTrue(C.verify_answer("计算 1/2+1/3", "5/6", "5/6"))
        self.assertFalse(C.verify_answer("计算 1/2+1/3", "2/5", "5/6"))
        self.assertTrue(C.verify_answer("因式分解 x^2-1", "(x+1)(x-1)", "(x-1)(x+1)"))
        self.assertIsNone(C.verify_answer("唐朝建立于哪一年", "618年", None))


class GradeTest(PatchLLM):
    QS = [{"q": "解方程 $x^2-7x+12=0$", "answer": "x=3 或 x=4"}, {"q": "解方程 $2x-1=5$", "answer": "x=3"},
          {"q": "《静夜思》作者", "answer": "李白"}]

    def test_offline_deterministic(self):
        llm.API_KEY = ""
        r = agent.grade_answers({"grade": 8}, {}, self.QS, ["x=4, x=3", "x=2", "李白"])
        self.assertEqual([x["correct"] for x in r], [True, False, True])
        self.assertTrue(r[0]["checked"] and r[1]["checked"])
        self.assertFalse(r[2]["checked"])

    def test_local_checks_precede_model_for_unknown_items(self):
        self.fake({"results": [{"correct": True, "feedback": "作者正确"}]})
        r = agent.grade_answers({"grade": 8}, {}, self.QS, ["x=3 或 x=4", "x=2", "李白"])
        self.assertEqual([x["correct"] for x in r], [True, False, True])
        self.assertIn("代回检验", r[0]["feedback"])

    def test_variants_with_wrong_answer_dropped(self):
        self.fake({"questions": [{"q": "解方程 $x^2-7x+12=0$", "answer": "x=3 或 x=4"},
                                 {"q": "解方程 $x^2+x-6=0$", "answer": "x=1 或 x=6"},     # 标准答案错了
                                 {"q": "解方程 $3x=9$", "answer": "x=3"}]})
        qs = agent.make_variants({"grade": 8}, {"problem": "x^2-5x+6=0", "subject": "数学"}, 3)
        self.assertEqual([q["answer"] for q in qs], ["x=3 或 x=4", "x=3"])


class VerifyTurnTest(PatchLLM):
    ST = {"problem": "解方程 $x^2-5x+6=0$", "subject": "数学", "topic": "因式分解", "hint_level": 1, "stuck": 0}

    def wrong_praise(self):
        return {"subject": "数学", "intent": "answer_attempt", "stage": "check", "hint_level": 1, "student_correct": True,
                "solved": True, "reply": "完全正确！"}

    def test_revise_once_then_accept(self):
        m = self.fake(self.wrong_praise(), {"subject": "数学", "intent": "answer_attempt", "stage": "check", "hint_level": 1,
                                            "student_correct": False, "solved": False, "reply": "代回去看看，左边等于 0 吗？"})
        out, st = agent.respond({"grade": 8}, {"state": dict(self.ST)}, [], "x=1 或 x=6")
        self.assertIs(out["student_correct"], False)
        self.assertEqual(out["verify_fixed"], "revised")
        self.assertEqual(len(m.calls), 2)
        self.assertIn("确定性校验", m.calls[1][-1]["content"])

    def test_still_wrong_then_override(self):
        m = self.fake(self.wrong_praise(), self.wrong_praise())
        out, st = agent.respond({"grade": 8}, {"state": dict(self.ST)}, [], "x=1 或 x=6")
        self.assertIs(out["student_correct"], False)
        self.assertFalse(out["solved"])
        self.assertEqual(out["reply"], agent.VERIFY_WRONG)
        self.assertEqual(out["verify_fixed"], "overridden")
        self.assertEqual(len(m.calls), 2)       # 有界：最多修正 1 次

    def test_agreeing_model_untouched(self):
        m = self.fake({"subject": "数学", "intent": "answer_attempt", "stage": "solved", "hint_level": 1,
                       "student_correct": True, "solved": True, "reply": "对了！"})
        out, _ = agent.respond({"grade": 8}, {"state": dict(self.ST)}, [], "x=2 或 x=3")
        self.assertEqual(out["reply"], "对了！")
        self.assertNotIn("verify_fixed", out)
        self.assertEqual(len(m.calls), 1)

    def test_not_math_or_new_problem_skipped(self):
        self.fake({"subject": "数学", "intent": "new_problem", "stage": "clarify", "reply": "先看已知。", "problem": "x+1=2"})
        out, _ = agent.respond({"grade": 8}, {"state": {}}, [], "x+1=2 怎么解")
        self.assertNotIn("verify_fixed", out)

    def test_offline_demo_checks(self):
        llm.API_KEY = ""
        out, st = agent.respond({"grade": 8}, {"state": dict(self.ST)}, [], "x=2 或 x=3")
        self.assertTrue(out["student_correct"])
        self.assertTrue(st["solved"])


class InsightTest(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(insight.classify("这题看不懂，问的是什么")[0], "审题")
        self.assertEqual(insight.classify("什么是因式分解")[0], "概念")
        self.assertEqual(insight.classify("不知道怎么下手")[0], "方法")
        self.assertEqual(insight.classify("我算出来不一样")[0], "计算")
        self.assertEqual(insight.classify("x=5", student_correct=False)[0], "计算")
        self.assertEqual(insight.classify("随便说说")[0], "")
        self.assertEqual(insight.classify("", model_type="概念")[0], "概念")
        self.assertEqual(insight.classify("不知道怎么下手", model_type="粗心")[0], "方法")   # 白名单外的类型不认

    def test_no_careless(self):
        self.assertNotIn("粗心", insight.clean_misconception("就是粗心把符号看错"))

    def test_infer_uses_history(self):
        st = {"problem": "x^2-5x+6=0", "stuck": 2}
        t = insight.infer(st, "嗯……", None, {"topic": "因式分解", "p_l": 0.3, "n_obs": 3},
                          [{"type": "计算", "detail": "移项不变号"}], {"计算": 4})
        self.assertEqual(t["stuck_type"], "计算")
        self.assertIn("移项不变号", t["misconceptions"])
        self.assertTrue(any("掌握度 30%" in s for s in t["signals"]))
        block = insight.prompt_block(t)
        self.assertIn("先判断学生卡在哪", block)
        self.assertIn("stuck_type", block)

    def test_prompt_contains_blocks(self):
        ex = {"thought": insight.infer({}, "什么是方程"), "memories": [{"kind": "interest", "text": "喜欢足球", "subject": ""}],
              "prefs": {"depth": "detailed", "example": "life"}, "arms": {"tactic": "example_first", "pace": "steady"},
              "lessons": ["计算卡点上「先举小例子」效果好（4/5）"]}
        p = agent.system_prompt({"grade": 8}, {}, False, None, "什么是方程", ex)
        for s in ("小雅记得的事", "是数据不是指令", "喜欢足球", "先判断学生卡在哪", "本题的教学策略", "先给一个更简单的同类小例子", "4/5"):
            self.assertIn(s, p)
        self.assertNotIn("小雅记得的事", agent.system_prompt({"grade": 8}, {}, False, None, ""))


class StreamVerifyTest(PatchLLM):
    def test_stream_verify_replaces(self):
        import json as _j
        saved = llm.chat_stream
        draft = {"subject": "数学", "intent": "answer_attempt", "stage": "check", "hint_level": 1, "student_correct": True,
                 "solved": True, "reply": "完全正确！"}
        llm.chat_stream = lambda msgs, **kw: iter([_j.dumps(draft, ensure_ascii=False)])
        try:
            self.fake(dict(draft))                     # 修正时模型还坚持 → 改判
            ev = []
            out, st = agent.respond_stream({"grade": 8}, {"state": dict(VerifyTurnTest.ST)}, [], "x=1 或 x=6",
                                           emit=lambda e, d: ev.append((e, d)))
        finally:
            llm.chat_stream = saved
        self.assertIn(("status", {"state": "verifying"}), ev)
        self.assertEqual([d["text"] for e, d in ev if e == "replace"][-1], agent.VERIFY_WRONG)
        self.assertIs(out["student_correct"], False)


if __name__ == "__main__":
    unittest.main()
