"""不调用真实模型：用假的 llm.chat 检查「卡住 3 次 / 主动要求 → 允许完整解法」等策略。
运行：python -m unittest discover -s tests"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lyceum import agent, llm

class Fake:
    def __init__(self): self.calls = []
    def __call__(self, msgs, **kw):
        self.calls.append(msgs)
        allow = '本轮是否允许给完整解法：是' in msgs[0]['content']
        return {"subject": "数学", "topic": "一元二次方程", "intent": "stuck", "problem": "解方程 x^2-5x+6=0",
                "stage": "full" if allow else "hint", "hint_level": 1, "student_correct": None, "solved": allow, "reply": "…"}

class PolicyTest(unittest.TestCase):
    def setUp(self):
        self.fake = Fake(); self._chat = llm.chat; llm.chat = self.fake; llm.API_KEY = 'x'
    def tearDown(self): llm.chat = self._chat; llm.API_KEY = ''
    def run_turn(self, st, text, action=None):
        out, st = agent.respond({"grade": 8}, {"state": st}, [], text, None, action)
        return out, st
    def test_stuck_three_times_unlocks_full(self):
        st = {"problem": "解方程 x^2-5x+6=0", "hint_level": 1, "stuck": 0}
        allows = []
        for _ in range(3):
            out, st = self.run_turn(st, "我不会")
            allows.append(out["allow_full"])
        self.assertEqual(allows, [False, False, True])
    def test_explicit_request_needs_one_hint_first(self):
        out, _ = self.run_turn({"problem": "p", "hint_level": 0, "stuck": 0}, "直接告诉我答案")
        self.assertFalse(out["allow_full"])
        out, _ = self.run_turn({"problem": "p", "hint_level": 1, "stuck": 0}, "直接告诉我答案")
        self.assertTrue(out["allow_full"])
    def test_full_button(self):
        out, _ = self.run_turn({"problem": "p", "hint_level": 0, "stuck": 0}, "", "full")
        self.assertTrue(out["allow_full"])
    def test_no_problem_never_full(self):
        out, _ = self.run_turn({}, "告诉我答案")
        self.assertFalse(out["allow_full"])

if __name__ == '__main__': unittest.main()
