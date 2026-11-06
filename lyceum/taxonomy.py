"""知识点规范表与确定性归一化。

模型给出的知识点标签换个说法就会分裂（「因式分解」/「一元二次方程·因式分解」）。这里把标签映射到
taxonomy.json 里的规范名，规则全部确定、可复现，不调用模型：

  1. 清洗：Unicode NFKC（全角→半角）、转小写、去空白和标点；「· / - — > | :」等统一当层级分隔符。
  2. 候选串：整串（去掉分隔符）在前，然后各层级片段从最后一段（最具体）往前。
  3. 依次尝试（同一学科内，先当前学段、再同科其他学段）：
       a. 精确：候选串 = 某个规范名或别名；
       b. 包含：候选串包含某个规范名/别名（≥2 字），取在串中结束位置最靠后的（中文偏正结构，中心词在后），
          再取最长的；或某个规范名/别名包含候选串（候选 ≥3 字，且只命中一个知识点）；
       c. 相似：字符 bigram Dice 系数 ≥ 0.6（候选 ≥3 字），最高分唯一。
  4. 都不中：保留清洗后的原标签，标记「未归类」（unmatched）。不同学科永远不合并。
"""
import json
import os
import re
import unicodedata

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "taxonomy.json")
with open(_PATH, encoding="utf-8") as _f:
    _RAW = json.load(_f)

VERSION = _RAW["version"]
BANDS = ("primary", "middle", "high")
BAND_NAMES = {"primary": "小学", "middle": "初中", "high": "高中"}
FUZZY_MIN = 0.6
SEP_CHARS = "·•・‧∙/\\-–—―>|:~→"
_SEP_RE = re.compile("[" + re.escape(SEP_CHARS) + "]+")
_ELLIPSIS_RE = re.compile(r"(…|\.{2,})+$")


def band_of_grade(grade):
    g = int(grade or 8)
    return "primary" if g <= 6 else ("middle" if g <= 9 else "high")


def _nfkc(s):
    return unicodedata.normalize("NFKC", s or "").lower()


def _is_punct(ch):
    cat = unicodedata.category(ch)
    return cat[0] in ("P", "S", "Z", "C")


def segments(raw):
    """清洗后的层级片段（每段已去空白标点）。"""
    t = _ELLIPSIS_RE.sub("", _nfkc(raw).strip())
    parts = _SEP_RE.split(t)
    out = []
    for p in parts:
        p = "".join(ch for ch in p if not _is_punct(ch))
        if p:
            out.append(p)
    return out


def norm(raw):
    """匹配用的键：NFKC、小写、去空白标点和分隔符。"""
    return "".join(segments(raw))


def clean_label(raw):
    """未归类时保留的显示名：去首尾空白和省略号，层级分隔符统一成「·」，全角转半角（中文不受影响）。"""
    segs = []
    t = _ELLIPSIS_RE.sub("", unicodedata.normalize("NFKC", raw or "").strip())
    for p in _SEP_RE.split(t):
        p = re.sub(r"\s+", " ", p).strip(" ，,。.、;；!！?？")
        p = re.sub(r"(?<=[^\x00-\x7f]) | (?=[^\x00-\x7f])", "", p)  # 中文旁边的空格去掉，英文词间保留
        if p:
            segs.append(p)
    return "·".join(segs)[:20]


# ---------------- 索引 ----------------
class _Entry:
    __slots__ = ("subject", "band", "name", "keys")

    def __init__(self, subject, band, name, keys):
        self.subject, self.band, self.name, self.keys = subject, band, name, keys


def _build():
    idx = {}  # subject -> band -> [ _Entry ]
    for subj, bands in _RAW["subjects"].items():
        for band, items in bands.items():
            lst = []
            for it in items:
                names = [x.strip() for x in it.split("|") if x.strip()]
                keys = []
                for n in names:
                    k = norm(n)
                    if k and k not in keys:
                        keys.append(k)
                lst.append(_Entry(subj, band, names[0], keys))
            idx.setdefault(subj, {})[band] = lst
    return idx


INDEX = _build()


def subjects():
    return list(INDEX)


def names(subject, band):
    return [e.name for e in INDEX.get(subject, {}).get(band, [])]


def all_entries(subject, band=None):
    bands = INDEX.get(subject, {})
    return [e for b in BANDS if band in (None, b) for e in bands.get(b, [])]


def is_canonical(subject, topic):
    return any(e.name == topic for e in all_entries(subject))


