"""SQLite 存储：学生档案、会话、消息、变式练习、错题本、知识点掌握度与复习排程。"""
import json
import os
import sqlite3
import threading
import time

from . import mastery as M
from . import taxonomy as TX
from . import memory as MEM
from . import evolve as EVO

_lock = threading.Lock()
_mlock = threading.RLock()  # 掌握度更新是「读-算-写」，串行化
SCHEMA_VERSION = 4
SCHEMA = """
CREATE TABLE IF NOT EXISTS profile (id INTEGER PRIMARY KEY CHECK (id = 1), grade INTEGER, textbook TEXT, nickname TEXT, updated REAL);
CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, created REAL, updated REAL, title TEXT,
  subject TEXT, topic TEXT, problem TEXT, state TEXT);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER, role TEXT, content TEXT,
  image TEXT, meta TEXT, created REAL);
CREATE TABLE IF NOT EXISTS practice (
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER, subject TEXT, topic TEXT,
  questions TEXT, results TEXT, created REAL);
CREATE TABLE IF NOT EXISTS mistakes (
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER, subject TEXT, topic TEXT,
  question TEXT, user_answer TEXT, correct_answer TEXT, explain TEXT, source TEXT,
  mastered INTEGER DEFAULT 0, created REAL);
CREATE TABLE IF NOT EXISTS skills (
  id INTEGER PRIMARY KEY AUTOINCREMENT, subject TEXT NOT NULL, topic TEXT NOT NULL DEFAULT '',
  p_init REAL, p_transit REAL, p_slip REAL, p_guess REAL, p_l REAL, n_obs INTEGER DEFAULT 0,
  review_step INTEGER DEFAULT 0, review_streak INTEGER DEFAULT 0, next_review TEXT, last_review TEXT,
  mastered INTEGER DEFAULT 0, created REAL, updated REAL, UNIQUE(subject, topic));
CREATE TABLE IF NOT EXISTS mastery_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, skill_id INTEGER, mistake_id INTEGER, scope TEXT, ts REAL, day TEXT,
  kind TEXT, correct INTEGER, weight REAL, p_before REAL, p_after REAL,
  step_before INTEGER, step_after INTEGER, next_before TEXT, next_after TEXT, streak_after INTEGER,
  counted INTEGER, mastered_after INTEGER, ref TEXT);
CREATE INDEX IF NOT EXISTS ix_events_skill ON mastery_events(skill_id, ts);
CREATE TABLE IF NOT EXISTS topic_aliases (
  id INTEGER PRIMARY KEY AUTOINCREMENT, subject TEXT NOT NULL, raw TEXT NOT NULL, raw_norm TEXT NOT NULL,
  topic TEXT NOT NULL, matched INTEGER, method TEXT, taxonomy_version INTEGER, created REAL, UNIQUE(subject, raw));
CREATE TABLE IF NOT EXISTS topic_merges (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, subject TEXT, from_skill_id INTEGER, from_topic TEXT,
  to_skill_id INTEGER, to_topic TEXT, method TEXT, events INTEGER, mistakes INTEGER, taxonomy_version INTEGER);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS item_stats (
  item_id TEXT PRIMARY KEY, attempts INTEGER NOT NULL DEFAULT 0, correct INTEGER NOT NULL DEFAULT 0,
  difficulty REAL NOT NULL, first_seen REAL, updated REAL);
CREATE TABLE IF NOT EXISTS item_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, item_id TEXT NOT NULL, subject TEXT, topic TEXT,
  correct INTEGER, answer TEXT, theta_before REAL, difficulty_before REAL, difficulty_after REAL, ts REAL);
CREATE INDEX IF NOT EXISTS ix_item_attempts ON item_attempts(item_id, ts);
CREATE TABLE IF NOT EXISTS writing_reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT, subject TEXT, band TEXT, task TEXT, text TEXT,
  total INTEGER, max INTEGER, coverage TEXT, dims TEXT, notes TEXT, hints TEXT, created REAL);
CREATE INDEX IF NOT EXISTS ix_writing ON writing_reviews(subject, created);
"""
# 旧库缺的列：(表, 列, 定义)。只加列，不删不改，旧数据原样保留。
ADD_COLUMNS = [
    ("mistakes", "review_step", "INTEGER DEFAULT 0"), ("mistakes", "review_streak", "INTEGER DEFAULT 0"),
    ("mistakes", "next_review", "TEXT"), ("mistakes", "last_review", "TEXT"),
    ("mistakes", "self_report", "REAL"), ("mistakes", "mastered_at", "REAL"),
    ("practice", "mistake_id", "INTEGER"),
    # v3 知识点规范化：canon=1 归入规范表 / 0 未归类；merged_into=合并到哪个知识点（旧行保留不删）；
    # void=1 的事件已被合并重放的新事件取代（保留原样，只是不再展示）；topic_raw=改名前模型给的原标签
    ("skills", "canon", "INTEGER"), ("skills", "merged_into", "INTEGER"),
    ("mastery_events", "void", "INTEGER DEFAULT 0"),
    ("mistakes", "topic_raw", "TEXT"), ("sessions", "topic_raw", "TEXT"), ("practice", "topic_raw", "TEXT"),
    # v4 记忆与自进化：错题的错因（审题/概念/方法/计算/表达）与误区一句话
    ("mistakes", "cause", "TEXT"), ("mistakes", "misconception", "TEXT"),
]


