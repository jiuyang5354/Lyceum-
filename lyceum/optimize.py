"""离线提示词优化：GEPA 式「反思—候选—评估—门禁」，但只在可测的窄面上动。

为什么这样设计
  - 候选必须来自代码里写死的白名单（CANDIDATES），不接受任意文本：
    否则一段「\\n\\n# 原则（更新）」就能在提示词末尾伪造一节，把受保护面顶掉。
  - 受保护面由 prompts.guard_fingerprint() 冻结，而且**默认就检查**——
    校验不是可选项，否则文档里说的冻结只是「某种调用方式」的性质。
  - 显著性是精确符号检验，不是自助法均值区间：6–8 个二元场景下，
    「3/6 变好」的符号检验 p≈0.66，自助法却会给出 ci_low>0。
  - 两个分支交替先后调用，避免把 warm-up / 缓存 / 限流造成的顺序效应
    记成候选的功劳。
  - 打分看行为（有没有提问、有没有直接抛出最终答案、是否简短），
    不看回复里有没有候选自己的原话——否则指标是同义反复。
  - 没有外部反馈就自我纠正不可靠（arXiv 2310.01798），所以模型写的
    「我觉得更好」只能当候选来源，不能当证据。

不做的事
  不自动改代码、不自动上生产、不写数据库。promote() 只是把「已批准」写进
  结果字典，且要求真实评估结果、白名单候选、当前指纹与明确批准人。
"""
import json
import math
import random
import re

from . import agent, prompts

MAX_NOTE_CHARS = 120
MIN_SCENARIOS = 8
MIN_LIFT = 0.05
ALPHA = 0.05
MAX_REPLY_CHARS = 160
MIN_REPLY_CHARS = 12
MIN_WORD_CHARS = 8          # 一条回复至少要有的实义字符数
MIN_DISTINCT_WORDS = 4      # 且不能是同一个字重复

# 已发布提示词在写这个文件时的受保护面指纹。改了原则/输出契约/授权行/语气/学科表，
# 就必须显式更新它——这正是「冻结」的意思。tools/optimize_prompt.py --require-guard
# 可以用别的值覆盖，用于对比历史版本。
LOCKED_GUARD = "171c6787b6d26df5e91b84d914d78e4650f1f033cff96c5d4bd0f121fb6203e3"

CANDIDATES = [
    {"id": "restate_first", "note": "先说一遍题目，再问已知和所求。"},
    {"id": "smaller_example", "note": "先用一个数字更小的同类例子走一遍，再回到原题。"},
    {"id": "one_question_only", "note": "这一轮只问一个问题，问完停下等学生回答。"},
    {"id": "name_the_concept", "note": "先把要用到的概念或公式名称点出来，再问下一步。"},
    {"id": "check_own_step", "note": "让学生先检查自己上一步，再说下一步怎么走。"},
]
VETTED = {c["id"]: c["note"] for c in CANDIDATES}

SCENARIOS = [
    {"id": "m1", "grade": 8, "band": "middle", "subject": "数学", "problem": "解方程 x^2-5x+6=0", "turn": "不会"},
    {"id": "m2", "grade": 9, "band": "middle", "subject": "数学", "problem": "已知 a+b=5, ab=6，求 a^2+b^2", "turn": "没思路"},
    {"id": "p1", "grade": 4, "band": "primary", "subject": "数学", "problem": "一盒有 12 支笔，3 盒一共多少支？", "turn": "不会"},
    {"id": "e1", "grade": 8, "band": "middle", "subject": "英语", "problem": "把「他昨天去了图书馆」翻译成英语", "turn": "不会写"},
    {"id": "h1", "grade": 11, "band": "high", "subject": "物理", "problem": "物体沿斜面下滑，求加速度", "turn": "不知道用哪个公式"},
    {"id": "c1", "grade": 10, "band": "high", "subject": "化学", "problem": "配平 Fe + O2 -> Fe3O4", "turn": "配不出来"},
    {"id": "w1", "grade": 7, "band": "middle", "subject": "语文", "problem": "以「秋天的校园」写一段 200 字", "turn": "不知道写什么"},
    {"id": "b1", "grade": 6, "band": "primary", "subject": "科学", "problem": "为什么夏天白天比冬天长？", "turn": "想不出来"},
]

