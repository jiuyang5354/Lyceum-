"""v0.2 设置：服务商预设、模型能力标签、对话自动选模型、config 读写与掩码、备份导出导入、清空学习数据、
检查更新（mock）、自动识别 / 测试连接（mock）、备用模型、用量统计、无边框窗口的纯函数。全部离线。"""
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
import urllib.error
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from lyceum import backup as B  # noqa: E402
from lyceum import config as C  # noqa: E402
from lyceum import llm  # noqa: E402
from lyceum import models as M  # noqa: E402
from lyceum import winchrome as W  # noqa: E402

KEY = "sk-abcdefghijklmnop9876"


class PresetTest(unittest.TestCase):
    def test_presets_have_no_keys_and_valid_urls(self):
        ids = [p["id"] for p in M.PRESETS]
        for need in ("openai", "deepseek", "qwen", "zhipu", "kimi", "siliconflow", "openrouter", "ollama", "custom"):
            self.assertIn(need, ids)
        for p in M.PRESETS:
            self.assertEqual(set(p), {"id", "name", "base_url", "model"})
            if p["id"] != "custom":
                self.assertTrue(p["base_url"].startswith(("https://", "http://127.0.0.1")), p)
                self.assertTrue(p["model"])
            self.assertNotIn("key", json.dumps(p).lower().replace("kimi", ""))

    def test_preset_lookup_and_validation(self):
        self.assertEqual(M.preset("deepseek")["model"], "deepseek-chat")
        self.assertIsNone(M.preset("nope"))
        self.assertEqual(C.validate({"preset": "ollama"}), {"preset": "ollama"})
        with self.assertRaises(ValueError):
            C.validate({"preset": "nope"})
        with self.assertRaises(ValueError):
            C.validate({"route_mode": "smart"})


class TagTest(unittest.TestCase):
    def t(self, m):
        return M.tags(m)

    def test_vision(self):
        for m in ("gpt-4o", "gpt-4o-mini", "qwen-vl-max", "Qwen/Qwen2.5-VL-72B-Instruct", "glm-4v-flash", "llava:13b", "gemini-2.0-flash"):
            self.assertIn("vision", self.t(m), m)
        for m in ("deepseek-chat", "qwen-plus", "moonshot-v1-8k"):
            self.assertNotIn("vision", self.t(m), m)

    def test_reasoning(self):
        for m in ("o3", "o1-preview", "deepseek-reasoner", "deepseek-ai/DeepSeek-R1", "qwq-32b", "claude-opus-4"):
            self.assertIn("reasoning", self.t(m), m)
        for m in ("o4-mini", "gpt-4o-mini", "glm-4-flash"):
            self.assertNotIn("reasoning", self.t(m), m)

    def test_fast(self):
        for m in ("gpt-4o-mini", "glm-4-flash", "claude-3-5-haiku", "qwen2.5:7b", "deepseek-chat", "gpt-4.1-nano"):
            self.assertIn("fast", self.t(m), m)
        self.assertNotIn("fast", self.t("o3"))
        self.assertEqual(self.t(""), [])

    def test_parse_models_filters_non_chat(self):
        data = {"data": [{"id": "gpt-4o"}, {"id": "text-embedding-3-small"}, {"id": "whisper-1"}, {"id": "dall-e-3"},
                         {"id": "o3"}, {"id": "gpt-4o"}, {"id": "tts-1"}, {"id": "BAAI/bge-m3"}]}
        self.assertEqual(M.parse_models(data), ["gpt-4o", "o3"])
        self.assertEqual(M.parse_models({"models": [{"name": "qwen2.5:7b"}]}), ["qwen2.5:7b"])
        self.assertEqual(M.parse_models(["a-chat", "b"]), ["a-chat", "b"])
        self.assertEqual(M.parse_models({}), [])


