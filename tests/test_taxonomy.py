"""知识点规范表、标签归一化、旧库分裂标签合并（证据按时间重放）、迁移幂等、提示词里的规范表。
全部离线：不调用任何模型（用假的 llm.chat）。运行：python -m unittest discover -s tests"""
import datetime
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lyceum import agent, llm  # noqa: E402
from lyceum import mastery as M  # noqa: E402
from lyceum import taxonomy as T  # noqa: E402
from lyceum.db import DB  # noqa: E402

TZ8 = datetime.timezone(datetime.timedelta(hours=8))


def ts(mo, d, h=20, mi=0):
    return datetime.datetime(2026, mo, d, h, mi, tzinfo=TZ8).timestamp()


NINE = ["语文", "数学", "英语", "物理", "化学", "生物", "历史", "地理", "道德与法治"]


class NormalizeTest(unittest.TestCase):
    def test_norm_width_space_punct_separators(self):
        self.assertEqual(T.norm(" 一元二次方程 · 因式分解 "), "一元二次方程因式分解")
        self.assertEqual(T.norm("一元二次方程／因式分解"), T.norm("一元二次方程-因式分解"))  # 全角斜杠 = 半角
        self.assertEqual(T.norm("ＡＢＣ（一）"), "abc一")
        self.assertEqual(T.segments("一元二次方程——因式分解法"), ["一元二次方程", "因式分解法"])
        self.assertEqual(T.segments("一元二次方程·因式分…"), ["一元二次方程", "因式分"])

    def test_clean_label_keeps_english_spaces(self):
        self.assertEqual(T.clean_label(" Present   Perfect "), "Present Perfect")
        self.assertEqual(T.clean_label("我的 标签 / 子项…"), "我的标签·子项")

    def test_dice(self):
        self.assertAlmostEqual(T.dice("一元二次方式", "一元二次方程"), 0.8)
        self.assertEqual(T.dice("光合作用", "欧姆定律"), 0.0)


class ResolveTest(unittest.TestCase):
    def r(self, subject, raw, band="middle"):
        return T.resolve(subject, raw, band)

    def test_split_labels_converge(self):
        variants = ["因式分解", "一元二次方程·因式分解", "一元二次方程-因式分解法", "一元二次方程 / 因式分解",
                    "一元二次方程的因式分解", "因式分解（提公因式）", "十字相乘法", "一元二次方程·因式分…"]
        got = {v: self.r("数学", v)["topic"] for v in variants}
        self.assertEqual(set(got.values()), {"因式分解"}, got)

    def test_methods(self):
        self.assertEqual(self.r("数学", "因式分解")["method"], "exact")
        self.assertEqual(self.r("数学", "韦达定理")["method"], "alias")
        self.assertEqual(self.r("数学", "一元二次方程·因式分解")["method"], "exact")  # 最后一段精确命中
        self.assertEqual(self.r("数学", "二次函数图象与性质")["method"], "contains")
        self.assertEqual(self.r("数学", "一元二次方式"), {"topic": "一元二次方程", "matched": True, "method": "fuzzy", "band": "middle"})
        self.assertEqual(self.r("数学", "一元二次方程·因式分…")["method"], "prefix")

    def test_head_final_containment(self):
        # 没有分隔符时，中心词在后：「…的因式分解」归因式分解，「用因式分解法解一元二次方程」归一元二次方程
        self.assertEqual(self.r("数学", "一元二次方程的因式分解")["topic"], "因式分解")
        self.assertEqual(self.r("数学", "用因式分解法解一元二次方程")["topic"], "一元二次方程")

    def test_same_subject_only_and_unmatched_kept(self):
        self.assertEqual(self.r("生物", "光合作用")["topic"], "光合作用")
        phys = self.r("物理", "光合作用")
        self.assertEqual((phys["topic"], phys["matched"]), ("光合作用", False))  # 不跨学科合并
        un = self.r("数学", "演示模式")
        self.assertEqual((un["topic"], un["matched"], un["method"]), ("演示模式", False, "unmatched"))
        self.assertFalse(self.r("其他", "因式分解")["matched"])  # 不在规范表里的学科
        self.assertEqual(self.r("数学", "")["topic"], "")

    def test_band_preference_then_other_bands(self):
        self.assertEqual(T.resolve("数学", "抛物线", "middle")["topic"], "二次函数")
        self.assertEqual(T.resolve("数学", "抛物线", "high")["topic"], "圆锥曲线")
        r = T.resolve("数学", "鸡兔同笼问题", "high")  # 当前学段没有 → 同科其他学段
        self.assertEqual((r["topic"], r["band"]), ("鸡兔同笼", "primary"))

    def test_examples_across_subjects(self):
        cases = [("物理", "参照物与运动", "机械运动"), ("语文", "古诗词鉴赏", "古诗文赏析"), ("英语", "动词时态", "时态"),
                 ("化学", "化学方程式的配平", "化学方程式"), ("历史", "辛亥革命的意义", "辛亥革命"),
                 ("地理", "经纬网定位", "地球与地图"), ("道德与法治", "公民的权利和义务", "公民权利和义务")]
        for subj, raw, want in cases:
            self.assertEqual(self.r(subj, raw)["topic"], want, (subj, raw))

    def test_idempotent(self):
        for subj in NINE:
            for band in T.BANDS:
                for n in T.names(subj, band):
                    self.assertEqual(T.resolve(subj, n, band)["topic"], n)
        self.assertEqual(T.canonical("数学", T.canonical("数学", "我的 标签")), "我的标签")


