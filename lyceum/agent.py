"""小雅的教学策略：意图判断 → 苏格拉底式分步提示 → 卡住 3 次/主动要求后给完整解法 → 变式题与批改。"""
import os
import re
import time

from . import context
from . import evolve
from . import insight
from . import leak as leakmod
from . import llm
from . import mathcheck
from . import models
from . import memory as memmod
from . import prompts
from . import strategies
from . import taxonomy
from .streaming import ReplyExtractor, SentenceGate

GRADES = {i: n for i, n in enumerate(
    ["小学一年级", "小学二年级", "小学三年级", "小学四年级", "小学五年级", "小学六年级",
     "初一（七年级）", "初二（八年级）", "初三（九年级）", "高一", "高二", "高三"], start=1)}
SUBJECTS = list(prompts.SUBJECTS)

STUCK_RE = re.compile(r"(不会|不懂|不知道|想不出|没思路|卡住|看不懂|还是不明白|不明白|算不出|做不出|没头绪|不理解|\?\?|？？)")
FULL_RE = re.compile(r"(完整(的)?(解法|过程|答案|步骤)|直接(告诉|给|说)(我)?(答案|结果)?|告诉我答案|给我答案|看答案|标准答案|答案是(什么|多少)|直接讲)")
STUCK_LIMIT = 3


def band(grade):
    return "primary" if grade <= 6 else ("middle" if grade <= 9 else "high")


def build_prompt(profile, st, allow_full, route=None, text="", extras=None):
    """装配小雅的系统提示词，返回带分节度量的 Build。文本在 prompts.py，这里只算上下文与路由。"""
    g = int(profile.get("grade") or 8)
    if route is None:
        route = strategies.route("", st.get("problem") or "", st.get("subject") or "", band(g))
    strat = strategies.prompt_block(route["subject"], band(g), (st.get("problem") or "") + "\n" + (text or ""))
    tb = profile.get("textbook") or "人教版"
    ex = extras or {}
    extra_blocks = "\n\n".join(b for b in (
        memmod.prompt_block(ex.get("memories"), ex.get("prefs")),
        insight.prompt_block(ex.get("thought")),
        evolve.prompt_block(ex.get("arms"), ex.get("lessons"))) if b)
    state_lines = {
        "problem": st.get("problem") or "（还没有）",
        "hint_level": st.get("hint_level", 0),
        "stuck": st.get("stuck", 0),
        "allow_note": "（只针对当前这道题；如果学生这次发来的是一道新题，这条不适用，按新题从头引导）" if allow_full else "",
    }
    return prompts.build(
        grade=GRADES.get(g, "初二"), textbook=tb, band=band(g), strat=strat,
        taxonomy_block=taxonomy.prompt_block(band(g), route["subject"], focused=True),
        extra_blocks=extra_blocks, state_lines=state_lines, allow_full=allow_full,
        subjects="|".join(SUBJECTS), tail_note=prompts.FOLLOWUP_RULE,
    )


def system_prompt(profile, st, allow_full, route=None, text="", extras=None):
    """系统提示词的最终字符串。"""
    return build_prompt(profile, st, allow_full, route, text, extras).text


def history_messages(msgs, limit=14):
    return context.select_history(msgs, limit)[0]


