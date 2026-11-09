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


def review(text, subject="语文", band="middle", task="", chat=None, use_model=False):
    """返回分项结果。use_model 默认关闭：没有模型时只出形式维度，并说清楚。"""
    subject = subject if subject in TARGET else "语文"
    band = band if band in ("primary", "middle", "high") else "middle"
    dims, f = rule_dimensions(text, subject, band)
    notes = []
    if not str(text or "").strip():
        notes.append("没有内容可评")
    if use_model:
        m_dims, why = model_dimensions(text, subject, band, task, chat=chat)
        if m_dims:
            dims += m_dims
        elif why:
            notes.append(why)
    else:
        notes.append("未启用模型评分：本次只覆盖篇幅/结构/连贯/句式四个形式维度")
    total = sum(d["score"] for d in dims)
    return {"subject": subject, "band": band, "total": total, "max": sum(d["max"] for d in dims),
            "coverage": "形式 + 内容" if any(d["source"] == "model" for d in dims) else "仅形式维度",
            "dims": dims, "features": f, "notes": notes}
