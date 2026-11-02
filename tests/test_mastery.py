"""掌握度（BKT）、证据折算、复习排程、数据库迁移的离线测试。不调用任何模型。
运行：python -m unittest discover -s tests"""
import datetime
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lyceum import mastery as M  # noqa: E402
from lyceum import db as DBMOD  # noqa: E402
from lyceum.db import DB  # noqa: E402

TZ8 = datetime.timezone(datetime.timedelta(hours=8))


def ts(y, mo, d, h=20):
    """上海时间某天晚上 8 点的时间戳。"""
    return datetime.datetime(y, mo, d, h, 0, tzinfo=TZ8).timestamp()


class BKTTest(unittest.TestCase):
    def test_posterior_by_hand(self):
        # P=0.2 做对：0.2·0.9 / (0.2·0.9 + 0.8·0.2) = 0.18/0.34
        self.assertAlmostEqual(M.posterior(0.2, True), 0.18 / 0.34, places=9)
        # P=0.2 做错：0.2·0.1 / (0.2·0.1 + 0.8·0.8) = 0.02/0.66
        self.assertAlmostEqual(M.posterior(0.2, False), 0.02 / 0.66, places=9)

    def test_update_adds_transit(self):
        p = M.bkt_update(0.2, True)
        post = 0.18 / 0.34
        self.assertAlmostEqual(p, post + (1 - post) * 0.15, places=9)  # ≈ 0.6

    def test_two_rights_cross_threshold_one_wrong_drops(self):
        p = M.apply_evidence(M.P_INIT, "variant_right")
        p = M.apply_evidence(p, "variant_right")
        self.assertGreaterEqual(p, M.MASTERY_P)
        self.assertLess(M.apply_evidence(p, "variant_wrong"), 0.7)

    def test_weight_zero_is_transit_only_and_no_transit_flag(self):
        self.assertAlmostEqual(M.bkt_update(0.5, True, weight=0.0), 0.5 + 0.5 * 0.15)
        self.assertAlmostEqual(M.bkt_update(0.5, True, weight=0.0, transit=False), 0.5)

    def test_hint_levels_are_ordered(self):
        gains = [M.apply_evidence(0.3, M.solve_kind(h)) for h in range(4)]
        self.assertEqual(gains, sorted(gains, reverse=True))  # 用的提示越多，涨得越少
        self.assertGreater(gains[3], 0.3)                      # 第 3 级仍是弱正确
        self.assertLess(M.apply_evidence(0.3, "full_solution"), 0.3)  # 看完整解法视作错误
        self.assertEqual(M.solve_kind(7), "solve_h3")

    def test_self_report_is_weak_and_capped(self):
        p = M.P_INIT
        once = M.apply_evidence(p, "self_report")
        self.assertLess(once - p, M.apply_evidence(p, "variant_right") - p)
        for _ in range(200):
            p = M.apply_evidence(p, "self_report")
        self.assertLessEqual(p, M.SELF_REPORT_CAP)
        self.assertLess(p, M.MASTERY_P)
        # 已经高于上限时，自评不会把它拉低
        self.assertAlmostEqual(M.apply_evidence(0.9, "self_report"), 0.9)

    def test_params_exposed(self):
        pr = M.params()
        self.assertEqual(pr["ladder_days"], [1, 2, 4, 7, 15, 30])
        self.assertEqual(pr["mastery_p"], 0.85)
        self.assertIn("self_report", pr["evidence"])


class ChatEvidenceTest(unittest.TestCase):
    def test_mapping(self):
        st = {"problem": "p", "hint_level": 2}
        self.assertEqual(M.chat_evidence({"student_correct": True, "solved": True, "stage": "solved"}, st), "solve_h2")
        self.assertEqual(M.chat_evidence({"stage": "full", "solved": True}, st), "full_solution")
        self.assertIsNone(M.chat_evidence({"student_correct": False, "stage": "check"}, st))
        self.assertIsNone(M.chat_evidence({"student_correct": True, "solved": False, "stage": "check"}, st))  # 只对了中间一步
        self.assertEqual(M.chat_evidence({"student_correct": True, "solved": True}, {"problem": "p"}), "solve_h0")

    def test_once_per_problem_and_needs_problem(self):
        self.assertIsNone(M.chat_evidence({"stage": "full"}, {"problem": "p", "ev_logged": "solve_h1"}))
        self.assertIsNone(M.chat_evidence({"stage": "full"}, {}))