def _prepare(profile, session, text, image_data_url, action, extras=None):
    st = dict(session.get("state") or {})
    st.setdefault("hint_level", 0)
    st.setdefault("stuck", 0)
    text = (text or "").strip()
    rule_stuck = bool(STUCK_RE.search(text)) or action == "stuck"
    rule_full = bool(FULL_RE.search(text)) or action == "full"
    pre_stuck = st["stuck"] + (1 if rule_stuck and st.get("problem") else 0)
    # 主动要求：至少已经带着想过一步（给过 1 层提示）才给完整解法；卡住 3 次直接给
    allow_full = bool(st.get("problem")) and (pre_stuck >= STUCK_LIMIT or (rule_full and st["hint_level"] >= 1))
    if action == "full" and st.get("problem"):
        allow_full = True
    b = band(int(profile.get("grade") or 8))
    route = strategies.route(text, st.get("problem") or "", st.get("subject") or "", b)
    user_text = text or "（学生只发了一张图片）"
    if action == "hint":
        user_text = (text + "\n" if text else "") + "（学生点了「再给一点提示」）"
    elif action == "stuck":
        user_text = (text + "\n" if text else "") + "（学生点了「我卡住了」）"
    elif action == "full":
        user_text = (text + "\n" if text else "") + "（学生点了「看完整解法」）"
    content = user_text
    if image_data_url:
        content = [{"type": "text", "text": user_text},
                   {"type": "image_url", "image_url": {"url": image_data_url}}]
    return {"st": st, "text": text, "allow_full": allow_full, "rule_stuck": rule_stuck, "band": b, "route": route,
            "content": content, "vision": bool(image_data_url), "extras": extras or {},
            "task": models.route_task(bool(image_data_url), action, text, allow_full)}


def _messages(ctx, profile, history):
    selected, stats = context.select_history(history)
    ctx["context_usage"] = stats
    msgs = [{"role": "system", "content": system_prompt(profile, ctx["st"], ctx["allow_full"], ctx["route"], ctx["text"],
                                                        ctx.get("extras"))}]
    if stats["history_omitted_messages"]:
        msgs[0]["content"] += "\n# 历史范围\n" + context.OMITTED_NOTICE
    msgs += selected
    msgs.append({"role": "user", "content": ctx["content"]})
    return msgs


def strategy_of(ctx, out=None):
    """本轮实际采用的策略：模型返回的 subject 优先，没有就用发请求前路由出的学科。"""
    st, b = ctx["st"], ctx["band"]
    r = strategies.route(ctx["text"], st.get("problem") or "", st.get("subject") or "", b,
                         (out or {}).get("subject") or "")
    if r["source"] != "model":
        r = ctx["route"]
    prob = (out or {}).get("problem") or st.get("problem") or ""
    return strategies.public(r, b, prob + "\n" + ctx["text"])


def _rewrite(ctx, msgs, out, leak, profile):
    """漏题：让模型按同样格式重写一次；还漏就换该科固定引导句。"""
    st, text = ctx["st"], ctx["text"]
    ctx["repair_calls"] = ctx.get("repair_calls", 0) + 1
    fix = {"role": "system", "content": f"你上一版回复直接写出了关键结果「{leak}」，违反了「提示不得直接给出关键中间结果 / 答案」。"
           "请按同样的 JSON 格式重写 reply：只说该做什么、怎么想，用一个小问题让学生自己写出这一步，不要出现这个结果，也不要给最终答案。"}
    out2 = normalize(llm.chat(context.repair_messages(msgs, out["reply"], fix), vision=ctx["vision"], task=ctx["task"]))
    if not out2.get("subject"):
        out2["subject"] = out.get("subject")
    if leak_of(ctx, out2):
        out2["reply"] = strategies.fallback(out2.get("subject") or st.get("subject") or ctx["route"]["subject"])
        out2.update(stage="hint", solved=False, student_correct=None)
    out2["leak_fixed"] = True
    out2["leak"] = leak
    canon_topic(out2, profile)
    return out2


def respond(profile, session, history, text, image_data_url=None, action=None, extras=None):
    """返回 (reply_dict, new_state)。action: hint|stuck|full|None（来自界面按钮）。非流式。
    extras（可选，服务端从数据库算好）：memories / prefs / thought / arms / lessons / rules。"""
    ctx = _prepare(profile, session, text, image_data_url, action, extras)
    if not llm.enabled():
        return _attach(ctx, mock_reply(ctx["st"], ctx["text"], ctx["allow_full"], ctx["rule_stuck"], ctx), ctx["st"]), ctx["st"]
    msgs = _messages(ctx, profile, history)
    out = normalize(llm.chat(msgs, vision=ctx["vision"], task=ctx["task"]))
    canon_topic(out, profile)
    # ---- 服务端闸门：提示里不许直接摆出关键中间结果（第 3 层或允许完整解法时放开）
    if not ctx["allow_full"]:
        leak = leak_of(ctx, out)
        if leak:
            out = _rewrite(ctx, msgs, out, leak, profile)
    # ---- 数学确定性校验：起草 → 验证 → 修正一次 → 仍不一致则改判
    verdict = verify_math(ctx, out)
    if verdict is not None:
        out = _verify_fix(ctx, msgs, out, verdict, profile)
    return _finish(ctx, out)


