"""知识点先修关系：给「下一步练什么」一个能说清楚的依据。

为什么需要
  BKT 回答「这个知识点掌握了吗」，但不回答「现在该练哪一个」。没有先修关系时，
  推荐的只能是「到期的那一个」或「掌握度最低的那一个」，遇到「二次函数没会、
  其实是一元二次方程没会」这种情况就补错了地方。

设计
  - 数据在 lyceum/prereq.json，只写**直接**前置，跨学段（小学→初中）允许。
  - 导入时校验：每个名字必须真实存在于 taxonomy.json 的同一学科里；不允许自环、
    不允许环。数据错了在导入时就炸，而不是等学生用到才出错。
  - 纯函数，不碰数据库、不调模型，可离线单测。

不做的事
  不排序整份课程、不做自适应选题算法、不给提示词加内容。这里只输出
  「推荐哪个知识点 + 一句为什么」，剩下交给调用方。
"""
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
PREREQ_FILE = os.path.join(_HERE, "prereq.json")
TAXONOMY_FILE = os.path.join(_HERE, "taxonomy.json")

MASTERY_P = 0.85   # 与 mastery.MASTERY_P 同口径：低于它就算「还没稳」


def _load_taxonomy_topics(path=TAXONOMY_FILE):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    out = {}
    for subject, bands in data["subjects"].items():
        names = set()
        for items in bands.values():
            for row in items:
                names.add(row.split("|")[0])
        out[subject] = names
    return out


def load_edges(path=PREREQ_FILE, topics=None):
    """读入并校验先修表；返回 {subject: {topic: (prereq, ...)}}。"""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    topics = topics if topics is not None else _load_taxonomy_topics()
    out = {}
    for subject, rows in data.get("edges", {}).items():
        if subject not in topics:
            raise ValueError("先修表里的学科不在知识点表里：%s" % subject)
        table = {}
        for topic, prereqs in rows:
            if topic not in topics[subject]:
                raise ValueError("%s 的知识点不在 taxonomy.json 里：%s" % (subject, topic))
            for p in prereqs:
                if p not in topics[subject]:
                    raise ValueError("%s 的前置不在 taxonomy.json 里：%s -> %s" % (subject, topic, p))
                if p == topic:
                    raise ValueError("%s 不能以自己为前置" % topic)
            table[topic] = tuple(prereqs)
        out[subject] = table
    _check_cycles(out)
    return out


def _check_cycles(edges):
    for subject, table in edges.items():
        WHITE, GREY, BLACK = 0, 1, 2
        color = {}

        def visit(node, stack):
            color[node] = GREY
            for p in table.get(node, ()):
                c = color.get(p, WHITE)
                if c == GREY:
                    raise ValueError("%s 的先修关系成环：%s" % (subject, " → ".join(stack + [node, p])))
                if c == WHITE:
                    visit(p, stack + [node])
            color[node] = BLACK

        for node in table:
            if color.get(node, WHITE) == WHITE:
                visit(node, [])


EDGES = load_edges()


def prereqs(subject, topic):
    """直接前置。"""
    return EDGES.get(subject, {}).get(topic, ())


def chain(subject, topic):
    """全部祖先，按「先学 → 后学」排序（拓扑序，去重）。"""
    table = EDGES.get(subject, {})
    seen, order = set(), []
    stack = [(topic, False)]
    while stack:
        node, done = stack.pop()
        if done:
            if node not in seen:
                seen.add(node)
                order.append(node)
            continue
        if node in seen:
            continue
        stack.append((node, True))
        for p in reversed(table.get(node, ())):
            if p not in seen:
                stack.append((p, False))
    return [t for t in order if t != topic]


def blockers(subject, topic, mastery):
    """直接前置里还没稳的，按「有证据的优先、再按掌握度从低到高」排序。

    为什么把「从没学过」排在后面：一个 0.00 的未知知识点可能是两年前就该会的，
    也可能是根本没接触过的前置课。先补学生**确实在练、但没稳住**的那一步，
    比直接跳到一个陌生知识点更容易接上。
    """
    weak = []
    for p in prereqs(subject, topic):
        known = (subject, p) in mastery or p in mastery
        value = mastery.get((subject, p), mastery.get(p))
        value = 0.0 if value is None else float(value)
        if value < MASTERY_P:
            weak.append({"topic": p, "p_l": round(value, 2), "seen": known})
    weak.sort(key=lambda r: (0 if r["seen"] else 1, r["p_l"], r["topic"]))
    return weak


def recommend(mastery, due=(), today=None):
    """下一步练什么，以及为什么。

    mastery: {(subject, topic): p_l}
    due:     已到期、可以复习的知识点 [(subject, topic), ...]
    返回 {"subject","topic","reason","p_l","blocked_by"} 或 None。
    """
    due = [(s, t) for s, t in due]
    if due:
        subject, target = min(due, key=lambda k: (mastery.get(k, 0.0), k))
        head, path = _root_cause(subject, target, mastery)
        if head != target:
            return {"subject": subject, "topic": head, "p_l": _p(subject, head, mastery),
                    "blocked_by": head,
                    "reason": _blocked_reason(subject, head, mastery, path)}
        p = _p(subject, target, mastery)
        return {"subject": subject, "topic": target, "p_l": p, "blocked_by": None,
                "reason": "到期复习，上次掌握度 %.2f" % p}
    # 没到期：从最弱的一个出发，往先修链下面走，直到找到「确实在练但没稳住」的那一步
    if mastery:
        (subject, topic), value = min(mastery.items(), key=lambda kv: (kv[1], kv[0]))
        head, path = _root_cause(subject, topic, mastery)
        if head != topic:
            return {"subject": subject, "topic": head, "p_l": _p(subject, head, mastery),
                    "blocked_by": head, "reason": _blocked_reason(subject, head, mastery, path)}
        return {"subject": subject, "topic": topic, "p_l": round(float(value), 2), "blocked_by": None,
                "reason": "还没到期，但掌握度只有 %.2f，建议先巩固" % float(value)}
    return None


def _p(subject, topic, mastery):
    value = mastery.get((subject, topic), mastery.get(topic))
    return 0.0 if value is None else round(float(value), 2)


def _root_cause(subject, topic, mastery, depth=3):
    """沿先修链往下找「确实在练、但没稳住」的那一步。

    只在**有作答证据**的前置上继续往下走：没学过的知识点往更早的课追，会推到
    两三个学期以前，对学生没有帮助。遇到没学过的就停在当前这一步。
    """
    path, node = [], topic
    for _ in range(depth):
        weak = blockers(subject, node, mastery)
        if not weak:
            break
        seen = [w for w in weak if w["seen"]]
        if not seen:
            if node == topic:
                node = weak[0]["topic"]
            break
        node = seen[0]["topic"]
        path.append(node)
    return node, path


def _blocked_reason(subject, head, mastery, path):
    known = (subject, head) in mastery or head in mastery
    state = ("还没稳（%.2f < %.2f）" % (_p(subject, head, mastery), MASTERY_P)) if known else "还没学过（0.00）"
    target = path[-2] if len(path) >= 2 else None
    tail = ("，先补这一步再看 %s" % target) if target and target != head else "，先补这一步"
    return head + " " + state + tail