class ScheduleTest(unittest.TestCase):
    D = datetime.date(2026, 11, 2)

    def test_first_evidence_tomorrow(self):
        for eff in ("right", "wrong", "none"):
            sch, counted = M.schedule({}, eff, self.D)
            self.assertEqual(sch, {"review_step": 0, "review_streak": 0, "next_review": "2026-11-03"})
            self.assertFalse(counted)

    def test_full_ladder_walk(self):
        item, d, got = {}, self.D, []
        item, _ = M.schedule(item, "right", d)
        for _ in range(7):
            d = M.as_date(item["next_review"])
            item, counted = M.schedule(item, "right", d)
            self.assertTrue(counted)
            got.append((M.as_date(item["next_review"]) - d).days)
        self.assertEqual(got, [2, 4, 7, 15, 30, 30, 30])  # 封顶 30 天
        self.assertEqual(item["review_streak"], 7)

    def test_early_right_does_not_advance(self):
        item = {"review_step": 1, "review_streak": 1, "next_review": "2026-11-05"}
        sch, counted = M.schedule(item, "right", self.D)
        self.assertEqual(sch, item)
        self.assertFalse(counted)

    def test_wrong_resets_even_if_early(self):
        item = {"review_step": 4, "review_streak": 4, "next_review": "2026-11-20"}
        sch, counted = M.schedule(item, "wrong", self.D)
        self.assertEqual(sch, {"review_step": 0, "review_streak": 0, "next_review": "2026-11-03"})
        self.assertFalse(counted)  # 没到期，不算一次间隔复习，但照样回到 1 天
        sch, counted = M.schedule(dict(item, next_review="2026-11-01"), "wrong", self.D)
        self.assertTrue(counted)

    def test_overdue_counts(self):
        sch, counted = M.schedule({"review_step": 0, "review_streak": 0, "next_review": "2026-10-20"}, "right", self.D)
        self.assertTrue(counted)
        self.assertEqual(sch["next_review"], "2026-11-04")

    def test_none_keeps(self):
        item = {"review_step": 2, "review_streak": 2, "next_review": "2026-11-01"}
        self.assertEqual(M.schedule(item, "none", self.D), (item, False))

    def test_today_is_shanghai(self):
        utc_late = datetime.datetime(2026, 11, 1, 16, 30, tzinfo=datetime.timezone.utc).timestamp()
        self.assertEqual(M.today(utc_late), datetime.date(2026, 11, 2))  # UTC 16:30 = 上海次日 0:30


class DBTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = DB(os.path.join(self.dir, "lyceum.db"))

    def tearDown(self):
        self.db.conn.close()
        shutil.rmtree(self.dir)

    def test_events_are_auditable(self):
        t = ts(2026, 11, 2)
        sk = self.db.record_evidence("数学", "一元二次方程", "variant_right", ref={"practice_id": 9}, now=t)
        self.assertAlmostEqual(sk["p_l"], M.bkt_update(0.2, True))
        _, ev = self.db.skill_events(sk["id"])
        self.assertEqual(len(ev), 1)
        e = ev[0]
        self.assertEqual((e["kind"], e["day"], e["correct"], e["weight"]), ("variant_right", "2026-11-02", 1, 1.0))
        self.assertAlmostEqual(e["p_before"], 0.2)
        self.assertAlmostEqual(e["p_after"], sk["p_l"])
        self.assertEqual(e["ref"], {"practice_id": 9})
        self.assertEqual(e["next_after"], "2026-11-03")

    def test_mastery_needs_two_spaced_reviews(self):
        t = ts(2026, 11, 2)
        for _ in range(3):  # 同一天连对三道：P 够了，但没有间隔复习
            sk = self.db.record_evidence("数学", "因式分解", "variant_right", now=t)
        self.assertGreaterEqual(sk["p_l"], M.MASTERY_P)
        self.assertEqual(sk["mastered"], 0)
        self.assertEqual(M.status(sk), "consolidating")
        sk = self.db.record_evidence("数学", "因式分解", "retry_right", now=ts(2026, 11, 3))  # 第 1 次到期复习
        self.assertEqual((sk["mastered"], sk["review_streak"], sk["next_review"]), (0, 1, "2026-11-05"))
        sk = self.db.record_evidence("数学", "因式分解", "variant_right", now=ts(2026, 11, 4))  # 提前做：不算
        self.assertEqual(sk["review_streak"], 1)
        sk = self.db.record_evidence("数学", "因式分解", "variant_right", now=ts(2026, 11, 5))  # 第 2 次到期复习
        self.assertEqual((sk["mastered"], sk["review_streak"], sk["next_review"]), (1, 2, "2026-11-09"))
        self.assertEqual(M.status(sk), "mastered")
        sk = self.db.record_evidence("数学", "因式分解", "variant_wrong", now=ts(2026, 11, 9))  # 到期答错：掉回去
        self.assertEqual((sk["mastered"], sk["review_streak"], sk["next_review"]), (0, 0, "2026-11-10"))

    def test_self_report_never_masters_mistake(self):
        mid = self.db.add_mistake(session_id=1, subject="物理", topic="参照物", question="q", user_answer="a",
                                  correct_answer="b", explain="", source="变式题", created=ts(2026, 11, 1))
        for i in range(30):
            self.db.self_report_mistake(mid, now=ts(2026, 11, 2) + i)
        m = self.db.get_mistake(mid)
        sk = self.db.skill("物理", "参照物")
        self.assertEqual(m["mastered"], 0)
        self.assertEqual(m["next_review"], "2026-11-02")  # 排程没被自评改动
        self.assertLess(sk["p_l"], M.MASTERY_P)
        self.assertEqual(sk["mastered"], 0)

    def test_mistake_review_and_today_list(self):
        mid = self.db.add_mistake(session_id=1, subject="数学", topic="因式分解", question="q1", user_answer="a",
                                  correct_answer="b", explain="", source="变式题", created=ts(2026, 11, 1))
        self.assertEqual(self.db.get_mistake(mid)["next_review"], "2026-11-02")
        self.db.record_evidence("数学", "因式分解", "variant_wrong", now=ts(2026, 11, 1))
        today = self.db.review_today(now=ts(2026, 11, 2))
        self.assertEqual(today["date"], "2026-11-02")
        self.assertEqual([m["id"] for m in today["mistakes"]], [mid])
        self.assertEqual([s["topic"] for s in today["skills"]], ["因式分解"])
        self.assertEqual(self.db.review_today(now=ts(2026, 11, 1))["mistakes"], [])
        # 到期两次全对，且知识点 P(L) 够高 → 错题出本
        for day in (2, 4):
            for _ in range(2):
                self.db.record_evidence("数学", "因式分解", "retry_right", now=ts(2026, 11, day))
            m = self.db.review_mistake(mid, True, now=ts(2026, 11, day))
        self.assertEqual((m["mastered"], m["review_streak"], m["next_review"]), (1, 2, None))
        ev = self.db.q("SELECT * FROM mastery_events WHERE mistake_id=? AND scope='mistake'", (mid,))
        self.assertEqual(len(ev), 2)
        # 答错：错题回到 1 天
        mid2 = self.db.add_mistake(session_id=1, subject="数学", topic="因式分解", question="q2", user_answer="a",
                                   correct_answer="b", explain="", source="变式题", created=ts(2026, 11, 1))
        m2 = self.db.review_mistake(mid2, False, now=ts(2026, 11, 2))
        self.assertEqual((m2["review_step"], m2["next_review"], m2["mastered"]), (0, "2026-11-03", 0))

    def test_mastery_list(self):
        self.db.record_evidence("英语", "时态", "full_solution", now=ts(2026, 11, 1))
        rows = self.db.mastery_list(now=ts(2026, 11, 2))
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["status"], rows[0]["due"], rows[0]["interval_days"]), ("learning", True, 1))
        self.assertLess(rows[0]["p_l"], M.P_INIT + M.P_TRANSIT)


