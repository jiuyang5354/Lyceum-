"""「提示不得直接给出关键中间结果」：提示词 + 服务端闸门。不调用真实模型（假的 llm.chat 按脚本返回）。
用例取自 2026-11-01 真实模型输出：第 2 轮（检查答案）直接写出了 (x-2)(x-3)=0。"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lyceum import agent, llm

PROBLEM = "解方程 $x^2-5x+6=0$"
LEAKY = {"subject": "数学", "topic": "一元二次方程·因式分解", "intent": "answer_attempt", "problem": PROBLEM, "stage": "check",
         "hint_level": 2, "student_correct": False, "solved": False,
         "reply": "找出的两个数 $-2$ 和 $-3$ 对了，但它们不是方程的根。因式分解后是 $(x-2)(x-3)=0$，因此至少一个因式为零。"}
CLEAN = dict(LEAKY, reply="$-2$ 和 $-3$ 找对了。它们是用来把左边写成两个括号相乘的，不是方程的根。你试着用这两个数把左边写成两个括号相乘？")


class Script:
    def __init__(self, *outs): self.outs = list(outs); self.calls = []
    def __call__(self, msgs, **kw):
        self.calls.append(msgs); return dict(self.outs.pop(0))


class HintLeakTest(unittest.TestCase):
    def setUp(self): self._chat = llm.chat; llm.API_KEY = 'x'
    def tearDown(self): llm.chat = self._chat; llm.API_KEY = ''
    def turn(self, st, text):
        return agent.respond({"grade": 8}, {"state": st}, [], text)

    def test_prompt_has_rule(self):
        p = agent.system_prompt({"grade": 8}, {"problem": PROBLEM, "hint_level": 1}, False)
        self.assertIn("提示不得直接给出关键中间结果", p)
        self.assertIn("不能写出 $(x-2)(x-3)$", p)

    def test_leak_is_rewritten_once(self):
        llm.chat = Script(LEAKY, CLEAN)
        out, _ = self.turn({"problem": PROBLEM, "hint_level": 1, "stuck": 0}, "是 -2 和 -3，所以 x=-2 或 x=-3")
        self.assertEqual(len(llm.chat.calls), 2)                     # 重写了一次
        self.assertIn("关键中间结果", llm.chat.calls[1][-1]["content"])  # 纠正指令
        self.assertNotIn("(x-2)(x-3)", out["reply"])
        self.assertTrue(out.get("leak_fixed"))

    def test_still_leaking_falls_back(self):
        llm.chat = Script(LEAKY, LEAKY)
        out, _ = self.turn({"problem": PROBLEM, "hint_level": 1, "stuck": 0}, "是 -2 和 -3")
        self.assertEqual(out["reply"], agent.SAFE_HINT)

    def test_clean_hint_untouched(self):
        llm.chat = Script(CLEAN)
        out, _ = self.turn({"problem": PROBLEM, "hint_level": 1, "stuck": 0}, "是 -2 和 -3")
        self.assertEqual(len(llm.chat.calls), 1)
        self.assertEqual(out["reply"], CLEAN["reply"])

    def test_level3_may_show_intermediate_but_not_final(self):
        lv3 = dict(LEAKY, stage="hint", hint_level=3, reply="左边写成 $(x-2)(x-3)$ 了。先看 $x-2=0$，两边都加 2，得到什么？")
        llm.chat = Script(lv3)
        out, _ = self.turn({"problem": PROBLEM, "hint_level": 2, "stuck": 1}, "我不懂")
        self.assertEqual(len(llm.chat.calls), 1)
        final = dict(lv3, reply="所以 $x=2$ 或 $x=3$。")
        self.assertTrue(agent.find_leak(final, {"problem": PROBLEM, "hint_level": 3}, ""))

    def test_full_solution_allowed(self):
        full = dict(LEAKY, stage="full", solved=True, reply="$(x-2)(x-3)=0$，所以 $x=2$ 或 $x=3$。")
        self.assertEqual(agent.find_leak(full, {"problem": PROBLEM}, ""), "")

    def test_student_own_expression_not_a_leak(self):
        o = dict(LEAKY, reply="你写的 $(x-2)(x-3)$ 对了！下一步呢？")
        self.assertEqual(agent.find_leak(o, {"problem": PROBLEM, "hint_level": 1}, "我分解成 (x-2)(x-3)=0"), "")


if __name__ == '__main__': unittest.main()