class RouteTest(unittest.TestCase):
    def test_route_task(self):
        self.assertEqual(M.route_task(image=True), "vision")
        self.assertEqual(M.route_task(image=True, action="full"), "vision")
        self.assertEqual(M.route_task(kind="grade"), "strong")
        self.assertEqual(M.route_task(kind="variants"), "strong")
        self.assertEqual(M.route_task(action="full"), "strong")
        self.assertEqual(M.route_task(allow_full=True), "strong")
        self.assertEqual(M.route_task(text="帮我看看这篇作文"), "strong")
        self.assertEqual(M.route_task(text="2x+3=7 怎么解"), "fast")
        self.assertEqual(M.route_task(action="hint"), "fast")

    DET = ["gpt-4o", "o3", "gpt-4o-mini", "deepseek-chat"]

    def test_fixed_mode(self):
        cfg = {"model": "main", "vision_model": "", "route_mode": "fixed", "detected": self.DET}
        for r in ("fast", "strong", "main"):
            self.assertEqual(M.pick_model(r, cfg), "main")
        self.assertEqual(M.pick_model("vision", cfg), "main")
        self.assertEqual(M.pick_model("vision", dict(cfg, vision_model="vl")), "vl")

    def test_auto_from_detected(self):
        cfg = {"model": "main", "route_mode": "auto", "detected": self.DET}
        self.assertEqual(M.pick_model("vision", cfg), "gpt-4o")
        self.assertEqual(M.pick_model("strong", cfg), "o3")
        self.assertIn(M.pick_model("fast", cfg), ("gpt-4o-mini", "deepseek-chat"))
        self.assertEqual(M.pick_model("main", cfg), "main")

    def test_auto_manual_roles_win(self):
        cfg = {"model": "main", "route_mode": "auto", "detected": self.DET, "roles": {"strong": "my-big", "fast": "", "vision": ""}}
        self.assertEqual(M.pick_model("strong", cfg), "my-big")
        self.assertEqual(M.pick_model("vision", dict(cfg, vision_model="vl")), "vl")

    def test_auto_falls_back_to_main(self):
        cfg = {"model": "main", "route_mode": "auto", "detected": ["deepseek-chat"]}
        self.assertEqual(M.pick_model("vision", cfg), "main")
        self.assertEqual(M.pick_model("strong", cfg), "main")
        self.assertEqual(M.pick_model("fast", cfg), "deepseek-chat")
        self.assertEqual(M.pick_model("strong", {"model": "main", "route_mode": "auto"}), "main")

    def test_chain(self):
        self.assertEqual(M.chain("a", ["b", "a", " ", "c"], "main"), ["a", "b", "c", "main"])
        self.assertEqual(M.chain("main", [], "main"), ["main"])
        self.assertEqual(M.split_list("a, b，c  d"), ["a", "b", "c", "d"])


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_save_keeps_ui_and_detected(self):
        C.save(self.dir, {"api_key": KEY, "model": "m1", "route_mode": "auto"}, ui={"theme": "dark", "bogus": 1, "font": "huge"})
        C.save(self.dir, {}, detected_models=["gpt-4o", "o3"], detected_base="https://x/v1/")
        C.save(self.dir, {"model": "m2"})
        raw = C.load_raw(self.dir)
        self.assertEqual(raw["ui"], {"theme": "dark"})
        self.assertEqual(raw["detected"]["models"], ["gpt-4o", "o3"])
        self.assertEqual(raw["model"], "m2")
        self.assertEqual(raw["api_key"], KEY)
        self.assertEqual(C.ui_prefs(self.dir)["theme"], "dark")
        self.assertTrue(C.ui_prefs(self.dir)["three_d"])
        self.assertEqual(C.detected(self.dir, "https://x/v1"), ["gpt-4o", "o3"])
        self.assertEqual(C.detected(self.dir, "https://other/v1"), [])

    def test_public_masks_key_and_routes(self):
        C.save(self.dir, {"api_key": KEY, "fast_model": "f", "strong_model": "s", "fallbacks": "a,b"})
        pub = C.public(self.dir, env={})
        self.assertNotIn(KEY, json.dumps(pub))
        self.assertTrue(pub["key_hint"].endswith("9876"))
        self.assertEqual(pub["fast_model"], "f")
        self.assertEqual(pub["route_mode"], "fixed")
        C.save(self.dir, {"api_key": ""})
        self.assertTrue(C.public(self.dir, env={})["key_set"])  # 空 = 不改
        C.save(self.dir, {}, clear_key=True)
        self.assertFalse(C.public(self.dir, env={})["key_set"])

    def test_env_wins_for_new_fields(self):
        C.save(self.dir, {"route_mode": "fixed", "fast_model": "file-fast"})
        env = {"LYCEUM_ROUTE": "auto", "LYCEUM_FAST_MODEL": "env-fast"}
        vals, src = C.effective(self.dir, env)
        self.assertEqual((vals["route_mode"], vals["fast_model"]), ("auto", "env-fast"))
        self.assertIn("fast_model", C.public(self.dir, env)["locked"])

    def test_apply_sets_route(self):
        C.save(self.dir, {"api_key": KEY, "model": "main", "route_mode": "auto", "fallbacks": "fb1, fb2"},
               detected_models=["o3", "gpt-4o-mini"], detected_base=C.DEFAULTS["base_url"])

        class Fake:
            pass
        f = Fake()
        C.apply(f, self.dir, env={})
        self.assertEqual(f.ROUTE["route_mode"], "auto")
        self.assertEqual(f.ROUTE["fallbacks"], ["fb1", "fb2"])
        self.assertEqual(M.pick_model("strong", f.ROUTE), "o3")
        self.assertEqual(f.USAGE_FILE, os.path.join(self.dir, "usage.json"))