OLD_SCHEMA = """
CREATE TABLE profile (id INTEGER PRIMARY KEY CHECK (id = 1), grade INTEGER, textbook TEXT, nickname TEXT, updated REAL);
CREATE TABLE sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, created REAL, updated REAL, title TEXT, subject TEXT, topic TEXT, problem TEXT, state TEXT);
CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER, role TEXT, content TEXT, image TEXT, meta TEXT, created REAL);
CREATE TABLE practice (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER, subject TEXT, topic TEXT, questions TEXT, results TEXT, created REAL);
CREATE TABLE mistakes (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER, subject TEXT, topic TEXT, question TEXT, user_answer TEXT, correct_answer TEXT, explain TEXT, source TEXT, mastered INTEGER DEFAULT 0, created REAL);
"""


class MigrationTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def counts(self, path):
        c = sqlite3.connect(path)
        out = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("profile", "sessions", "messages", "practice", "mistakes")}
        cols = {r[1] for r in c.execute("PRAGMA table_info(mistakes)")}
        topic = "COALESCE(topic_raw, topic)" if "topic_raw" in cols else "topic"  # v3 改名后原标签在 topic_raw
        rows = c.execute(f"SELECT id, subject, {topic}, question, user_answer, mastered, created FROM mistakes ORDER BY id").fetchall()
        c.close()
        return out, rows

    def check(self, path):
        before, rows_before = self.counts(path)
        d = DB(path)
        after, rows_after = self.counts(path)
        self.assertEqual(before, after)          # 一行不丢
        self.assertEqual(rows_before, rows_after)  # 旧列原样
        self.assertEqual(d.conn.execute("PRAGMA user_version").fetchone()[0], DBMOD.SCHEMA_VERSION)
        n_ev = d.q("SELECT COUNT(*) AS n FROM mastery_events", one=True)["n"]
        open_m = d.q("SELECT COUNT(*) AS n FROM mistakes WHERE mastered=0 AND next_review IS NULL", one=True)["n"]
        self.assertEqual(open_m, 0)  # 旧的未掌握错题都排上了复习
        d.conn.close()
        d2 = DB(path)  # 再开一次：不重复回放
        self.assertEqual(d2.q("SELECT COUNT(*) AS n FROM mastery_events", one=True)["n"], n_ev)
        return d2, n_ev

    def test_synthetic_old_db(self):
        p = os.path.join(self.dir, "old.db")
        c = sqlite3.connect(p)
        c.executescript(OLD_SCHEMA)
        t = ts(2026, 10, 30)
        c.execute("INSERT INTO practice (session_id, subject, topic, questions, results, created) VALUES (1,'数学','方程','[]',?,?)",
                  (json.dumps([{"correct": True}, {"correct": False}]), t))
        c.execute("INSERT INTO mistakes (session_id, subject, topic, question, source, mastered, created) VALUES (1,'英语','时态','q','讲解',0,?)", (t,))
        c.execute("INSERT INTO mistakes (session_id, subject, topic, question, source, mastered, created) VALUES (1,'数学','方程','q2','变式题',1,?)", (t,))
        c.commit()
        c.close()
        d, n_ev = self.check(p)
        self.assertEqual(n_ev, 3)  # 2 道变式题 + 1 条看完整解法
        ev = d.q("SELECT kind, ref FROM mastery_events ORDER BY ts, id")
        self.assertTrue(all(json.loads(e["ref"]).get("backfill") == 1 for e in ev))
        m = d.q("SELECT * FROM mistakes ORDER BY id")
        self.assertEqual(m[0]["next_review"], "2026-10-31")
        self.assertIsNone(m[1]["next_review"])  # 已掌握的旧错题不排程
        self.assertEqual(m[1]["mastered"], 1)
        d.conn.close()

    def test_screens_testdata_copy(self):
        src = os.path.join(os.path.dirname(ROOT), "testdata", "screens", "lyceum.db")
        if not os.path.exists(src):
            self.skipTest("没有 testdata/screens/lyceum.db")
        p = os.path.join(self.dir, "lyceum.db")
        shutil.copy(src, p)
        d, n_ev = self.check(p)
        self.assertGreater(n_ev, 0)
        self.assertGreater(len(d.mastery_list()), 0)
        d.conn.close()


