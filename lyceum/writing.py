"""写作分项评分：先把「能确定判的」判掉，再让模型只碰它擅长的部分。

为什么这样切
  作文/英语写作不能像数学题那样对答案，但也不是只能交给模型拍脑袋：
  篇幅、段落、句长、过渡词、标点这些**形式维度**可以确定性计算，而且能给出证据
  （「第 3 段只有 1 句」比「结构 3 分」有用得多）。内容是否切题、语言是否地道，
  才需要模型或人来判。

所以每个维度都带 `source`：
  - `rule`  —— 规则算出，可复现、可单测；
  - `model` —— 模型打分，必须显式开启，且带理由；
  - `human` —— 预留，给以后的教师校准。

总分只汇总**已评的维度**，并在 `coverage` 里说清楚这次只覆盖了哪一层。
不把形式分包装成「作文总分」。
"""
import re

CJK = re.compile(r"[\u4e00-\u9fff]")
WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")
SENT_SPLIT = re.compile(r"[.!?。！？；;]+")
PARA_SPLIT = re.compile(r"\n\s*\n|\n")

EN_CONNECTIVES = [
    "however", "therefore", "because", "although", "moreover", "furthermore", "in addition",
    "for example", "for instance", "on the other hand", "as a result", "first", "second",
    "finally", "besides", "meanwhile", "in conclusion", "what is more", "instead", "otherwise",
]
ZH_CONNECTIVES = [
    "因此", "所以", "然而", "但是", "首先", "其次", "然后", "接着", "最后", "总之", "此外",
    "不仅", "而且", "虽然", "尽管", "例如", "比如", "由此可见", "另一方面", "与此同时", "反过来",
]

TARGET = {
    "英语": {"primary": 40, "middle": 80, "high": 120},
    "语文": {"primary": 300, "middle": 600, "high": 800},
}


def _sentences(text):
    return [s.strip() for s in SENT_SPLIT.split(text) if s.strip()]


def features(text, subject):
    text = str(text or "")
    paras = [p.strip() for p in PARA_SPLIT.split(text) if p.strip()]
    sents = _sentences(text)
    if subject == "英语":
        words = WORD.findall(text)
        units = len(words)
        conn = sum(len(re.findall(r"\b" + re.escape(c) + r"\b", text, re.I)) for c in EN_CONNECTIVES)
        avg = round(len(words) / len(sents), 1) if sents else 0.0
        lengths = [len(WORD.findall(s)) for s in sents] or [0]
        punct = len(set(ch for ch in text if ch in ".,!?;:'\"-"))
    else:
        units = len(CJK.findall(text))
        conn = sum(text.count(c) for c in ZH_CONNECTIVES)
        avg = round(units / len(sents), 1) if sents else 0.0
        lengths = [len(CJK.findall(s)) for s in sents] or [0]
        punct = len(set(ch for ch in text if ch in "，。！？；：、“”‘’（）—…"))
    mean = sum(lengths) / len(lengths)
    var = sum((x - mean) ** 2 for x in lengths) / len(lengths)
    return {"units": units, "sentences": len(sents), "paragraphs": len(paras),
            "avg_sentence": avg, "sentence_sd": round(var ** 0.5, 1), "connectives": conn,
            "punct_kinds": punct, "chars": len(text)}


def _score_length(f, target):
    if target <= 0:
        return 0, "篇幅目标未设置"
    ratio = f["units"] / target
    if ratio >= 0.9:
        return 25, "%s 达到目标的 %d%%" % (f["units"], round(ratio * 100))
    if ratio >= 0.7:
        return 18, "%s 只到目标的 %d%%，还差一点" % (f["units"], round(ratio * 100))
    if ratio >= 0.5:
        return 12, "%s 只有目标的 %d%%，明显偏短" % (f["units"], round(ratio * 100))
    return max(0, round(ratio * 20)), "%s 远低于目标（%d%%）" % (f["units"], round(ratio * 100))


