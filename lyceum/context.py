"""Deterministic context selection: no summarizer call, no student-text rewriting.

The character budget is soft: preserve the newest two complete exchanges even
when they exceed it. Current input, problem state and safety policy are outside
this optional-history budget. Characters are NOT provider token counts.
"""
import os

DEFAULT_HISTORY_CHARS = 6000
OMITTED_NOTICE = "较早的对话已省略；以当前题干和保留的学生作答为准。若缺少早先条件或步骤，先请学生补充，不要猜测。"


def repair_messages(messages, draft, instruction):
    """Keep policy, two recent exchanges, current input, draft and repair rules.

    Preserve the current multimodal message verbatim; no image/number rewriting.
    """
    # A zero soft budget retains the mandatory newest two complete exchanges,
    # preserving referenced student work without replaying older conversation.
    recent, _ = select_history(messages[1:-1], limit=len(messages), max_chars=0)
    return [messages[0], *recent, messages[-1], {"role": "assistant", "content": draft}, instruction]


def history_budget():
    try:
        value = int(os.environ.get("LYCEUM_HISTORY_CHARS", DEFAULT_HISTORY_CHARS))
    except (TypeError, ValueError):
        value = DEFAULT_HISTORY_CHARS
    return max(1000, min(24000, value))


def select_history(messages, limit=14, max_chars=None):
    """Return (whole recent exchanges, text-only accounting); never mutate input."""
    budget = history_budget() if max_chars is None else max(0, int(max_chars))
    normalized = []
    for message in messages or []:
        role = message.get("role")
        if role not in ("user", "assistant"):
            continue
        text = message.get("content") or ""
        if not isinstance(text, str):
            continue
        if role == "user" and message.get("image"):
            text = (text + "\n[学生之前上传过一张题目图片，题干已转写在当前状态里]").strip()
        normalized.append({"role": role, "content": text})
    window = normalized[-max(0, limit):] if limit > 0 else []
    groups = []
    for message in window:
        if message["role"] == "user":
            groups.append([message])
        elif groups:
            groups[-1].append(message)
    chosen, used = [], 0
    for group in reversed(groups):
        size = sum(len(m["content"]) for m in group)
        if len(chosen) >= 2 and used + size > budget:
            break
        chosen.append(group)
        used += size
    selected = [m for group in reversed(chosen) for m in group]
    return selected, {
        "history_input_chars": sum(len(m["content"]) for m in normalized),
        "history_sent_chars": used,
        "history_omitted_messages": len(normalized) - len(selected),
        "history_budget_chars": budget,
        "history_budget_exceeded": used > budget,
    }
