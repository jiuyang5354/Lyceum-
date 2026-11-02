"""小雅的自进化：可审计、可回滚、有边界。

做什么
  1. 逐轮记录信号（turn_log）：卡点类型、提示层级、卡住次数、判对错、漏题拦截、数学校验修正、本题用的策略变体。
  2. 一道题结束（自己做对 / 看了完整解法 / 换了新题）→ 一个 episode → 反思：
       奖励 = 结果（自己做对按提示层级折算；看完整解法 0.1；没做完 0.2）− 多卡住 − 漏题拦截，再按掌握度变化微调；
       之后变式题批改再补一次观察（权重 0.5）。
     反思器可插拔：OfflineReflector（确定性规则，默认）/ LLMReflector（只有设置 LYCEUM_REFLECTOR=llm 且接了模型才用，失败退回离线）。
  3. 策略自调：只在白名单参数内——每科的「追问方式」tactic 与「提示推进速度」pace，各有几个写死在代码里的变体；
     按（学生, 学科）用 Thompson 采样选变体，每次选择和奖励都写 bandit_log。
     一个变体观察 ≥8 次且均值比最好的低 0.25 以上 → 停用（至少留一个）。
  4. 教学经验：（学科, 卡点类型, 追问方式）的有效次数 / 总次数，有效 = 奖励 ≥0.6；够 3 次才进提示词。
  5. 候选漏题规则：只进影子模式统计命中与误报，**永远不自动上线**；人工批准后才作为额外的拦截（只会更严，不会放松）。
  6. 版本化：策略参数（各变体的 Beta 后验、停用表、教学经验统计、已批准规则）每变一次就存一个新版本；
     回滚 = 以目标版本的参数新建一个版本（只追加，不删历史）。

护栏（永远不能被改）：不直接给答案的核心规则、完整解法的释放条件、隐私过滤。
参数校验只认白名单键；任何试图写入其它键（如 stuck_limit / leak / privacy）都会抛 GuardrailError。
"""
import hashlib
import json
import os
import random
import re
import time

TACTICS = {
    "question_first": ("先抛小问题", "先抛一个学生马上能答上的小问题，让他自己迈出下一步。"),
    "example_first": ("先举小例子", "先给一个更简单的同类小例子（数字更小或情境更熟悉），让他在小例子上做一遍，再回到原题。"),
    "visual_first": ("先画出来", "先让他把题目画出来或列成表（线段图、受力图、表格、时间线），从图里找关系。"),
}
PACES = {
    "steady": ("每轮推进一层", "学生说卡住时，提示往下推进一层（仍然不跳层）。"),
    "patient": ("同层多问一次", "学生第一次说卡住时，先在同一层换一个问法再追问一次；第二次还卡再进下一层。"),
}
PARAMS = {"tactic": TACTICS, "pace": PACES}
ALLOWED_KEYS = {"tactic", "pace", "disabled", "lessons", "rules"}
PROTECTED = ("不直接给答案的核心规则（提示词原则 2–4 + leak.py 漏题拦截）",
             "完整解法释放条件（同题卡住 3 次 / 点「看完整解法」/ 已给过 1 层提示后主动要求）",
             "隐私过滤（privacy.py：不记姓名、住址、学校、电话等）")
PRIOR = (1.0, 1.0)
MAX_PARAM = 500.0
DISABLE_MIN_N = 8
DISABLE_GAP = 0.25
LESSON_MIN_N = 3
LESSON_GOOD = 0.6
MAX_CANDIDATES = 30
SOLVE_REWARD = {0: 1.0, 1: 0.85, 2: 0.65, 3: 0.4}
STUDENT = "local"   # 单机单学生；多学生时换成学生 id

