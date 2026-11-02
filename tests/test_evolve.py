"""自进化：白名单与护栏、Thompson 选择可复现、反思与奖励、版本化与回滚、自动停用、教学经验、
候选规则影子模式、可插拔反思器（假模型）、离线 HTTP 全流程。不调用任何真实模型。"""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lyceum import agent, leak, llm, privacy  # noqa: E402
from lyceum import evolve as E  # noqa: E402
from lyceum.db import DB  # noqa: E402

T0 = 1_790_000_000.0


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = DB(os.path.join(self.dir, "e.db"))

    def tearDown(self):
        self.db.conn.close()
        shutil.rmtree(self.dir)

    def episode(self, sid, arm, outcome, hints=0, stuck=0, subject="数学", stuck_type="计算", now=T0):
        self.db.x("INSERT INTO turn_log (ts, session_id, subject, stuck_type) VALUES (?,?,?,?)", (now, sid, subject, stuck_type))
        st = {"problem": "p%d" % sid, "subject": subject, "topic": "因式分解", "hint_level": hints, "stuck": stuck,
              "arms": {"tactic": arm, "pace": "steady"}, "ep_start": now}
        return E.close_episode(self.db, sid, st, outcome, reflector=E.OfflineReflector(), now=now + 1)


class GuardrailTest(Base):
    def test_whitelist_only(self):
        for bad in ({"stuck_limit": 5}, {"leak": {}}, {"privacy": False}, {"tactic": {"数学": {"give_answer": [3, 1]}}},
                    {"tactic": {"数学": {"question_first": [9999, 1]}}},
                    {"disabled": {"tactic|数学": list(E.TACTICS)}}):
            with self.assertRaises(E.GuardrailError, msg=str(bad)):
                E.commit(self.db, bad, "坏参数", "test")
        self.assertTrue(E.validate({"tactic": {"数学": {"example_first": [3, 2]}}, "pace": {}, "lessons": {"数学|计算|x": [2, 1]}}))

    def test_core_rules_untouched(self):
        # 护栏是代码常量，不在参数里；跑一堆反思之后依然不变
        for i in range(12):
            self.episode(i + 1, "visual_first", "full", now=T0 + i * 10)
        self.assertEqual(agent.STUCK_LIMIT, 3)
        self.assertTrue(leak.find_leak({"reply": "所以 x=2 或 x=3", "subject": "数学"}, {"problem": "x^2-5x+6=0"}, ""))
        self.assertIsNone(privacy.filter_for_memory("我叫王小明"))
        p = E.params(self.db)
        self.assertLessEqual(set(p), E.ALLOWED_KEYS)


class BanditTest(Base):
    def test_choose_reproducible_and_logged(self):
        a = E.choose(self.db, 7, "数学", "x^2-5x+6=0", now=T0)
        b = E.choose(self.db, 7, "数学", "x^2-5x+6=0", now=T0)
        self.assertEqual((a["tactic"], a["pace"]), (b["tactic"], b["pace"]))
        self.assertIn(a["tactic"], E.TACTICS)
        self.assertEqual(self.db.q("SELECT COUNT(*) AS n FROM bandit_log", one=True)["n"], 4)

    def test_learns_to_prefer_good_arm(self):
        for i in range(10):
            self.episode(100 + i, "example_first", "solved", hints=0, now=T0 + i * 10)
            self.episode(200 + i, "visual_first", "full", now=T0 + i * 10 + 5)
        picks = [E.choose(self.db, 900 + i, "数学", "q%d" % i)["tactic"] for i in range(30)]
        self.assertGreater(picks.count("example_first"), 20)
        p = E.params(self.db)
        self.assertIn("visual_first", p["disabled"]["tactic|数学"])          # 明显更差 → 停用（留下其它）
        self.assertNotIn("visual_first", picks[-10:])


