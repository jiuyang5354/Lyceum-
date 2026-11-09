"""本机接口的来源校验：恶意网页不能借浏览器打本地端口。

攻击面：浏览器发来的请求永远来自 127.0.0.1，只查 client_address 等于没查。
这里锁住三条：Host 必须是本机端口、Origin 必须是本机页面、写操作必须是 JSON。
"""
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class GuardUnitTest(unittest.TestCase):
    """纯函数：Host / Origin 的判定规则。"""

    def setUp(self):
        import server
        self.S = server

    def test_host_must_be_loopback_and_our_port(self):
        self.assertTrue(self.S._host_ok("127.0.0.1:8000", 8000))
        self.assertTrue(self.S._host_ok("localhost:8000", 8000))
        self.assertTrue(self.S._host_ok("[::1]:8000", 8000))
        self.assertFalse(self.S._host_ok("evil.com:8000", 8000))
        self.assertFalse(self.S._host_ok("127.0.0.1:9999", 8000))
        self.assertFalse(self.S._host_ok("", 8000))
        self.assertFalse(self.S._host_ok("127.0.0.1.evil.com:8000", 8000))

    def test_origin_rules(self):
        self.assertTrue(self.S._origin_ok("", 8000))                       # curl / 同源 GET
        self.assertTrue(self.S._origin_ok("http://127.0.0.1:8000", 8000))
        self.assertTrue(self.S._origin_ok("http://localhost:8000", 8000))
        self.assertFalse(self.S._origin_ok("http://evil.com", 8000))
        self.assertFalse(self.S._origin_ok("http://127.0.0.1:9999", 8000))
        self.assertFalse(self.S._origin_ok("null", 8000))                   # file:// / 沙箱
        self.assertFalse(self.S._origin_ok("https://127.0.0.1.evil.com", 8000))


class GuardHttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        os.environ["LYCEUM_DATA"] = cls.dir
        os.environ.pop("LYCEUM_API_KEY", None)
        from lyceum import llm
        llm.API_KEY = ""
        llm.chat = lambda *a, **k: (_ for _ in ()).throw(AssertionError("不该调用模型"))
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
        shutil.rmtree(cls.dir, ignore_errors=True)

    def post(self, path, body, headers=None, raw_ct=None):
        data = json.dumps(body).encode() if not isinstance(body, bytes) else body
        h = {"Content-Type": raw_ct or "application/json"}
        h.update(headers or {})
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), data=data, headers=h)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def raw(self, request):
        s = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        s.sendall(request.encode())
        out = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            out += chunk
        s.close()
        return out.decode("utf-8", "ignore")

    def test_page_request_works(self):
        code, body = self.post("/api/profile", {"grade": 8, "textbook": "人教版"})
        self.assertEqual(code, 200, body)
        self.assertEqual(body["profile"]["grade"], 8)

    def test_same_origin_page_is_allowed(self):
        code, body = self.post("/api/profile", {"grade": 8},
                               headers={"Origin": "http://127.0.0.1:%d" % self.port})
        self.assertEqual(code, 200, body)

    def test_cross_site_origin_is_refused(self):
        code, body = self.post("/api/profile", {"grade": 8}, headers={"Origin": "https://evil.example"})
        self.assertEqual(code, 403)
        self.assertIn("本机", body.get("error", ""))

    def test_null_origin_is_refused(self):
        code, body = self.post("/api/profile", {"grade": 8}, headers={"Origin": "null"})
        self.assertEqual(code, 403)

    def test_plain_text_post_is_refused(self):
        # 跨站 no-cors 只能发 text/plain，这条挡住「网页偷偷调用本地接口」
        code, body = self.post("/api/profile", '{"grade": 8}', raw_ct="text/plain")
        self.assertEqual(code, 415, body)

    def test_foreign_host_header_is_refused(self):
        raw = self.raw("GET /api/settings HTTP/1.1\r\nHost: evil.example\r\nConnection: close\r\n\r\n")
        self.assertIn(" 403 ", raw.splitlines()[0] + " ")
        self.assertNotIn("\"model\"", raw)

    def test_host_with_wrong_port_is_refused(self):
        raw = self.raw("GET /api/settings HTTP/1.1\r\nHost: 127.0.0.1:1\r\nConnection: close\r\n\r\n")
        self.assertIn(" 403 ", raw.splitlines()[0] + " ")

    def test_normal_get_is_allowed(self):
        raw = self.raw("GET /api/settings HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nConnection: close\r\n\r\n" % self.port)
        self.assertIn(" 200 ", raw.splitlines()[0] + " ")


if __name__ == "__main__":
    unittest.main()