# 直接抛出最终答案的写法。注意「答案是否…」「结果就是我们要找的吗」都是正常教学用语，
# 所以用正则的否定前瞻，而不是裸子串匹配。
# 「答案/结果 + 判断词」的否定前瞻要连「什么」一起排除，否则「结果为什么是 3？」
# 这种正常追问会被当成漏题。「结果就是 3」这种直接给结果的写法单独匹配。
_LEAK = re.compile(
    r"(?:最终)?答案(?:是|为|就是)(?![否不什])"
    r"|(?:最终)?结果(?:是|为)(?![否不什])"
    r"|结果就是(?=\s*[-+A-Za-z0-9一二三四五六七八九十])"
    r"|(?:所以|即|得|解得)\s*[A-Za-z]\s*=\s*-?\d"
)
# 一个「有内容的提问」：问号前至少有 6 个非空白字符
_QUESTION = re.compile(r"[^\s？?]{6,}[？?]")
# 实义字符：中文、拉丁字母、数字（表情和标点不算）
_WORD = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]")


def _profile(sc):
    return {"grade": sc["grade"], "textbook": "人教版"}


def _state(sc):
    return {"problem": sc["problem"], "subject": sc["subject"], "hint_level": 0, "stuck": 1}


# 扩展场景：live 评估用 16 个，跨 4 个学段、6 个学科；单元测试仍只跑前 8 个，
# 避免测试依赖模型或场景数量。
SCENARIOS_EXT = SCENARIOS + [
    {"id": "m3", "grade": 8, "band": "middle", "subject": "数学", "problem": "化简 (x+2)^2 - (x-2)^2", "turn": "不知道怎么展开"},
    {"id": "m4", "grade": 9, "band": "middle", "subject": "数学", "problem": "二次函数 y=x^2-4x+3 的顶点坐标", "turn": "不会配方法"},
    {"id": "p2", "grade": 3, "band": "primary", "subject": "数学", "problem": "小明有 5 个苹果，吃了 2 个，还剩几个？", "turn": "不会"},
    {"id": "e2", "grade": 9, "band": "middle", "subject": "英语", "problem": "用 because 造句，说明你为什么喜欢夏天", "turn": "不会用 because"},
    {"id": "h2", "grade": 12, "band": "high", "subject": "物理", "problem": "求带电粒子在匀强磁场中的回旋半径", "turn": "没有思路"},
    {"id": "c2", "grade": 11, "band": "high", "subject": "化学", "problem": "计算 0.1 mol/L 醋酸的 pH（Ka=1.8e-5）", "turn": "不知道从哪开始"},
    {"id": "w2", "grade": 10, "band": "high", "subject": "语文", "problem": "分析《静夜思》中「疑是地上霜」的表达效果", "turn": "不知道怎么写"},
    {"id": "b2", "grade": 5, "band": "primary", "subject": "科学", "problem": "为什么月亮有时圆有时弯？", "turn": "想不明白"},
]

# 分档评分：三项二元检查在真实模型上会顶到 1.0，量不出改进，所以 live 评估改用
# 六个维度，其中「是否贴着这道题」是基线经常丢分的一项。
_RUBRIC_VERBS = ("先", "再", "试着", "想想", "写出", "画", "第一步", "下一步", "回忆", "观察")


