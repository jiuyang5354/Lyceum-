"""学习周报：数字要对，外部文本必须转义，页面必须自包含。"""
import os
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lyceum import report as R  # noqa: E402
from lyceum.db import DB  # noqa: E402


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = DB(os.path.join(self.dir.name, "t.db"))
        self.db.set_profile(8, "人教版", "小雅")
        self.now = time.time()
        sid = self.db.new_session("为什么人站在匀速上升的电梯里感觉不到自己在动？")
        self.db.update_session(sid, subject="物理", topic="机械运动", updated=self.now - 3600)
        self.db.add_message(sid, "user", "为什么？")
        self.db.add_message(sid, "assistant", "先想想受力。")
        self.db.add_mistake(subject="物理", topic="机械运动", question="电梯题", user_answer="错", correct_answer="对")
        self.db.record_evidence("物理", "机械运动", "variant_right", now=self.now - 1800)
        self.db.save_writing_review({"subject": "语文", "band": "middle", "total": 68, "max": 100,
                                     "coverage": "仅形式维度", "dims": [], "notes": [], "hints": []},
                                    task="记一次比赛", text="去年秋天，我参加了比赛。")

    def tearDown(self):
        self.dir.cleanup()

    def test_counts_only_the_last_seven_days(self):
        old = self.db.new_session("上周的旧会话")
        # update_session 会把 updated 改成现在，这里要造一条真的旧记录
        self.db.x("UPDATE sessions SET updated=? WHERE id=?", (self.now - 9 * 86400, old))
        data = R.week(self.db, now=self.now)
        self.assertEqual(data["sessions"], 1)
        self.assertGreaterEqual(data["messages"], 2)
        self.assertEqual(data["new_mistakes"], 1)
        self.assertEqual(len(data["writing"]), 1)
        self.assertTrue(any(s["topic"] == "机械运动" for s in data["skills"]))
        self.assertEqual(data["grade"], 8)

    def test_report_is_self_contained(self):
        page = R.render(R.week(self.db, now=self.now))
        self.assertIn("<!doctype html>", page.lower())
        self.assertNotIn("<script", page.lower())
        self.assertNotIn("http://", page)
        self.assertNotIn("https://", page)
        self.assertIn("学习周报", page)

    def test_external_text_is_escaped(self):
        self.db.q("UPDATE profile SET nickname=? WHERE id=1", ("<img src=x onerror=alert(1)>",))
        self.db.q("UPDATE skills SET topic=? WHERE topic=?", ("<b>机械运动</b>", "机械运动"))
        page = R.render(R.week(self.db, now=self.now))
        self.assertNotIn("<img src=x", page)
        self.assertNotIn("<b>机械运动</b>", page)
        self.assertIn("&lt;img", page)

    def test_empty_week_still_renders_with_placeholder(self):
        empty = DB(os.path.join(self.dir.name, "empty.db"))
        page = R.render(R.week(empty, now=self.now))
        self.assertIn("这周还没有", page)
        self.assertIn("—", page)


if __name__ == "__main__":
    unittest.main()