MOCK_DELAY = float(os.environ.get("LYCEUM_MOCK_DELAY", "0.04"))


def mock_chunks(text):
    """离线演示的「流式」：按字切成 1–3 字一块（确定性）。"""
    i, k, out = 0, 0, []
    while i < len(text):
        n = k % 3 + 1
        out.append(text[i:i + n])
        i += n
        k += 1
    return out


def respond_stream(profile, session, history, text, image_data_url=None, action=None, emit=None, delay=None, extras=None):
    """流式版：通过 emit(event, data) 发 meta / delta / status / replace，返回 (reply_dict, new_state)。
    done / error 由调用方（server）发。漏题协调：
      - 只有服务端允许完整解法时，reply 才逐块直接转发；模型 stage 不授予权限；
      - 其余回复进 SentenceGate，整句过 find_leak 才放行；
        一旦命中就停止转发（继续把上游读完拿到完整 JSON），发 status=revising，重写 / 兜底后发 replace 整条替换。"""
    emit = emit or (lambda e, d: None)
    ctx = _prepare(profile, session, text, image_data_url, action, extras)
    st = ctx["st"]
    emit("meta", {"strategy": strategy_of(ctx), "allow_full": ctx["allow_full"]})
    if not llm.enabled():
        out = _attach(ctx, mock_reply(st, ctx["text"], ctx["allow_full"], ctx["rule_stuck"], ctx), st)
        d = MOCK_DELAY if delay is None else delay
        for piece in mock_chunks(out["reply"]):
            emit("delta", {"text": piece})
            if d:
                time.sleep(d)
        return out, st
    msgs = _messages(ctx, profile, history)
    ext, gate, held = ReplyExtractor(), None, False

    def check(t):
        meta = dict(ext.meta)
        meta["reply"] = t
        return leak_of(ctx, meta)

    for chunk in llm.chat_stream(msgs, vision=ctx["vision"], task=ctx["task"]):
        new = ext.feed(chunk)
        if not new:
            continue
        if gate is None:
            gate = SentenceGate(check, direct=ctx["allow_full"])
        piece = gate.feed(new)
        if piece:
            emit("delta", {"text": piece})
        if gate.leak and not held:
            held = True
            emit("status", {"state": "revising"})
    out = normalize(llm.parse_json(ext.raw))
    canon_topic(out, profile)
    if gate is None:                       # 没解出 reply 字段：整段过一遍闸门
        gate = SentenceGate(check, direct=ctx["allow_full"])
        ext.meta = {k: out.get(k) for k in ("subject", "stage", "hint_level", "student_correct")}
        piece = gate.feed(out["reply"])
        if piece:
            emit("delta", {"text": piece})
    if not gate.leak:
        piece = gate.flush()
        if piece:
            emit("delta", {"text": piece})
    leak = gate.leak or ("" if ctx["allow_full"] else leak_of(ctx, out))
    if leak:
        if not held:
            emit("status", {"state": "revising"})
        out = _rewrite(ctx, msgs, out, leak, profile)
        emit("replace", {"text": out["reply"], "reason": "leak"})
    elif gate.released != out["reply"]:
        emit("replace", {"text": out["reply"], "reason": "sync"})
    verdict = verify_math(ctx, out)
    if verdict is not None:
        emit("status", {"state": "verifying"})
        out = _verify_fix(ctx, msgs, out, verdict, profile)
        emit("replace", {"text": out["reply"], "reason": "verify"})
    return _finish(ctx, out)