SCHEMA = """
CREATE TABLE IF NOT EXISTS turn_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, session_id INTEGER, subject TEXT, topic TEXT, band TEXT,
  stuck_type TEXT, hint_level INTEGER, stuck INTEGER, student_correct INTEGER, leak INTEGER, verify_fix INTEGER,
  tactic TEXT, pace TEXT, thought TEXT);
CREATE TABLE IF NOT EXISTS episodes (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, session_id INTEGER, problem TEXT, subject TEXT, topic TEXT,
  stuck_type TEXT, tactic TEXT, pace TEXT, outcome TEXT, hints INTEGER, stuck INTEGER, turns INTEGER, leaks INTEGER,
  verify_fixes INTEGER, var_right INTEGER, var_total INTEGER, p_before REAL, p_after REAL, reward REAL,
  reflector TEXT, summary TEXT, version INTEGER);
CREATE TABLE IF NOT EXISTS bandit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, session_id INTEGER, student TEXT, subject TEXT, param TEXT, arm TEXT,
  sample REAL, version INTEGER, episode_id INTEGER, reward REAL, weight REAL);
CREATE TABLE IF NOT EXISTS policy_versions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, parent INTEGER, params TEXT, reason TEXT, author TEXT);
CREATE TABLE IF NOT EXISTS evolve_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, version INTEGER, op TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS candidate_rules (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, subject TEXT, pattern TEXT, example TEXT, source TEXT,
  status TEXT DEFAULT 'shadow', hits INTEGER DEFAULT 0, fp INTEGER DEFAULT 0, tp INTEGER DEFAULT 0, updated REAL,
  UNIQUE(subject, pattern));
"""


class GuardrailError(ValueError):
    pass


# ---------------- 版本化参数 ----------------
def validate(params):
    if not isinstance(params, dict):
        raise GuardrailError("参数必须是对象")
    bad = set(params) - ALLOWED_KEYS
    if bad:
        raise GuardrailError("不在白名单里的参数：%s（护栏不可改：%s）" % ("、".join(sorted(bad)), "；".join(PROTECTED)))
    for p in ("tactic", "pace"):
        for subj, arms in (params.get(p) or {}).items():
            for arm, ab in arms.items():
                if arm not in PARAMS[p]:
                    raise GuardrailError("未知变体 %s.%s" % (p, arm))
                if not (isinstance(ab, list) and len(ab) == 2 and all(isinstance(v, (int, float)) and 0.5 <= v <= MAX_PARAM for v in ab)):
                    raise GuardrailError("变体参数越界 %s.%s.%s" % (p, subj, arm))
    for k, arms in (params.get("disabled") or {}).items():
        p = k.split("|")[0]
        if p not in PARAMS or set(arms) - set(PARAMS[p]) or len(set(arms)) >= len(PARAMS[p]):
            raise GuardrailError("停用表不合法：%s（至少要留一个变体）" % k)
    for k, v in (params.get("lessons") or {}).items():
        if not (isinstance(v, list) and len(v) == 2 and 0 <= v[1] <= v[0]):
            raise GuardrailError("教学经验统计不合法：" + k)
    if not all(isinstance(i, int) for i in params.get("rules") or []):
        raise GuardrailError("已批准规则必须是 id 列表")
    return True


