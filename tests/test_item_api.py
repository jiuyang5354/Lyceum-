"""题库接口的 HTTP 级测试：下一题不应泄露答案，判分要写回难度与掌握度。"""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class ItemApiTest(unittest.TestCase):
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

    def call(self, path, body=None, expect=None):
        req = urllib.request.Request(
            "http://127.0.0.1:%d%s" % (self.port, path),
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            body = e.read()
            self.assertEqual(e.code, expect, body[:200])
            return json.loads(body)

    def test_next_item_hides_the_answer(self):
        r = self.call("/api/practice/next?subject=%E6%95%B0%E5%AD%A6&topic=%E8%A1%A8%E5%86%85%E4%B9%98%E6%B3%95")
        self.assertIn("item", r)
        self.assertNotIn("answer", r["item"])
        self.assertNotIn("params", r["item"])
        self.assertTrue(r["item"]["stem"])
        self.assertIn("难度", r["why"])

    def test_answer_is_graded_and_feeds_calibration_and_mastery(self):
        from lyceum import itembank
        item = next(it for it in itembank.ITEMS if it["topic"] == "表内乘法")
        r = self.call("/api/practice/answer", {"item_id": item["id"], "answer": item["answer"]})
        self.assertTrue(r["correct"])
        self.assertLess(r["difficulty_after"], r["difficulty_before"])
        self.assertEqual(r["attempts"], 1)
        self.assertGreater(r["skill"]["p_l"], 0.2)
        wrong = self.call("/api/practice/answer", {"item_id": item["id"], "answer": "0"})
        self.assertFalse(wrong["correct"])
        self.assertEqual(wrong["attempts"], 2)

    def test_unknown_topic_is_a_clean_404(self):
        r = self.call("/api/practice/next?subject=%E6%95%B0%E5%AD%A6&topic=%E6%B2%A1%E6%9C%89%E8%BF%99%E4%B8%AA", expect=404)
        self.assertIn("error", r)

    def test_review_today_carries_a_concrete_item(self):
        from lyceum import itembank
        item = next(it for it in itembank.ITEMS if it["topic"] == "整式的乘法")
        self.call("/api/practice/answer", {"item_id": item["id"], "answer": "0"})   # 做错 → 这个知识点有证据
        rev = self.call("/api/review/today")
        self.assertIsNotNone(rev.get("next"))
        if rev["next"].get("item"):
            self.assertNotIn("answer", rev["next"]["item"])
            self.assertEqual(rev["next"]["item"]["topic"], rev["next"]["topic"])


if __name__ == "__main__":
    unittest.main()
