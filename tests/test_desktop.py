"""桌面版：模型设置的读取优先级、config.json 读写、数据目录选择、/api/settings、启动器自检。
全部离线，不调用任何模型。运行：python -m unittest discover -s tests"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "desktop"))
from lyceum import config as C  # noqa: E402

KEY = "sk-abcdefghijklmnop1234"


class DataDirTest(unittest.TestCase):
    def test_windows_appdata(self):
        d = C.default_data_dir("win32", {"APPDATA": r"C:\Users\x\AppData\Roaming"}, home=r"C:\Users\x")
        self.assertEqual(d, os.path.join(r"C:\Users\x\AppData\Roaming", "Lyceum"))

    def test_windows_without_appdata(self):
        d = C.default_data_dir("win32", {}, home="/h")
        self.assertEqual(d, os.path.join("/h", "AppData", "Roaming", "Lyceum"))

    def test_macos(self):
        self.assertEqual(C.default_data_dir("darwin", {}, home="/Users/x"),
                         os.path.join("/Users/x", "Library", "Application Support", "Lyceum"))

    def test_linux_xdg(self):
        self.assertEqual(C.default_data_dir("linux", {"XDG_DATA_HOME": "/x"}, home="/h"), os.path.join("/x", "lyceum"))
        self.assertEqual(C.default_data_dir("linux", {}, home="/h"), os.path.join("/h", ".local", "share", "lyceum"))

    def test_env_overrides(self):
        self.assertEqual(C.resolve_data_dir({"LYCEUM_DATA": "/custom"}, platform="win32"), "/custom")
        self.assertEqual(C.resolve_data_dir({"APPDATA": "/ad"}, platform="win32"), os.path.join("/ad", "Lyceum"))

    def test_launcher_sets_env_and_creates_dir(self):
        import launcher
        tmp = tempfile.mkdtemp()
        try:
            env = {"LYCEUM_DATA": os.path.join(tmp, "a", "b")}
            d = launcher.prepare_data_dir(env)
            self.assertTrue(os.path.isdir(d))
            self.assertEqual(env["LYCEUM_DATA"], d)
        finally:
            shutil.rmtree(tmp)


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_defaults_offline(self):
        v, src = C.effective(self.dir, env={})
        self.assertEqual(v["api_key"], "")
        self.assertEqual(v["model"], C.DEFAULTS["model"])
        self.assertEqual(v["vision_model"], v["model"])  # 不填识图模型 = 同主模型
        self.assertEqual(set(src.values()), {"default"})
        self.assertEqual(C.public(self.dir, env={})["mode"], "offline")

    def test_file_over_default(self):
        C.save(self.dir, {"api_key": KEY, "model": "m-file", "base_url": "https://x.example/v1/"})
        v, src = C.effective(self.dir, env={})
        self.assertEqual((v["api_key"], v["model"], v["base_url"]), (KEY, "m-file", "https://x.example/v1"))
        self.assertEqual(src["api_key"], "file")

    def test_env_over_file(self):
        C.save(self.dir, {"api_key": KEY, "model": "m-file"})
        v, src = C.effective(self.dir, env={"LYCEUM_API_KEY": "sk-env", "LYCEUM_MODEL": " m-env "})
        self.assertEqual((v["api_key"], v["model"]), ("sk-env", "m-env"))
        self.assertEqual((src["api_key"], src["model"]), ("env", "env"))
        self.assertEqual(sorted(C.public(self.dir, env={"LYCEUM_API_KEY": "sk-env"})["locked"]), ["api_key"])

    def test_empty_env_falls_through(self):
        C.save(self.dir, {"model": "m-file"})
        v, src = C.effective(self.dir, env={"LYCEUM_MODEL": "  "})
        self.assertEqual((v["model"], src["model"]), ("m-file", "file"))

    def test_blank_key_keeps_saved_key_clear_removes(self):
        C.save(self.dir, {"api_key": KEY})
        C.save(self.dir, {"api_key": "", "model": "m2"})
        self.assertEqual(C.load_file(self.dir)["api_key"], KEY)
        C.save(self.dir, {}, clear_key=True)
        self.assertNotIn("api_key", C.load_file(self.dir))
        self.assertEqual(C.load_file(self.dir)["model"], "m2")

    def test_blank_field_resets_to_default(self):
        C.save(self.dir, {"model": "m2"})
        C.save(self.dir, {"model": ""})
        self.assertEqual(C.effective(self.dir, env={})[0]["model"], C.DEFAULTS["model"])

    def test_public_never_contains_key(self):
        C.save(self.dir, {"api_key": KEY})
        pub = C.public(self.dir, env={})
        self.assertNotIn(KEY, json.dumps(pub))
        self.assertTrue(pub["key_set"])
        self.assertEqual(pub["key_hint"], "sk-…1234")
        self.assertEqual(C.mask("short"), "•••••")
        self.assertEqual(C.mask(""), "")

    def test_validation(self):
        with self.assertRaises(ValueError):
            C.save(self.dir, {"base_url": "ftp://x"})
        with self.assertRaises(ValueError):
            C.save(self.dir, {"api_key": "a\nb"})
        with self.assertRaises(ValueError):
            C.save(self.dir, {"model": 3})
        C.save(self.dir, {"unknown": "x", "model": "ok"})
        self.assertEqual(C.load_file(self.dir), {"model": "ok"})

    def test_corrupt_file_is_ignored(self):
        with open(C.path(self.dir), "w") as f:
            f.write("{not json")
        self.assertEqual(C.load_file(self.dir), {})
        with open(C.path(self.dir), "w") as f:
            f.write('["list"]')
        self.assertEqual(C.load_file(self.dir), {})

    @unittest.skipIf(sys.platform.startswith("win"), "Windows 没有 POSIX 权限位")
    def test_file_mode_600(self):
        C.save(self.dir, {"api_key": KEY})
        self.assertEqual(os.stat(C.path(self.dir)).st_mode & 0o777, 0o600)

    def test_apply_sets_llm_globals(self):
        class Fake:
            pass
        m = Fake()
        C.save(self.dir, {"api_key": KEY, "model": "m-file", "vision_model": "v-file"})
        C.apply(m, self.dir, env={"LYCEUM_BASE_URL": "https://env.example/v1/"})
        self.assertEqual((m.API_KEY, m.MODEL, m.VISION_MODEL, m.BASE_URL), (KEY, "m-file", "v-file", "https://env.example/v1"))


class SettingsHTTPTest(unittest.TestCase):
    """/api/settings：存进数据目录，llm 立刻生效，响应里没有完整 key。"""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls._env = {k: os.environ.get(k) for k in list(C.ENV.values()) + ["LYCEUM_DATA"]}
        for k in C.ENV.values():
            os.environ.pop(k, None)
        os.environ["LYCEUM_DATA"] = cls.dir
        from lyceum import llm
        cls.llm = llm
        cls._saved = (llm.API_KEY, llm.MODEL, llm.BASE_URL, llm.VISION_MODEL, llm.chat)

        def no_model(*a, **k):
            raise AssertionError("测试里不应调用模型")
        llm.chat = no_model
        import importlib
        import server
        server.db.conn.close()  # reload replaces the module DB; close the previous fixture first.
        cls.server_mod = importlib.reload(server)
        cls.srv = cls.server_mod.make_server("127.0.0.1", 0)
        cls.port = cls.srv.server_address[1]
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.thread.join(timeout=5)
        cls.server_mod.db.conn.close()
        shutil.rmtree(cls.dir)
        llm = cls.llm
        llm.API_KEY, llm.MODEL, llm.BASE_URL, llm.VISION_MODEL, llm.chat = cls._saved
        for k, v in cls._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def call(self, path, body=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}",
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req) as r:
            return r.read().decode()

    def test_roundtrip(self):
        s = json.loads(self.call("/api/settings"))
        self.assertEqual(s["mode"], "offline")
        self.assertFalse(json.loads(self.call("/api/profile"))["llm"])
        raw = self.call("/api/settings", {"api_key": KEY, "model": "m-ui", "base_url": "https://relay.example/v1"})
        self.assertNotIn(KEY, raw)
        s = json.loads(raw)
        self.assertEqual((s["mode"], s["model"], s["key_hint"]), ("model", "m-ui", "sk-…1234"))
        self.assertEqual(self.llm.API_KEY, KEY)
        self.assertEqual(self.llm.BASE_URL, "https://relay.example/v1")
        with open(os.path.join(self.dir, "config.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["api_key"], KEY)
        # 留空 key 保持；clear_key 清掉 → 回到离线演示
        s = json.loads(self.call("/api/settings", {"api_key": "", "model": "m-ui"}))
        self.assertTrue(s["key_set"])
        s = json.loads(self.call("/api/settings", {"clear_key": True}))
        self.assertEqual(s["mode"], "offline")
        self.assertEqual(self.llm.API_KEY, "")

    def test_bad_url_is_400(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.call("/api/settings", {"base_url": "not-a-url"})
        self.assertEqual(cm.exception.code, 400)

    def test_js_mime(self):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{self.port}/js/app.js") as r:
            self.assertTrue(r.headers["Content-Type"].startswith("text/javascript"))
        self.assertTrue(self.server_mod._loopback("127.0.0.1"))
        self.assertFalse(self.server_mod._loopback("192.168.1.5"))


class LauncherCheckTest(unittest.TestCase):
    def test_refs_parser(self):
        import launcher
        html = '<link href="/css/a.css"><script src="/js/x.js"></script><a href="#/s">' \
               '<script type="importmap">{ "imports": { "three": "/vendor/three.js" } }</script>'
        self.assertEqual(sorted(launcher._refs(html, "/index.html")), ["/css/a.css", "/js/x.js", "/vendor/three.js"])
        css = "@font-face{src:url(fonts/K.woff2) format('woff2')}"
        self.assertEqual(launcher._refs(css, "/vendor/katex/katex.min.css"), ["/vendor/katex/fonts/K.woff2"])
        js = "import { a } from './svg.js'; const m = await import('./stage.js');"
        self.assertEqual(sorted(launcher._refs(js, "/js/app.js")), ["/js/stage.js", "/js/svg.js"])

    def test_headless_check_subprocess(self):
        env = {k: v for k, v in os.environ.items() if k not in C.ENV.values() and k != "LYCEUM_DATA"}
        r = subprocess.run([sys.executable, os.path.join(ROOT, "desktop", "launcher.py"), "--headless-check"],
                           capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("[headless-check] OK", r.stdout)


if __name__ == "__main__":
    unittest.main()