class LLMRouteTest(unittest.TestCase):
    def setUp(self):
        self.saved = (llm.API_KEY, llm.MODEL, llm.VISION_MODEL, llm.ROUTE, llm.USAGE_FILE, llm._post)
        self.dir = tempfile.mkdtemp()
        llm.API_KEY, llm.MODEL, llm.VISION_MODEL = "k", "main", "main"
        llm.USAGE_FILE = os.path.join(self.dir, "usage.json")
        self.calls = []

    def tearDown(self):
        llm.API_KEY, llm.MODEL, llm.VISION_MODEL, llm.ROUTE, llm.USAGE_FILE, llm._post = self.saved
        shutil.rmtree(self.dir, ignore_errors=True)

    def fake(self, fail=()):
        def post(payload):
            self.calls.append(payload["model"])
            if payload["model"] in fail:
                raise urllib.error.HTTPError("u", 404, "no", {}, io.BytesIO(b"model not found"))
            return {"choices": [{"message": {"content": '{"reply": "ok"}'}}], "usage": {"prompt_tokens": 10, "completion_tokens": 3}}
        llm._post = post

    def test_auto_route_picks_role_model_and_records(self):
        llm.ROUTE = {"route_mode": "auto", "detected": ["o3", "gpt-4o", "gpt-4o-mini"], "fallbacks": []}
        self.fake()
        llm.reset_last()
        llm.chat_routed([{"role": "user", "content": "x"}], task="strong")
        self.assertEqual(self.calls[-1], "o3")
        self.assertEqual(llm.last_model(), "o3")
        llm.chat_routed([{"role": "user", "content": "x"}], vision=True, task="vision")
        self.assertEqual(self.calls[-1], "gpt-4o")
        llm.chat_routed([{"role": "user", "content": "x"}], task="fast")
        self.assertEqual(self.calls[-1], "gpt-4o-mini")
        tot = llm.usage_totals()
        self.assertEqual(tot["o3"]["calls"], 1)
        self.assertEqual(tot["o3"]["prompt_tokens"], 10)

    def test_fixed_without_route_uses_main(self):
        llm.ROUTE = None
        self.fake()
        llm.chat_routed([{"role": "user", "content": "x"}], task="strong")
        self.assertEqual(self.calls, ["main"])

    def test_fallback_chain(self):
        llm.ROUTE = {"route_mode": "fixed", "fallbacks": ["fb1", "fb2"]}
        self.fake(fail=("main", "fb1"))
        out = llm.chat_routed([{"role": "user", "content": "x"}], retries=0)
        self.assertEqual(out["reply"], "ok")
        self.assertEqual(self.calls, ["main", "fb1", "fb2"])
        self.assertEqual(llm.last_model(), "fb2")

    def test_all_fail_raises(self):
        llm.ROUTE = {"route_mode": "fixed", "fallbacks": ["fb1"]}
        self.fake(fail=("main", "fb1"))
        with self.assertRaises(llm.LLMError):
            llm.chat_routed([{"role": "user", "content": "x"}], retries=0)