class TaxonomyDataTest(unittest.TestCase):
    def test_coverage(self):
        expect = {"语文": T.BANDS, "数学": T.BANDS, "英语": T.BANDS, "物理": ("middle", "high"), "化学": ("middle", "high"),
                  "生物": ("middle", "high"), "历史": ("middle", "high"), "地理": ("middle", "high"), "道德与法治": T.BANDS}
        for subj, bands in expect.items():
            for b in bands:
                self.assertGreaterEqual(len(T.names(subj, b)), 9, (subj, b))
        self.assertTrue(set(NINE) <= set(T.subjects()))

    def test_names_short_and_aliases_unique_per_band(self):
        for subj in T.INDEX:
            for band, entries in T.INDEX[subj].items():
                seen = {}
                for e in entries:
                    self.assertLessEqual(len(e.name), 10, e.name)
                    for k in e.keys:
                        self.assertNotIn(k, seen, f"{subj}/{band} 别名重复：{k}（{seen.get(k)} / {e.name}）")
                        seen[k] = e.name


class FakeLLM:
    def __init__(self, topic):
        self.topic, self.calls = topic, []

    def __call__(self, msgs, **kw):
        self.calls.append(msgs)
        return {"subject": "数学", "topic": self.topic, "intent": "new_problem", "problem": "解方程 x^2-5x+6=0",
                "stage": "hint", "hint_level": 1, "student_correct": None, "solved": False, "reply": "先想想：哪两个数乘积是 6？"}


class PromptTest(unittest.TestCase):
    def setUp(self):
        self._chat, self._key = llm.chat, llm.API_KEY
        llm.API_KEY = "x"

    def tearDown(self):
        llm.chat, llm.API_KEY = self._chat, self._key

    def test_prompt_lists_band_taxonomy(self):
        p8 = agent.system_prompt({"grade": 8, "textbook": "人教版"}, {"subject": "数学"}, False)
        self.assertIn("规范知识点", p8)
        self.assertIn("初中各学科规范知识点", p8)
        self.assertIn("因式分解", p8)
        for subj in NINE:
            self.assertIn(f"- {subj}：", p8)
        self.assertNotIn("圆锥曲线", p8)   # 高中才有
        self.assertNotIn("一元二次方程·因式分解", p8)  # 旧示例已去掉
        block = p8.split("初中各学科规范知识点")[1]
        self.assertTrue(block.split("\n")[1].startswith("- 数学："))  # 当前学科放第一行
        p11 = agent.system_prompt({"grade": 11}, {}, False)
        self.assertIn("高中各学科规范知识点", p11)
        self.assertIn("圆锥曲线", p11)
        p3 = agent.system_prompt({"grade": 3}, {}, False)
        self.assertIn("小学各学科规范知识点", p3)
        self.assertIn("- 科学：", p3)

    def test_fake_model_topic_is_canonicalized(self):
        fake = FakeLLM("一元二次方程·因式分解")
        llm.chat = fake
        out, st = agent.respond({"grade": 8}, {"state": {}}, [], "解方程 x^2-5x+6=0")
        self.assertIn("初中各学科规范知识点", fake.calls[0][0]["content"])
        self.assertEqual((out["topic"], out["topic_raw"], out["topic_matched"]), ("因式分解", "一元二次方程·因式分解", True))
        self.assertEqual(st["topic"], "因式分解")
        fake.topic = "完全不在表里的东西"
        out, _ = agent.respond({"grade": 8}, {"state": {}}, [], "新题")
        self.assertEqual((out["topic"], out["topic_matched"]), ("完全不在表里的东西", False))


