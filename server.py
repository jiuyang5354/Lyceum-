"""Lyceum 学园 · 本地服务（Python 标准库）。

    python server.py            # 默认 http://127.0.0.1:8000
"""
import base64
import json
import mimetypes
import os
import re
import sys
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from lyceum import agent, evolve, insight, llm, mastery, strategies  # noqa: E402
from lyceum import memory as memmod  # noqa: E402
from lyceum.streaming import sse  # noqa: E402
from lyceum.db import DB  # noqa: E402

DATA = os.environ.get("LYCEUM_DATA", os.path.join(ROOT, "data"))
STATIC = os.path.join(ROOT, "static")
UPLOADS = os.path.join(DATA, "uploads")
os.makedirs(UPLOADS, exist_ok=True)
db = DB(os.path.join(DATA, "lyceum.db"))
MAX_IMAGE = 6 * 1024 * 1024
HEARTBEAT = float(os.environ.get("LYCEUM_HEARTBEAT", "15"))
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("font/woff2", ".woff2")


def save_image(data_url):
    m = re.match(r"data:(image/(png|jpeg|jpg|webp|gif));base64,(.+)", data_url or "", re.S)
    if not m:
        raise ValueError("图片格式不支持（请用 PNG / JPG / WebP）")
    raw = base64.b64decode(m.group(3))
    if len(raw) > MAX_IMAGE:
        raise ValueError("图片太大了（不超过 6MB）")
    name = f"{uuid.uuid4().hex[:12]}.{'jpg' if m.group(2) in ('jpeg', 'jpg') else m.group(2)}"
    with open(os.path.join(UPLOADS, name), "wb") as f:
        f.write(raw)
    return "/uploads/" + name


