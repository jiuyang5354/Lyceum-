"""答前「心智推断」与误区 / 错因分类（确定性，离线可用）。

思路来源：
  - plastic-labs/tutor-gpt（GPL-3.0，只借思路）：回复前先跑一个 thought 步骤，推断学生在想什么、需要什么，
    推断结果作为元数据存档，回复以它为条件；
  - CAHLR/OATutor（MIT）analyzeStudentState：先用确定性规则算出 strugglingWith / commonMistakes / suggestedApproach 再喂给模型；
  - X-RayLuan/Openclaw-Study-Coach（MIT）错题卡「错因」分类，禁止用「粗心」；
  - ArnaudGuiovanna/tutor-mcp（MIT）误区按（知识点, 误区类型）分组，最近 3 次里不再出现就算已解决。
都是自己重写的规则，没有拷代码。
"""
import re

# 卡点 / 错因类型（Openclaw 的 6 类去掉「书写」「习惯」，合并成「表达」；禁用「粗心」）
TYPES = {
    "审题": "没读懂题意或漏了条件",
    "概念": "概念、定义、规则没弄清",
    "方法": "知道概念但不知道从哪下手、选什么方法",
    "计算": "思路对，算错或符号出错",
    "表达": "会做但写不规范、说不完整（单位、步骤、语言组织）",
}
TYPE_KEYS = tuple(TYPES)
BANNED_CAUSE = ("粗心", "马虎", "不认真")

_RULES = [
    ("审题", re.compile(r"(看不懂|读不懂|题目.{0,4}(什么意思|啥意思)|不懂题|题意|问的是什么|求什么|哪个条件|条件.{0,3}(没用|漏))")),
    ("概念", re.compile(r"(什么是|是什么意思|啥是|定义|概念|为什么.{0,6}(叫|是)|区别|分不清|不知道.{0,4}(是什么|指什么)|公式是)")),
    ("方法", re.compile(r"(怎么(做|下手|开始|列|设|证|想)|从哪(里)?(开始|下手)|没思路|没头绪|不知道.{0,4}(用什么|怎么)|用什么(方法|公式)|第一步)")),
    ("计算", re.compile(r"(算(错|不对|不出|出来不一样)|算了.{0,6}(不对|不一样)|结果不对|符号|约分|通分|进位|借位|移项|算得|算出)")),
    ("表达", re.compile(r"(怎么写|格式|单位|步骤.{0,3}(写|规范)|怎么(说|表述|组织)|写不(出|好)|扣分)")),
]
_NUMERIC_ATTEMPT = re.compile(r"(?:[a-zA-Z]\s*=\s*-?\d|=\s*-?\d|答案是|我算|我觉得是|得\s*-?\d)")

# 每类卡点的建议追问方向（和 strategies 里各科的追问模板互补；只说方向，不给结果）
APPROACH = {
    "审题": "先让学生用自己的话复述题目，圈出已知和所求，问哪个条件还没用上。",
    "概念": "先用一个生活里的例子或最简单的例子把概念说清，再让学生用自己的话复述，最后回到题目。",
    "方法": "问「这题和学过的哪类题像？那类题第一步做什么？」，必要时把题拆成更小的一步。",
    "计算": "让学生把每一步写出来，从第一步开始逐行对，定位第一处出错的那一行，让他自己改。",
    "表达": "先肯定思路，再指出缺的是哪一项（单位 / 步骤 / 关键词），让学生自己补完整。",
    "": "先问一个能马上回答的小问题，确认学生现在想到哪一步了。",
}


def classify(text, student_correct=None, hint_level=0, model_type=""):
    """学生本轮文字 → 卡点类型（审题 / 概念 / 方法 / 计算 / 表达 / ""）与依据。模型给的类型在白名单里时优先。"""
    mt = (model_type or "").strip()
    if mt in TYPES:
        return mt, "模型判断"
    t = text or ""
    for k, rx in _RULES:
        m = rx.search(t)
        if m:
            return k, "学生说「%s」" % m.group(0)
    if student_correct is False and _NUMERIC_ATTEMPT.search(t):
        return "计算", "给出了数值答案但不对"
    if student_correct is False:
        return "方法", "作答不对"
    return "", ""


def infer(st, text, action=None, skill=None, misconceptions=(), stuck_stats=None):
    """答前推断：学生现在大概卡在哪、依据是什么、建议怎么追问。纯函数，返回 dict（会存进消息 meta.thought）。
    skill: 当前知识点的掌握度行（可为 None）；misconceptions: 该知识点仍活跃的误区；stuck_stats: {类型: 次数}（该学科历史）。"""
    t = text or ""
    typ, why = classify(t)
    signals = []
    if action == "stuck" or re.search(r"(不会|卡住|不懂|没思路)", t):
        signals.append("学生表示卡住")
    if int(st.get("stuck") or 0) >= 2:
        signals.append("这道题已卡住 %d 次" % int(st.get("stuck")))
    if st.get("problem") and _NUMERIC_ATTEMPT.search(t):
        signals.append("本轮写了答案 / 步骤，先判对错")
    elif not st.get("problem"):
        signals.append("新题：先确认学生读懂题意、知道已知和所求")
    low = bool(skill and (skill.get("n_obs") or 0) >= 1 and (skill.get("p_l") or 0) < 0.5)
    if low:
        signals.append("「%s」掌握度 %d%%，偏低" % (skill.get("topic") or "当前知识点", round((skill.get("p_l") or 0) * 100)))
    if not typ and misconceptions:
        typ, why = misconceptions[0].get("type") or "", "这个知识点上有没解决的误区"
    if not typ and stuck_stats:
        best = max(stuck_stats.items(), key=lambda kv: (kv[1], kv[0]))
        if best[1] >= 2 and signals:
            typ, why = best[0], "这一科以前常卡在「%s」（%d 次）" % best
    if not typ and low:
        typ, why = "概念", "掌握度偏低，可能概念没立住"
    return {"stuck_type": typ, "why": why, "signals": signals, "approach": APPROACH.get(typ, APPROACH[""]),
            "misconceptions": [m.get("detail") or m.get("type") for m in (misconceptions or [])][:2]}


def prompt_block(thought):
    if not thought:
        return ""
    lines = ["# 先判断学生卡在哪（服务端答前推断，仅供参考；与学生实际表现不符时以实际为准）"]
    if thought.get("stuck_type"):
        lines.append("- 可能的卡点：%s（%s）——%s" % (thought["stuck_type"], TYPES[thought["stuck_type"]], thought.get("why") or ""))
    else:
        lines.append("- 还看不出卡点：先问一个小问题确认他想到哪一步了。")
    for s in thought.get("signals") or []:
        lines.append("- " + s)
    for m in thought.get("misconceptions") or []:
        lines.append("- 这个知识点上以前的误区：%s（留意是否又出现，出现了就针对它追问）" % m)
    lines.append("- 建议追问方向：" + thought.get("approach", ""))
    lines.append("- 在输出 JSON 里额外填 \"stuck_type\"（审题|概念|方法|计算|表达|空字符串）；学生答错时再填 \"misconception\"（一句话说他错在哪种想法上，不超过 20 字，不写「粗心」）。")
    return "\n".join(lines)


def clean_misconception(text):
    t = re.sub(r"\s+", "", str(text or ""))[:30]
    for b in BANNED_CAUSE:
        t = t.replace(b, "")
    return t
