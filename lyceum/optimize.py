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

from . import agent, prompts

MAX_NOTE_CHARS = 120
MIN_SCENARIOS = 8
MIN_LIFT = 0.05
ALPHA = 0.05
MAX_REPLY_CHARS = 160

# 已发布提示词在写这个文件时的受保护面指纹。改了原则/输出契约/授权行/语气/学科表，
# 就必须显式更新它——这正是「冻结」的意思。tools/optimize_prompt.py --require-guard
# 可以用别的值覆盖，用于对比历史版本。
LOCKED_GUARD = "df14e94b3739dce8b185512b9bae47e5d3f28fcce32fc14fde539d062cda95fa"

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

# 直接抛出最终答案的写法；只匹配「给结果」，不匹配「检查你的答案」这类正常教学用语。
_LEAK = ("答案是", "答案为", "答案就是", "最终答案是", "最终结果是", "结果就是")


def _profile(sc):
    return {"grade": sc["grade"], "textbook": "人教版"}


def _state(sc):
    return {"problem": sc["problem"], "subject": sc["subject"], "hint_level": 0, "stuck": 1}


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


def _score(reply, scenario=None):
    """行为分：会不会先提问、有没有直接抛最终答案、是否够短。"""
    reply = str(reply or "").strip()
    if not reply:
        return 0.0
    asked = ("？" in reply) or ("?" in reply)
    leaked = any(mark in reply for mark in _LEAK)
    short = len(reply) <= MAX_REPLY_CHARS
    return round((float(asked) + float(not leaked) + float(short)) / 3, 4)


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
    """白名单校验：候选必须是已发布的 id 且文本逐字一致。"""
    if not isinstance(candidate, dict):
        return False
    cid, note = candidate.get("id"), candidate.get("note") or ""
    if cid not in VETTED or note != VETTED[cid]:
        return False
    if len(note) > MAX_NOTE_CHARS or "\n" in note or "#" in note:
        return False
    return True


def evaluate(candidate, runner=None, scenarios=None, locked_guard=None):
    """评估一个候选；返回可审计的决策，不产生任何副作用。"""
    runner = runner or mock_runner
    scenarios = list(SCENARIOS if scenarios is None else scenarios)
    guard = prompts.guard_fingerprint()
    lock = LOCKED_GUARD if locked_guard is None else locked_guard
    note = (candidate or {}).get("note") or ""
    result = {
        "candidate": (candidate or {}).get("id"), "note": note, "scenarios": len(scenarios),
        "guard": guard, "synthetic": getattr(runner, "synthetic", True),
        "accept": False, "decision": "insufficient_evidence",
        "ci_low": 0.0, "ci_high": 0.0, "lift": 0.0, "p_value": 1.0,
        "improved": 0, "worsened": 0, "detail": [],
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
    if len({sc.get("id") for sc in scenarios}) != len(scenarios):
        result["decision"] = "duplicate_scenarios"
        return result
    if prompt_for(scenarios[0], note) == prompt_for(scenarios[0]):
        result["decision"] = "no_change"
        return result

    diffs = []
    for i, sc in enumerate(scenarios):
        base_p, cand_p = prompt_for(sc), prompt_for(sc, note)
        if i % 2:                      # 交替先后，抵消顺序效应
            cand = _score((runner(cand_p, sc) or {}).get("reply"), sc)
            base = _score((runner(base_p, sc) or {}).get("reply"), sc)
        else:
            base = _score((runner(base_p, sc) or {}).get("reply"), sc)
            cand = _score((runner(cand_p, sc) or {}).get("reply"), sc)
        diffs.append(cand - base)
        result["detail"].append({"scenario": sc["id"], "baseline": base, "candidate": cand})

    pos, neg = sum(1 for d in diffs if d > 0), sum(1 for d in diffs if d < 0)
    low, high = _bootstrap_ci(diffs)
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
    if not result.get("accept") or result.get("decision") != "accept":
        return {"promoted": False, "reason": "not_accepted"}
    if result.get("synthetic", True):
        return {"promoted": False, "reason": "synthetic_evidence"}
    cand = {"id": result.get("candidate"), "note": result.get("note")}
    if not _vet(cand):
        return {"promoted": False, "reason": "candidate_not_vetted"}
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
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return path