def _finish(ctx, out):
    st, text = ctx["st"], ctx["text"]
    rule_stuck, allow_full = ctx["rule_stuck"], ctx["allow_full"]
    if not allow_full and out.get("stage") == "full":
        out.update(stage="hint", solved=False)
    strategy = strategy_of(ctx, out)
    # ---- 更新状态
    intent = out["intent"]
    if intent == "new_problem" or (out["problem"] and out["problem"] != st.get("problem") and intent not in ("answer_attempt", "stuck", "ask_hint", "ask_full")):
        st = {"problem": out["problem"], "hint_level": 0, "stuck": 0, "full_given": False,
              "subject": out["subject"], "topic": out["topic"]}
    elif out["problem"] and not st.get("problem"):
        st["problem"] = out["problem"]
    if out["subject"]:
        st["subject"] = out["subject"]
    if out["topic"] and not st.get("topic"):
        st["topic"] = out["topic"]  # 同一道题的知识点保持不变，便于错题本归类
    if intent in ("stuck",) or (rule_stuck and intent not in ("new_problem",)):
        st["stuck"] = st.get("stuck", 0) + 1
    if out["student_correct"] is True:
        st["stuck"] = 0
    st["hint_level"] = max(st.get("hint_level", 0), out["hint_level"] or 0)
    if out["stage"] == "full":
        st["full_given"] = True
    if out["solved"]:
        st["solved"] = True
    st["strategy"] = strategy
    _attach(ctx, out, st)
    out["allow_full"] = allow_full
    out["strategy"] = strategy
    out["state"] = {k: st.get(k) for k in STATE_KEYS}
    return out, st


def _attach(ctx, out, st):
    """把服务端答前算好的推断与策略变体记到本轮结果 / 会话状态上（离线演示也走这里）。"""
    ex = ctx.get("extras") or {}
    if ctx.get("context_usage"):
        out["context_usage"] = dict(ctx["context_usage"])
    if ex.get("thought") is not None:
        out["thought"] = ex["thought"]
    if ex.get("arms"):
        st["arms"] = {k: ex["arms"].get(k) for k in ("tactic", "pace", "version")}
    return out


STATE_KEYS = ("hint_level", "stuck", "solved", "full_given", "subject", "topic", "strategy")


def canon_topic(out, profile):
    """模型给的知识点标签 → 规范名（同科才合并；匹配不到保留原标签，标「未归类」）。原标签留在 topic_raw。"""
    raw = out.get("topic") or ""
    r = taxonomy.resolve(out.get("subject") or "其他", raw, taxonomy.band_of_grade(profile.get("grade") or 8))
    out["topic_raw"], out["topic"], out["topic_matched"] = raw, r["topic"], r["matched"]
    return out


# ---------------- 「关键中间结果」检测（规则见 leak.py） ----------------
SAFE_HINT = strategies.STRATEGIES["数学"]["fallback"]
_PRODUCT_RE, _FINAL_RE, _norm = leakmod._PRODUCT_RE, leakmod._FINAL_RE, leakmod._norm


def find_leak(out, st, student_text):
    """按学科规则族检测：数学（乘积式 / 最终答案）、物理（数值+单位）、化学（配平结果 / 数值+单位）、英语（完整句子）；
    语文与文科只靠提示词，返回空串。"""
    return leakmod.find_leak(out, st, student_text)


def leak_of(ctx, out):
    """核心漏题规则（leak.py，护栏）+ 人工批准过的额外规则（只会多拦）。"""
    if ctx["allow_full"]:
        return ""
    # Stage is model content, not permission. Never let full/redirect skip policy.
    checked = dict(out)
    if checked.get("stage") in ("full", "redirect"):
        checked["stage"] = "hint"
        checked["student_correct"] = None
    hit = find_leak(checked, ctx["st"], ctx["text"])
    if hit:
        return hit
    rules = (ctx.get("extras") or {}).get("rules")
    if rules:
        seen = (ctx["st"].get("problem") or "") + (ctx["text"] or "")
        h = evolve.extra_leak(rules, out.get("subject") or ctx["st"].get("subject"), out.get("reply"))
        if h and h not in seen.replace(" ", "").replace("$", ""):
            return h
    return ""