class ProbeTest(unittest.TestCase):
    def test_probe_with_mock(self):
        seen = {}

        def fetch(url, key, body=None):
            seen.update(url=url, key=key)
            return {"data": [{"id": "gpt-4o"}, {"id": "text-embedding-3-large"}, {"id": "o3"}]}
        out = M.probe("https://api.example.com/v1/", "sk-x", fetch=fetch)
        self.assertEqual(seen, {"url": "https://api.example.com/v1/models", "key": "sk-x"})
        self.assertEqual([m["id"] for m in out], ["gpt-4o", "o3"])
        self.assertIn("vision", out[0]["tags"])
        with self.assertRaises(ValueError):
            M.probe("ftp://x", "k", fetch=fetch)

    def test_test_connection_with_mock(self):
        def fetch(url, key, body=None):
            self.assertTrue(url.endswith("/chat/completions"))
            self.assertEqual(body["max_tokens"], 8)
            return {"model": body["model"], "choices": [{"message": {"content": "OK"}}]}
        self.assertEqual(M.test("https://x/v1", "k", "m", fetch=fetch), {"ok": True, "model": "m", "reply": "OK"})
        with self.assertRaises(RuntimeError):
            M.test("https://x/v1", "k", "m", fetch=lambda *a, **k: {"oops": 1})
        with self.assertRaises(ValueError):
            M.test("https://x/v1", "k", "", fetch=fetch)


class BackupTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.conn = sqlite3.connect(os.path.join(self.dir, "lyceum.db"))
        self.conn.executescript("CREATE TABLE profile (id INTEGER PRIMARY KEY, grade INT); CREATE TABLE mistakes (id INTEGER PRIMARY KEY AUTOINCREMENT, q TEXT);"
                                "INSERT INTO profile VALUES (1, 8); INSERT INTO mistakes (q) VALUES ('1+1'), ('2+2');")
        self.conn.commit()
        C.save(self.dir, {"api_key": KEY, "model": "m"}, ui={"theme": "dark"})

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_export_excludes_key_by_default(self):
        data = B.export_zip(self.conn, C.load_raw(self.dir), "0.2.0")
        z = zipfile.ZipFile(io.BytesIO(data))
        self.assertEqual(set(z.namelist()), {"lyceum.db", "config.json", "manifest.json"})
        cfg = json.loads(z.read("config.json"))
        self.assertNotIn("api_key", cfg)
        self.assertEqual(cfg["ui"], {"theme": "dark"})
        self.assertIn("api_key", json.loads(zipfile.ZipFile(io.BytesIO(B.export_zip(self.conn, C.load_raw(self.dir), "0.2.0", True))).read("config.json")))

    def test_roundtrip_import_keeps_current_key(self):
        data = B.export_zip(self.conn, C.load_raw(self.dir), "0.2.0")
        self.conn.execute("DELETE FROM mistakes")
        self.conn.commit()
        C.save(self.dir, {"model": "changed"})
        res = B.import_zip(self.conn, self.dir, data, C)
        self.assertEqual(res["version"], "0.2.0")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM mistakes").fetchone()[0], 2)
        raw = C.load_raw(self.dir)
        self.assertEqual(raw["model"], "m")
        self.assertEqual(raw["api_key"], KEY)  # 备份里没有 key：保留现在的

    def test_import_rejects_garbage(self):
        for bad in (b"not a zip", self._zip({"x.txt": b"1"}), self._zip({"lyceum.db": b"nope", "manifest.json": b'{"app":"Lyceum"}'}),
                    self._zip({"lyceum.db": b"SQLite format 3\x00", "manifest.json": b'{"app":"Other"}'})):
            with self.assertRaises(ValueError):
                B.read_zip(bad)

    def _zip(self, files):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for k, v in files.items():
                z.writestr(k, v)
        return buf.getvalue()

    def test_clear_keeps_profile(self):
        done = B.clear_learning(self.conn)
        self.assertIn("mistakes", done)
        self.assertNotIn("profile", done)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM mistakes").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT grade FROM profile").fetchone()[0], 8)