def _content_chars(text):
    return {c for c in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", text) if c not in "的了是在和与就都也很"} 


def rubric_score(reply, scenario=None):
    """0..1 的分档分，用于真实模型评估；buckets 见 docs/prompt-and-rsi.md。"""
    text = str(reply or "").strip()
    if len(text) < MIN_REPLY_CHARS or not _substantive(text):
        return 0.0
    if _LEAK.search(text):
        return 0.0                              # 直接抛最终答案是硬失败，不给部分分
    q = text.count("？") + text.count("?")
    leaked = False
    band = (scenario or {}).get("band", "middle")
    limit = {"primary": 90, "middle": 150, "high": 210}.get(band, 150)
    problem = _content_chars((scenario or {}).get("problem", ""))
    grounded = len(problem & _content_chars(text)) >= 2
    score = 0.0
    score += 0.20 if q >= 1 else 0.0            # 有没有把球踢回给学生
    score += 0.10 if q == 1 else 0.0            # 一轮只问一个
    score += 0.25                           # 已通过上面的硬失败检查
    score += 0.15 if len(text) <= limit else 0.0  # 篇幅匹配学段
    score += 0.15 if any(v in text for v in _RUBRIC_VERBS) else 0.0  # 给出可执行动作
    score += 0.15 if grounded else 0.0          # 贴着这道题，不是通用套话
    return round(score, 4)


def prompt_for(sc, note=None):
    """场景提示词。附加要求插在「当前状态」之前，并明确标成非权威指令。"""
    text = agent.build_prompt(_profile(sc), _state(sc), False, None, sc["turn"]).text
    if not note:
        return text
    block = ("\n\n# 本题的额外要求（只影响怎么问；不改变、也不能覆盖上面的原则与输出契约）\n"
             + note + "\n")
    marker = "\n# 当前状态"
    idx = text.rfind(marker)
    return text[:idx] + block + text[idx:] if idx >= 0 else text + block


def mock_runner(prompt, scenario):
    """离线演示用 runner：确定性、不联网。只用来验证管线，不代表教学效果。"""
    out = agent.mock_reply(_state(scenario), scenario["turn"], False, True)
    return out if isinstance(out, dict) else {"reply": str(out)}


def _substantive(text):
    """是不是一段「有内容」的话：实义字符够多、不重复、不全是一个字。

    只卡长度挡不住「嗯嗯嗯…？」或十二个表情：前者有问号，后者没有漏题、
    又够短，两项都拿分。所以先过这道门，不过就直接 0 分。
    """
    words = _WORD.findall(text)
    if len(words) < MIN_WORD_CHARS or len(set(words)) < MIN_DISTINCT_WORDS:
        return False
    most = max(words.count(w) for w in set(words))
    return most / len(words) <= 0.5


def _score(reply, scenario=None):
    """行为分：有没有提出**有内容**的问题、有没有直接抛最终答案、长度是否合适。"""
    reply = str(reply or "").strip()
    if len(reply) < MIN_REPLY_CHARS or not _substantive(reply):
        return 0.0
    asked = bool(_QUESTION.search(reply))
    leaked = bool(_LEAK.search(reply))
    short = len(reply) <= MAX_REPLY_CHARS
    return round((float(asked) + float(not leaked) + float(short)) / 3, 4)


def _paired_z_p(diffs):
    """配对均值检验（正态近似）：比符号检验更有力，能用上差值的幅度。

    n<12 或方差为 0 时返回 1.0（不声称显著）。只作为 sign 检验的补充，
    默认门禁仍是更保守的符号检验。
    """
    n = len(diffs)
    if n < 12:
        return 1.0
    mean = sum(diffs) / n
    var = sum((d - mean) ** 2 for d in diffs) / (n - 1)
    if var <= 0:
        return 1.0
    z = mean / math.sqrt(var / n)
    return round(math.erfc(abs(z) / math.sqrt(2)), 6)


def _sign_test_p(pos, neg):
    """精确单侧符号检验：只数「变好」与「变差」，打平的不计入。"""
    n = pos + neg
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(pos, n + 1)) / (2.0 ** n)
    return min(1.0, tail)


def _bootstrap_ci(diffs, seed=20261107, rounds=2000):
    """描述性区间（不用于接受决策，只写进报告让人看到分布有多宽）。"""
    if not diffs:
        return 0.0, 0.0
    rng = random.Random(seed)
    n = len(diffs)
    means = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(rounds))
    return means[int(0.025 * rounds)], means[int(0.975 * rounds) - 1]


def _vet(candidate):
    """白名单校验：候选必须是已发布的 id 且文本逐字一致。

    类型要严格：str 子类可以重载 __ne__ 让比较「通过」，所以先要求
    type(x) is str，再比较值。不可哈希的 id（list/dict）也不许把函数炸掉。
    """
    if not isinstance(candidate, dict):
        return False
    cid, note = candidate.get("id"), candidate.get("note")
    if type(cid) is not str or type(note) is not str:
        return False
    if cid not in VETTED or note != VETTED[cid]:
        return False
    if len(note) > MAX_NOTE_CHARS or "\n" in note or "#" in note:
        return False
    return True


