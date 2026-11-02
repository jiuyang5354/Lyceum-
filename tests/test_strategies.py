"""各科引导策略 + 学科路由 + 各科漏题规则（正反例）。纯离线，不调模型。"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lyceum import agent, leak, llm, strategies as S

NINE = ["语文", "数学", "英语", "物理", "化学", "生物", "历史", "地理", "道德与法治"]


class StrategyDataTest(unittest.TestCase):
    def test_every_subject_complete(self):
        for s in NINE + ["科学", "通用"]:
            st = S.STRATEGIES[s]
            for k in ("mode", "levels", "stuck", "never", "allow", "check", "fallback", "demo"):
                self.assertTrue(st[k], (s, k))
            self.assertEqual(len(st["levels"]), 3, s)
            self.assertIn("leak", st)
            for b in S.BANDS:
                self.assertLessEqual(len(S.get(s, b)["mode"]), 32, (s, b))   # 答疑区一行小字

    def test_leak_families(self):
        self.assertEqual(S.leak_family("数学"), "math")
        self.assertEqual(S.leak_family("物理"), "physics")
        self.assertEqual(S.leak_family("化学"), "chem")
        self.assertEqual(S.leak_family("英语"), "english")
        for s in ("语文", "历史", "地理", "生物", "道德与法治", "思想政治"):
            self.assertIsNone(S.leak_family(s), s)
        self.assertEqual(S.leak_family(""), "math")      # 未知学科沿用原数学规则

    def test_never_give_rules_by_subject(self):
        self.assertIn("最终答案", S.STRATEGIES["数学"]["never"])
        self.assertIn("数值+单位", S.STRATEGIES["物理"]["never"])
        self.assertIn("配平", S.STRATEGIES["化学"]["never"])
        self.assertIn("完整翻译", S.STRATEGIES["英语"]["never"])
        self.assertIn("标准答案句式", S.STRATEGIES["语文"]["never"])
        self.assertIn("作文成段代写", S.STRATEGIES["语文"]["never"])
        self.assertIn("复述", S.STRATEGIES["历史"]["allow"])        # 文科记忆题：给事实但要复述/关联

    def test_band_overrides(self):
        self.assertEqual(S.get("道德与法治", "high")["label"], "思想政治")
        self.assertNotEqual(S.get("数学", "primary")["mode"], S.get("数学", "middle")["mode"])
        self.assertIn("小学用语", S.prompt_block("数学", "primary"))
        self.assertNotIn("小学用语", S.prompt_block("数学", "middle"))
        self.assertEqual(S.route("", "", "物理", "primary")["subject"], "科学")   # 小学没有物理
        self.assertEqual(S.route("", "", "历史", "primary")["subject"], "道德与法治")

    def test_genres(self):
        self.assertEqual(S.get("语文", "middle", "帮我写一篇《我的妈妈》，400 字")["genre"], "作文")
        self.assertEqual(S.get("英语", "middle", "把这句话翻译成英语")["genre"], "翻译")
        self.assertIn("不给整句译文", S.prompt_block("英语", "middle", "翻译成英语"))


class RouteTest(unittest.TestCase):
    CASES = [("解方程 x^2-5x+6=0", "数学"), ("为什么人站在匀速上升的电梯里，感觉不到自己在动？", "物理"),
             ("一个物体质量 2kg，受到 10N 的拉力，求加速度", "物理"), ("配平 Fe + O2 → Fe3O4", "化学"),
             ("She ___ (go) to school yesterday.", "英语"), ("把“我昨天去了公园”翻译成英语", "英语"),
             ("“落霞与孤鹜齐飞，秋水共长天一色”好在哪里？", "语文"), ("光合作用的原料和产物", "生物"),
             ("鸦片战争对中国社会有什么影响", "历史"), ("我国东部季风区的降水为什么夏季多", "地理"),
             ("公民的基本权利和义务有哪些", "道德与法治")]

    def test_keyword_fallback(self):
        for t, want in self.CASES:
            self.assertEqual(S.classify(t)[0], want, t)
            r = S.route(t, "", "", "middle")
            self.assertEqual((r["subject"], r["source"]), (want, "keyword"), t)

    def test_model_field_wins(self):
        r = S.route("解方程 x^2-1=0", "", "数学", "middle", model_subject="物理")
        self.assertEqual((r["subject"], r["source"]), ("物理", "model"))
        self.assertEqual(S.route("", "", "", "high", "思想政治")["subject"], "道德与法治")

    def test_session_subject_for_followups(self):
        r = S.route("我不会", "", "英语", "middle")
        self.assertEqual((r["subject"], r["source"]), ("英语", "session"))
        r = S.route("x=3", "", "物理", "middle")               # 短答案不改学科
        self.assertEqual(r["subject"], "物理")

    def test_new_problem_switches_subject(self):
        r = S.route("解方程 x^2-1=0，求 x", "", "物理", "middle")
        self.assertEqual((r["subject"], r["source"]), ("数学", "keyword"))

    def test_nothing_known_is_generic(self):
        r = S.route("", "", "", "middle")
        self.assertEqual((r["subject"], r["source"]), ("通用", "default"))
        self.assertIn("先判断这道题属于哪一科", S.prompt_block("", "middle"))

    def test_prompt_gets_subject_block(self):
        st = {"problem": "She ___ (go) to school yesterday.", "subject": "英语", "hint_level": 1}
        p = agent.system_prompt({"grade": 8}, st, False)
        self.assertIn("本题按「英语」引导", p)
        self.assertIn("完整翻译", p)
        p2 = agent.system_prompt({"grade": 3}, {"problem": "分苹果", "subject": "数学"}, False)
        self.assertIn("小学用语", p2)


class FakeChat:
    def __init__(self, *outs): self.outs = list(outs); self.calls = []
    def __call__(self, msgs, **kw):
        self.calls.append(msgs); return dict(self.outs.pop(0))


class RecordedTest(unittest.TestCase):
    """会话状态里记下学科与引导方式。"""
    def setUp(self): self._chat = llm.chat; llm.API_KEY = 'x'
    def tearDown(self): llm.chat = self._chat; llm.API_KEY = ''

    def test_state_strategy(self):
        o = {"subject": "物理", "topic": "参照物", "intent": "new_problem", "problem": "电梯问题", "stage": "hint",
             "hint_level": 1, "student_correct": None, "solved": False, "reply": "你以谁为参照物？"}
        llm.chat = FakeChat(o)
        out, st = agent.respond({"grade": 8}, {"state": {}}, [], "为什么人站在匀速上升的电梯里，感觉不到自己在动？")
        self.assertEqual(st["strategy"]["subject"], "物理")
        self.assertEqual(st["strategy"]["source"], "model")
        self.assertEqual(out["state"]["strategy"]["mode"], S.STRATEGIES["物理"]["mode"])
        self.assertIn("本题按「物理」引导", llm.chat.calls[0][0]["content"])   # 关键词路由已注入

    def test_offline_mock_uses_subject(self):
        llm.API_KEY = ''
        out, st = agent.respond({"grade": 8}, {"state": {}}, [], "She ___ (go) to school yesterday.")
        self.assertEqual(out["subject"], "英语")
        self.assertIn("表示时间的词", out["reply"])
        self.assertEqual(st["strategy"]["subject"], "英语")


def L(subject, reply, level=1, stage="hint", sc=None):
    return {"subject": subject, "reply": reply, "hint_level": level, "stage": stage, "student_correct": sc}


class SubjectLeakTest(unittest.TestCase):
    PHY = "质量为 $2\\,\\text{kg}$ 的物体受到 $10\\,\\text{N}$ 的水平拉力，光滑水平面，求加速度。"

    def test_physics_numeric(self):
        st = {"problem": self.PHY, "hint_level": 1}
        self.assertTrue(agent.find_leak(L("物理", "用 $a=F/m$，代进去 $a = 5\\,\\text{m/s}^2$。"), st, ""))
        self.assertTrue(agent.find_leak(L("物理", "加速度为 5 m/s²，你再检查一下。", 2, "check"), st, ""))
        # 反例：复述已知量、只说公式、学生自己算出来的
        self.assertEqual(agent.find_leak(L("物理", "已知 $m = 2\\,\\text{kg}$，$F = 10\\,\\text{N}$，用哪个公式？"), st, ""), "")
        self.assertEqual(agent.find_leak(L("物理", "g 取 9.8 N/kg，先写出 $a=F/m$。"), st, ""), "")
        self.assertEqual(agent.find_leak(L("物理", "你算的 5 m/s² 单位写对了吗？", 2, "check"), st, "a=5m/s²"), "")

    def test_physics_level3_only_final_phrasing(self):
        st = {"problem": self.PHY, "hint_level": 3}
        self.assertEqual(agent.find_leak(L("物理", "代入：$a = 10\\,\\text{N} / 2\\,\\text{kg}$，算一算等于多少？", 3), st, ""), "")
        self.assertTrue(agent.find_leak(L("物理", "所以加速度为 5 m/s²。", 3), st, ""))
        self.assertEqual(agent.find_leak(L("物理", "所以加速度为 5 m/s²。", 3, "full"), st, ""), "")

    def test_chem_balanced_equation(self):
        st = {"problem": "配平化学方程式：Fe + O2 → Fe3O4", "hint_level": 1}
        self.assertTrue(agent.find_leak(L("化学", "配好是 $3Fe + 2O_2 \\xrightarrow{点燃} Fe_3O_4$，你看对吗？"), st, ""))
        self.assertTrue(agent.find_leak(L("化学", "应该写成 3Fe+2O₂=点燃=Fe₃O₄。", 2), st, ""))
        self.assertTrue(agent.find_leak(L("化学", "2H2 + O2 = 2H2O 就配平了。"), {"problem": "氢气燃烧", "hint_level": 1}, ""))
        # 反例：题目原式、没配平的式子、学生自己写对的
        self.assertEqual(agent.find_leak(L("化学", "先看 Fe + O2 → Fe3O4，左边几个 O？"), st, ""), "")
        self.assertEqual(agent.find_leak(L("化学", "你写的 2Fe + 2O2 = Fe3O4 里铁原子对得上吗？", 2, "check"), st, ""), "")
        self.assertEqual(agent.find_leak(L("化学", "对，3Fe+2O2=Fe3O4 配平了！", 2, "check", True), st, "3Fe+2O2=Fe3O4"), "")

    def test_chem_numeric(self):
        st = {"problem": "用 10 g 碳酸钙与足量盐酸反应，生成二氧化碳多少克？", "hint_level": 2}
        self.assertTrue(agent.find_leak(L("化学", "按比例算得 4.4 g。", 2), st, ""))
        self.assertEqual(agent.find_leak(L("化学", "10 g 碳酸钙是多少 mol？先求这个。", 2), st, ""), "")

    def test_english_sentence(self):
        st = {"problem": "用所给词的适当形式填空：She ___ (go) to school yesterday.", "hint_level": 1}
        self.assertTrue(agent.find_leak(L("英语", "注意 yesterday，所以是 She went to school yesterday."), st, ""))
        self.assertTrue(agent.find_leak(L("英语", "你写的不对，应该是 **She went to school yesterday.**", 2, "check"), st, "She goes to school yesterday."))
        # 反例：和本题不同的例句、复述原题、第 3 层
        self.assertEqual(agent.find_leak(L("英语", "比如 I watched TV last night. 这里也有表示过去的时间词。"), st, ""), "")
        self.assertEqual(agent.find_leak(L("英语", "看原句 She ___ (go) to school yesterday. 时间词是哪个？"), st, ""), "")
        self.assertEqual(agent.find_leak(L("英语", "She went to school yesterday.", 3), dict(st, hint_level=3), ""), "")

    def test_english_translation(self):
        st = {"problem": "把“我昨天去了公园”翻译成英语", "hint_level": 1}
        self.assertTrue(agent.find_leak(L("英语", "可以这样说：I went to the park yesterday."), st, ""))
        self.assertEqual(agent.find_leak(L("英语", "主干是「我 + 去 + 公园」，go 的过去式是什么？"), st, ""), "")
        self.assertEqual(agent.find_leak(L("英语", "对了！I went to the park yesterday.", 2, "check", True), st, "I went to the park yesterday."), "")

    def test_humanities_not_hard_blocked(self):
        st = {"problem": "“落霞与孤鹜齐飞”好在哪里？", "hint_level": 1}
        self.assertEqual(agent.find_leak(L("语文", "答案是：运用对偶，动静结合，表达了作者的喜爱之情。"), st, ""), "")
        self.assertEqual(agent.find_leak(L("历史", "鸦片战争是 1840 年爆发的，你复述一下？"), {"problem": "鸦片战争", "hint_level": 1}, ""), "")

    def test_math_unchanged(self):
        st = {"problem": "解方程 $x^2-5x+6=0$", "hint_level": 1}
        self.assertTrue(agent.find_leak(L("数学", "分解成 $(x-2)(x-3)=0$。"), st, ""))
        self.assertTrue(agent.find_leak(L("物理", "所以 x = 2 或 x = 3"), st, ""))     # 物理也跑数学规则


class SubjectRewriteTest(unittest.TestCase):
    def setUp(self): self._chat = llm.chat; llm.API_KEY = 'x'
    def tearDown(self): llm.chat = self._chat; llm.API_KEY = ''

    def test_fallback_is_subject_specific(self):
        bad = {"subject": "英语", "topic": "一般过去时", "intent": "ask_hint", "problem": "She ___ (go) to school yesterday.",
               "stage": "hint", "hint_level": 1, "student_correct": None, "solved": False,
               "reply": "答案就是 She went to school yesterday."}
        llm.chat = FakeChat(bad, bad)
        out, _ = agent.respond({"grade": 8}, {"state": {"problem": bad["problem"], "subject": "英语", "hint_level": 0}}, [], "提示一下")
        self.assertEqual(len(llm.chat.calls), 2)
        self.assertEqual(out["reply"], S.STRATEGIES["英语"]["fallback"])

    def test_chem_rewrite_once(self):
        bad = {"subject": "化学", "topic": "化学方程式", "intent": "ask_hint", "problem": "配平 Fe + O2 → Fe3O4",
               "stage": "hint", "hint_level": 2, "student_correct": None, "solved": False, "reply": "是 3Fe + 2O2 = Fe3O4。"}
        good = dict(bad, reply="先数氧原子：右边 Fe3O4 有几个 O？左边 O2 前面要配几？")
        llm.chat = FakeChat(bad, good)
        out, _ = agent.respond({"grade": 9}, {"state": {"problem": bad["problem"], "subject": "化学", "hint_level": 1}}, [], "还是不会")
        self.assertEqual(out["reply"], good["reply"])
        self.assertTrue(out["leak_fixed"])


if __name__ == '__main__': unittest.main()