def _meta(db, key, value=None):
    if value is None:
        r = db.q("SELECT value FROM meta WHERE key=?", (key,), one=True)
        return r["value"] if r else None
    db.x("INSERT INTO meta (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


def log(db, op, detail, version=None, now=None):
    db.x("INSERT INTO evolve_log (ts, version, op, detail) VALUES (?,?,?,?)",
         (now or time.time(), version or active_version(db), op, json.dumps(detail, ensure_ascii=False)))


def ensure(db, now=None):
    if not db.q("SELECT id FROM policy_versions LIMIT 1", one=True):
        vid = db.x("INSERT INTO policy_versions (ts, parent, params, reason, author) VALUES (?,?,?,?,?)",
                   (now or time.time(), None, json.dumps({}), "初始策略：所有变体先验 Beta(1,1)", "system"))
        _meta(db, "policy_version", vid)


def active_version(db):
    v = _meta(db, "policy_version")
    return int(v) if v else None


def params(db, version=None):
    v = version or active_version(db)
    r = db.q("SELECT params FROM policy_versions WHERE id=?", (v,), one=True) if v else None
    return json.loads(r["params"]) if r else {}


def commit(db, new_params, reason, author, now=None):
    """校验 → 存新版本 → 切换为当前版本。参数没变就不建版本。"""
    validate(new_params)
    cur = active_version(db)
    if cur and params(db, cur) == new_params:
        return cur
    vid = db.x("INSERT INTO policy_versions (ts, parent, params, reason, author) VALUES (?,?,?,?,?)",
               (now or time.time(), cur, json.dumps(new_params, ensure_ascii=False, sort_keys=True), reason, author))
    _meta(db, "policy_version", vid)
    log(db, "version", {"from": cur, "to": vid, "reason": reason, "author": author}, vid, now)
    return vid


def rollback(db, version, now=None):
    r = db.q("SELECT * FROM policy_versions WHERE id=?", (int(version),), one=True)
    if not r:
        raise ValueError("没有这个版本")
    p = json.loads(r["params"])
    validate(p)
    cur = active_version(db)
    vid = db.x("INSERT INTO policy_versions (ts, parent, params, reason, author) VALUES (?,?,?,?,?)",
               (now or time.time(), cur, r["params"], "回滚到 v%d" % r["id"], "rollback"))
    _meta(db, "policy_version", vid)
    log(db, "rollback", {"from": cur, "to": vid, "target": r["id"]}, vid, now)
    return vid


# ---------------- Thompson 采样 ----------------
def _arms(p, param, subject):
    got = (p.get(param) or {}).get(subject) or {}
    off = set((p.get("disabled") or {}).get("%s|%s" % (param, subject), []))
    return {a: list(got.get(a, PRIOR)) for a in PARAMS[param] if a not in off}


def _seed(*parts):
    return int(hashlib.sha256("|".join(str(x) for x in parts).encode()).hexdigest()[:12], 16)


def choose(db, session_id, subject, problem="", now=None):
    """按（学生, 学科）选本题的 tactic 与 pace。确定性随机种子（同一会话同一道题同一版本 → 同一选择），写 bandit_log。"""
    ensure(db, now)
    v = active_version(db)
    p = params(db, v)
    subj = subject or "通用"
    out = {"version": v}
    for param in ("tactic", "pace"):
        rng = random.Random(_seed(STUDENT, subj, session_id, problem[:60], v, param))
        best, best_s = None, -1
        for arm, (a, b) in sorted(_arms(p, param, subj).items()):
            s = rng.betavariate(a, b)
            if s > best_s:
                best, best_s = arm, s
        out[param] = best
        db.x("INSERT INTO bandit_log (ts, session_id, student, subject, param, arm, sample, version) VALUES (?,?,?,?,?,?,?,?)",
             (now or time.time(), session_id, STUDENT, subj, param, best, round(best_s, 4), v))
    return out


def prompt_block(arms, lessons=()):
    lines = []
    if arms and arms.get("tactic") in TACTICS:
        lines.append("- 本题追问方式：" + TACTICS[arms["tactic"]][1])
    if arms and arms.get("pace") in PACES:
        lines.append("- 提示推进：" + PACES[arms["pace"]][1] + "（完整解法何时给由服务端决定，与此无关）")
    for l in lessons or []:
        lines.append("- 经验：" + l)
    if not lines:
        return ""
    return "# 本题的教学策略（服务端按以往效果自动选择，只影响怎么问，不改变任何原则）\n" + "\n".join(lines)


# ---------------- 逐轮信号 ----------------
def log_turn(db, session_id, st, out, thought=None, band="", now=None):
    arms = st.get("arms") or {}
    db.x("INSERT INTO turn_log (ts, session_id, subject, topic, band, stuck_type, hint_level, stuck, student_correct, leak, "
         "verify_fix, tactic, pace, thought) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
         (now or time.time(), session_id, st.get("subject") or "", st.get("topic") or "", band,
          out.get("stuck_type") or (thought or {}).get("stuck_type") or "", st.get("hint_level") or 0, st.get("stuck") or 0,
          None if out.get("student_correct") is None else int(bool(out.get("student_correct"))),
          int(bool(out.get("leak_fixed"))), int(bool(out.get("verify_fixed"))), arms.get("tactic"), arms.get("pace"),
          json.dumps(thought or {}, ensure_ascii=False)))


# ---------------- 反思 ----------------
def reward_of(ep):
    if ep["outcome"] == "solved":
        r = SOLVE_REWARD.get(min(3, int(ep["hints"] or 0)), 0.4)
    elif ep["outcome"] == "full":
        r = 0.1
    else:
        r = 0.2
    r -= 0.1 * max(0, int(ep["stuck"] or 0) - 1)
    r -= 0.1 * int(ep["leaks"] or 0)
    if ep.get("p_after") is not None and ep.get("p_before") is not None:
        r += max(-0.1, min(0.1, (ep["p_after"] - ep["p_before"]) * 0.3))
    return round(max(0.0, min(1.0, r)), 3)


class OfflineReflector:
    name = "offline"

    def reflect(self, ep):
        out = {"solved": "自己做对", "full": "看了完整解法", "abandoned": "没做完就换题"}[ep["outcome"]]
        t = TACTICS.get(ep["tactic"], ("—",))[0]
        pc = PACES.get(ep["pace"], ("—",))[0]
        return "%s·%s：用「%s / %s」，%s（%d 层提示、卡住 %d 次%s），奖励 %.2f" % (
            ep["subject"] or "通用", (ep["stuck_type"] or "未识别") + "卡点", t, pc, out, ep["hints"] or 0, ep["stuck"] or 0,
            "、漏题拦截 %d 次" % ep["leaks"] if ep["leaks"] else "", ep["reward"])


class LLMReflector(OfflineReflector):
    """可插拔：接了模型时让模型写一句反思摘要；任何失败都退回离线规则。奖励与统计永远由规则算，模型只写摘要。"""
    name = "llm"

    def __init__(self, chat=None):
        self.chat = chat

    def reflect(self, ep):
        try:
            chat = self.chat
            if chat is None:
                from . import llm
                if not llm.enabled():
                    raise RuntimeError("no model")
                chat = llm.chat
            out = chat([{"role": "user", "content": "用一句不超过 60 字的中文总结这次辅导经验（只总结追问方式是否有效，不写学生身份信息），"
                                                    "只输出 JSON {\"summary\": \"...\"}：\n" + json.dumps(ep, ensure_ascii=False)}])
            s = str((out or {}).get("summary") or "").strip()[:80]
            return s or OfflineReflector.reflect(self, ep)
        except Exception:
            return OfflineReflector.reflect(self, ep)


def default_reflector():
    return LLMReflector() if os.environ.get("LYCEUM_REFLECTOR") == "llm" else OfflineReflector()


def lesson_key(subject, stuck_type, tactic):
    return "%s|%s|%s" % (subject or "通用", stuck_type or "未识别", tactic or "")


def close_episode(db, session_id, st, outcome, p_before=None, p_after=None, reflector=None, now=None):
    """一道题结束 → 写 episode、算奖励、更新 bandit 后验与教学经验、存新策略版本。返回 episode dict。"""
    now = time.time() if now is None else now
    ensure(db, now)
    since = st.get("ep_start") or 0
    turns = db.q("SELECT * FROM turn_log WHERE session_id=? AND ts>=? ORDER BY id", (session_id, since))
    types = [t["stuck_type"] for t in turns if t["stuck_type"]]
    arms = st.get("arms") or {}
    ep = {"session_id": session_id, "problem": (st.get("problem") or "")[:200], "subject": st.get("subject") or "通用",
          "topic": st.get("topic") or "", "stuck_type": max(set(types), key=lambda x: (types.count(x), x)) if types else "",
          "tactic": arms.get("tactic"), "pace": arms.get("pace"), "outcome": outcome, "hints": int(st.get("hint_level") or 0),
          "stuck": int(st.get("stuck") or 0), "turns": len(turns), "leaks": sum(t["leak"] or 0 for t in turns),
          "verify_fixes": sum(t["verify_fix"] or 0 for t in turns), "var_right": 0, "var_total": 0,
          "p_before": p_before, "p_after": p_after}
    ep["reward"] = reward_of(ep)
    rf = reflector or default_reflector()
    ep["summary"] = rf.reflect(dict(ep))
    ep["reflector"] = rf.name
    p = params(db)
    subj = ep["subject"]
    for param in ("tactic", "pace"):
        arm = ep[param]
        if arm in PARAMS[param]:
            _observe(p, param, subj, arm, ep["reward"], 1.0)
    if ep["tactic"]:
        k = lesson_key(subj, ep["stuck_type"], ep["tactic"])
        n, w = (p.setdefault("lessons", {}).get(k) or [0, 0])
        p["lessons"][k] = [n + 1, w + (1 if ep["reward"] >= LESSON_GOOD else 0)]
    _auto_disable(db, p, subj, now)
    vid = commit(db, p, "反思：" + ep["summary"], "reflect", now)
    ep["version"] = vid
    cols = [c for c in ep]
    eid = db.x("INSERT INTO episodes (ts, %s) VALUES (?, %s)" % (", ".join(cols), ", ".join("?" * len(cols))),
               (now, *[ep[c] for c in cols]))
    db.x("UPDATE bandit_log SET episode_id=?, reward=?, weight=1.0 WHERE session_id=? AND episode_id IS NULL",
         (eid, ep["reward"], session_id))
    ep["id"] = eid
    return ep


def _observe(p, param, subj, arm, r, w):
    a, b = (p.setdefault(param, {}).setdefault(subj, {}).get(arm) or list(PRIOR))
    p[param][subj][arm] = [round(min(MAX_PARAM, a + w * r), 4), round(min(MAX_PARAM, b + w * (1 - r)), 4)]


def _auto_disable(db, p, subj, now):
    for param in ("tactic", "pace"):
        arms = (p.get(param) or {}).get(subj) or {}
        key = "%s|%s" % (param, subj)
        off = set((p.get("disabled") or {}).get(key, []))
        stats = {a: (ab[0] / (ab[0] + ab[1]), ab[0] + ab[1] - 2) for a, ab in arms.items() if a not in off}
        seasoned = {a: m for a, (m, n) in stats.items() if n >= DISABLE_MIN_N}
        if len(seasoned) < 2:
            continue
        best = max(seasoned.values())
        for a, m in sorted(seasoned.items()):
            if m < best - DISABLE_GAP and len(off) + 1 < len(PARAMS[param]):
                off.add(a)
                log(db, "disable", {"param": param, "subject": subj, "arm": a, "mean": round(m, 3), "best": round(best, 3)}, now=now)
        if off:
            p.setdefault("disabled", {})[key] = sorted(off)


def variant_feedback(db, session_id, right, total, now=None):
    """变式题批改：给本会话最近一个 episode 补一次观察（权重 0.5），存新版本。没有 episode 返回 None。"""
    if not total:
        return None
    ep = db.q("SELECT * FROM episodes WHERE session_id=? ORDER BY id DESC LIMIT 1", (session_id,), one=True)
    if not ep:
        return None
    acc = right / total
    db.x("UPDATE episodes SET var_right=var_right+?, var_total=var_total+? WHERE id=?", (right, total, ep["id"]))
    p = params(db)
    for param in ("tactic", "pace"):
        if ep[param] in PARAMS[param]:
            _observe(p, param, ep["subject"], ep[param], acc, 0.5)
            db.x("INSERT INTO bandit_log (ts, session_id, student, subject, param, arm, sample, version, episode_id, reward, weight) "
                 "VALUES (?,?,?,?,?,?,?,?,?,?,?)", (now or time.time(), session_id, STUDENT, ep["subject"], param, ep[param], None,
                                                    active_version(db), ep["id"], round(acc, 3), 0.5))
    return commit(db, p, "变式题 %d/%d 补充观察（%s · %s）" % (right, total, ep["subject"], TACTICS.get(ep["tactic"], ("—",))[0]),
                  "reflect", now)


def lessons_for(db, subject, stuck_type="", limit=2):
    """提示词里用的教学经验：本科、优先同卡点类型，样本 ≥3。"""
    p = params(db)
    rows = []
    for k, (n, w) in (p.get("lessons") or {}).items():
        s, t, arm = k.split("|")
        if s != (subject or "通用") or n < LESSON_MIN_N or arm not in TACTICS:
            continue
        rate = w / n
        if rate >= LESSON_GOOD or rate <= 0.3:
            rows.append((0 if t == stuck_type else 1, -n, k, "%s卡点上「%s」%s（%d/%d）" % (
                t, TACTICS[arm][0], "效果好" if rate >= LESSON_GOOD else "效果不好，换别的方式", w, n)))
    rows.sort()
    return [r[3] for r in rows[:limit]]


# ---------------- 候选漏题规则（影子模式） ----------------
_TOKEN = re.compile(r"(?:\([^()]{1,20}\)\s*){2}|[a-zA-Z]\s*=\s*-?\d+(?:\.\d+)?|-?\d+(?:\.\d+)?\s*(?:N|J|W|V|A|Ω|kg|m/s|cm|m|s|g|mol|℃)\b")


def generalize(token):
    """把具体片段泛化成规则：数字 → 任意数，单字母 → 任意字母，加减号 → 任一符号。"""
    t = re.escape(re.sub(r"\s+", "", token))
    t = re.sub(r"\d+(?:\\\.\d+)?", "\x00", t)
    t = t.replace("\\-", "\x01").replace("\\+", "\x01")
    t = re.sub(r"(?<![\\a-zA-Z])[a-zA-Z](?![a-zA-Z])", "[a-zA-Z]", t)
    return t.replace("\x00", r"\d+(?:\.\d+)?").replace("\x01", r"[+\-]?")


def suspect_missed_leak(db, session_id, subject, prev_reply, prev_stage, student_text, problem, now=None):
    """上一轮是提示（没放开完整解法），回复里出现了题目里没有的关键片段，而学生这轮原样抄了它并被判对 → 可能漏拦。
    生成候选规则（影子模式），返回规则 id 或 None。"""
    if not prev_reply or prev_stage in ("full", "redirect"):
        return None
    norm = lambda s: re.sub(r"[\s$]", "", s or "")  # noqa: E731
    for m in _TOKEN.finditer(prev_reply.replace("$", "")):
        tok = norm(m.group(0))
        if len(tok) < 3 or tok in norm(problem) or tok not in norm(student_text):
            continue
        n = db.q("SELECT COUNT(*) AS n FROM candidate_rules", one=True)["n"]
        if n >= MAX_CANDIDATES:
            return None
        pat = generalize(m.group(0))
        try:
            re.compile(pat)
        except re.error:
            continue
        db.x("INSERT OR IGNORE INTO candidate_rules (ts, subject, pattern, example, source, updated) VALUES (?,?,?,?,?,?)",
             (now or time.time(), subject or "通用", pat, tok[:40], json.dumps({"session_id": session_id}), now or time.time()))
        r = db.q("SELECT id FROM candidate_rules WHERE subject=? AND pattern=?", (subject or "通用", pat), one=True)
        log(db, "candidate", {"rule_id": r["id"], "pattern": pat, "example": tok[:40], "status": "shadow"}, now=now)
        return r["id"]
    return None


def shadow_eval(db, subject, reply, stage, allow_full, seen_text, now=None):
    """每条回复都过一遍影子规则：只统计，不拦截。允许给完整解法 / 学生自己写过 → 记误报。"""
    hits = []
    for r in db.q("SELECT * FROM candidate_rules WHERE status='shadow' AND subject IN (?, '通用')", (subject or "通用",)):
        try:
            m = re.search(r["pattern"], (reply or "").replace("$", "").replace(" ", ""))
        except re.error:
            continue
        if not m:
            continue
        fp = allow_full or stage in ("full", "redirect") or m.group(0) in re.sub(r"[\s$]", "", seen_text or "")
        db.x("UPDATE candidate_rules SET hits=hits+1, fp=fp+?, tp=tp+?, updated=? WHERE id=?",
             (int(fp), int(not fp), now or time.time(), r["id"]))
        hits.append(r["id"])
    return hits


def set_rule_status(db, rule_id, status, now=None):
    """人工批准 / 驳回候选规则（批准后作为额外拦截，只会更严）。批准要求影子命中 ≥10 且误报率 ≤10%。"""
    r = db.q("SELECT * FROM candidate_rules WHERE id=?", (rule_id,), one=True)
    if not r or status not in ("approved", "rejected", "shadow"):
        raise ValueError("规则或状态不对")
    if status == "approved" and (r["hits"] < 10 or r["fp"] / max(1, r["hits"]) > 0.1):
        raise GuardrailError("影子模式数据不够（命中 %d、误报率 %.0f%%），不能批准" % (r["hits"], 100 * r["fp"] / max(1, r["hits"])))
    db.x("UPDATE candidate_rules SET status=?, updated=? WHERE id=?", (status, now or time.time(), rule_id))
    p = params(db)
    rules = set(p.get("rules") or [])
    rules = rules | {rule_id} if status == "approved" else rules - {rule_id}
    p["rules"] = sorted(rules)
    return commit(db, p, "规则 #%d → %s" % (rule_id, status), "human", now)


def approved_rules(db):
    ids = params(db).get("rules") or []
    if not ids:
        return []
    return db.q("SELECT id, subject, pattern FROM candidate_rules WHERE id IN (%s)" % ",".join("?" * len(ids)), ids)


def extra_leak(rules, subject, reply):
    """已批准的额外规则（只会多拦，不会少拦）。"""
    t = (reply or "").replace("$", "").replace(" ", "")
    for r in rules or []:
        if r["subject"] in (subject or "通用", "通用"):
            m = re.search(r["pattern"], t)
            if m:
                return m.group(0)
    return ""


# ---------------- 给前端的只读视图 ----------------
def overview(db, limit=12):
    ensure(db)
    v = active_version(db)
    p = params(db, v)
    subjects = sorted(set(p.get("tactic", {})) | set(p.get("pace", {})))
    strat = []
    for s in subjects:
        row = {"subject": s, "params": {}}
        for param in ("tactic", "pace"):
            off = set((p.get("disabled") or {}).get("%s|%s" % (param, s), []))
            arms = []
            for arm, (label, _) in PARAMS[param].items():
                a, b = ((p.get(param) or {}).get(s) or {}).get(arm) or list(PRIOR)
                arms.append({"arm": arm, "label": label, "mean": round(a / (a + b), 3), "n": round(a + b - 2, 1),
                             "disabled": arm in off})
            last = db.q("SELECT arm FROM bandit_log WHERE subject=? AND param=? AND sample IS NOT NULL ORDER BY id DESC LIMIT 1",
                        (s, param), one=True)
            row["params"][param] = {"arms": arms, "current": last["arm"] if last else None}
        strat.append(row)
    lessons = []
    for k, (n, w) in sorted((p.get("lessons") or {}).items(), key=lambda kv: -kv[1][0]):
        s, t, arm = k.split("|")
        lessons.append({"subject": s, "stuck_type": t, "tactic": TACTICS.get(arm, (arm,))[0], "n": n, "wins": w,
                        "rate": round(w / n, 3) if n else 0, "ready": n >= LESSON_MIN_N})
    eps = db.q("SELECT id, ts, subject, topic, stuck_type, tactic, pace, outcome, reward, summary, version, var_right, var_total "
               "FROM episodes ORDER BY id DESC LIMIT ?", (limit,))
    versions = db.q("SELECT id, ts, parent, reason, author FROM policy_versions ORDER BY id DESC LIMIT 20")
    rules = db.q("SELECT id, subject, pattern, example, status, hits, fp, tp, ts FROM candidate_rules ORDER BY id DESC")
    for r in rules:
        r["fp_rate"] = round(r["fp"] / r["hits"], 3) if r["hits"] else None
    return {"version": v, "strategies": strat, "lessons": lessons, "episodes": eps, "versions": versions, "rules": rules,
            "protected": list(PROTECTED), "reflector": default_reflector().name,
            "tactics": {k: v[0] for k, v in TACTICS.items()}, "paces": {k: v[0] for k, v in PACES.items()}}