class ReflectTest(Base):
    def test_reward_and_version(self):
        v0 = E.active_version(self.db)
        ep = self.episode(1, "question_first", "solved", hints=2, stuck=2)
        self.assertAlmostEqual(ep["reward"], 0.55)                   # 0.65 − 0.1·(2−1)
        self.assertGreater(ep["version"], v0)
        self.assertEqual(E.params(self.db)["tactic"]["数学"]["question_first"], [1.55, 1.45])
        self.assertIn("自己做对", ep["summary"])
        self.assertEqual(E.reward_of({"outcome": "full", "hints": 0, "stuck": 0, "leaks": 0}), 0.1)
        self.assertEqual(E.reward_of({"outcome": "abandoned", "hints": 0, "stuck": 0, "leaks": 2}), 0.0)

    def test_variant_feedback(self):
        self.episode(1, "example_first", "solved", hints=1)
        v = E.variant_feedback(self.db, 1, 1, 2)
        self.assertEqual(E.active_version(self.db), v)
        a, b = E.params(self.db)["tactic"]["数学"]["example_first"]
        self.assertAlmostEqual(a, 1 + 0.85 + 0.25)
        self.assertIsNone(E.variant_feedback(self.db, 999, 1, 2))

    def test_lessons_need_three(self):
        for i in range(2):
            self.episode(i + 1, "example_first", "solved")
        self.assertEqual(E.lessons_for(self.db, "数学", "计算"), [])
        self.episode(3, "example_first", "solved")
        ls = E.lessons_for(self.db, "数学", "计算")
        self.assertEqual(len(ls), 1)
        self.assertIn("3/3", ls[0])
        self.assertIn("先举小例子", ls[0])

    def test_pluggable_reflector(self):
        fake = lambda msgs, **kw: {"summary": "先举小例子对计算卡点有效"}  # noqa: E731
        ep = {"subject": "数学", "stuck_type": "计算", "tactic": "example_first", "pace": "steady", "outcome": "solved",
              "hints": 1, "stuck": 0, "leaks": 0, "reward": 0.85}
        self.assertEqual(E.LLMReflector(fake).reflect(ep), "先举小例子对计算卡点有效")

        def boom(msgs, **kw):
            raise RuntimeError("down")
        self.assertIn("奖励 0.85", E.LLMReflector(boom).reflect(ep))      # 失败退回离线规则
        self.assertEqual(E.default_reflector().name, "offline")


class RollbackTest(Base):
    def test_rollback_restores_params_append_only(self):
        v1 = E.active_version(self.db)
        self.episode(1, "example_first", "solved")
        v2 = E.active_version(self.db)
        self.episode(2, "example_first", "solved")
        self.assertNotEqual(E.params(self.db), E.params(self.db, v2))
        v4 = E.rollback(self.db, v2)
        self.assertEqual(E.params(self.db), E.params(self.db, v2))
        self.assertEqual(self.db.q("SELECT COUNT(*) AS n FROM policy_versions", one=True)["n"], 4)   # 只追加
        E.rollback(self.db, v1)
        self.assertEqual(E.params(self.db), {})
        self.assertGreater(E.active_version(self.db), v4)
        ops = [r["op"] for r in self.db.q("SELECT op FROM evolve_log ORDER BY id")]
        self.assertEqual(ops.count("rollback"), 2)
        with self.assertRaises(ValueError):
            E.rollback(self.db, 999)