class ServerFlowTest(unittest.TestCase):
    """离线演示模式下走一遍真实 HTTP 接口（llm 未启用，不发任何网络请求给模型）。"""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        os.environ["LYCEUM_DATA"] = cls.dir
        os.environ.pop("LYCEUM_API_KEY", None)
        from lyceum import llm
        llm.API_KEY = ""

        def no_model(*a, **k):
            raise AssertionError("测试里不应调用模型")
        llm.chat = no_model
        import importlib
        import server
        cls.server_mod = importlib.reload(server)
        from http.server import ThreadingHTTPServer
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), cls.server_mod.H)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.server_mod.db.conn.close()
        shutil.rmtree(cls.dir)

    def call(self, path, body=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 本机请求不走代理
        with opener.open(req) as r:
            return json.loads(r.read())

    def test_flow(self):
        r = self.call("/api/chat", {"message": "解方程 x^2-7x+12=0"})
        sid = r["session_id"]
        self.call("/api/chat", {"session_id": sid, "message": "", "action": "full"})
        self.call("/api/chat", {"session_id": sid, "message": "", "action": "full"})  # 同一道题不重复记
        sk = self.call("/api/mastery")["skills"]
        self.assertEqual(len(sk), 1)
        ev = self.call(f"/api/mastery/{sk[0]['id']}/events")["events"]
        self.assertEqual([e["kind"] for e in ev], ["full_solution"])
        p = self.call("/api/practice", {"session_id": sid, "n": 2})
        g = self.call("/api/grade", {"practice_id": p["practice_id"], "answers": ["x=3 或 x=4", "错的"]})
        self.assertEqual((g["right"], g["total"]), (1, 2))
        self.assertIn("mastery", g)
        ms = self.call("/api/mistakes")["mistakes"]
        variant_m = [m for m in ms if m["source"] == "变式题"][0]
        self.assertIsNotNone(variant_m["next_review"])
        # 「我会了」：弱证据，错题仍在本子里
        r = self.call(f"/api/mistakes/{variant_m['id']}/master", {})
        self.assertEqual(r["mistake"]["mastered"], 0)
        self.assertTrue(any(m["id"] == variant_m["id"] for m in self.call("/api/mistakes")["mistakes"]))
        # 再练一次 → practice 带 mistake_id → 批改后写错题复习事件
        rp = self.call(f"/api/mistakes/{variant_m['id']}/retry", {})
        self.call("/api/grade", {"practice_id": rp["practice_id"], "answers": ["x=3 或 x=4", "x=2 或 x=-3"]})
        ev = self.call(f"/api/mastery/{sk[0]['id']}/events")["events"]
        kinds = [e["kind"] for e in ev]
        self.assertEqual(kinds, ["full_solution", "variant_right", "variant_wrong", "self_report", "retry_right", "retry_right", "retry_right"])
        self.assertEqual(ev[-1]["scope"], "mistake")
        today = self.call("/api/review/today")
        self.assertIn("skills", today)
        self.assertIn("mistakes", today)
        rs = self.call(f"/api/review/skill/{sk[0]['id']}", {})
        self.assertEqual(len(rs["questions"]), 2)


if __name__ == "__main__":
    unittest.main()
