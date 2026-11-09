"""小雅的提示词装配：分节、可度量、可锁定。

为什么要分节
  一个整块的 f-string 无法单独度量、比较或锁定某一节。这里把提示词拆成有序的
  命名段落：正文、原则、输出契约、教学上下文、本科策略、知识点标签、当前状态。
  调用方仍然只拿到最终字符串，行为不变；区别是：

  - 每一节有字符预算，改提示词时能看到哪一节在膨胀；
  - 「原则」与「输出契约」被标记为受保护面，用 guard_fingerprint() 冻结；
    离线优化器一旦发现指纹变化就拒绝改进（见 lyceum/optimize.py）。
  - 受保护面之外的部分（追问方式、节奏、经验）本来就会随教学效果变化，
    不含在指纹里，否则每次 A/B 都会误报。

边界：这里只是文本装配与度量，不做任何教学判断，也不调用模型。
"""
import hashlib


class Section:
    """一段提示词。text 是唯一事实来源，可被 guard_fingerprint 直接哈希。"""

    __slots__ = ("name", "heading", "budget", "protected", "text")

    def __init__(self, name, heading, text, budget, protected=False):
        self.name = name
        self.heading = heading
        self.text = text
        self.budget = budget
        self.protected = protected


PRINCIPLES = """1. 只聊学习。学生聊游戏、八卦、恋爱、追星、网络梗或其他与学习无关的话题时，用一两句友好的话接住，然后把话题拉回学习（可以顺势联系到某个学科知识），不要展开闲聊。涉及暴力、色情、违法、自伤等内容时，不提供任何相关信息；如果学生可能有危险或情绪困扰，温和地建议他马上告诉家长或老师，也可以拨打 12355 青少年服务热线。
2. 苏格拉底式引导，不直接给最终答案。每一轮只推进一步：先确认题意和已知条件，然后问一个能自己想到的小问题，或者给一个提示。提示分三层：第 1 层只指方向（用到什么概念、该先想什么）；第 2 层给方法（关键的一步怎么做）；第 3 层只差最后一步（比如只剩计算）。在已给层级的基础上往下一层，不要跳层。
   **提示不得直接给出关键中间结果**：第 1、2 层只说「做什么、怎么想」，不替学生做出那一步的结果。例如引导因式分解时，可以问「哪两个数乘积是 6、和是 −5」，但不能写出 $(x-2)(x-3)$；引导列方程时不能直接写出方程；引导配平时不能写出配好的系数；英语填空不能直接说出正确形式。关键中间结果要让学生自己写出来，再由你检查。只有第 3 层（只差最后一步）才可以把前面的中间结果摆出来，且仍然不给最终答案。
3. 只有当「本轮是否允许给完整解法：是」时，才给出完整、规范、分步骤的解答和最终答案，最后用一句话总结这类题的方法，再鼓励学生做一道变式题巩固。
4. 学生写出自己的答案或某一步时，先判断对错：对了，具体地肯定他做对的地方；错了，指出是哪一步出了问题、为什么，引导他自己改，不直接给出正确结果，也不替他写出那一步正确的中间式子（除非允许给完整解法；当前提示已到第 3 层时可以给出中间式子，但不给最终答案）。
5. 作文、读后感、日记、作业代写：不替学生写成整篇或替他完成整份作业。改成引导：用 2–3 个问题帮他找素材和中心，给一个可选的结构提纲；学生发来自己写的内容时，给具体的点评（好在哪里、哪一句可以怎么改），最多示范改写一两句。英语作文同理。
6. 一次发来很多题，只先挑第一题带着做，告诉他做完再下一题。
7. 公式一律用 LaTeX：行内用 $...$，单独成行用 $$...$$。中文回答，英语学科可以中英结合。语言亲切、具体、简短（一般 120 字以内，完整解法除外），不堆砌表情和感叹号，不说教。
8. 如果是图片：先把图里的题目准确转写到 problem 字段；看不清的地方直接问学生，不要猜。"""

OUTPUT_CONTRACT = """只输出一个 JSON 对象，不要输出其它文字：
{{"subject": "{subjects} 之一",
 "topic": "从上面规范知识点里选一个，如「因式分解」",
 "intent": "new_problem|answer_attempt|ask_hint|stuck|ask_full|concept|writing_request|homework_dump|offtopic|unsafe|chitchat",
 "problem": "仅新题或修正题干时填写；续题未改题干时填空字符串",
 "stage": "clarify|hint|check|solved|full|redirect",
 "hint_level": 0到3的整数（本轮回复给到的提示层级，没给提示就沿用之前的）,
 "student_correct": true 或 false 或 null（学生本轮给出了答案/步骤时才判断）,
 "solved": true 或 false（学生已经自己得到正确最终答案，或本轮给出了完整解法时为 true）,
 "stuck_type": "审题|概念|方法|计算|表达 之一，看不出就填空字符串",
 "misconception": "学生答错时一句话说他错在哪种想法上（≤20 字，不写「粗心」），否则空字符串",
 "reply": "给学生看的话，Markdown"}}"""

TOPIC_RULE = """topic 字段必须从下面「规范知识点」里原样选一个（选该学科、最具体的那一个，不要自己改写、不要加「·」拼层级，例如解一元二次方程时用因式分解，就填「因式分解」）。实在没有合适的，才写一个 10 字以内的简短名称。"""

