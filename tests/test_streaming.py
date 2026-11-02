"""流式输出：SSE 事件格式、半截 JSON 解 reply、句子缓冲放行与 replace、离线流式、断流 / 上游报错。
上游是本地起的假 OpenAI 兼容服务（stream=true 时按 SSE 逐块吐），绝不调用真实模型。"""
import importlib, json, os, shutil, sys, tempfile, threading, unittest, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["no_proxy"] = os.environ["NO_PROXY"] = "127.0.0.1,localhost"
from lyceum import agent, llm, strategies
from lyceum.streaming import ReplyExtractor, SentenceGate, sse

ORIG_CHAT, ORIG_STREAM = llm.chat, llm.chat_stream
PROBLEM = "解方程 $x^2-5x+6=0$"


def model_json(reply, **kw):
    o = {"subject": "数学", "topic": "因式分解", "intent": "ask_hint", "problem": PROBLEM, "stage": "hint",
         "hint_level": 1, "student_correct": None, "solved": False}
    o.update(kw)
    o["reply"] = reply
    return json.dumps(o, ensure_ascii=False)


class FakeUpstream(BaseHTTPRequestHandler):
    """脚本：每个请求从 SCRIPT 取一项 {kind: stream|json|error|drop, content, chunk}。"""
    SCRIPT, PAYLOADS = [], []

    def log_message(self, *a): pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(n))
        FakeUpstream.PAYLOADS.append(payload)
        item = FakeUpstream.SCRIPT.pop(0)
        if item["kind"] == "error":
            body = b'{"error":{"message":"upstream boom"}}'
            self.send_response(500); self.send_header("Content-Length", str(len(body))); self.end_headers()
            self.wfile.write(body); return
        if not payload.get("stream"):
            body = json.dumps({"choices": [{"message": {"content": item["content"]}}], "usage": {}}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
        c, k = item["content"], item.get("chunk", 4)
        for i in range(0, len(c), k):
            d = {"choices": [{"index": 0, "delta": {"content": c[i:i + k]}, "finish_reason": None}]}
            self.wfile.write(f"data: {json.dumps(d, ensure_ascii=False)}\n\n".encode()); self.wfile.flush()
        if item["kind"] == "drop":
            return                                    # 断流：没有 finish_reason / [DONE]
        self.wfile.write(b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')


def start(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class UnitTest(unittest.TestCase):
    def test_sse_format(self):
        b = sse("delta", {"text": "你好\n$x$"}).decode()
        self.assertTrue(b.startswith("event: delta\ndata: "))
        self.assertTrue(b.endswith("\n\n"))
        self.assertEqual(b.count("\n"), 3)                      # 数据里的换行被 JSON 转义，不会断事件
        self.assertEqual(json.loads(b.split("data: ", 1)[1]), {"text": "你好\n$x$"})

    def test_extractor_char_by_char(self):
        reply = '先看 "已知"：\n$x^2$ 中\u6587 😀 \\ 结束'
        raw = "```json\n" + json.dumps({"subject": "物理", "stage": "hint", "hint_level": 2, "reply": reply}) + "\n```"
        ex, got = ReplyExtractor(), ""
        for ch in raw:
            got += ex.feed(ch)
        self.assertEqual(got, reply)
        self.assertTrue(ex.closed)
        self.assertEqual((ex.meta["subject"], ex.meta["stage"], ex.meta["hint_level"]), ("物理", "hint", 2))

    def test_extractor_plain_text(self):
        ex = ReplyExtractor()
        self.assertEqual(ex.feed("模型没按 JSON"), "模型没按 JSON")
        self.assertEqual(ex.mode, "text")

    def test_gate_releases_whole_sentences(self):
        g = SentenceGate(lambda t: "")
        self.assertEqual(g.feed("先看已知"), "")
        self.assertEqual(g.feed("条件。然后"), "先看已知条件。")
        self.assertEqual(g.feed("想 $a.b"), "")                  # 公式里的点不切
        self.assertEqual(g.feed(" c$ 是什么？"), "然后想 $a.b c$ 是什么？")
        self.assertEqual(g.flush(), "")

    def test_gate_closes_on_leak(self):
        g = SentenceGate(lambda t: "(x-2)(x-3)" if "(x-2)(x-3)" in t else "")
        self.assertEqual(g.feed("找对了。分解后是 (x-2)"), "找对了。")
        self.assertEqual(g.feed("(x-3)=0。所以"), "")
        self.assertEqual(g.leak, "(x-2)(x-3)")
        self.assertEqual(g.feed("后面的都不放。"), "")
        self.assertEqual(g.flush(), "")
        self.assertEqual(g.released, "找对了。")

    def test_gate_direct(self):
        g = SentenceGate(lambda t: "always", direct=True)
        self.assertEqual(g.feed("半"), "半")
        self.assertEqual(g.leak, "")

    def test_mock_chunks(self):
        t = "（演示模式）先别急着算。"
        self.assertEqual("".join(agent.mock_chunks(t)), t)
        self.assertTrue(all(1 <= len(c) <= 3 for c in agent.mock_chunks(t)))


class StreamAgentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.up = start(FakeUpstream)
        cls.base = f"http://127.0.0.1:{cls.up.server_address[1]}/v1"

    @classmethod
    def tearDownClass(cls): cls.up.shutdown()

    def setUp(self):
        self._saved = (llm.BASE_URL, llm.API_KEY, llm.TIMEOUT)
        llm.chat, llm.chat_stream = ORIG_CHAT, ORIG_STREAM
        llm.BASE_URL, llm.API_KEY, llm.TIMEOUT = self.base, "test-key", 5
        FakeUpstream.SCRIPT[:], FakeUpstream.PAYLOADS[:] = [], []
        self.events = []

    def tearDown(self):
        llm.BASE_URL, llm.API_KEY, llm.TIMEOUT = self._saved

    def emit(self, e, d): self.events.append((e, d))
    def kinds(self): return [e for e, _ in self.events]
    def deltas(self): return "".join(d["text"] for e, d in self.events if e == "delta")

    def run_turn(self, st, text, action=None):
        return agent.respond_stream({"grade": 8}, {"state": st}, [], text, None, action, self.emit)

    def test_clean_hint_streams_by_sentence(self):
        reply = "$-2$ 和 $-3$ 找对了。它们不是方程的根。你试着用这两个数把左边写成两个括号相乘？"
        FakeUpstream.SCRIPT.append({"kind": "stream", "content": model_json(reply, stage="check", hint_level=2), "chunk": 3})
        out, st = self.run_turn({"problem": PROBLEM, "hint_level": 1, "stuck": 0}, "是 -2 和 -3")
        self.assertTrue(FakeUpstream.PAYLOADS[0]["stream"])
        self.assertEqual(self.kinds()[0], "meta")
        self.assertEqual(self.events[0][1]["strategy"]["subject"], "数学")
        self.assertEqual(self.deltas(), reply)
        ds = [d["text"] for e, d in self.events if e == "delta"]
        self.assertEqual(ds[0], "$-2$ 和 $-3$ 找对了。")              # 按句子放行
        self.assertNotIn("replace", self.kinds())
        self.assertEqual(out["reply"], reply)
        self.assertEqual(st["strategy"]["subject"], "数学")

    def test_leak_stops_and_replaces(self):
        leaky = "找出的两个数对了。因式分解后是 $(x-2)(x-3)=0$，因此至少一个因式为零。所以 $x=2$ 或 $x=3$。"
        clean = "两个数找对了。你试着用它们把左边写成两个括号相乘？"
        FakeUpstream.SCRIPT += [{"kind": "stream", "content": model_json(leaky, stage="check", hint_level=2), "chunk": 2},
                                {"kind": "json", "content": model_json(clean, stage="check", hint_level=2)}]
        out, _ = self.run_turn({"problem": PROBLEM, "hint_level": 1, "stuck": 0}, "是 -2 和 -3")
        self.assertEqual(self.deltas(), "找出的两个数对了。")            # 漏题那句之后一个字都没放
        self.assertNotIn("(x-2)", self.deltas())
        k = self.kinds()
        self.assertLess(k.index("status"), k.index("replace"))
        rep = [d for e, d in self.events if e == "replace"][0]
        self.assertEqual((rep["text"], rep["reason"]), (clean, "leak"))
        self.assertFalse(FakeUpstream.PAYLOADS[1].get("stream"))          # 重写走非流式
        self.assertIn("关键结果", FakeUpstream.PAYLOADS[1]["messages"][-1]["content"])
        self.assertEqual(out["reply"], clean)
        self.assertTrue(out["leak_fixed"])

    def test_still_leaking_gets_subject_fallback(self):
        bad = "加速度为 5 m/s²。"
        FakeUpstream.SCRIPT += [{"kind": "stream", "content": model_json(bad, subject="物理", hint_level=1)},
                                {"kind": "json", "content": model_json(bad, subject="物理", hint_level=1)}]
        out, st = self.run_turn({"problem": "质量 2 kg 的物体受 10 N 拉力，求加速度", "subject": "物理", "hint_level": 0}, "提示一下")
        self.assertEqual(self.deltas(), "")
        rep = [d for e, d in self.events if e == "replace"][0]
        self.assertEqual(rep["text"], strategies.STRATEGIES["物理"]["fallback"])
        self.assertEqual(st["strategy"]["subject"], "物理")

    def test_english_leak_in_stream(self):
        bad = "注意 yesterday。所以是 She went to school yesterday. 懂了吗？"
        good = "注意 yesterday。它提示时间是过去，go 要变成什么形式？"
        FakeUpstream.SCRIPT += [{"kind": "stream", "content": model_json(bad, subject="英语", hint_level=1)},
                                {"kind": "json", "content": model_json(good, subject="英语", hint_level=1)}]
        self.run_turn({"problem": "She ___ (go) to school yesterday.", "subject": "英语", "hint_level": 0}, "提示")
        self.assertEqual(self.deltas(), "注意 yesterday。")
        self.assertEqual([d for e, d in self.events if e == "replace"][0]["text"], good)

    def test_full_solution_streams_directly(self):
        full = "$(x-2)(x-3)=0$，所以 $x=2$ 或 $x=3$。这类题先因式分解。"
        FakeUpstream.SCRIPT.append({"kind": "stream", "content": model_json(full, stage="full", hint_level=3, solved=True), "chunk": 2})
        out, st = self.run_turn({"problem": PROBLEM, "hint_level": 1, "stuck": 0}, "", "full")
        ds = [d["text"] for e, d in self.events if e == "delta"]
        self.assertGreater(len(ds), 10)                                    # 逐块转发，不等句子
        self.assertEqual("".join(ds), full)
        self.assertNotIn("replace", self.kinds())
        self.assertTrue(st["full_given"])

    def test_upstream_error_raises(self):
        FakeUpstream.SCRIPT.append({"kind": "error"})
        with self.assertRaises(llm.LLMError):
            self.run_turn({"problem": PROBLEM, "hint_level": 1}, "提示")

    def test_drop_raises(self):
        FakeUpstream.SCRIPT.append({"kind": "drop", "content": model_json("说到一半。还有")})
        with self.assertRaises(llm.LLMError) as cm:
            self.run_turn({"problem": PROBLEM, "hint_level": 1}, "提示")
        self.assertIn("中断", str(cm.exception))


def read_sse(resp):
    events, ev, data = [], None, []
    for raw in resp:
        line = raw.decode("utf-8").rstrip("\n")
        if line.startswith("event:"):
            ev = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].strip())
        elif line == "" and ev:
            events.append((ev, json.loads("\n".join(data)))); ev, data = None, []
    return events


class ServerSSETest(unittest.TestCase):
    """真的起一个 Lyceum 服务，走 HTTP 拿 text/event-stream。"""
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        os.environ["LYCEUM_DATA"] = cls.dir
        import server
        cls.mod = importlib.reload(server)
        cls.srv = start(cls.mod.H)
        cls.up = start(FakeUpstream)
        cls.port = cls.srv.server_address[1]
        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.up.shutdown(); cls.mod.db.conn.close(); shutil.rmtree(cls.dir)

    def setUp(self):
        self._saved = (llm.BASE_URL, llm.API_KEY, agent.MOCK_DELAY)
        llm.chat, llm.chat_stream = ORIG_CHAT, ORIG_STREAM
        llm.BASE_URL = f"http://127.0.0.1:{self.up.server_address[1]}/v1"
        agent.MOCK_DELAY = 0
        FakeUpstream.SCRIPT[:] = []

    def tearDown(self):
        llm.BASE_URL, llm.API_KEY, agent.MOCK_DELAY = self._saved

    def post(self, path, body):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        return self.opener.open(req)

    def test_offline_stream(self):
        llm.API_KEY = ""
        with self.post("/api/chat/stream", {"message": "为什么人站在匀速上升的电梯里，感觉不到自己在动？"}) as r:
            self.assertTrue(r.headers["Content-Type"].startswith("text/event-stream"))
            ev = read_sse(r)
        k = [e for e, _ in ev]
        self.assertEqual(k[:2], ["open", "meta"])
        self.assertEqual(k[-1], "done")
        meta = ev[1][1]
        self.assertEqual(meta["strategy"]["subject"], "物理")
        self.assertTrue(meta["strategy"]["mode"])
        deltas = [d["text"] for e, d in ev if e == "delta"]
        self.assertGreater(len(deltas), 20)
        done = ev[-1][1]
        self.assertEqual("".join(deltas), done["reply"])
        self.assertEqual(done["meta"]["strategy"]["subject"], "物理")
        # 写进了会话；会话状态里记着策略
        with self.opener.open(f"http://127.0.0.1:{self.port}/api/sessions/{done['session_id']}") as r2:
            s = json.loads(r2.read())
        self.assertEqual(s["session"]["state"]["strategy"]["subject"], "物理")
        self.assertEqual(len(s["messages"]), 2)

    def test_upstream_error_event_and_nothing_saved(self):
        llm.API_KEY = "test-key"
        FakeUpstream.SCRIPT.append({"kind": "error"})
        with self.opener.open(f"http://127.0.0.1:{self.port}/api/sessions") as r:
            before = len(json.loads(r.read())["sessions"])
        with self.post("/api/chat/stream", {"message": "解方程 x^2-1=0"}) as r:
            ev = read_sse(r)
        self.assertEqual(ev[-1][0], "error")
        self.assertTrue(ev[-1][1]["retry"])
        with self.opener.open(f"http://127.0.0.1:{self.port}/api/sessions") as r:
            self.assertEqual(len(json.loads(r.read())["sessions"]), before)   # 新会话被撤掉，重试不会重复

    def test_stream_with_fake_model_and_replace(self):
        llm.API_KEY = "test-key"
        leaky = "这题先看等号两边。配好是 3Fe + 2O2 = Fe3O4。"
        clean = "这题先看等号两边。右边 Fe3O4 里有几个 O？"
        FakeUpstream.SCRIPT += [{"kind": "stream", "content": model_json(leaky, subject="化学", problem="配平 Fe + O2 → Fe3O4", intent="new_problem")},
                                {"kind": "json", "content": model_json(clean, subject="化学", problem="配平 Fe + O2 → Fe3O4", intent="new_problem")}]
        with self.post("/api/chat/stream", {"message": "配平 Fe + O2 → Fe3O4"}) as r:
            ev = read_sse(r)
        k = [e for e, _ in ev]
        self.assertIn("replace", k)
        self.assertEqual("".join(d["text"] for e, d in ev if e == "delta"), "这题先看等号两边。")
        self.assertEqual(ev[-1][1]["reply"], clean)
        self.assertEqual(ev[1][1]["strategy"]["subject"], "化学")             # meta 里的策略来自关键词路由

    def test_heartbeat_comment(self):
        llm.API_KEY = ""
        self.mod.HEARTBEAT, agent.MOCK_DELAY = 0.05, 0.01
        try:
            with self.post("/api/chat/stream", {"message": "光合作用的原料和产物"}) as r:
                raw = r.read().decode()
        finally:
            self.mod.HEARTBEAT = 15
        self.assertIn(": ping\n\n", raw)                       # SSE 注释行，前端解析时跳过
        self.assertIn("event: done", raw)

    def test_non_stream_still_works(self):
        llm.API_KEY = ""
        with self.post("/api/chat", {"message": "She ___ (go) to school yesterday."}) as r:
            j = json.loads(r.read())
        self.assertEqual(j["strategy"]["subject"], "英语")
        self.assertEqual(j["state"]["strategy"]["mode"], strategies.STRATEGIES["英语"]["mode"])


if __name__ == '__main__': unittest.main()