class MergeTest(unittest.TestCase):
    """模拟 v2 旧库：同一知识点被模型写成几种说法，各自攒了证据和错题。"""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "lyceum.db")
        d = DB(self.path)
        d.set_profile(8, "人教版")
        self.raw = {}

        def raw_skill(subject, topic):  # 绕过归一化，直接写旧式标签
            d.x("INSERT INTO skills (subject, topic, p_init, p_transit, p_slip, p_guess, p_l, n_obs, review_step, review_streak, "
                "next_review, mastered, created, updated) VALUES (?,?,?,?,?,?,?,0,0,0,NULL,0,?,?)",
                (subject, topic, M.P_INIT, M.P_TRANSIT, M.P_SLIP, M.P_GUESS, M.P_INIT, ts(10, 1), ts(10, 1)))
            self.raw[(subject, topic)] = d.q("SELECT id FROM skills WHERE subject=? AND topic=?", (subject, topic), one=True)["id"]

        def ev(subject, topic, kind, when):
            sk = d.q("SELECT * FROM skills WHERE id=?", (self.raw[(subject, topic)],), one=True)
            d._apply(sk, kind, when, ref={"demo": 1})

        for s, t in [("数学", "因式分解"), ("数学", "一元二次方程·因式分解"), ("数学", "一元二次方程-因式分解法"),
                     ("物理", "参照物与运动"), ("数学", "演示 模式"), ("数学", "演示模式"),
                     ("生物", "光合作用"), ("化学", "光合作用")]:
            raw_skill(s, t)
        # 三种说法交错着记证据
        self.seq = [("一元二次方程·因式分解", "full_solution", ts(10, 20)), ("因式分解", "variant_right", ts(10, 21)),
                    ("一元二次方程-因式分解法", "variant_wrong", ts(10, 22)), ("一元二次方程·因式分解", "variant_right", ts(10, 23)),
                    ("因式分解", "self_report", ts(10, 23, 21)), ("一元二次方程·因式分解", "variant_right", ts(10, 25))]
        for t, k, w in self.seq:
            ev("数学", t, k, w)
        ev("物理", "参照物与运动", "variant_right", ts(10, 26))
        ev("数学", "演示 模式", "variant_wrong", ts(10, 27))
        ev("生物", "光合作用", "variant_right", ts(10, 28))
        ev("化学", "光合作用", "variant_wrong", ts(10, 28))
        for i, t in enumerate(["一元二次方程·因式分解", "一元二次方程·因式分解", "因式分解"]):
            d.x("INSERT INTO mistakes (session_id, subject, topic, question, source, mastered, created, review_step, review_streak, next_review) "
                "VALUES (1,'数学',?,?,'变式题',0,?,0,0,'2026-10-24')", (t, f"q{i}", ts(10, 23)))
        sid = d.new_session("s")
        d.update_session(sid, subject="数学", topic="一元二次方程·因式分解")
        d.x("INSERT INTO mastery_events (skill_id, scope, ts, day, kind, correct, weight, p_before, p_after, ref) "
            "VALUES (?, 'mistake', ?, '2026-10-24', 'retry_wrong', 0, 1.0, 0, 0, '{}')", (self.raw[("数学", "一元二次方程·因式分解")], ts(10, 24)))
        self.n_events_before = d.q("SELECT COUNT(*) AS n FROM mastery_events", one=True)["n"]
        self.before_target = d.q("SELECT * FROM skills WHERE id=?", (self.raw[("数学", "因式分解")],), one=True)
        d.x("PRAGMA user_version = 2")
        d.x("DELETE FROM meta")
        d.conn.close()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_merge_replays_in_time_order(self):
        d = DB(self.path)
        live = d.mastery_list()
        math = [k for k in live if k["subject"] == "数学"]
        self.assertEqual(sorted(k["topic"] for k in math), ["因式分解", "演示模式"])  # 三种说法 → 一个；空白差异的未归类也合并
        tgt = next(k for k in math if k["topic"] == "因式分解")
        self.assertEqual(tgt["id"], self.raw[("数学", "因式分解")])  # 目标沿用已有的规范名那一行
        # 期望值：按时间顺序把三种说法的证据依次折算（不是平均）
        p, item = M.P_INIT, {}
        for _, kind, when in self.seq:
            p = M.apply_evidence(p, kind)
            item, _ = M.schedule(item, M.EVIDENCE[kind][3], M.today(when))
        self.assertAlmostEqual(tgt["p_l"], p, places=12)
        self.assertEqual((tgt["next_review"], tgt["review_step"], tgt["review_streak"]),
                         (item["next_review"], item["review_step"], item["review_streak"]))
        self.assertEqual(tgt["n_obs"], len(self.seq))
        _, evs = d.skill_events(tgt["id"])
        self.assertEqual([e["kind"] for e in evs], [k for _, k, _ in self.seq[:5]] + ["retry_wrong"] + [k for _, k, _ in self.seq[5:]])
        self.assertTrue(all("replay_of" in e["ref"] and "merged_from" in e["ref"] for e in evs))
        self.assertEqual(evs[0]["ref"]["merged_from"], "一元二次方程·因式分解")
        # 不是取平均：三个旧知识点 P(L) 的平均值和重放结果不同
        olds = [d.q("SELECT p_l FROM skills WHERE id=?", (self.raw[("数学", t)],), one=True)["p_l"]
                for t in ("因式分解", "一元二次方程·因式分解", "一元二次方程-因式分解法")]
        self.assertGreater(abs(sum(olds[1:]) / 2 - tgt["p_l"]), 0.05)

    def test_old_rows_kept_and_mistakes_moved_and_log(self):
        d = DB(self.path)
        tid = self.raw[("数学", "因式分解")]
        for t in ("一元二次方程·因式分解", "一元二次方程-因式分解法"):
            row = d.q("SELECT * FROM skills WHERE id=?", (self.raw[("数学", t)],), one=True)
            self.assertEqual(row["merged_into"], tid)
            self.assertEqual(row["topic"], t)  # 旧行原样保留
        # 旧事件一条不删；目标自己的旧事件标 void，被重放事件取代
        self.assertEqual(d.q("SELECT COUNT(*) AS n FROM mastery_events WHERE COALESCE(void,0)=1", one=True)["n"], 2)
        total = d.q("SELECT COUNT(*) AS n FROM mastery_events", one=True)["n"]
        self.assertEqual(total, self.n_events_before + len(self.seq) + 1 + 1 + 1)  # 数学重放 7 + 机械运动 1 + 演示模式 1
        ms = d.q("SELECT topic, topic_raw FROM mistakes ORDER BY id")
        self.assertEqual([m["topic"] for m in ms], ["因式分解"] * 3)
        self.assertEqual([m["topic_raw"] for m in ms], ["一元二次方程·因式分解", "一元二次方程·因式分解", None])
        self.assertEqual(d.q("SELECT topic, topic_raw FROM sessions", one=True), {"topic": "因式分解", "topic_raw": "一元二次方程·因式分解"})
        log = {(r["from_topic"], r["to_topic"]): r for r in d.merge_log()}
        self.assertEqual(set(log), {("一元二次方程·因式分解", "因式分解"), ("一元二次方程-因式分解法", "因式分解"),
                                    ("参照物与运动", "机械运动"), ("演示 模式", "演示模式")})
        r = log[("一元二次方程·因式分解", "因式分解")]
        self.assertEqual((r["events"], r["mistakes"], r["method"]), (4, 2, "exact"))
        self.assertEqual(log[("一元二次方程-因式分解法", "因式分解")]["method"], "alias")
        # 单条改名（参照物与运动 → 机械运动）：新建规范名行，旧行指过去
        phys = [k for k in d.mastery_list() if k["subject"] == "物理"]
        self.assertEqual([(k["topic"], k["canon"], k["n_obs"]) for k in phys], [("机械运动", 1, 1)])
        un = next(k for k in d.mastery_list() if k["topic"] == "演示模式")
        self.assertEqual(un["canon"], 0)  # 未归类
        # 不同学科的同名标签不合并
        self.assertEqual(sorted(k["subject"] for k in d.mastery_list() if k["topic"] == "光合作用"), ["化学", "生物"])
        # 别名表
        al = {(a["subject"], a["raw"]): a["topic"] for a in d.q("SELECT * FROM topic_aliases")}
        self.assertEqual(al[("数学", "一元二次方程·因式分解")], "因式分解")
        self.assertIn("一元二次方程·因式分解", next(k for k in d.mastery_list() if k["topic"] == "因式分解")["aliases"])

    def test_idempotent_and_new_writes_hit_target(self):
        d = DB(self.path)
        snap = lambda: (d.q("SELECT COUNT(*) AS n FROM mastery_events", one=True)["n"], len(d.merge_log()),
                        d.q("SELECT COUNT(*) AS n FROM skills", one=True)["n"],
                        [(k["id"], round(k["p_l"], 12), k["next_review"]) for k in d.mastery_list()])
        first = snap()
        # v4（记忆与自进化）在 v3 之上只加表加列：版本号 ≥3 即说明规范化迁移已完成（原断言为 == 3）
        self.assertGreaterEqual(d.conn.execute("PRAGMA user_version").fetchone()[0], 3)
        d.conn.close()
        d = DB(self.path)  # 再开：user_version=3 且规范表版本没变，不再合并
        self.assertEqual(snap(), first)
        self.assertEqual(d.merge_topics(), 0)  # 直接再跑一遍也什么都不做
        self.assertEqual(snap(), first)
        # 迁移之后，模型再写旧说法，证据也记到同一个知识点
        tid = self.raw[("数学", "因式分解")]
        sk = d.record_evidence("数学", "一元二次方程·因式分解", "variant_right", now=ts(11, 2))
        self.assertEqual(sk["id"], tid)
        mid = d.add_mistake(session_id=1, subject="数学", topic="一元二次方程 / 因式分解", question="新题", user_answer="a",
                            correct_answer="b", explain="", source="变式题", created=ts(11, 2))
        self.assertEqual((d.get_mistake(mid)["topic"], d.get_mistake(mid)["topic_raw"]), ("因式分解", "一元二次方程 / 因式分解"))
        self.assertEqual(len([k for k in d.mastery_list() if k["subject"] == "数学" and k["canon"] == 1]), 1)
        d.conn.close()

    def test_taxonomy_version_bump_reruns(self):
        d = DB(self.path)
        d.x("UPDATE meta SET value='0' WHERE key='taxonomy_version'")
        n = len(d.merge_log())
        d.conn.close()
        d = DB(self.path)
        self.assertEqual(len(d.merge_log()), n)  # 重跑了，但已经规范，不产生新的合并
        self.assertEqual(d.q("SELECT value FROM meta WHERE key='taxonomy_version'", one=True)["value"], str(T.VERSION))
        d.conn.close()