class DB:
    def __init__(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA + MEM.SCHEMA + EVO.SCHEMA)   # v4：记忆、误区、自进化表（只加不删）
        self.conn.commit()
        self.migrate()

    # ---- 迁移：旧库自动补列、补表，并把历史练习回放成掌握度事件（只做一次）
    def migrate(self, now=None):
        with _lock:
            for table, col, ddl in ADD_COLUMNS:
                have = {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}
                if col not in have:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
            self.conn.commit()
            ver = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if ver < 2:
            self._backfill(now)
            with _lock:
                self.conn.execute("PRAGMA user_version = 2")
                self.conn.commit()
        tv = self.q("SELECT value FROM meta WHERE key='taxonomy_version'", one=True)
        if ver < 3 or not tv or tv["value"] != str(TX.VERSION):
            # 规范表第一次上线或规范表改版：把已有的分裂标签合并（幂等：已经规范的什么都不做）
            self.merge_topics(now)
            self.x("INSERT INTO meta (key, value) VALUES ('taxonomy_version', ?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(TX.VERSION),))
            with _lock:
                self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                self.conn.commit()
        elif ver < SCHEMA_VERSION:
            with _lock:
                self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                self.conn.commit()
        EVO.ensure(self, now)

    # ---- 知识点规范化（规则见 lyceum/taxonomy.py）
    def band(self):
        p = self.get_profile()
        return TX.band_of_grade(p["grade"]) if p and p.get("grade") else None

    def canon(self, subject, topic, band=None, record=True):
        """（学科, 原标签）→ (学科, 规范知识点, 是否归入规范表, 匹配方式)。同科才合并；匹配不到保留清洗后的原标签。"""
        subj, top = self.skill_key(subject, topic)
        if not top:
            return subj, "", False, "empty"
        r = TX.resolve(subj, top, band or self.band())
        if record and r["topic"] != top:
            self.x("INSERT INTO topic_aliases (subject, raw, raw_norm, topic, matched, method, taxonomy_version, created) "
                   "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(subject, raw) DO UPDATE SET topic=excluded.topic, "
                   "matched=excluded.matched, method=excluded.method, taxonomy_version=excluded.taxonomy_version",
                   (subj, top, TX.norm(top), r["topic"], int(r["matched"]), r["method"], TX.VERSION, time.time()))
        return subj, r["topic"], r["matched"], r["method"]

    def merge_topics(self, now=None):
        """把同一学科里归到同一个规范知识点的旧知识点合并：
          - 目标 = 已有的同名规范知识点（没有就新建一行）；其余旧行保留，只标 merged_into；
          - 所有成员的掌握度证据按时间顺序（ts, id）在目标上重放（不是取平均），重放事件的 ref 记 replay_of / merged_from；
            目标自己原来的事件标 void=1（保留，不展示），由重放结果取代；
          - 错题 / 会话 / 练习的 topic 改成规范名，原标签存进 topic_raw；每一对 from→to 写一条 topic_merges。
        幂等：所有知识点都已规范时什么也不做。返回合并日志条数。"""
        now = time.time() if now is None else now
        band = self.band()
        groups = {}
        for sk in self.q("SELECT * FROM skills WHERE merged_into IS NULL ORDER BY id"):
            subj, top, matched, method = self.canon(sk["subject"], sk["topic"], band)
            groups.setdefault((subj, top), []).append((sk, matched, method))
        n_log = 0
        for (subj, top), members in groups.items():
            matched = members[0][1]
            ids = [m[0]["id"] for m in members]
            self.x(f"UPDATE skills SET canon=? WHERE id IN ({','.join('?' * len(ids))})", (int(matched), *ids))
            if len(members) == 1 and members[0][0]["topic"] == top and members[0][0]["subject"] == subj:
                continue
            with _mlock:
                tgt = next((m[0] for m in members if m[0]["topic"] == top and m[0]["subject"] == subj), None)
                created = min((m[0]["created"] or now) for m in members)
                if tgt is None:
                    self.x("INSERT INTO skills (subject, topic, p_init, p_transit, p_slip, p_guess, p_l, n_obs, review_step, "
                           "review_streak, next_review, mastered, created, updated, canon) VALUES (?,?,?,?,?,?,?,0,0,0,NULL,0,?,?,?)",
                           (subj, top, M.P_INIT, M.P_TRANSIT, M.P_SLIP, M.P_GUESS, M.P_INIT, created, now, int(matched)))
                    tgt = self.q("SELECT * FROM skills WHERE subject=? AND topic=?", (subj, top), one=True)
                events = self.q(f"SELECT * FROM mastery_events WHERE skill_id IN ({','.join('?' * len(ids))}) "
                                "AND COALESCE(void,0)=0 ORDER BY ts, id", tuple(ids))
                self.x("UPDATE mastery_events SET void=1 WHERE skill_id=? AND COALESCE(void,0)=0", (tgt["id"],))
                self.x("UPDATE skills SET p_l=p_init, n_obs=0, review_step=0, review_streak=0, next_review=NULL, last_review=NULL, "
                       "mastered=0, created=?, updated=? WHERE id=?", (created, now, tgt["id"]))
                cur = self.q("SELECT * FROM skills WHERE id=?", (tgt["id"],), one=True)
                topic_of = {m[0]["id"]: m[0]["topic"] for m in members}
                for e in events:
                    ref = json.loads(e["ref"] or "{}")
                    ref.update({"replay_of": e["id"], "merged_from": topic_of.get(e["skill_id"], "")})
                    if e["scope"] == "skill" and e["kind"] in M.EVIDENCE:
                        cur = self._apply(cur, e["kind"], e["ts"], ref=ref, mistake_id=e["mistake_id"])
                    else:  # 错题复习事件不改 P(L)，原样复制到目标上
                        row = {k: e[k] for k in ("mistake_id", "scope", "ts", "day", "kind", "correct", "weight", "step_before",
                                                 "step_after", "next_before", "next_after", "streak_after", "counted", "mastered_after")}
                        self._event(skill_id=cur["id"], p_before=cur["p_l"], p_after=cur["p_l"], ref=ref, **row)
                for sk, _, method in members:
                    if sk["id"] == tgt["id"]:
                        continue
                    self.x("UPDATE skills SET merged_into=?, updated=? WHERE id=?", (tgt["id"], now, sk["id"]))
                    n_ev = sum(1 for e in events if e["skill_id"] == sk["id"])
                    n_mi = self.q("SELECT COUNT(*) AS n FROM mistakes WHERE COALESCE(NULLIF(TRIM(subject),''),'其他')=? "
                                  "AND TRIM(COALESCE(topic,''))=?", (sk["subject"], sk["topic"]), one=True)["n"]
                    self.x("INSERT INTO topic_merges (ts, subject, from_skill_id, from_topic, to_skill_id, to_topic, method, events, "
                           "mistakes, taxonomy_version) VALUES (?,?,?,?,?,?,?,?,?,?)",
                           (now, subj, sk["id"], sk["topic"], tgt["id"], top, method, n_ev, n_mi, TX.VERSION))
                    n_log += 1
        # 错题 / 会话 / 练习：标签改成规范名，原标签留在 topic_raw
        for table in ("mistakes", "sessions", "practice"):
            for r in self.q(f"SELECT DISTINCT subject, topic FROM {table} WHERE topic IS NOT NULL AND topic!=''"):
                _, top, _, _ = self.canon(r["subject"], r["topic"], band)
                if top != r["topic"]:
                    self.x(f"UPDATE {table} SET topic_raw=COALESCE(topic_raw, topic), topic=? WHERE subject IS ? AND topic=?",
                           (top, r["subject"], r["topic"]))
        return n_log

    def merge_log(self):
        return self.q("SELECT * FROM topic_merges ORDER BY id")

    def _backfill(self, now=None):
        """按时间顺序回放：已批改的变式题 → variant_right/wrong；看完整解法进错题本的 → full_solution；
        还没排程的未掌握错题 → 从它进错题本那天起第 0 级（次日复习）。回放事件的 ref 带 backfill=1。"""
        jobs = []
        for p in self.q("SELECT id, subject, topic, results, created, mistake_id FROM practice WHERE results IS NOT NULL"):
            try:
                res = json.loads(p["results"])
            except Exception:
                continue
            for r in res:
                kind = "variant_right" if r.get("correct") else "variant_wrong"
                jobs.append((p["created"] or 0, "ev", (p["subject"], p["topic"], kind, {"practice_id": p["id"], "backfill": 1})))
        for m in self.q("SELECT id, subject, topic, source, created, mastered, next_review FROM mistakes"):
            if m["source"] == "讲解":
                jobs.append((m["created"] or 0, "ev", (m["subject"], m["topic"], "full_solution", {"mistake_id": m["id"], "backfill": 1})))
            if not m["mastered"] and not m["next_review"]:
                jobs.append((m["created"] or 0, "mi", m))
        jobs.sort(key=lambda j: (j[0], j[1]))
        for ts, typ, a in jobs:
            if typ == "ev":
                self.record_evidence(a[0], a[1], a[2], ref=a[3], now=ts)
            else:
                d = M.today(ts)
                self.x("UPDATE mistakes SET review_step=0, review_streak=0, next_review=? WHERE id=?",
                       (M.add_days(d, M.LADDER[0]), a["id"]))
                self.skill(a["subject"], a["topic"], now=ts)

    def q(self, sql, args=(), one=False):
        with _lock:
            cur = self.conn.execute(sql, args)
            rows = [dict(r) for r in cur.fetchall()]
        return (rows[0] if rows else None) if one else rows

    def x(self, sql, args=()):
        with _lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur.lastrowid

    # ---- 题库：在线难度标定
    def item_stats(self):
        return {r["item_id"]: {"attempts": r["attempts"], "correct": r["correct"], "difficulty": r["difficulty"]}
                for r in self.q("SELECT item_id, attempts, correct, difficulty FROM item_stats")}

    def item_stat(self, item_id):
        return self.q("SELECT item_id, attempts, correct, difficulty FROM item_stats WHERE item_id=?",
                      (item_id,), one=True)

    def record_item_attempt(self, item_id, subject, topic, theta, difficulty, correct, answer="", now=None):
        """写一次作答，按 Elo 式更新该题难度。返回 (difficulty_before, difficulty_after, attempts)。"""
        from . import itembank
        now = time.time() if now is None else now
        row = self.item_stat(item_id)
        attempts = int(row["attempts"]) if row else 0
        before = float(row["difficulty"]) if row and attempts else float(difficulty)
        _, after = itembank.update_pair(theta, before, correct, attempts)
        with _mlock:
            if row:
                self.x("UPDATE item_stats SET attempts=attempts+1, correct=correct+?, difficulty=?, updated=? "
                       "WHERE item_id=?", (1 if correct else 0, after, now, item_id))
            else:
                self.x("INSERT INTO item_stats(item_id, attempts, correct, difficulty, first_seen, updated) "
                       "VALUES(?,1,?,?,?,?)", (item_id, 1 if correct else 0, after, now, now))
            self.x("INSERT INTO item_attempts(item_id, subject, topic, correct, answer, theta_before, "
                   "difficulty_before, difficulty_after, ts) VALUES(?,?,?,?,?,?,?,?,?)",
                   (item_id, subject, topic, 1 if correct else 0, str(answer)[:200], float(theta), before, after, now))
        return before, after, attempts + 1

    # ---- 写作记录
    def save_writing_review(self, result, task="", text="", now=None):
        """存一次评阅结果，返回 id。只存结果，不存任何模型密钥。"""
        import json as _json
        now = time.time() if now is None else now
        return self.x("INSERT INTO writing_reviews(subject, band, task, text, total, max, coverage, dims, notes, hints, created) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (result.get("subject"), result.get("band"), str(task)[:200], str(text)[:20000],
                       int(result.get("total", 0)), int(result.get("max", 0)), result.get("coverage"),
                       _json.dumps(result.get("dims", []), ensure_ascii=False),
                       _json.dumps(result.get("notes", []), ensure_ascii=False),
                       _json.dumps(result.get("hints", []), ensure_ascii=False), now))

    def writing_history(self, subject=None, limit=12):
        rows = self.q("SELECT id, subject, band, task, total, max, coverage, created FROM writing_reviews "
                      "WHERE (? IS NULL OR subject=?) ORDER BY created DESC LIMIT ?", (subject, subject, int(limit)))
        return rows

    # ---- profile
    def get_profile(self):
        return self.q("SELECT grade, textbook, nickname FROM profile WHERE id=1", one=True)

    def set_profile(self, grade, textbook, nickname=""):
        self.x("INSERT INTO profile (id, grade, textbook, nickname, updated) VALUES (1,?,?,?,?) "
               "ON CONFLICT(id) DO UPDATE SET grade=excluded.grade, textbook=excluded.textbook, nickname=excluded.nickname, updated=excluded.updated",
               (grade, textbook, nickname, time.time()))

    # ---- sessions
    def new_session(self, title=""):
        now = time.time()
        return self.x("INSERT INTO sessions (created, updated, title, state) VALUES (?,?,?,?)",
                      (now, now, title, json.dumps({})))

    def get_session(self, sid):
        s = self.q("SELECT * FROM sessions WHERE id=?", (sid,), one=True)
        if s:
            s["state"] = json.loads(s["state"] or "{}")
        return s

    def update_session(self, sid, **kw):
        if "state" in kw:
            kw["state"] = json.dumps(kw["state"], ensure_ascii=False)
        kw["updated"] = time.time()
        cols = ", ".join(f"{k}=?" for k in kw)
        self.x(f"UPDATE sessions SET {cols} WHERE id=?", (*kw.values(), sid))

    def list_sessions(self, limit=30):
        return self.q("SELECT id, created, updated, title, subject, topic FROM sessions "
                      "WHERE id IN (SELECT DISTINCT session_id FROM messages) ORDER BY updated DESC LIMIT ?", (limit,))

    def add_message(self, sid, role, content, image=None, meta=None):
        return self.x("INSERT INTO messages (session_id, role, content, image, meta, created) VALUES (?,?,?,?,?,?)",
                      (sid, role, content, image, json.dumps(meta or {}, ensure_ascii=False), time.time()))

    def messages(self, sid):
        rows = self.q("SELECT id, role, content, image, meta, created FROM messages WHERE session_id=? ORDER BY id", (sid,))
        for r in rows:
            r["meta"] = json.loads(r["meta"] or "{}")
        return rows

    # ---- practice
    def add_practice(self, sid, subject, topic, questions, mistake_id=None):
        return self.x("INSERT INTO practice (session_id, subject, topic, questions, created, mistake_id) VALUES (?,?,?,?,?,?)",
                      (sid, subject, topic, json.dumps(questions, ensure_ascii=False), time.time(), mistake_id))

    def get_practice(self, pid):
        p = self.q("SELECT * FROM practice WHERE id=?", (pid,), one=True)
        if p:
            p["questions"] = json.loads(p["questions"])
            p["results"] = json.loads(p["results"]) if p["results"] else None
        return p

    def set_practice_results(self, pid, results):
        self.x("UPDATE practice SET results=? WHERE id=?", (json.dumps(results, ensure_ascii=False), pid))

    # ---- mistakes
    def add_mistake(self, **m):
        exists = self.q("SELECT id FROM mistakes WHERE question=? AND mastered=0", (m.get("question", ""),), one=True)
        if exists:
            return exists["id"]
        m.setdefault("created", time.time())
        _, top, _, _ = self.canon(m.get("subject"), m.get("topic"))
        if (m.get("topic") or "") != top:
            m["topic_raw"], m["topic"] = m.get("topic"), top
        m.setdefault("review_step", 0)
        m.setdefault("review_streak", 0)
        m.setdefault("next_review", M.add_days(M.today(m["created"]), M.LADDER[0]))
        self.skill(m.get("subject"), m.get("topic"), now=m["created"])
        cols = ", ".join(m.keys())
        return self.x(f"INSERT INTO mistakes ({cols}) VALUES ({', '.join('?' * len(m))})", tuple(m.values()))

    def list_mistakes(self, subject=None, include_mastered=False):
        sql = "SELECT * FROM mistakes WHERE 1=1"
        args = []
        if subject:
            sql += " AND subject=?"
            args.append(subject)
        if not include_mastered:
            sql += " AND mastered=0"
        return self.q(sql + " ORDER BY created DESC", args)

    def get_mistake(self, mid):
        return self.q("SELECT * FROM mistakes WHERE id=?", (mid,), one=True)

    def set_mastered(self, mid, v=1):
        self.x("UPDATE mistakes SET mastered=? WHERE id=?", (v, mid))
        if not v:  # 移回错题本：没有排程的话从明天重新开始
            self.x("UPDATE mistakes SET review_step=0, review_streak=0, next_review=? WHERE id=? AND next_review IS NULL",
                   (M.add_days(M.today(), M.LADDER[0]), mid))

    def delete_mistake(self, mid):
        self.x("DELETE FROM mistakes WHERE id=?", (mid,))

    # ---- 掌握度（BKT）与复习排程；规则见 lyceum/mastery.py
    @staticmethod
    def skill_key(subject, topic):
        return (subject or "其他").strip() or "其他", (topic or "").strip()

    def skill(self, subject, topic, now=None, create=True):
        """取（必要时新建）知识点。标签先按规范表归一化，所以「一元二次方程·因式分解」和「因式分解」是同一行。"""
        subj, top, matched, _ = self.canon(subject, topic)
        sk = self.q("SELECT * FROM skills WHERE subject=? AND topic=?", (subj, top), one=True)
        if sk and sk.get("merged_into"):  # 理论上不会发生（合并目标总是规范名），保险起见跟到目标
            sk = self.q("SELECT * FROM skills WHERE id=?", (sk["merged_into"],), one=True)
        if sk or not create:
            return sk
        now = time.time() if now is None else now
        self.x("INSERT OR IGNORE INTO skills (subject, topic, p_init, p_transit, p_slip, p_guess, p_l, n_obs, review_step, "
               "review_streak, next_review, mastered, created, updated, canon) VALUES (?,?,?,?,?,?,?,0,0,0,NULL,0,?,?,?)",
               (subj, top, M.P_INIT, M.P_TRANSIT, M.P_SLIP, M.P_GUESS, M.P_INIT, now, now, int(matched)))
        return self.q("SELECT * FROM skills WHERE subject=? AND topic=?", (subj, top), one=True)

    def _event(self, **e):
        e["ref"] = json.dumps(e.get("ref") or {}, ensure_ascii=False)
        cols = ", ".join(e.keys())
        return self.x(f"INSERT INTO mastery_events ({cols}) VALUES ({', '.join('?' * len(e))})", tuple(e.values()))

    def record_evidence(self, subject, topic, kind, ref=None, mistake_id=None, now=None):
        """一条证据 → 更新该知识点的 P(L) 与排程，写一条事件。返回更新后的知识点。"""
        if kind not in M.EVIDENCE:
            raise ValueError("未知证据类型 " + kind)
        now = time.time() if now is None else now
        with _mlock:
            sk = self._apply(self.skill(subject, topic, now=now), kind, now, ref=ref, mistake_id=mistake_id)
        if M.EVIDENCE[kind][0]:
            self.resolve_misconceptions(subject, topic, now)
        return sk

    def _apply(self, sk, kind, now, ref=None, mistake_id=None):
        """在给定知识点行上折算一条证据（record_evidence 和合并重放共用）。"""
        d = M.today(now)
        obs, w, _, effect, _ = M.EVIDENCE[kind]
        with _mlock:
            p0 = sk["p_l"] if sk["p_l"] is not None else sk["p_init"]
            p1 = M.apply_evidence(p0, kind, sk)
            sch, counted = M.schedule(sk, effect, d)
            mastered = 1 if M.is_mastered(p1, sch["review_streak"]) else 0
            self.x("UPDATE skills SET p_l=?, n_obs=n_obs+1, review_step=?, review_streak=?, next_review=?, "
                   "last_review=CASE WHEN ? THEN ? ELSE last_review END, mastered=?, updated=? WHERE id=?",
                   (p1, sch["review_step"], sch["review_streak"], sch["next_review"], int(counted), d.isoformat(),
                    mastered, now, sk["id"]))
            self._event(skill_id=sk["id"], mistake_id=mistake_id, scope="skill", ts=now, day=d.isoformat(), kind=kind,
                        correct=obs, weight=w, p_before=p0, p_after=p1, step_before=sk["review_step"],
                        step_after=sch["review_step"], next_before=sk["next_review"], next_after=sch["next_review"],
                        streak_after=sch["review_streak"], counted=int(counted), mastered_after=mastered, ref=ref)
            return self.q("SELECT * FROM skills WHERE id=?", (sk["id"],), one=True)

    def review_mistake(self, mid, correct, ref=None, now=None):
        """错题自己的排程：「再练一次」整组全对 = 对，有错 = 错。错题出本 = 自己连续两次到期复习答对 且 所属知识点 P(L)≥0.85。"""
        now = time.time() if now is None else now
        d = M.today(now)
        with _mlock:
            m = self.get_mistake(mid)
            if not m:
                return None
            sk = self.skill(m["subject"], m["topic"], now=now)
            sch, counted = M.schedule(m, "right" if correct else "wrong", d)
            done = 1 if (not m["mastered"] and M.is_mastered(sk["p_l"], sch["review_streak"])) else 0
            self.x("UPDATE mistakes SET review_step=?, review_streak=?, next_review=?, "
                   "last_review=CASE WHEN ? THEN ? ELSE last_review END, mastered=CASE WHEN ? THEN 1 ELSE mastered END, "
                   "mastered_at=CASE WHEN ? THEN ? ELSE mastered_at END WHERE id=?",
                   (sch["review_step"], sch["review_streak"], None if done else sch["next_review"], int(counted), d.isoformat(),
                    done, done, now, mid))
            self._event(skill_id=sk["id"], mistake_id=mid, scope="mistake", ts=now, day=d.isoformat(),
                        kind="retry_right" if correct else "retry_wrong", correct=int(bool(correct)), weight=1.0,
                        p_before=sk["p_l"], p_after=sk["p_l"], step_before=m["review_step"], step_after=sch["review_step"],
                        next_before=m["next_review"], next_after=None if done else sch["next_review"],
                        streak_after=sch["review_streak"], counted=int(counted), mastered_after=done, ref=ref)
            return self.get_mistake(mid)

    def self_report_mistake(self, mid, now=None):
        """「我会了」：只记一条弱证据，不出错题本，不改错题排程。"""
        now = time.time() if now is None else now
        m = self.get_mistake(mid)
        if not m:
            return None
        sk = self.record_evidence(m["subject"], m["topic"], "self_report", ref={"mistake_id": mid}, mistake_id=mid, now=now)
        self.x("UPDATE mistakes SET self_report=? WHERE id=?", (now, mid))
        return sk

    def _decorate(self, sk, d):
        sk = dict(sk)
        sk["status"] = M.status(sk)
        sk["due"] = bool(sk.get("next_review") and sk["next_review"] <= d)
        sk["interval_days"] = M.LADDER[min(int(sk.get("review_step") or 0), len(M.LADDER) - 1)]
        return sk

    def mastery_list(self, subject=None, now=None):
        d = M.today(now).isoformat()
        sql, args = "SELECT * FROM skills WHERE merged_into IS NULL", []
        if subject:
            sql += " AND subject=?"
            args.append(subject)
        rows = self.q(sql + " ORDER BY subject, p_l DESC, id", args)
        open_n, due_n = self._mistake_counts(d)
        aliases = {}
        for a in self.q("SELECT subject, raw, topic FROM topic_aliases WHERE matched=1 ORDER BY id"):
            aliases.setdefault((a["subject"], a["topic"]), []).append(a["raw"])
        out = []
        for r in rows:
            r = self._decorate(r, d)
            k = (r["subject"], r["topic"])
            r["mistakes_open"] = open_n.get(k, 0)
            r["mistakes_due"] = due_n.get(k, 0)
            r["review_today"] = bool(r["due"] or r["mistakes_due"])  # 「今日复习」口径：知识点到期 或 有到期错题
            r["aliases"] = aliases.get(k, [])
            out.append(r)
        return out

    def _mistake_counts(self, d):
        open_n, due_n = {}, {}
        for r in self.q("SELECT subject, topic, COUNT(*) AS n, SUM(CASE WHEN next_review IS NOT NULL AND next_review<=? THEN 1 ELSE 0 END) AS due "
                        "FROM mistakes WHERE mastered=0 GROUP BY subject, topic", (d,)):
            k = self.skill_key(r["subject"], r["topic"])
            open_n[k] = open_n.get(k, 0) + r["n"]
            due_n[k] = due_n.get(k, 0) + (r["due"] or 0)
        return open_n, due_n

    def skill_events(self, skill_id):
        sk = self.q("SELECT * FROM skills WHERE id=?", (skill_id,), one=True)
        if not sk:
            return None, []
        ev = self.q("SELECT * FROM mastery_events WHERE skill_id=? AND COALESCE(void,0)=0 ORDER BY ts, id", (skill_id,))
        for e in ev:
            e["ref"] = json.loads(e["ref"] or "{}")
            e["label"] = M.EVIDENCE.get(e["kind"], (0, 0, 0, 0, e["kind"]))[4]
        return self._decorate(sk, M.today().isoformat()), ev

    def review_today(self, now=None):
        d = M.today(now).isoformat()
        skills = [self._decorate(r, d) for r in self.q(
            "SELECT * FROM skills WHERE merged_into IS NULL AND next_review IS NOT NULL AND next_review<=? ORDER BY next_review, p_l", (d,))]
        mistakes = self.q("SELECT * FROM mistakes WHERE mastered=0 AND next_review IS NOT NULL AND next_review<=? "
                          "ORDER BY next_review, created", (d,))
        upcoming = self.q("SELECT MIN(next_review) AS nx FROM skills WHERE merged_into IS NULL AND next_review>?", (d,), one=True)["nx"]
        # 统一口径：「今日复习」按知识点计 = 到期的知识点 ∪ 有到期错题的知识点；错题另报道数
        topics = {(k["subject"], k["topic"]) for k in skills} | {self.skill_key(m["subject"], m["topic"]) for m in mistakes}
        # 「下一步练什么」：前置没稳时先补前置。只读，不改任何状态。
        from . import curriculum
        mastery = {(r["subject"], r["topic"]): r["p_l"] for r in self.q(
            "SELECT subject, topic, p_l FROM skills WHERE merged_into IS NULL")}
        nxt = curriculum.recommend(mastery, [(k["subject"], k["topic"]) for k in skills])
        return {"date": d, "skills": skills, "mistakes": mistakes, "next_date": upcoming,
                "topics_due": len(topics), "mistakes_due": len(mistakes), "next": nxt}

    # ---- 误区（tutor-mcp：按（知识点, 类型）分组；之后该知识点连续 3 条证据都对 → 已解决）
    MISC_WINDOW = 3

    def add_misconception(self, subject, topic, typ, detail="", session_id=None, source="chat", now=None):
        from . import insight
        if typ not in insight.TYPES:
            return None
        subj, top, _, _ = self.canon(subject, topic)
        return self.x("INSERT INTO misconceptions (ts, subject, topic, type, detail, session_id, source) VALUES (?,?,?,?,?,?,?)",
                      (time.time() if now is None else now, subj, top, typ, insight.clean_misconception(detail), session_id, source))

    def active_misconceptions(self, subject, topic):
        subj, top, _, _ = self.canon(subject, topic, record=False)
        return self.q("SELECT type, detail, COUNT(*) AS n, MAX(ts) AS last FROM misconceptions WHERE subject=? AND topic=? "
                      "AND resolved_at IS NULL GROUP BY type ORDER BY n DESC, last DESC", (subj, top))

    def resolve_misconceptions(self, subject, topic, now=None):
        """该知识点最近 MISC_WINDOW 条（未作废的知识点级）证据都是「对」，且都晚于误区最后一次出现 → 标已解决。返回解决条数。"""
        sk = self.skill(subject, topic, create=False)
        if not sk:
            return 0
        last = self.q("SELECT MAX(ts) AS t FROM misconceptions WHERE subject=? AND topic=? AND resolved_at IS NULL",
                      (sk["subject"], sk["topic"]), one=True)["t"]
        if last is None:
            return 0
        ev = self.q("SELECT correct, ts FROM mastery_events WHERE skill_id=? AND scope='skill' AND COALESCE(void,0)=0 "
                    "AND kind!='self_report' ORDER BY ts DESC, id DESC LIMIT ?", (sk["id"], self.MISC_WINDOW))
        if len(ev) < self.MISC_WINDOW or not all(e["correct"] and e["ts"] > last for e in ev):
            return 0
        now = time.time() if now is None else now
        n = self.q("SELECT COUNT(*) AS n FROM misconceptions WHERE subject=? AND topic=? AND resolved_at IS NULL",
                   (sk["subject"], sk["topic"]), one=True)["n"]
        self.x("UPDATE misconceptions SET resolved_at=? WHERE subject=? AND topic=? AND resolved_at IS NULL",
               (now, sk["subject"], sk["topic"]))
        return n

    def stuck_stats(self, subject):
        return {r["stuck_type"]: r["n"] for r in self.q(
            "SELECT stuck_type, COUNT(*) AS n FROM turn_log WHERE subject=? AND stuck_type!='' GROUP BY stuck_type", (subject or "",))}

    # ---- stats
    def stats(self):
        days = [r["d"] for r in self.q(
            "SELECT DISTINCT date(created, 'unixepoch', 'localtime') AS d FROM messages WHERE role='user' ORDER BY d DESC")]
        import datetime
        streak, today = 0, datetime.date.today()
        for i, d in enumerate(days):
            if d == (today - datetime.timedelta(days=i)).isoformat():
                streak += 1
            else:
                break
        by_subject = self.q("SELECT subject, COUNT(*) AS n FROM sessions WHERE subject IS NOT NULL AND subject!='' "
                            "AND id IN (SELECT DISTINCT session_id FROM messages) GROUP BY subject ORDER BY n DESC")
        week = self.q("SELECT COUNT(*) AS n FROM messages WHERE role='user' AND created > ?", (time.time() - 7 * 86400,), one=True)["n"]
        practice = self.q("SELECT results FROM practice WHERE results IS NOT NULL")
        right = total = 0
        for p in practice:
            for r in json.loads(p["results"]):
                total += 1
                right += 1 if r.get("correct") else 0
        mist = self.q("SELECT COUNT(*) AS n, SUM(mastered) AS m FROM mistakes", one=True)
        d = M.today().isoformat()
        sk = self.q("SELECT COUNT(*) AS n, SUM(mastered) AS m, SUM(CASE WHEN p_l>=? AND mastered=0 THEN 1 ELSE 0 END) AS c, "
                    "SUM(CASE WHEN next_review<=? THEN 1 ELSE 0 END) AS due FROM skills WHERE n_obs>0 AND merged_into IS NULL",
                    (M.MASTERY_P, d), one=True)
        due_m = self.q("SELECT COUNT(*) AS n FROM mistakes WHERE mastered=0 AND next_review<=?", (d,), one=True)["n"]
        rv = self.review_today()
        return {
            "streak": streak, "active_days": len(days), "week_questions": week,
            "by_subject": by_subject, "practice_total": total, "practice_right": right,
            "mistakes_open": (mist["n"] or 0) - (mist["m"] or 0), "mistakes_mastered": mist["m"] or 0,
            "skills_total": sk["n"] or 0, "skills_mastered": sk["m"] or 0, "skills_consolidating": sk["c"] or 0,
            "skills_due": sk["due"] or 0, "mistakes_due": due_m, "review_topics_due": rv["topics_due"],
        }
