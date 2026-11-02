"""「提示不得直接给出关键中间结果 / 最终答案」的确定性检测（不调模型）。

按学科分规则族（strategies.leak_family）：
  math     题目和学生都没写过的因式分解乘积式（第 1–2 层）；`x=… 或 x=…`、「答案是」等最终答案（任何层）
  physics  数值 + 单位的结果（`= 12 N`、`为 3 m/s²`）：第 1–2 层一律拦；第 3 层只拦「所以 / 答案 / 结果 / 求得」后面的；
           另外也跑 math 规则
  chem     配平后的化学方程式（逐元素数原子，左右守恒且有系数 ≥2 或题目要求写方程式）；数值 + 单位的计算结果（同 physics）；
           另外也跑 math 规则
  english  第 1–2 层 / 检查答案时出现完整的英语句子（≥4 个词、句末标点），且题目和学生都没写过，并且
           （题目里几乎没有英文 = 翻译 / 写作题）或（和题目英文词重合 ≥ 60% = 填空 / 改写后的整句）
  None     语文、生物、历史、地理、道德与法治、科学：只靠提示词约束，不做硬拦截
都满足「学生已经写过的不算」：先把题目 + 学生本轮文字归一化，命中的片段若在里面出现过就放过。
"""
import re

from . import strategies

# ---------------- 通用归一化 ----------------
def _norm(t):
    return re.sub(r"[\s$\\{}]", "", t or "")


def _detex(t):
    t = t or ""
    t = re.sub(r"\\(?:text|mathrm|rm|mathbf|operatorname)\s*\{([^{}]*)\}", r"\1", t)
    t = re.sub(r"\\ce\s*\{([^{}]*)\}", r"\1", t)
    rep = {r"\Omega": "Ω", r"\times": "×", r"\cdot": "·", r"\approx": "≈", r"\,": " ", r"\;": " ", r"\ ": " ",
           r"\%": "%", r"^\circ": "°", r"\degree": "°", "^{2}": "²", "^2": "²", "^{3}": "³", "^3": "³"}
    for a, b in rep.items():
        t = t.replace(a, b)
    return t.replace("$", "").replace("**", "")


# ---------------- 数学（原规则，保持不变） ----------------
_PRODUCT_RE = re.compile(r"\(\s*[a-zA-Z][^()]{0,24}\)\s*(?:\\cdot|\\times|·|×|\*)?\s*\(\s*[a-zA-Z][^()]{0,24}\)")
_FINAL_RE = re.compile(r"(?:答案是|结果是|解得|所以\s*[a-zA-Z]\s*=|[a-zA-Z]_?[12]?\s*=\s*-?\d+(?:\.\d+)?\s*(?:或|,|，|和)\s*[a-zA-Z]_?[12]?\s*=\s*-?\d)")


def math_leak(reply, level, seen, student_correct):
    if level < 3:
        for m in _PRODUCT_RE.finditer(reply):
            if _norm(m.group(0)) not in seen:
                return m.group(0)
    m = _FINAL_RE.search(reply.replace("$", ""))
    if m and _norm(m.group(0)) not in seen and student_correct is not True:
        return m.group(0)
    return ""


# ---------------- 物理 / 化学：数值 + 单位 ----------------
UNITS = (r"m/s²|m/s|km/h|kW·h|kWh|kW|kJ|kPa|kg|km|cm³|cm²|cm|mm|mL|mA|mol/L|mol|g/cm³|N·m|"
         r"Pa|Hz|Wb|N|J|W|V|A|Ω|℃|°C|K|C|T|L|g|m|s|h|%")
_NUM_UNIT = re.compile(r"(?:=|＝|≈|是|为|等于|约为|约|得)\s*(-?\d+(?:\.\d+)?(?:\s*×\s*10\^?\{?-?\d+\}?)?)\s*(" + UNITS + r")(?![A-Za-z/])")
_FINAL_WORDS = re.compile(r"(所以|因此|答案|结果|最终|求得|解得|算得)")


def _unit_key(num, unit):
    return _norm(num) + _norm(unit).replace("^2", "²")


def numeric_leak(reply, level, seen, student_correct):
    t = _detex(reply)
    for m in _NUM_UNIT.finditer(t):
        key = _unit_key(m.group(1), m.group(2))
        if key in seen or _norm(m.group(1) + m.group(2)) in seen:
            continue
        if level >= 3:
            if student_correct is True or not _FINAL_WORDS.search(t[max(0, m.start() - 10):m.start() + 1]):
                continue
        return m.group(0)
    return ""


# ---------------- 化学方程式配平 ----------------
_SUBS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
_SP = r"\d*(?:[A-Z][a-z]?\d*|\((?:[A-Z][a-z]?\d*)+\)\d*)+"
_EQ = re.compile(rf"{_SP}(?:\s*\+\s*{_SP})*\s*=\s*{_SP}(?:\s*\+\s*{_SP})*")