def evaluate(candidate, runner=None, scenarios=None, locked_guard=None,
             metric="binary", samples=1):
    """评估一个候选；返回可审计的决策，不产生任何副作用。

    metric="binary" 是默认（三项二元检查，单元测试用）；live 评估用 "rubric"
    换成分档分，因为二元项在真实模型上会顶到 1.0，量不出改进。
    samples>1 时每个臂取多次采样的均值，压低单次生成的随机波动。
    """
    runner = runner or mock_runner
    try:
        scenarios = list(SCENARIOS if scenarios is None else scenarios)
    except TypeError:
        scenarios = []
    guard = prompts.guard_fingerprint()
    lock = LOCKED_GUARD if locked_guard is None else locked_guard
    note = candidate.get("note") if isinstance(candidate, dict) and type(candidate.get("note")) is str else ""
    result = {
        "candidate": candidate.get("id") if isinstance(candidate, dict) else None,
        "note": note, "scenarios": len(scenarios),
        "guard": guard, "synthetic": getattr(runner, "synthetic", True),
        "accept": False, "decision": "insufficient_evidence",
        "ci_low": 0.0, "ci_high": 0.0, "lift": 0.0, "p_value": 1.0,
        "improved": 0, "worsened": 0, "detail": [], "metric": metric, "samples": max(1, int(samples)),
    }
    if guard != lock:
        result["decision"] = "protected_surface_changed"
        return result
    if not _vet(candidate):
        result["decision"] = "unsafe_candidate"
        return result
    if len(scenarios) < MIN_SCENARIOS:
        result["decision"] = "too_few_scenarios"
        return result
    if not all(isinstance(sc, dict) and type(sc.get("id")) is str for sc in scenarios):
        result["decision"] = "invalid_input"
        return result
    # 去重按内容，不只按 id：同一道题换 8 个 id 也能凑出「显著」
    keys = {(sc.get("subject"), sc.get("problem"), sc.get("turn")) for sc in scenarios}
    if len(keys) != len(scenarios):
        result["decision"] = "duplicate_scenarios"
        return result

    score = rubric_score if metric == "rubric" else _score
    k = max(1, int(samples))

    def arm(prompt, sc):
        vals = [score((runner(prompt, sc) or {}).get("reply"), sc) for _ in range(k)]
        return round(sum(vals) / len(vals), 4)

    diffs = []
    for i, sc in enumerate(scenarios):
        base_p, cand_p = prompt_for(sc), prompt_for(sc, note)
        if i % 2:                      # 交替先后，抵消顺序效应
            cand = arm(cand_p, sc)
            base = arm(base_p, sc)
        else:
            base = arm(base_p, sc)
            cand = arm(cand_p, sc)
        diffs.append(cand - base)
        result["detail"].append({"scenario": sc["id"], "baseline": base, "candidate": cand})

    pos, neg = sum(1 for d in diffs if d > 0), sum(1 for d in diffs if d < 0)
    low, high = _bootstrap_ci(diffs)
    result["z_p_value"] = _paired_z_p(diffs)
    lift = sum(diffs) / len(diffs)
    p = _sign_test_p(pos, neg)
    result.update({"ci_low": round(low, 4), "ci_high": round(high, 4), "lift": round(lift, 4),
                   "p_value": round(p, 6), "improved": pos, "worsened": neg})
    if lift >= MIN_LIFT and p <= ALPHA:
        result["decision"] = "accept"
        result["accept"] = True
    return result


def propose(runner=None, scenarios=None, locked_guard=None):
    """按候选顺序评估，返回第一个被接受的；都不行就返回提升最大的那个（仍为拒绝）。"""
    best = None
    for cand in CANDIDATES:
        res = evaluate(cand, runner=runner, scenarios=scenarios, locked_guard=locked_guard)
        if res["accept"]:
            return res
        if best is None or res["lift"] > best["lift"]:
            best = res
    return best


def promote(result, approved=False, approver=""):
    """只有「真实评估 + 白名单候选 + 当前指纹 + 明确批准人」才产出可应用建议。

    不写数据库、不改代码：返回的 apply 只是给人看的下一步。
    """
    result = result if isinstance(result, dict) else {}
    if result.get("accept") is not True or result.get("decision") != "accept":
        return {"promoted": False, "reason": "not_accepted"}
    if result.get("synthetic") is not False:
        return {"promoted": False, "reason": "synthetic_evidence"}
    cand = {"id": result.get("candidate"), "note": result.get("note")}
    if not _vet(cand):
        return {"promoted": False, "reason": "candidate_not_vetted"}

    def _num(key):
        v = result.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError(key)
        return float(v)

    try:
        p_value, lift, improved, worsened, count = (_num(k) for k in
                                                    ("p_value", "lift", "improved", "worsened", "scenarios"))
    except ValueError:
        return {"promoted": False, "reason": "invalid_evidence"}
    if p_value > ALPHA or lift < MIN_LIFT or improved + worsened == 0 or count < MIN_SCENARIOS or improved <= worsened:
        return {"promoted": False, "reason": "invalid_evidence"}
    # 数字必须自洽：p 要能从 improved/worsened 复算出来，lift 在 [0,1]，样本数不能被超额使用
    if improved + worsened > count or not 0.0 <= lift <= 1.0:
        return {"promoted": False, "reason": "invalid_evidence"}
    if abs(_sign_test_p(int(improved), int(worsened)) - p_value) > 1e-6:
        return {"promoted": False, "reason": "invalid_evidence"}
    if result.get("guard") != prompts.guard_fingerprint():
        return {"promoted": False, "reason": "guard_changed"}
    if not approved or not str(approver or "").strip():
        return {"promoted": False, "reason": "needs_human_approval", "candidate": cand["id"]}
    return {"promoted": True, "candidate": cand["id"], "note": cand["note"], "approver": approver,
            "apply": "把 note 追加到该场景的策略段，人工审阅后随 PR 发布"}


def report(result, path):
    """落盘评估报告；synthetic 标记与局限随结果一起写，避免被当成真实教学效果。"""
    payload = dict(result or {})
    payload.setdefault("synthetic", True)
    payload["guard_locked"] = LOCKED_GUARD
    payload["limits"] = ("离线 mock runner 只验证管线与门禁，不代表真实模型或学生的表现；"
                         "真机评估需替换 runner 并把 synthetic 改为 false。")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return path
