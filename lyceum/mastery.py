"""掌握度（BKT）与复习排程 —— 确定性、可审计的规则。

模型只负责「讲」和「判对错」；一个知识点算不算掌握、什么时候该复习，全部由这里的规则决定，
每次更新都在 mastery_events 里留一条记录（时间、证据类型、前后 P(L)、排程变化）。
本模块是纯函数，不碰数据库，便于离线单测。
"""
import datetime
import time

try:  # Python 3.9+
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # 没有 tzdata 的环境退回固定 UTC+8（上海无夏令时，结果相同）
    TZ = datetime.timezone(datetime.timedelta(hours=8), "Asia/Shanghai")

# ---------------- BKT 参数（可调常量） ----------------
P_INIT = 0.20      # 第一次见到这个知识点时，已经会的先验概率
P_TRANSIT = 0.15   # 每做一次练习，从「不会」变成「会」的概率
P_SLIP = 0.10      # 会了但做错（粗心）的概率
P_GUESS = 0.20     # 不会但蒙对的概率
MASTERY_P = 0.85   # P(L) 达到这个值才有资格算掌握
MASTERY_STREAK = 2  # 还要连续答对的「到期复习」次数
SELF_REPORT_CAP = 0.80  # 「我会了」自评最多把 P(L) 推到这里，单靠自评永远跨不过 0.85

# ---------------- 复习梯度（天） ----------------
# 固定梯度而不是 SM-2：批改只有对/错两档，没有 SM-2 需要的 0–5 质量分；易度因子会漂移，
# 学生和家长也看不懂「为什么是 13 天」。固定梯度一眼能核对：第几级 → 隔几天。
LADDER = (1, 2, 4, 7, 15, 30)

# ---------------- 证据折算 ----------------
# kind: (观察 1=对/0=错, 权重 w, 是否计一次学习机会(transit), 对排程的作用, 说明)
# 权重 w 把一次观察「打折」：P' = P + w·(P(L|obs) − P)，w=1 就是标准 BKT。
# 排程作用：right = 若已到期则升一级；wrong = 回到 1 天；none = 不动排程。
EVIDENCE = {
    "solve_h0": (1, 1.0, True, "right", "答疑：没用提示，自己做对"),
    "solve_h1": (1, 0.8, True, "right", "答疑：用了 1 级提示（方向）后自己做对"),
    "solve_h2": (1, 0.5, True, "right", "答疑：用了 2 级提示（方法）后自己做对"),
    "solve_h3": (1, 0.2, True, "wrong", "答疑：用到第 3 级提示才做对（弱正确，排程按没过关处理）"),
    "full_solution": (0, 1.0, True, "wrong", "答疑：看了完整解法（视作错误）"),
    "variant_right": (1, 1.0, True, "right", "变式题做对"),
    "variant_wrong": (0, 1.0, True, "wrong", "变式题做错"),
    "retry_right": (1, 1.0, True, "right", "错题本「再练一次」做对"),
    "retry_wrong": (0, 1.0, True, "wrong", "错题本「再练一次」做错"),
    "self_report": (1, 0.3, False, "none", "「我会了」自评（弱证据，不改排程）"),
}
PRACTICE_KINDS = {"variant_right", "variant_wrong", "retry_right", "retry_wrong"}


def params():
    return {"p_init": P_INIT, "p_transit": P_TRANSIT, "p_slip": P_SLIP, "p_guess": P_GUESS,
            "mastery_p": MASTERY_P, "mastery_streak": MASTERY_STREAK, "self_report_cap": SELF_REPORT_CAP,
            "ladder_days": list(LADDER), "timezone": "Asia/Shanghai",
            "evidence": {k: {"correct": bool(v[0]), "weight": v[1], "transit": v[2], "schedule": v[3], "label": v[4]}
                         for k, v in EVIDENCE.items()}}


# ---------------- 日期 ----------------
def today(now=None):
    """Asia/Shanghai 的日历日。"""
    return datetime.datetime.fromtimestamp(time.time() if now is None else now, TZ).date()