def _score_structure(f):
    if not f["sentences"]:
        return 0, "没有成形的段落"
    if f["paragraphs"] >= 3 and f["sentences"] >= f["paragraphs"] * 2:
        return 25, "%d 段，平均每段 %.1f 句" % (f["paragraphs"], f["sentences"] / f["paragraphs"])
    if f["paragraphs"] == 2:
        return 16, "只有 2 段，缺少结尾或开头"
    if f["paragraphs"] <= 1 and f["sentences"] >= 3:
        return 10, "整篇一段，没有分段"
    return 6, "只有 %d 段、%d 句，结构还没成形" % (f["paragraphs"], f["sentences"])


def _score_cohesion(f):
    if not f["units"]:
        return 0, "没有内容"
    per100 = f["connectives"] / f["units"] * 100
    if f["connectives"] >= 4 and per100 >= 1.5:
        return 25, "过渡词 %d 处（每百词约 %.1f 处）" % (f["connectives"], per100)
    if f["connectives"] >= 2:
        return 16, "过渡词只用了 %d 处，句子之间还比较跳" % f["connectives"]
    if f["connectives"] == 1:
        return 9, "只有 1 处过渡，几乎靠句子硬接"
    return 0, "没有任何过渡词"


def _score_sentence(f, subject):
    if not f["sentences"]:
        return 0, "没有句子"
    lo, hi = (8, 22) if subject == "英语" else (12, 45)
    avg, sd = f["avg_sentence"], f["sentence_sd"]
    if lo <= avg <= hi and (sd >= 2.5 or f["sentences"] < 3):
        return 25, "平均句长 %.1f，长短有变化（标准差 %.1f）" % (avg, sd)
    if lo <= avg <= hi:
        return 18, "平均句长 %.1f，但句子长短太齐（标准差 %.1f）" % (avg, sd)
    if avg < lo:
        return 12, "平均句长只有 %.1f，句子偏碎" % avg
    return 10, "平均句长 %.1f，长句偏多，读起来吃力" % avg


def rule_dimensions(text, subject, band):
    f = features(text, subject)
    target = TARGET.get(subject, {}).get(band, 80)
    specs = [
        ("length", "篇幅", _score_length(f, target)),
        ("structure", "结构", _score_structure(f)),
        ("cohesion", "连贯", _score_cohesion(f)),
        ("sentence", "句式", _score_sentence(f, subject)),
    ]
    dims = [{"key": k, "name": n, "score": s, "max": 25, "source": "rule", "evidence": e}
            for k, n, (s, e) in specs]
    return dims, f


MODEL_PROMPT = """你是资深{subject}教研员。请只按下面两个维度给这篇{band}学生作文打分，各 25 分制。
维度：{dims}
要求：
1) 只输出 JSON：{{"dims":[{{"key":"...","score":数字,"reason":"不超过 40 字的具体理由"}}]}}
2) 理由必须指向文本里的具体位置或问题，不要写「语言优美」这类空话。
3) 拿不准就给中间分，不要为了鼓励抬分。

题目：{task}
作文：
{text}"""

MODEL_DIMS = {
    "英语": [("content", "内容切题"), ("language", "语言质量")],
    "语文": [("content", "内容立意"), ("language", "语言表达")],
}


def model_dimensions(text, subject, band, task="", chat=None):
    """让模型评内容/语言两个维度。未启用或解析失败返回 (None, 原因)。"""
    if chat is None:
        from . import llm
        chat = llm.chat
    dims = MODEL_DIMS.get(subject, [])
    names = "、".join("%s(%s)" % (n, k) for k, n in dims)
    prompt = MODEL_PROMPT.format(subject=subject, band=band, dims=names, task=task or "（未提供）", text=text)
    try:
        raw = chat([{"role": "user", "content": prompt}], task="strong", json_mode=True, temperature=0.2, max_tokens=600)
        import json
        data = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(data, dict):
            return None, "模型返回的不是对象"
        out = []
        for key, name in dims:
            hit = next((d for d in data.get("dims", []) if d.get("key") == key), None)
            if not hit:
                continue
            score = max(0, min(25, int(round(float(hit.get("score", 0))))))
            out.append({"key": key, "name": name, "score": score, "max": 25, "source": "model",
                        "evidence": str(hit.get("reason", ""))[:120]})
        if len(out) != len(dims):
            return None, "模型返回的维度不完整"
        return out, ""
    except Exception as exc:
        return None, "模型评分失败：%s" % str(exc)[:80]