# ---------------- 数学确定性校验（思路：socratic-math-tutor 起草→验证→修正；实现见 mathcheck.py） ----------------
_ANSWER_LIKE = re.compile(r"[a-zA-Z]\s*[=＝]\s*-?\s*\d|^\s*-?\d+(?:\.\d+)?(?:\s*/\s*\d+)?\s*(?:[,，、或和]\s*-?\d+(?:\.\d+)?)*\s*$")


def verify_math(ctx, out):
    """数学题：学生本轮写了 x=… 这样的答案，把它代回题干里的方程。返回 True / False（确定）或 None（判不了 / 不需要）。
    只在模型的判断和确定性结论不一致（或模型没判）时才返回结论，交给 _verify_fix。"""
    st, text = ctx["st"], ctx["text"] or ""
    subj = out.get("subject") or st.get("subject") or ""
    if strategies.canonical(subj) not in ("数学", "") or out.get("stage") == "full" or ctx["allow_full"]:
        return None
    problem = st.get("problem") or out.get("problem") or ""
    if not problem or problem.strip() == text.strip() or not _ANSWER_LIKE.search(text):
        return None
    v = mathcheck.check_roots(problem, text)
    if v is None:
        return None
    sc = out.get("student_correct")
    if sc is v:
        return None
    if sc is None and out.get("intent") not in ("answer_attempt", "ask_hint", "stuck", "chitchat"):
        return None
    return v


VERIFY_RIGHT = "我把你的答案代回原方程检验了一下：两边相等，你算对了！说说你是怎么想到这一步的？"
VERIFY_WRONG = "我把你的答案代回原方程检验了一下，两边不相等。别急，把你的过程一步步写给我，我们找找是哪一步出了问题？"


def _verify_fix(ctx, msgs, out, verdict, profile):
    """修正一次：把确定性结论告诉模型，让它按同样 JSON 重写；还不一致就直接改判并换固定句（有界：最多 1 次）。"""
    out = dict(out)
    if llm.enabled() and ctx.get("repair_calls", 0) < 1:
        ctx["repair_calls"] = ctx.get("repair_calls", 0) + 1
        fix = {"role": "system", "content": "确定性校验（把学生的答案代回原方程精确计算）：学生的答案%s。"
               "请据此按同样的 JSON 格式重写，student_correct 填 %s；答错时不要给出正确结果，引导他自己找错。" %
               ("正确" if verdict else "不正确", "true" if verdict else "false")}
        try:
            out2 = normalize(llm.chat(context.repair_messages(msgs, out["reply"], fix), vision=ctx["vision"], task=ctx["task"]))
            out2["subject"] = out2.get("subject") or out.get("subject")
            canon_topic(out2, profile)
            if out2.get("student_correct") is verdict and not leak_of(ctx, out2):
                out2["verify_fixed"] = "revised"
                return out2
        except llm.LLMError:
            pass
    out["student_correct"] = verdict
    out["solved"] = bool(verdict)
    out["stage"] = "solved" if verdict else "check"
    out["reply"] = VERIFY_RIGHT if verdict else VERIFY_WRONG
    if not verdict and not out.get("stuck_type"):
        out["stuck_type"] = "计算"
    out["verify_fixed"] = "overridden"
    return out


def normalize(o):
    o = o if isinstance(o, dict) else {"reply": str(o)}
    subj = o.get("subject") or ""
    if subj not in SUBJECTS and strategies.canonical(subj):
        subj = strategies.canonical(subj)
    if subj not in SUBJECTS:
        subj = next((s for s in SUBJECTS if s and s in subj), "其他" if subj else "")
    try:
        hl = int(o.get("hint_level") or 0)
    except Exception:
        hl = 0
    sc = o.get("student_correct")
    if isinstance(sc, str):
        sc = {"true": True, "false": False}.get(sc.lower())
    return {
        "subject": subj, "topic": (o.get("topic") or "")[:20], "intent": o.get("intent") or "chitchat",
        "problem": o.get("problem") or "", "stage": o.get("stage") or "hint",
        "hint_level": max(0, min(3, hl)), "student_correct": sc,
        "solved": bool(o.get("solved")) and o.get("solved") not in ("false",),
        "reply": o.get("reply") or "我没听清，可以再说一遍吗？",
        "stuck_type": o.get("stuck_type") if o.get("stuck_type") in insight.TYPES else "",
        "misconception": insight.clean_misconception(o.get("misconception") or "") if sc is False else "",
    }