def _chem_text(t):
    t = _detex(t).translate(_SUBS)
    t = re.sub(r"\\x(?:right|long)?(?:arrow|equal)\s*(?:\[[^\]]*\])?\s*\{[^{}]*\}", "=", t)
    t = re.sub(r"\\overset\s*\{[^{}]*\}\s*\{[^{}]*\}|\\(?:long)?rightarrow|\\to|⟶|→|—+|=+\s*[\u4e00-\u9fff△]{1,4}\s*=+|=+", "=", t)
    t = re.sub(r"[_{}↑↓]|\\uparrow|\\downarrow", "", t)
    return t


def _atoms(species):
    """'2Ca(OH)2' → (系数, {元素: 个数})"""
    m = re.match(r"(\d*)(.*)", species)
    coef = int(m.group(1) or 1)
    body = m.group(2)
    cnt = {}

    def add(s, mult):
        for g in re.finditer(r"\(((?:[A-Z][a-z]?\d*)+)\)(\d*)|([A-Z][a-z]?)(\d*)", s):
            if g.group(1):
                add(g.group(1), mult * int(g.group(2) or 1))
            else:
                cnt[g.group(3)] = cnt.get(g.group(3), 0) + mult * int(g.group(4) or 1)
    add(body, 1)
    return coef, cnt


def _side(s):
    tot, coefs = {}, []
    for sp in re.split(r"\s*\+\s*", s.strip()):
        c, a = _atoms(sp)
        coefs.append(c)
        for k, v in a.items():
            tot[k] = tot.get(k, 0) + c * v
    return tot, coefs


def balanced(eq):
    left, right = eq.split("=", 1)
    lt, lc = _side(left)
    rt, rc = _side(right)
    return lt == rt and bool(lt), max(lc + rc)


def chem_eq_leak(reply, seen_chem, problem, student_correct):
    if student_correct is True:
        return ""
    t = _chem_text(reply)
    for m in _EQ.finditer(t):
        eq = re.sub(r"\s+", "", m.group(0))
        if eq.count("=") != 1 or eq in seen_chem:
            continue
        ok, maxc = balanced(eq)
        if ok and (maxc >= 2 or re.search(r"方程式|配平", problem or "")):
            return m.group(0).strip()
    return ""


# ---------------- 英语：完整句子 ----------------
_EN_SENT = re.compile(r"[A-Z][A-Za-z']*(?:[ ,]+[A-Za-z'-]+){3,}[.!?]")


def _en_words(t):
    return re.findall(r"[a-z']+", (t or "").lower())


def english_leak(reply, level, stage, seen_text, problem):
    if level >= 3:
        return ""
    seen_n = " ".join(_en_words(seen_text))
    prob_words = set(_en_words(problem))
    for m in _EN_SENT.finditer(reply.replace("**", "").replace("*", "")):
        cand = _en_words(m.group(0))
        if len(cand) < 4 or " ".join(cand) in seen_n:
            continue
        if len(prob_words) < 4:                  # 翻译 / 写作：题目几乎没有英文，任何完整新句都算
            return m.group(0)
        overlap = sum(1 for w in cand if w in prob_words) / len(cand)
        if overlap >= 0.6:                       # 填空 / 改写：和题目句子高度重合 = 直接给出了改好的整句
            return m.group(0)
    return ""


# ---------------- 入口 ----------------
def find_leak(out, st, student_text):
    """第 1–2 层提示 / 检查答案时，回复里出现了题目和学生都没写过的关键结果，返回那段文字；否则返回空串。"""
    reply = out.get("reply") or ""
    if out.get("stage") in ("full", "redirect"):
        return ""
    level = max(int(st.get("hint_level") or 0), int(out.get("hint_level") or 0))
    problem = st.get("problem") or out.get("problem") or ""
    seen_raw = problem + "\n" + (student_text or "")
    seen = _norm(seen_raw)
    sc = out.get("student_correct")
    fam = strategies.leak_family(out.get("subject") or st.get("subject") or "")
    if fam is None:
        return ""
    if fam == "english":
        return english_leak(reply, level, out.get("stage"), seen_raw, problem)
    hit = math_leak(reply, level, seen, sc)
    if hit:
        return hit
    if fam in ("physics", "chem"):
        seen_u = _norm(_detex(seen_raw))
        hit = numeric_leak(reply, level, seen_u, sc)
        if hit:
            return hit
    if fam == "chem":
        seen_chem = re.sub(r"\s+", "", _chem_text(seen_raw))
        hit = chem_eq_leak(reply, seen_chem, problem, sc)
        if hit:
            return hit
    return ""