SEMANTIC_PROMPT = """你是{subject}教研员。判断下面这篇{band}学生的作文是否在写题目要求的内容。

题目：{task}

作文：
{text}

只输出 JSON，不要任何解释：
{{"verdict":"on_topic|partial|off_topic","evidence":"作文里的一句原话，逐字摘录，不超过40字","reason":"不超过30字，说明判断依据"}}

判定标准：
- on_topic：正面回应了题目的要求；
- partial：沾边，但没写到题目要求的重点；
- off_topic：主要内容写的是别的题目或话题。
规则：
1) evidence 必须从作文里原样复制，不得改写、不得引用题目里的句子。
2) 拿不准时给 partial，不要猜。
3) reason 指向文本，不写“语言优美”这类空话。
"""

VERDICT_SCORE = {"off_topic": (0, 8), "partial": (9, 17), "on_topic": (18, 25)}
VERDICT_LABEL = {"on_topic": "切题", "partial": "部分切题", "off_topic": "偏题"}


def _same_text(quote, text):
    """证据必须是原文。模型常改标点或空格，所以先严格比，再忽略空白和标点比一次。"""
    quote = str(quote or "").strip()
    if not quote:
        return False
    if quote in text:
        return True
    squeeze = lambda s: re.sub(r"[\s\W_]+", "", s)
    q, t = squeeze(quote), squeeze(text)
    return bool(q) and q in t


def semantic_topic(text, task="", subject="语文", band="middle", chat=None):
    """让模型判断「是否切题」，并且要求它给出原文证据。

    切题是语义判断，规则算不出来；但模型可以编造，所以这里做三道闸：
      1) 判定只能是三个枚举值；
      2) evidence 必须是原文（忽略标点/空白后仍要能对上），否则整条作废；
      3) 分数锁在判定对应的区间里（off_topic ≤8、partial 9–17、on_topic ≥18）。
    任何一道不过，返回 (None, 原因)，由调用方降级成「未评估」，绝不冒充评过。
    """
    import json
    text = str(text or "").strip()
    task = str(task or "").strip()
    if not text:
        return None, "没有内容可判切题"
    if not task:
        return None, "没有题目，无法判断是否切题"
    if chat is None:
        from . import llm
        chat = llm.chat
    prompt = SEMANTIC_PROMPT.format(subject=subject, band=band, task=task, text=text)
    try:
        raw = chat([{"role": "user", "content": prompt}], task="strong", json_mode=True,
                   temperature=0.0, max_tokens=320)
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception as exc:
        return None, "切题判断失败：%s" % str(exc)[:80]
    if not isinstance(data, dict):
        return None, "切题判断返回的不是对象"
    verdict = str(data.get("verdict", "")).strip()
    if verdict not in VERDICT_SCORE:
        return None, "切题判断的结论不可识别"
    evidence = str(data.get("evidence", "")).strip()
    if not _same_text(evidence, text):
        return None, "切题判断的证据不是原文摘录"
    lo, hi = VERDICT_SCORE[verdict]
    try:
        score = int(round(float(data.get("score", (lo + hi) / 2))))
    except (TypeError, ValueError):
        score = (lo + hi) // 2
    score = max(lo, min(hi, score))
    return {"key": "topic", "name": "切题", "score": score, "max": 25, "source": "model",
            "verdict": verdict, "label": VERDICT_LABEL[verdict],
            "evidence": evidence[:120], "reason": str(data.get("reason", ""))[:80]}, ""


TIME_WORDS = ["去年", "今年", "那天", "那天", "第一次", "小时候", "上个月", "周末", "放学", "中午",
              "晚上", "清晨", "暑假", "寒假", "昨天", "当时", "后来"]
FEELING_WORDS = ["我觉得", "我发现", "我明白", "让我", "我意识到", "收获", "感受到", "心里想", "我才知道"]