# ---------------- 相似度 ----------------
def _bigrams(s):
    return [s[i:i + 2] for i in range(len(s) - 1)] if len(s) > 1 else [s]


def dice(a, b):
    """字符 bigram Dice 系数（多重集）。"""
    A, B = _bigrams(a), _bigrams(b)
    if not A or not B:
        return 0.0
    pool = list(B)
    hit = 0
    for x in A:
        if x in pool:
            pool.remove(x)
            hit += 1
    return 2.0 * hit / (len(A) + len(B))


# ---------------- 匹配 ----------------
def _match_in(entries, cands, prefix=None):
    """在一组知识点里按 精确 → 包含 → 相似 的顺序匹配，返回 (entry, method) 或 (None, None)。
    prefix：原标签末尾带省略号（被截断）时的最后一段，先按「前缀」匹配，且只命中一个知识点才算。"""
    if not entries:
        return None, None
    if prefix and len(prefix) >= 2:
        hits = {id(e): e for e in entries for k in e.keys if k.startswith(prefix)}
        if len(hits) == 1:
            return next(iter(hits.values())), "prefix"
    for c in cands:  # a. 精确
        for e in entries:
            if c in e.keys:
                return e, ("exact" if c == e.keys[0] else "alias")
    for c in cands:  # b1. 候选包含规范名/别名：结束位置最靠后，再最长
        best = None
        for e in entries:
            for k in e.keys:
                if len(k) < 2:
                    continue
                pos = c.rfind(k)
                if pos >= 0:
                    score = (pos + len(k), len(k))
                    if best is None or score > best[0]:
                        best = (score, e)
        if best:
            return best[1], "contains"
    for c in cands:  # b2. 规范名/别名包含候选（只命中一个知识点才算）
        if len(c) < 3:
            continue
        hits = {id(e): e for e in entries for k in e.keys if c in k}
        if len(hits) == 1:
            return next(iter(hits.values())), "contained"
    for c in cands:  # c. bigram 相似度
        if len(c) < 3:
            continue
        scored = {}
        for e in entries:
            s = max(dice(c, k) for k in e.keys)
            if s >= FUZZY_MIN:
                scored[id(e)] = (s, e)
        if scored:
            ranked = sorted(scored.values(), key=lambda x: -x[0])
            if len(ranked) == 1 or ranked[0][0] > ranked[1][0]:
                return ranked[0][1], "fuzzy"
    return None, None


def resolve(subject, raw, band=None):
    """把（学科, 原标签）映射到规范知识点。
    返回 dict：topic（规范名或清洗后的原标签）、matched（是否归入规范表）、method、band。"""
    subject = (subject or "").strip()
    raw = (raw or "").strip()
    cleaned = clean_label(raw)
    if not raw:
        return {"topic": "", "matched": False, "method": "empty", "band": None}
    segs = segments(raw)
    if not segs or subject not in INDEX:
        return {"topic": cleaned, "matched": False, "method": "unmatched", "band": None}
    whole = "".join(segs)
    cands = [whole] + ([s for s in reversed(segs)] if len(segs) > 1 else [])
    truncated = bool(_ELLIPSIS_RE.search(_nfkc(raw).strip()))
    if truncated:  # 末段被截断：完整串和末段都不可靠，末段只做前缀匹配
        cands = [s for s in reversed(segs[:-1])] or cands
    order = ([band] if band in BANDS else []) + [b for b in BANDS if b != band]
    for b in order:
        e, method = _match_in(INDEX[subject].get(b, []), cands, segs[-1] if truncated else None)
        if e:
            return {"topic": e.name, "matched": True, "method": method, "band": b}
    return {"topic": cleaned, "matched": False, "method": "unmatched", "band": None}


def canonical(subject, raw, band=None):
    return resolve(subject, raw, band)["topic"]


# ---------------- 提示词用 ----------------
def prompt_block(band, subject=None, *, focused=False):
    """已知学科时可按需加载；未知学科仍提供完整表，规范化索引始终不裁剪。"""
    subs = [s for s in INDEX if band in INDEX[s]]
    if subject in subs:
        subs.remove(subject)
        subs.insert(0, subject)
        if focused:
            subs = [subject]
    lines = [f"- {s}：" + "、".join(names(s, band)) for s in subs]
    return f"{BAND_NAMES.get(band, '')}各学科规范知识点（人教版口径）：\n" + "\n".join(lines)