# ---------------- 变式题与批改 ----------------
def make_variants(profile, st, n=3):
    g = int(profile.get("grade") or 8)
    problem = st.get("problem") or ""
    if not llm.enabled():
        return mock_variants(st)
    prompt = f"""你是中小学出题老师。学生：{GRADES.get(g)}，教材：{profile.get('textbook') or '人教版'}。
刚讲完的题：{problem}
学科：{st.get('subject')}；知识点：{st.get('topic')}
请出 {n} 道「变式题」：考同一个知识点和方法，但换数字、换情境或换问法，难度从和原题相当到稍难一点。每道题必须有唯一、明确、简短的标准答案（数字、表达式、词语或一句话），便于批改；不要出需要画图或长篇论述的题。公式用 LaTeX（$...$）。
只输出 JSON：{{"questions": [{{"q": "题干", "answer": "标准答案", "explain": "两三句话的解析"}}]}}"""
    out = llm.chat([{"role": "user", "content": prompt}], temperature=0.7, task="strong")
    qs = [q for q in (out.get("questions") or []) if isinstance(q, dict) and q.get("q")]
    # 验证：标准答案代回题干方程，不成立的题丢掉（起草 → 验证 → 过滤）
    qs = [q for q in qs if mathcheck.check_roots(q["q"], str(q.get("answer", ""))) is not False]
    return qs[:n]


def deterministic_grade(q, a):
    """能确定性判就判：方程的根 / 与标准答案的数值集合或恒等式比较。返回 True / False / None。"""
    if not (a or "").strip():
        return False
    return mathcheck.verify_answer(q.get("q") or "", a, str(q.get("answer") or ""))


def grade_answers(profile, st, questions, answers):
    answers = list(answers or [])[:len(questions)]
    answers += [""] * (len(questions) - len(answers))
    det = [deterministic_grade(q, a) for q, a in zip(questions, answers)]
    if len(det) == len(questions) and all(d is not None for d in det):
        return [{"correct": d, "feedback": "代回检验：答案正确。" if d else "代回检验：这个答案不满足题目，请检查过程。",
                 "checked": True} for d in det]
    if not llm.enabled():
        return [{"correct": d if d is not None else (a or "").strip() == str(q.get("answer", "")).strip(),
                 "feedback": "（代回检验）" if d is not None else "（演示模式按字面比对）", "checked": d is not None}
                for q, a, d in zip(questions, answers, det)]
    unknown = [i for i, d in enumerate(det) if d is None]
    items = "\n".join(f"{j+1}. 题目：{questions[i]['q']}\n   标准答案：{questions[i]['answer']}\n   学生答案：{answers[i] or '（空）'}"
                      for j, i in enumerate(unknown))
    prompt = f"""你在批改{GRADES.get(int(profile.get('grade') or 8))}学生的练习。判断每道题学生答案是否正确：数值相等、等价表达式、同义表述都算对；空白或只写过程没写结果算错。反馈要具体、简短（一两句），错了指出错在哪，用 LaTeX 写公式。
{items}
只输出 JSON：{{"results": [{{"correct": true/false, "feedback": "..."}}]}}，顺序与题目一致。"""
    out = llm.chat([{"role": "user", "content": prompt}], temperature=0.1, task="strong")
    res = out.get("results") if isinstance(out, dict) else None
    if (not isinstance(res, list) or len(res) != len(unknown)
            or any(not isinstance(r, dict) or type(r.get("correct")) is not bool for r in res)):
        raise llm.LLMError("批改结果不完整或格式错误；未记录对错，请重试。")
    by_index = dict(zip(unknown, res))
    fixed = []
    for i, d in enumerate(det):
        if d is not None:
            fixed.append({"correct": d, "feedback": "代回检验：答案正确。" if d else "代回检验：这个答案不满足题目，请检查过程。",
                          "checked": True})
        else:
            r = by_index.get(i)
            r = r if isinstance(r, dict) else {"correct": False, "feedback": "这题没批出来，再试一次。"}
            fixed.append({"correct": bool(r.get("correct")), "feedback": r.get("feedback") or "", "checked": False})
    return fixed