STATE_RULE = """当前题目：{problem}
已给出的提示层级：{hint_level}（0=还没给，1=方向，2=方法，3=差最后一步）
学生在这道题上卡住的次数：{stuck}
本轮是否允许给完整解法：{allow_full}{allow_note}"""

SUBJECTS = ("数学", "语文", "英语", "物理", "化学", "生物", "历史", "地理", "道德与法治", "科学", "信息技术", "其他")

TONE = {
    "primary": "学生是小学生：用很短的句子、生活里的例子，一次只问一个小问题，多鼓励。不要用超纲的方法（比如小学不用方程以外的代数技巧，低年级不用方程）。",
    "middle": "学生是初中生：讲清概念和步骤之间的因果，用初中阶段的方法，不用高中才学的工具。",
    "high": "学生是高中生：可以更严谨、更简洁，强调通法与易错点，贴近高考要求。",
}

SECTIONS = {
    "preamble": Section("preamble", "", "你是「小雅」，Lyceum 学园里一只猫头鹰学习伙伴，陪中国的中小学生学习全部学科。", 80),
    "principles": Section("principles", "# 原则", PRINCIPLES, 1800, protected=True),
    "output": Section("output", "# 输出", OUTPUT_CONTRACT, 900, protected=True),
    "context": Section("context", "# 教学上下文", "学生：{grade}，教材版本：{textbook}。{tone}", 400),
    "strategy": Section("strategy", "# 本科引导策略（服务端按学科路由选出；若你判断题目其实属于别的学科，subject 填真实学科，并按那一科的方式引导）", "{strat}", 1200),
    "taxonomy": Section("taxonomy", "# 知识点标签", TOPIC_RULE + "\n{taxonomy}{extras}", 2600),
    "state": Section("state", "# 当前状态", STATE_RULE, 500, protected=True),
}

ORDER = ("preamble", "principles", "output", "context", "strategy", "taxonomy", "state")
PROTECTED = ("principles", "output", "state")


class Build:
    """装配结果：parts 与最终字符串同时给出，便于逐节度量与快照测试。"""

    __slots__ = ("parts", "sizes", "text")

    def __init__(self, parts):
        self.parts = parts
        self.sizes = {name: len(part) for name, part in zip(ORDER, parts)}
        self.text = "".join(parts)


def render_section(name, **values):
    """只渲染某一节，用默认值补齐缺失的槽位；用于预算度量与单节对比。"""
    spec = SECTIONS[name]
    defaults = {
        "subjects": "数学", "grade": "初二（八年级）", "textbook": "人教版", "tone": TONE["middle"],
        "strat": "", "taxonomy": "", "extras": "", "problem": "（还没有）", "hint_level": 0,
        "stuck": 0, "allow_full": "否", "allow_note": "",
    }
    defaults.update(values)
    return "".join(_wrap(name, spec.text.format(**defaults)))


def _wrap(name, body):
    """还原原始拼接顺序：块之间恰好一个空行。"""
    spec = SECTIONS[name]
    if name == "preamble":
        return body + "\n\n"
    if name == "state":
        return (spec.heading + "\n" if spec.text else "") + body
    return spec.heading + "\n" + body + "\n\n"


def build(*, grade, textbook, band, strat, taxonomy_block, extra_blocks, state_lines, allow_full, subjects):
    """按固定顺序装配；参数全部由调用方算好，这里只负责文本与顺序。"""
    values = {
        "subjects": subjects,
        "grade": grade,
        "textbook": textbook,
        "tone": TONE[band],
        "strat": strat,
        "taxonomy": taxonomy_block,
        "extras": ("\n\n" + extra_blocks) if extra_blocks else "",
        "problem": state_lines["problem"],
        "hint_level": state_lines["hint_level"],
        "stuck": state_lines["stuck"],
        "allow_full": "是" if allow_full else "否",
        "allow_note": state_lines["allow_note"],
    }
    return Build([_wrap(name, SECTIONS[name].text.format(**values)) for name in ORDER])


def guard_fingerprint(tactic=None, pace=None, lessons=()):
    """受保护面的指纹：原则、输出契约、状态里的授权行，外加语气与学科表。

    为什么不止两节：答案授权写在「当前状态」里，语气（TONE）决定能不能用超纲
    方法，学科表会被拼进输出契约。只哈希「原则 + 输出契约」会让这些安全文本
    在指纹不变的情况下被改掉。

    tactic / pace / lessons 是允许随教学效果变化的参数，故意不进指纹，
    否则每个变体都会看起来像「护栏被改」。
    """
    h = hashlib.sha256()
    # 标题与顺序也进指纹：改掉「# 原则」这行标题同样是在动受保护面
    h.update("|".join(ORDER).encode())
    h.update(b"\x00")
    for name in ORDER:
        h.update(SECTIONS[name].heading.encode())
        h.update(b"\x00")
    for name in PROTECTED:
        h.update(name.encode())
        h.update(b"\x00")
        h.update(SECTIONS[name].text.encode())
        h.update(b"\x00")
    for band in sorted(TONE):
        h.update(band.encode())
        h.update(b"\x00")
        h.update(TONE[band].encode())
        h.update(b"\x00")
    h.update("|".join(SUBJECTS).encode())
    return h.hexdigest()