class ReviewCountTest(unittest.TestCase):
    def test_topics_due_is_union(self):
        tmp = tempfile.mkdtemp()
        try:
            d = DB(os.path.join(tmp, "lyceum.db"))
            d.record_evidence("数学", "一次函数", "variant_wrong", now=ts(11, 1))     # 知识点到期，无错题
            d.add_mistake(session_id=1, subject="数学", topic="因式分解", question="q1", user_answer="", correct_answer="",
                          explain="", source="变式题", created=ts(11, 1))               # 错题到期，知识点没证据
            d.add_mistake(session_id=1, subject="数学", topic="因式分解", question="q2", user_answer="", correct_answer="",
                          explain="", source="变式题", created=ts(11, 1))
            d.record_evidence("英语", "时态", "variant_wrong", now=ts(11, 1))         # 两者都到期
            d.add_mistake(session_id=1, subject="英语", topic="动词时态", question="q3", user_answer="", correct_answer="",
                          explain="", source="变式题", created=ts(11, 1))
            r = d.review_today(now=ts(11, 2))
            self.assertEqual((r["topics_due"], r["mistakes_due"], len(r["skills"])), (3, 3, 2))
            ml = {k["topic"]: k for k in d.mastery_list(now=ts(11, 2))}
            self.assertEqual(sum(1 for k in ml.values() if k["review_today"]), r["topics_due"])  # 两页同一口径
            self.assertEqual((ml["因式分解"]["mistakes_due"], ml["时态"]["mistakes_due"]), (2, 1))
            d.conn.close()
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