class H(BaseHTTPRequestHandler):
    server_version = "Lyceum/0.1"

    def log_message(self, fmt, *args):
        if "/api/" in (args[0] if args else ""):
            sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    # ---------- helpers
    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_IMAGE * 1.5:
            raise ValueError("请求太大")
        return json.loads(self.rfile.read(n) or b"{}")

    def send_file(self, path):
        if not os.path.isfile(path):
            self.send_error(404)
            return
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache" if path.endswith((".html", ".js", ".css")) else "max-age=86400")
        self.end_headers()
        self.wfile.write(data)

    # ---------- routing
    def do_GET(self):
        u = urlparse(self.path)
        p = u.path
        try:
            if p == "/api/profile":
                return self.send_json({"profile": db.get_profile(), "llm": llm.enabled(), "model": llm.MODEL})
            if p == "/api/sessions":
                return self.send_json({"sessions": db.list_sessions()})
            m = re.match(r"^/api/sessions/(\d+)$", p)
            if m:
                s = db.get_session(int(m.group(1)))
                if not s:
                    return self.send_json({"error": "没有这个会话"}, 404)
                return self.send_json({"session": s, "messages": db.messages(s["id"])})
            if p == "/api/mistakes":
                qs = parse_qs(u.query)
                return self.send_json({"mistakes": db.list_mistakes(qs.get("subject", [None])[0],
                                                                    qs.get("all", ["0"])[0] == "1")})
            if p == "/api/stats":
                return self.send_json({"stats": db.stats(), "sessions": db.list_sessions(12)})
            if p == "/api/review/today":
                return self.send_json(db.review_today())
            if p == "/api/mastery":
                qs = parse_qs(u.query)
                return self.send_json({"skills": db.mastery_list(qs.get("subject", [None])[0]), "params": mastery.params(),
                                       "today": mastery.today().isoformat()})
            m = re.match(r"^/api/mastery/(\d+)/events$", p)
            if m:
                sk, ev = db.skill_events(int(m.group(1)))
                if not sk:
                    return self.send_json({"error": "没有这个知识点"}, 404)
                return self.send_json({"skill": sk, "events": ev})
            if p == "/api/memory":
                return self.send_json(memmod.list_all(db))
            if p == "/api/growth":
                return self.send_json(evolve.overview(db))
            if p == "/api/usage":
                return self.send_json(llm.USAGE)
            if p.startswith("/uploads/"):
                return self.send_file(os.path.join(UPLOADS, os.path.basename(p)))
            if p in ("/", "/index.html"):
                return self.send_file(os.path.join(STATIC, "index.html"))
            fp = os.path.normpath(os.path.join(STATIC, p.lstrip("/")))
            if not fp.startswith(STATIC):
                return self.send_error(403)
            return self.send_file(fp)
        except Exception as e:
            traceback.print_exc()
            return self.send_json({"error": str(e)}, 500)

    def do_POST(self):
        p = urlparse(self.path).path
        try:
            b = self.body()
            if p == "/api/profile":
                g = int(b.get("grade") or 0)
                if not 1 <= g <= 12:
                    return self.send_json({"error": "年级不对"}, 400)
                db.set_profile(g, (b.get("textbook") or "人教版")[:20], (b.get("nickname") or "")[:20])
                return self.send_json({"profile": db.get_profile()})
            if p == "/api/chat":
                return self.chat(b)
            if p == "/api/chat/stream":
                return self.chat_stream(b)
            if p == "/api/practice":
                return self.practice(b)
            if p == "/api/grade":
                return self.grade(b)
            m = re.match(r"^/api/mistakes/(\d+)/(master|unmaster|delete)$", p)
            if m:
                mid, act = int(m.group(1)), m.group(2)
                if act == "delete":
                    db.delete_mistake(mid)
                elif act == "master":
                    # 「我会了」只是弱证据：记一条自评，不直接判掌握、不移出错题本
                    sk = db.self_report_mistake(mid)
                    return self.send_json({"ok": True, "skill": sk, "mistake": db.get_mistake(mid)})
                else:
                    db.set_mastered(mid, 0)
                return self.send_json({"ok": True})
            m = re.match(r"^/api/memory/(\d+)/(edit|delete)$", p)
            if m:
                mid = int(m.group(1))
                if m.group(2) == "delete":
                    return self.send_json({"ok": memmod.delete(db, mid)})
                item = memmod.edit(db, mid, b.get("text") or "")
                return self.send_json({"ok": bool(item), "item": item}, 200 if item else 404)
            if p == "/api/memory/clear":
                return self.send_json({"ok": True, "cleared": memmod.clear(db)})
            if p == "/api/memory/prefs":
                for k, v in (b or {}).items():
                    memmod.set_pref(db, k, v, source={"by": "student"})
                return self.send_json({"prefs": memmod.get_prefs(db)})
            if p == "/api/growth/rollback":
                return self.send_json({"version": evolve.rollback(db, int(b.get("version") or 0))})
            m = re.match(r"^/api/growth/rules/(\d+)/(approve|reject|shadow)$", p)
            if m:
                st = {"approve": "approved", "reject": "rejected", "shadow": "shadow"}[m.group(2)]
                return self.send_json({"version": evolve.set_rule_status(db, int(m.group(1)), st)})
            m = re.match(r"^/api/review/skill/(\d+)$", p)
            if m:
                return self.review_skill(int(m.group(1)))
            m = re.match(r"^/api/mistakes/(\d+)/retry$", p)
            if m:
                return self.retry_mistake(int(m.group(1)))
            return self.send_json({"error": "not found"}, 404)
        except llm.LLMError as e:
            return self.send_json({"error": "小雅暂时连不上模型，稍后再试。", "detail": str(e)[:300]}, 502)
        except ValueError as e:
            return self.send_json({"error": str(e)}, 400)
        except Exception as e:
            traceback.print_exc()
            return self.send_json({"error": "出了点问题：" + str(e)[:200]}, 500)

    # ---------- handlers
    def _chat_begin(self, b):
        profile = db.get_profile() or {"grade": 8, "textbook": "人教版"}
        text = (b.get("message") or "")[:4000]
        image = b.get("image")
        action = b.get("action") if b.get("action") in ("hint", "stuck", "full") else None
        if not text and not image and not action:
            raise ValueError("说点什么吧")
        image_url = save_image(image) if image else None
        sid = b.get("session_id")
        s = db.get_session(int(sid)) if sid else None
        new = not s
        if new:
            sid = db.new_session(text[:30])
            s = db.get_session(sid)
        shown = text or {"hint": "再给一点提示", "stuck": "我卡住了", "full": "看完整解法"}.get(action, "")
        c = {"profile": profile, "text": text, "image": image, "image_url": image_url, "action": action,
             "sid": sid, "s": s, "new": new, "shown": shown, "history": db.messages(sid), "t0": time.time()}
        c["extras"] = self._extras(c)
        return c

    def _extras(self, c):
        """答前准备（都从本地库确定性算出）：心智推断、相关记忆、偏好、本题策略变体、教学经验、已批准的额外规则。"""
        st = c["s"].get("state") or {}
        band = agent.band(int(c["profile"].get("grade") or 8))
        subj = strategies.route(c["text"], st.get("problem") or "", st.get("subject") or "", band)["subject"]
        subj = subj if subj != "通用" else (st.get("subject") or "")
        topic = st.get("topic") or ""
        sk = db.skill(subj, topic, create=False) if subj and topic else None
        misc = db.active_misconceptions(subj, topic) if subj and topic else []
        thought = insight.infer(st, c["text"], c["action"], sk, misc, db.stuck_stats(subj))
        arms = st.get("arms")
        if not arms or st.get("ep_closed") or not st.get("problem"):
            arms = evolve.choose(db, c["sid"], subj, st.get("problem") or c["text"])
        return {"thought": thought, "memories": memmod.retrieve(db, subj, topic, c["text"]), "prefs": memmod.get_prefs(db),
                "arms": arms, "lessons": evolve.lessons_for(db, subj, thought.get("stuck_type")),
                "rules": evolve.approved_rules(db), "band": band}

    def _chat_save(self, c, out, st):
        sid, s, text = c["sid"], c["s"], c["text"]
        db.add_message(sid, "user", c["shown"], c["image_url"], {"action": c["action"]})
        meta = {k: out.get(k) for k in ("subject", "topic", "intent", "stage", "hint_level", "student_correct", "solved", "allow_full",
                                        "strategy", "stuck_type", "misconception", "thought", "verify_fixed")}
        meta["arms"] = (st.get("arms") or {})
        meta["memories_used"] = [m["id"] for m in (c.get("extras") or {}).get("memories") or []]
        if out.get("leak_fixed"):
            meta["leak_fixed"] = True
        mid = db.add_message(sid, "assistant", out["reply"], None, meta)
        sk_before = db.skill(st.get("subject"), st.get("topic"), create=False) if st.get("topic") else None
        # 掌握度证据：同一道题只记一次（自己做对按提示层级折算 / 看完整解法视作错误）
        kind = mastery.chat_evidence(out, st)
        if kind:
            db.record_evidence(st.get("subject"), st.get("topic"), kind, ref={"session_id": sid, "message_id": mid})
            st["ev_logged"] = kind
        title = s.get("title") or (st.get("problem") or text)[:30]
        if st.get("problem") and (not s.get("problem") or s.get("problem") != st.get("problem")):
            title = st["problem"][:30]
        db.update_session(sid, state=st, subject=st.get("subject") or s.get("subject"),
                          topic=st.get("topic") or s.get("topic"), problem=st.get("problem"), title=title)
        self._after_turn(c, out, st, mid, sk_before)
        # 需要看完整解法才弄懂的题，自动进错题本（带上这道题里推断出的错因和误区）
        if out.get("stage") == "full" and st.get("problem"):
            cause = db.q("SELECT stuck_type, COUNT(*) AS n FROM turn_log WHERE session_id=? AND ts>=? AND stuck_type!='' "
                         "GROUP BY stuck_type ORDER BY n DESC LIMIT 1", (sid, st.get("ep_start") or 0), one=True)
            misc = db.q("SELECT detail FROM misconceptions WHERE session_id=? ORDER BY id DESC LIMIT 1", (sid,), one=True)
            db.add_mistake(session_id=sid, subject=st.get("subject") or "其他", topic=st.get("topic") or "",
                           question=st["problem"], user_answer="（看了完整解法）", correct_answer="",
                           explain=out["reply"], source="讲解", cause=cause["stuck_type"] if cause else None,
                           misconception=misc["detail"] if misc else None)
        return {"session_id": sid, "message_id": mid, "reply": out["reply"], "meta": meta,
                "state": out.get("state"), "strategy": out.get("strategy"), "image": c["image_url"],
                "user_text": c["shown"], "problem": st.get("problem")}

    def _after_turn(self, c, out, st, mid, sk_before):
        """每轮写库后：误区、逐轮信号、影子规则、记忆演化；一道题结束时反思（episode）。"""
        sid, text = c["sid"], c["text"]
        old = c["s"].get("state") or {}
        st.setdefault("ep_start", c["t0"])
        if old.get("problem") and old.get("problem") != st.get("problem") and not old.get("ep_closed"):
            evolve.close_episode(db, sid, old, "abandoned")             # 没做完就换了新题
            st["ep_start"] = c["t0"]
        if out.get("student_correct") is False and st.get("subject"):
            typ = insight.classify(text, False, st.get("hint_level"), out.get("stuck_type"))[0]
            if typ:
                db.add_misconception(st.get("subject"), st.get("topic"), typ, out.get("misconception") or "", sid)
        evolve.log_turn(db, sid, st, out, out.get("thought"), (c.get("extras") or {}).get("band", ""))
        prev = next((m for m in reversed(c["history"]) if m["role"] == "assistant"), None)
        if prev and out.get("student_correct") is True:
            evolve.suspect_missed_leak(db, sid, st.get("subject"), prev["content"], (prev.get("meta") or {}).get("stage"),
                                       text, st.get("problem") or "")
        evolve.shadow_eval(db, st.get("subject"), out["reply"], out.get("stage"), out.get("allow_full"),
                           (st.get("problem") or "") + text)
        if (st.get("solved") or st.get("full_given")) and not st.get("ep_closed") and st.get("problem"):
            sk = db.skill(st.get("subject"), st.get("topic"), create=False) if st.get("topic") else None
            outcome = "full" if st.get("full_given") else "solved"
            evolve.close_episode(db, sid, st, outcome, (sk_before or {}).get("p_l"), (sk or {}).get("p_l"))
            st["ep_closed"] = True
        src = {"session_id": sid, "message_id": mid}
        memmod.observe_text(db, text, src)
        memmod.refresh(db, src)

    def _drop_new_session(self, c):
        if c and c.get("new"):
            try:
                db.x("DELETE FROM sessions WHERE id=?", (c["sid"],))
            except Exception:
                pass

    def chat(self, b):
        c = self._chat_begin(b)
        try:
            out, st = agent.respond(c["profile"], c["s"], c["history"], c["text"], c["image"], c["action"], extras=c["extras"])
        except Exception:
            self._drop_new_session(c)
            raise
        return self.send_json(self._chat_save(c, out, st))

    def chat_stream(self, b):
        """SSE：event: meta / delta / status / replace / done / error。出错或客户端断开时什么都不写库，前端可原样重试。"""
        try:
            c = self._chat_begin(b)
        except ValueError as e:
            return self.send_json({"error": str(e)}, 400)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        wlock, stop = threading.Lock(), threading.Event()

        def emit(event, data):
            if event == "meta":
                data = dict(data, session_id=c["sid"], user_text=c["shown"], image=c["image_url"])
            with wlock:
                self.wfile.write(sse(event, data))
                self.wfile.flush()

        def heartbeat():  # 重写漏题时上游可能好一会儿没输出：每 15 秒发一行 SSE 注释，前端不会误判超时
            while not stop.wait(HEARTBEAT):
                try:
                    with wlock:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                except Exception:
                    return
        threading.Thread(target=heartbeat, daemon=True).start()

        try:
            emit("open", {"ts": time.time()})
            out, st = agent.respond_stream(c["profile"], c["s"], c["history"], c["text"], c["image"], c["action"], emit,
                                           extras=c["extras"])
            saved = self._chat_save(c, out, st)
            try:
                emit("done", saved)
            except (BrokenPipeError, ConnectionResetError):
                pass                           # 已经写库；前端重新打开会话能看到这条回复
        except (BrokenPipeError, ConnectionResetError):
            self._drop_new_session(c)          # 客户端走了：不写库
        except llm.LLMError as e:
            self._drop_new_session(c)
            self._safe_emit("error", {"error": "小雅暂时连不上模型，稍后再试。", "detail": str(e)[:300], "retry": True})
        except Exception as e:
            traceback.print_exc()
            self._drop_new_session(c)
            self._safe_emit("error", {"error": "出了点问题：" + str(e)[:200], "retry": True})
        finally:
            stop.set()

    def _safe_emit(self, event, data):
        try:
            self.wfile.write(sse(event, data))
            self.wfile.flush()
        except Exception:
            pass

    def practice(self, b):
        profile = db.get_profile() or {"grade": 8}
        s = db.get_session(int(b.get("session_id") or 0))
        if not s or not s["state"].get("problem"):
            return self.send_json({"error": "先讲一道题，小雅才能出变式题"}, 400)
        qs = agent.make_variants(profile, s["state"], int(b.get("n") or 3))
        if not qs:
            return self.send_json({"error": "这次没出好题，再点一次试试"}, 502)
        pid = db.add_practice(s["id"], s["state"].get("subject"), s["state"].get("topic"), qs)
        return self.send_json({"practice_id": pid, "subject": s["state"].get("subject"), "topic": s["state"].get("topic"),
                               "questions": [{"q": q["q"]} for q in qs]})

    def grade(self, b):
        profile = db.get_profile() or {"grade": 8}
        p = db.get_practice(int(b.get("practice_id") or 0))
        if not p:
            return self.send_json({"error": "练习不存在"}, 404)
        answers = [str(a)[:500] for a in (b.get("answers") or [])]
        answers += [""] * (len(p["questions"]) - len(answers))
        s = db.get_session(p["session_id"]) or {"state": {}}
        res = agent.grade_answers(profile, s["state"], p["questions"], answers)
        out = []
        for q, a, r in zip(p["questions"], answers, res):
            item = {"q": q["q"], "your": a, "correct": r["correct"], "feedback": r["feedback"],
                    "answer": q.get("answer"), "explain": q.get("explain")}
            out.append(item)
            if not r["correct"]:
                cause = insight.classify(a, False)[0] if (a or "").strip() else "方法"
                item["cause"] = cause
                db.add_mistake(session_id=p["session_id"], subject=p["subject"] or "其他", topic=p["topic"] or "",
                               question=q["q"], user_answer=a or "（空）", correct_answer=q.get("answer") or "",
                               explain=(r["feedback"] + "\n\n" + (q.get("explain") or "")).strip(), source="变式题", cause=cause)
                db.add_misconception(p["subject"], p["topic"], cause, "", p["session_id"], source="variant")
        db.set_practice_results(p["id"], out)
        # 掌握度：每道题一条证据；错题本「再练一次」另算一次错题复习
        before = db.skill(p["subject"], p["topic"])
        sk = before
        for i, item in enumerate(out):
            kind = ("retry_" if p.get("mistake_id") else "variant_") + ("right" if item["correct"] else "wrong")
            sk = db.record_evidence(p["subject"], p["topic"], kind, ref={"practice_id": p["id"], "q": i})
        if p.get("mistake_id"):
            db.review_mistake(p["mistake_id"], all(r["correct"] for r in out), ref={"practice_id": p["id"]})
        right = sum(1 for r in out if r["correct"])
        evolve.variant_feedback(db, p["session_id"], right, len(out))
        memmod.refresh(db, {"practice_id": p["id"]})
        return self.send_json({"results": out, "right": right, "total": len(out),
                               "mastery": {"before": before["p_l"], "after": sk["p_l"], "status": mastery.status(sk),
                                           "next_review": sk["next_review"], "mastered": bool(sk["mastered"])}})

    def retry_mistake(self, mid):
        profile = db.get_profile() or {"grade": 8}
        m = db.get_mistake(mid)
        if not m:
            return self.send_json({"error": "没有这道错题"}, 404)
        st = {"problem": m["question"], "subject": m["subject"], "topic": m["topic"]}
        sid = m["session_id"] or db.new_session(m["question"][:30])
        qs = agent.make_variants(profile, st, 2)
        if not qs:
            return self.send_json({"error": "这次没出好题，再点一次试试"}, 502)
        pid = db.add_practice(sid, m["subject"], m["topic"], qs, mistake_id=mid)
        return self.send_json({"practice_id": pid, "subject": m["subject"], "topic": m["topic"],
                               "questions": [{"q": q["q"]} for q in qs]})

    def review_skill(self, skill_id):
        """到期的知识点：拿这个知识点最近的一道错题（没有就拿最近讲过的题）当母题，出两道变式题。"""
        profile = db.get_profile() or {"grade": 8}
        sk = db.q("SELECT * FROM skills WHERE id=?", (skill_id,), one=True)
        if not sk:
            return self.send_json({"error": "没有这个知识点"}, 404)
        topic_sql = "topic=?" if sk["topic"] else "(topic IS NULL OR topic='')"
        args = (sk["subject"], sk["topic"]) if sk["topic"] else (sk["subject"],)
        seed = db.q(f"SELECT session_id, question AS problem FROM mistakes WHERE subject=? AND {topic_sql} "
                    "ORDER BY mastered, created DESC LIMIT 1", args, one=True) or \
            db.q(f"SELECT id AS session_id, problem FROM sessions WHERE subject=? AND {topic_sql} AND problem IS NOT NULL "
                 "AND problem!='' ORDER BY updated DESC LIMIT 1", args, one=True)
        if not seed:
            return self.send_json({"error": "这个知识点还没有可以参照的题，先去问一道吧"}, 400)
        st = {"problem": seed["problem"], "subject": sk["subject"], "topic": sk["topic"]}
        qs = agent.make_variants(profile, st, 2)
        if not qs:
            return self.send_json({"error": "这次没出好题，再点一次试试"}, 502)
        sid = seed["session_id"] or db.new_session(seed["problem"][:30])
        pid = db.add_practice(sid, sk["subject"], sk["topic"], qs)
        return self.send_json({"practice_id": pid, "subject": sk["subject"], "topic": sk["topic"],
                               "questions": [{"q": q["q"]} for q in qs]})


def main():
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    srv = ThreadingHTTPServer((host, port), H)
    mode = f"模型 {llm.MODEL} @ {llm.BASE_URL}" if llm.enabled() else "离线演示模式（未设置 LYCEUM_API_KEY）"
    print(f"Lyceum 学园 → http://{host}:{port}  ·  {mode}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