def as_date(s):
    return datetime.date.fromisoformat(s) if isinstance(s, str) else s


def add_days(d, n):
    return (as_date(d) + datetime.timedelta(days=n)).isoformat()


# ---------------- BKT ----------------
def posterior(p, correct, slip=P_SLIP, guess=P_GUESS):
    """一次观察后的 P(L | obs)。"""
    if correct:
        num, den = p * (1 - slip), p * (1 - slip) + (1 - p) * guess
    else:
        num, den = p * slip, p * slip + (1 - p) * (1 - guess)
    return num / den if den > 0 else p


def bkt_update(p, correct, weight=1.0, transit=True, p_transit=P_TRANSIT, slip=P_SLIP, guess=P_GUESS):
    """带权重的 BKT：先按观察更新（按 weight 在先验与后验之间插值），再加学习转移。"""
    w = max(0.0, min(1.0, weight))
    p_obs = p + w * (posterior(p, correct, slip, guess) - p)
    p_new = p_obs + (1 - p_obs) * p_transit if transit else p_obs
    return max(0.0, min(1.0, p_new))


def apply_evidence(p, kind, sk=None):
    """按证据类型更新 P(L)。sk 可带该知识点自己的参数（p_transit / p_slip / p_guess）。"""
    obs, w, tr, _, _ = EVIDENCE[kind]
    sk = sk or {}
    new = bkt_update(p, bool(obs), w, tr, sk.get("p_transit", P_TRANSIT), sk.get("p_slip", P_SLIP), sk.get("p_guess", P_GUESS))
    if kind == "self_report":
        new = min(new, max(p, SELF_REPORT_CAP))  # 自评不能单独把人推过掌握线
    return new


def solve_kind(hint_level):
    return "solve_h%d" % max(0, min(3, int(hint_level or 0)))


def chat_evidence(out, st):
    """答疑一轮结束后该记哪种证据；同一道题只记一次（st['ev_logged']）。返回 kind 或 None。"""
    if not st.get("problem") or st.get("ev_logged"):
        return None
    if out.get("stage") == "full":
        return "full_solution"
    if out.get("student_correct") is True and out.get("solved"):
        return solve_kind(st.get("hint_level"))
    return None


# ---------------- 排程 ----------------
def schedule(item, effect, d):
    """item: {review_step, review_streak, next_review}；effect: right|wrong|none；d: 今天(date 或 iso)。
    返回 (新排程 dict, 这次是否算一次「到期复习」)。
      - 第一次有证据：进第 0 级，明天复习。
      - wrong：不管到没到期，回到第 0 级（1 天后），连续答对清零。
      - right 且已到期：升一级，下次 = 今天 + 梯度[新级]，连续答对 +1。
      - right 但没到期（提前刷题）：排程不动，不算间隔复习——不鼓励临时抱佛脚。
      - none：不动。"""
    d = as_date(d)
    step = int(item.get("review_step") or 0)
    streak = int(item.get("review_streak") or 0)
    nxt = item.get("next_review")
    counted = False
    if not nxt:  # 第一次：不论对错，明天复习
        return {"review_step": 0, "review_streak": 0, "next_review": add_days(d, LADDER[0])}, False
    due = as_date(nxt) <= d
    if effect == "wrong":
        counted = due
        step, streak, nxt = 0, 0, add_days(d, LADDER[0])
    elif effect == "right" and due:
        counted = True
        step = min(step + 1, len(LADDER) - 1)
        streak += 1
        nxt = add_days(d, LADDER[step])
    return {"review_step": step, "review_streak": streak, "next_review": nxt}, counted


def is_mastered(p, streak):
    return p >= MASTERY_P and streak >= MASTERY_STREAK


def status(sk):
    """mastered 已掌握 / consolidating 待巩固(P 够了，复习次数不够) / learning 学习中 / new 还没证据"""
    if not sk.get("n_obs"):
        return "new"
    if sk.get("mastered"):
        return "mastered"
    return "consolidating" if sk.get("p_l", 0) >= MASTERY_P else "learning"
