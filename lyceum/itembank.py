"""题库与「在线难度标定」。

为什么要有这个
  只有知识点先修关系时，推荐只能说到「练 整式的乘法」，说不出「练哪一道、为什么是这道」。
  题库给题，难度标定让「这道题对你合适」成为可计算的事。

难度是怎么来的（重要）
  `difficulty_prior` 是**结构先验**，不是从学生数据拟合出来的：按学段基准 + 步骤数 +
  运算个数估一个 0~1 的数，只能当起点。真正的难度来自作答记录：
  - 用 1PL 形式的逻辑函数 p = 1 / (1 + e^(-K(θ - d))) 描述「能力 θ 的学生做对难度 d 的概率」；
  - 学生做对/做错后，双方各走一步 Elo 式更新：d 与 θ 都按 (score - p) 调整；
  - 步长随该题作答次数衰减，避免前几次作答把难度带飞。
  这是在线标定，不是 IRT 估计；样本为 0 时它等于先验，文档里也这么写。

判分
  只用确定性方法：数字/分数按值比较，表达式走 mathcheck.equivalent。判不了返回 None，
  由调用方决定交给模型，绝不猜。
"""
import json
import math
import os
import re
from fractions import Fraction

from . import mathcheck

_HERE = os.path.dirname(os.path.abspath(__file__))
ITEMS_FILE = os.path.join(_HERE, "items.json")
TAXONOMY_FILE = os.path.join(_HERE, "taxonomy.json")

BAND_BASE = {"primary": 0.22, "middle": 0.44, "high": 0.62}
K = 3.2          # 逻辑函数的陡峭度
LR = 0.12        # 基础步长
TARGET_P = 0.75  # 练习时希望学生做对的概率（最近发展区）
MIN_ATTEMPTS_FOR_EMPIRICAL = 5


def prior(band, steps, ops):
    """结构先验难度：学段基准 + 步骤 + 运算量。与 tools/build_items.py 用同一公式。"""
    d = BAND_BASE.get(band, 0.45) + 0.05 * (steps - 1) + 0.035 * max(0, ops - steps)
    return round(min(0.95, max(0.10, d)), 2)


def _topics():
    with open(TAXONOMY_FILE, encoding="utf-8") as f:
        data = json.load(f)["subjects"]
    return {s: {row.split("|")[0] for items in bands.values() for row in items} for s, bands in data.items()}


def load_items(path=ITEMS_FILE):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    topics = _topics()
    items, seen = [], set()
    for it in data["items"]:
        for key in ("id", "subject", "band", "topic", "stem", "answer", "params"):
            if not it.get(key):
                raise ValueError("题目缺字段 %s：%r" % (key, it))
        if it["id"] in seen:
            raise ValueError("题目 id 重复：%s" % it["id"])
        seen.add(it["id"])
        if it["topic"] not in topics.get(it["subject"], set()):
            raise ValueError("%s 的知识点不在 taxonomy 里：%s" % (it["subject"], it["topic"]))
        expect = prior(it["band"], int(it["steps"]), int(it["ops"]))
        if abs(float(it.get("difficulty_prior", -1)) - expect) > 1e-9:
            raise ValueError("%s 的先验难度与公式不一致：%s vs %s" % (it["id"], it.get("difficulty_prior"), expect))
        items.append(it)
    return items


ITEMS = load_items()
BY_ID = {it["id"]: it for it in ITEMS}


def topics():
    return sorted({(it["subject"], it["topic"]) for it in ITEMS})


def count(subject=None, topic=None):
    return sum(1 for it in ITEMS
               if (subject is None or it["subject"] == subject) and (topic is None or it["topic"] == topic))


def theta_from_mastery(p_l):
    """把 BKT 的 P(L) 映射到同一把「能力尺」上：p=0.5 → θ=0.5。"""
    p = min(0.98, max(0.02, float(p_l)))
    return round(0.5 + math.log(p / (1 - p)) / K, 4)


def p_correct(theta, difficulty):
    return 1.0 / (1.0 + math.exp(-K * (float(theta) - float(difficulty))))