STOP_CHARS = set("的了在是我你他她它和与就都也又很把被给让对从到这那有个着过吗呢吧啊")


def shared_phrases(task, text, minlen=2, limit=4):
    """题目与正文共有的**最长**片段（按长度排序）。

    用二元组交集会产生「次难」「忘的」这类碎片；改为最长公共子串，
    给出的是「一次难忘的经历」这种可读的呼应，而不是噪音。
    """
    from difflib import SequenceMatcher
    a = "".join(c for c in str(task or "") if CJK.match(c))
    b = "".join(c for c in str(text or "") if CJK.match(c))
    if not a or not b:
        return []
    blocks = [(i, n) for i, _j, n in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks() if n >= minlen]
    blocks.sort(key=lambda t: (-t[1], t[0]))
    return [a[i:i + n] for i, n in blocks[:limit]]


def _bigrams(s):
    chars = [c for c in str(s or "") if CJK.match(c)]
    return {chars[i] + chars[i + 1] for i in range(len(chars) - 1)}


def _content_bigrams(s):
    """去掉由虚词组成的二元组：的经、忘的 这类没有信息量。"""
    return {b for b in _bigrams(s) if not (set(b) & STOP_CHARS)}


def hints(text, task=""):
    """写作提示（不计分）：能不能确定判的几件事。

    这些是**线索**，不是分数：点题看题目与首尾段有没有共用词，具体事例看有没有时间/数字，
    感受看有没有感受句。判不了的（比如立意高不高）不放进这里。
    """
    text = str(text or "")
    paras = [p.strip() for p in PARA_SPLIT.split(text) if p.strip()]
    out = []
    shared = shared_phrases(task, (paras[0] if paras else "") + "\n" + (paras[-1] if paras else "")) if paras else []
    out.append({"key": "topic", "label": "首尾点题", "ok": bool(shared),
                "evidence": ("首/尾段呼应题目：" + "、".join(shared)) if shared
                            else "首段和末段都没有出现题目里的词"})
    has_time = any(w in text for w in TIME_WORDS)
    has_digit = any(ch.isdigit() for ch in text) or "一二三" in text
    out.append({"key": "detail", "label": "具体事例", "ok": has_time or has_digit,
                "evidence": "出现时间或数量线索" if (has_time or has_digit) else "没有时间、数量等具体线索，容易写成概括"})
    feel = next((w for w in FEELING_WORDS if w in text), "")
    out.append({"key": "feeling", "label": "写出感受", "ok": bool(feel),
                "evidence": ("出现「%s」" % feel) if feel else "没有直接写出自己的感受或变化"})
    return out


def review(text, subject="语文", band="middle", task="", chat=None, use_model=False, semantic=False):
    """返回分项结果。use_model / semantic 默认都关闭：没有模型时只出形式维度，并说清楚。

    semantic 与 use_model 分开：前者只判断「是否切题」并强制给原文证据，
    后者给内容/语言两个分数。两个都关时不产生任何模型调用。
    """
    subject = subject if subject in TARGET else "语文"
    band = band if band in ("primary", "middle", "high") else "middle"
    dims, f = rule_dimensions(text, subject, band)
    notes, layers = [], ["形式"]
    if not str(text or "").strip():
        notes.append("没有内容可评")
    if use_model:
        m_dims, why = model_dimensions(text, subject, band, task, chat=chat)
        if m_dims:
            dims += m_dims
            layers.append("内容")
        elif why:
            notes.append(why)
    if semantic:
        topic, why = semantic_topic(text, task, subject, band, chat=chat)
        if topic:
            dims.append(topic)
            layers.append("语义切题")
        elif why:
            notes.append(why)
    if not use_model and not semantic:
        notes.append("未启用模型评分：本次只覆盖篇幅/结构/连贯/句式四个形式维度")
    total = sum(d["score"] for d in dims)
    return {"subject": subject, "band": band, "total": total, "max": sum(d["max"] for d in dims),
            "coverage": "仅形式维度" if layers == ["形式"] else " + ".join(layers),
            "dims": dims, "features": f, "notes": notes, "hints": hints(text, task)}