class CandidateRuleTest(Base):
    def test_shadow_only_and_manual_approval(self):
        rid = E.suspect_missed_leak(self.db, 5, "数学", "可以写成 $(x-2)(x-3)$ 吗？", "hint", "(x-2)(x-3)=0", "x^2-5x+6=0")
        self.assertIsNotNone(rid)
        r = self.db.q("SELECT * FROM candidate_rules WHERE id=?", (rid,), one=True)
        self.assertEqual(r["status"], "shadow")
        self.assertEqual(E.approved_rules(self.db), [])                  # 不自动上线
        # 影子统计：提示阶段命中 → tp；完整解法里命中 → 误报
        E.shadow_eval(self.db, "数学", "试试 (x+1)(x-4)", "hint", False, "x^2-3x-4=0")
        E.shadow_eval(self.db, "数学", "完整解法：(x+1)(x-4)=0", "full", True, "")
        r = self.db.q("SELECT * FROM candidate_rules WHERE id=?", (rid,), one=True)
        self.assertEqual((r["hits"], r["tp"], r["fp"]), (2, 1, 1))
        with self.assertRaises(E.GuardrailError):
            E.set_rule_status(self.db, rid, "approved")                 # 数据不够、误报高，不能批准
        self.db.x("UPDATE candidate_rules SET hits=20, fp=1, tp=19 WHERE id=?", (rid,))
        v = E.set_rule_status(self.db, rid, "approved")
        self.assertEqual([x["id"] for x in E.approved_rules(self.db)], [rid])
        self.assertTrue(E.extra_leak(E.approved_rules(self.db), "数学", "写成 (x+5)(x-1) 看看"))
        E.rollback(self.db, v - 1)                                       # 回滚即撤销批准
        self.assertEqual(E.approved_rules(self.db), [])

    def test_no_candidate_when_student_wrote_it_or_full(self):
        self.assertIsNone(E.suspect_missed_leak(self.db, 5, "数学", "完整解法 (x-2)(x-3)", "full", "(x-2)(x-3)", "x"))
        self.assertIsNone(E.suspect_missed_leak(self.db, 5, "数学", "想想 (x-2)(x-3)", "hint", "我不会", "x"))


def start(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class ServerFlowTest(unittest.TestCase):
    """离线演示模式整条链路：答疑 → 推断 / 误区 / 反思 → 记忆页 / 成长页 / 回滚 / 清空。"""
    @classmethod
    def setUpClass(cls):
        import importlib
        cls.dir = tempfile.mkdtemp()
        os.environ["LYCEUM_DATA"] = cls.dir
        cls._key = llm.API_KEY
        llm.API_KEY = ""
        import server
        cls.mod = importlib.reload(server)
        cls.srv = start(cls.mod.H)
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        cls.op = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        llm.API_KEY = cls._key
        cls.srv.shutdown()
        cls.mod.db.conn.close()
        shutil.rmtree(cls.dir)

    def post(self, p, b):
        req = urllib.request.Request(self.base + p, data=json.dumps(b).encode(), headers={"Content-Type": "application/json"})
        return json.loads(self.op.open(req).read())

    def get(self, p):
        return json.loads(self.op.open(self.base + p).read())

    def test_flow(self):
        self.post("/api/profile", {"grade": 8})
        r = self.post("/api/chat", {"message": "解方程 x^2-5x+6=0。我叫王小明，我最喜欢踢足球"})
        sid = r["session_id"]
        self.assertIn(r["meta"]["arms"]["tactic"], E.TACTICS)
        self.assertIn("stuck_type", r["meta"]["thought"])
        r = self.post("/api/chat", {"message": "不知道怎么下手", "session_id": sid})
        self.assertEqual(r["meta"]["thought"]["stuck_type"], "方法")
        r = self.post("/api/chat", {"message": "x=1 或 x=6", "session_id": sid})
        self.assertIs(r["meta"]["student_correct"], False)
        r = self.post("/api/chat", {"message": "x=2 或 x=3", "session_id": sid})
        self.assertTrue(r["state"]["solved"])
        mem = self.get("/api/memory")
        texts = " ".join(i["text"] for i in mem["items"])
        self.assertIn("足球", texts)
        self.assertNotIn("王小明", texts)
        self.assertTrue(any(i["kind"] == "misconception" for i in mem["items"]))
        g = self.get("/api/growth")
        self.assertEqual(len(g["episodes"]), 1)
        self.assertEqual(g["episodes"][0]["outcome"], "solved")
        self.assertTrue(g["protected"])
        # 改、删、偏好、回滚、清空
        it = mem["items"][0]
        self.assertEqual(self.post("/api/memory/%d/edit" % it["id"], {"text": "改过的一条"})["item"]["text"], "改过的一条")
        self.assertEqual(self.post("/api/memory/prefs", {"depth": "brief"})["prefs"]["depth"], "brief")
        first = g["versions"][-1]["id"]
        v = self.post("/api/growth/rollback", {"version": first})["version"]
        self.assertEqual(self.get("/api/growth")["version"], v)
        self.post("/api/memory/clear", {})
        self.assertEqual(self.get("/api/memory")["count"], 0)


if __name__ == "__main__":
    unittest.main()