class UpdateTest(unittest.TestCase):
    REL = {"tag_name": "v0.3.0", "html_url": "https://github.com/jiuyang5354/Lyceum-/releases/tag/v0.3.0", "body": "notes",
           "assets": [{"name": "Lyceum-Setup-0.3.0.exe", "browser_download_url": "https://dl/x.exe"},
                      {"name": "Lyceum-0.3.0-macOS-arm64.dmg", "browser_download_url": "https://dl/x.dmg"}]}

    def test_newer(self):
        r = B.check_update("0.2.0", fetch=lambda url: self.REL)
        self.assertTrue(r["ok"] and r["newer"])
        self.assertEqual((r["latest"], r["exe"], r["dmg"]), ("0.3.0", "https://dl/x.exe", "https://dl/x.dmg"))

    def test_same_or_older(self):
        self.assertFalse(B.check_update("0.3.0", fetch=lambda url: self.REL)["newer"])
        self.assertFalse(B.check_update("0.10.0", fetch=lambda url: self.REL)["newer"])
        self.assertTrue(B.newer("0.10.0", "0.9.9"))

    def test_network_error(self):
        def boom(url):
            raise OSError("offline")
        r = B.check_update("0.2.0", fetch=boom)
        self.assertFalse(r["ok"])
        self.assertIn("offline", r["error"])


class WinChromeTest(unittest.TestCase):
    def test_frame_choice(self):
        self.assertTrue(W.use_custom_frame({}, "win32"))
        self.assertFalse(W.use_custom_frame({"LYCEUM_FRAME": "native"}, "win32"))
        self.assertFalse(W.use_custom_frame({}, "darwin"))
        self.assertFalse(W.use_custom_frame({}, "linux"))
        self.assertEqual(W.frame_url("http://127.0.0.1:5/", True), "http://127.0.0.1:5/?frame=custom")
        self.assertEqual(W.frame_url("http://h/?a=1", True), "http://h/?a=1&frame=custom")
        self.assertEqual(W.frame_url("http://h/", False), "http://h/")

    def test_resize_rect(self):
        r = (100, 100, 1500, 1000)
        self.assertEqual(W.resize_rect(11, r, 50, 0, 1200, 760), (100, 100, 1550, 1000))
        self.assertEqual(W.resize_rect(10, r, 500, 0, 1200, 760), (300, 100, 1500, 1000))  # 不小于最小宽
        self.assertEqual(W.resize_rect(17, r, 10, 20, 1200, 760), (100, 100, 1510, 1020))
        self.assertEqual(W.resize_rect(13, r, -10, -10, 1200, 760), (90, 90, 1500, 1000))

    def test_noop_off_windows(self):
        if sys.platform == "win32":
            self.skipTest("Windows 上会真的找窗口")
        w = W.WinChrome("x")
        self.assertFalse(w.is_max())
        self.assertFalse(w.toggle_max())
        self.assertFalse(w.begin(2))
        self.assertIsNone(w.step())


if __name__ == "__main__":
    unittest.main()