def target_difficulty(theta):
    """练习题的最佳难度：让预计做对概率落在 TARGET_P。"""
    return round(float(theta) - math.log(TARGET_P / (1 - TARGET_P)) / K, 4)


def effective_difficulty(item, stats=None):
    st = (stats or {}).get(item["id"])
    return float(st["difficulty"]) if st and st.get("attempts") else float(item["difficulty_prior"])


def select(subject, topic, theta=0.5, stats=None, exclude=()):
    """挑一道最接近目标难度的题；同难度时优先没做过的。返回 (item, why) 或 (None, None)。"""
    pool = [it for it in ITEMS
            if it["subject"] == subject and it["topic"] == topic and it["id"] not in set(exclude)]
    if not pool:
        return None, None
    target = target_difficulty(theta)
    best, best_key = None, None
    for it in pool:
        d = effective_difficulty(it, stats)
        tries = ((stats or {}).get(it["id"]) or {}).get("attempts", 0)
        key = (round(abs(d - target), 6), tries, it["id"])
        if best_key is None or key < best_key:
            best, best_key = it, key
    return best, explain(best, theta, effective_difficulty(best, stats))


def explain(item, theta, difficulty=None):
    d = effective_difficulty(item) if difficulty is None else difficulty
    p = p_correct(theta, d)
    return ("难度 %.2f，接近你当前 %.2f（预计做对 %d%%），%d 步"
            % (d, float(theta), round(p * 100), int(item["steps"])))


def _as_number(text):
    t = str(text or "").strip().replace(" ", "")
    if not t:
        return None
    try:
        return Fraction(t)
    except (ValueError, ZeroDivisionError):
        return None


TEXT_KINDS = {"dictation", "idiom", "verb_past", "plural"}


def _norm_text(s):
    """文本答案归一：全角转半角、去掉空白与常见标点、英文小写。

    只用于「答案唯一」的文本题（默写、成语、动词过去式、名词复数）；
    不做同义词判断——那需要语义模型，不能假装规则能判。
    """
    t = str(s or "").strip()
    out = []
    for ch in t:
        code = ord(ch)
        if code == 0x3000:
            out.append(" ")
        elif 0xFF01 <= code <= 0xFF5E:
            out.append(chr(code - 0xFEE0))
        else:
            out.append(ch)
    t = "".join(out).lower()
    return re.sub(r"[\s，。、；：！？,.;:!?'\"“”‘’()（）]", "", t)


def check(item, answer):
    """判分：True/False，判不了返回 None。"""
    user = str(answer or "").strip()
    if not user:
        return False
    if (item.get("params") or {}).get("kind") in TEXT_KINDS:
        return bool(_norm_text(user)) and _norm_text(user) == _norm_text(item["answer"])
    unit = item.get("unit") or ""
    if unit and user.endswith(unit):
        user = user[: -len(unit)].strip()
    want = item["answer"]
    a, b = _as_number(want), _as_number(user)
    if a is not None and b is not None:
        return a == b
    try:
        return mathcheck.equivalent(want, user)
    except Exception:
        return None


def update_pair(theta, difficulty, correct, attempts=0):
    """一次作答后同时更新「这道题的难度」与「这个学生的能力」。

    做对 → 题比预想的简单（难度下降），人比预想的强（能力上升）；做错反之。
    步长随该题作答次数衰减，前几次不会把难度带飞。返回 (theta, difficulty)。
    """
    p = p_correct(theta, difficulty)
    score = 1.0 if correct else 0.0
    k_eff = LR / (1.0 + attempts / 10.0)
    theta2 = float(theta) + k_eff * (score - p)
    d2 = float(difficulty) + k_eff * (p - score)
    return round(theta2, 4), round(min(0.98, max(0.02, d2)), 4)


def update_difficulty(item, stats, correct, theta):
    """便捷封装：只关心题目难度时用它。返回 (before, after, attempts_after)。"""
    st = stats or {}
    before = effective_difficulty(item, {item["id"]: st} if st else None)
    n = int(st.get("attempts", 0))
    _, after = update_pair(theta, before, correct, n)
    return before, after, n + 1