# ---------------- 离线演示（没有配置 key 时） ----------------
def mock_reply(st, text, allow_full, stuck, ctx=None):
    route = (ctx or {}).get("route") or strategies.route(text, st.get("problem") or "", st.get("subject") or "")
    b = (ctx or {}).get("band") or "middle"
    if not st.get("problem"):
        subj = route["subject"] if route["subject"] != "通用" else "数学"
        sg = strategies.get(subj, b, text)
        tr = taxonomy.resolve(subj, re.sub(r"[\s$0-9=+\-^*/()a-zA-Z，。,.!?？！]", "", text)[:24], b)
        st.update({"problem": text[:120], "subject": subj, "topic": tr["topic"] if tr["matched"] else "演示模式", "hint_level": 1})
        reply = (f"（演示模式：还没配置模型 key，下面是按「{sg['label'] or subj}」引导方式写的示例回复）\n\n{sg['demo']}\n\n"
                 f"一时想不出也没关系，先回答这个小问题：{sg['stuck'][0][1]}")
    elif allow_full:
        st["full_given"] = True
        reply = "（演示模式）这里会给出完整的分步解法。"
    elif (st.get("subject") in ("数学", None, "") and _ANSWER_LIKE.search(text or "")
          and mathcheck.check_roots(st.get("problem") or "", text) is not None):
        ok = mathcheck.check_roots(st.get("problem") or "", text)
        reply = "（演示模式 · 代回检验）" + (VERIFY_RIGHT if ok else VERIFY_WRONG)
        if ok:
            st["solved"] = True
        strategy = strategies.public(strategies.route("", st.get("problem") or "", st.get("subject") or "", b), b, st.get("problem") or "")
        st["strategy"] = strategy
        return {"subject": st.get("subject"), "topic": st.get("topic"), "intent": "answer_attempt", "problem": st.get("problem"),
                "stage": "solved" if ok else "check", "hint_level": st.get("hint_level", 0), "student_correct": ok,
                "solved": ok, "reply": reply, "allow_full": False, "strategy": strategy, "stuck_type": "" if ok else "计算",
                "misconception": "", "verify_fixed": "offline", "state": {k: st.get(k) for k in STATE_KEYS}}
    else:
        if stuck:
            st["stuck"] = st.get("stuck", 0) + 1
        st["hint_level"] = min(3, st.get("hint_level", 0) + 1)
        sg = strategies.get(st.get("subject") or "通用", b)
        q = sg["stuck"][st["hint_level"] % len(sg["stuck"])][1]
        reply = f"（演示模式）提示 {st['hint_level']}：{q}"
    strategy = strategies.public(strategies.route("", st.get("problem") or "", st.get("subject") or "", b), b,
                                 (st.get("problem") or "") + "\n" + (text or ""))
    st["strategy"] = strategy
    return {"subject": st.get("subject"), "topic": st.get("topic"), "intent": "ask_hint", "problem": st.get("problem"),
            "stage": "full" if allow_full else "hint", "hint_level": st.get("hint_level", 0), "student_correct": None,
            "solved": allow_full, "reply": reply, "allow_full": allow_full, "strategy": strategy,
            "stuck_type": insight.classify(text)[0] if stuck else "", "misconception": "",
            "state": {k: st.get(k) for k in STATE_KEYS}}


def mock_variants(st):
    return [{"q": "（演示）解方程 $x^2-7x+12=0$", "answer": "x=3 或 x=4", "explain": "因式分解为 $(x-3)(x-4)=0$。"},
            {"q": "（演示）解方程 $x^2+x-6=0$", "answer": "x=2 或 x=-3", "explain": "$(x-2)(x+3)=0$。"}]
