"""Offline, synthetic input-token/call benchmark; never invokes a model API.

python tools/benchmark_context.py --repo . --output benchmark.json
Optional development dependency: tiktoken (NOT needed to run Lyceum).
Numbers are o200k_base encodings of message text, not API/billing tokens.
Images, transport framing, generated output and server caching are excluded.
"""
import argparse
import json
from pathlib import Path
import sys
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(Path(args.repo).resolve()))
    from lyceum import agent, llm
    try:
        import tiktoken
    except ImportError:
        raise SystemExit("Benchmark only: install tiktoken in a development environment; runtime needs no dependency.")
    encoder = tiktoken.get_encoding("o200k_base")

    def tokens(messages):
        count = 0
        for message in messages:
            content = message.get("content", "")
            if isinstance(content, str):
                count += len(encoder.encode(content))
            elif isinstance(content, list):
                count += sum(len(encoder.encode(p.get("text", ""))) for p in content if p.get("type") == "text")
        return count

    state = {"problem": "解方程 x^2-5x+6=0", "subject": "数学", "topic": "因式分解", "hint_level": 1, "stuck": 0}
    short = [{"role": "user", "content": state["problem"]}, {"role": "assistant", "content": "先想想两个系数之间的关系。"}]
    long = []
    for i in range(7):
        long.extend([{"role": "user", "content": f"我的第{i}步：x=2/3，请检查。"},
                     {"role": "assistant", "content": "先核对已知条件，再观察符号与计算过程。" * (150 if i < 5 else 3)}])
    cases = [
        ("math_first_turn", {}, [], "解方程 x^2-5x+6=0", None),
        ("math_followup", state, short, "下一步怎么想？", None),
        ("physics_first_turn", {}, [], "物理题：质量2kg的物体受力6N，求加速度", None),
        ("long_history", state, long, "我还是没理解为什么要拆成两个括号", None),
        ("unknown_subject", {}, [], "这道题怎么想？", None),
        ("image_input", state, short, "请先确认图片上的公式", "data:image/png;base64,SYNTHETIC_NOT_A_REAL_IMAGE"),
    ]
    rows = []
    for name, st, hist, text, image in cases:
        ctx = agent._prepare({"grade": 8}, {"state": dict(st)}, text, image, None)
        messages = agent._messages(ctx, {"grade": 8}, hist)
        assert messages[-1]["content"] == ctx["content"]
        rows.append({"case": name, "text_input_tokens": tokens(messages), "messages": len(messages),
                     "model_calls": 1, "context": ctx.get("context_usage")})

    questions = [{"q": "计算 1/2+1/3", "answer": "5/6"}, {"q": "解方程 2x+3=11", "answer": "x=4"}]
    for name, qs, answers in [
        ("grade_all_local", questions, ["5/6", "x=3"]),
        ("grade_mixed", questions + [{"q": "《静夜思》作者", "answer": "李白"}], ["5/6", "x=3", "李白"]),
    ]:
        requests = []
        def fake(messages, **kwargs):
            requests.append(messages)
            n = messages[0]["content"].count("标准答案：")
            return {"results": [{"correct": True, "feedback": "模拟批改。"} for _ in range(n)]}
        with patch.object(llm, "enabled", return_value=True), patch.object(llm, "chat", side_effect=fake):
            result = agent.grade_answers({"grade": 8}, {}, qs, answers)
        expected = [True, False] + ([True] if name == "grade_mixed" else [])
        assert [r["correct"] for r in result] == expected
        rows.append({"case": name, "text_input_tokens": sum(tokens(x) for x in requests),
                     "model_calls": len(requests), "verdicts": expected})

    requests = []
    leaky = {"subject": "数学", "intent": "answer_attempt", "stage": "check", "hint_level": 1,
             "student_correct": True, "solved": True, "reply": "因式分解是 (x-2)(x-3)=0。"}
    wrong = dict(leaky, reply="完全正确！")
    def fake_repair(messages, **kwargs):
        requests.append(messages)
        return dict(leaky if len(requests) == 1 else wrong)
    with patch.object(llm, "enabled", return_value=True), patch.object(llm, "chat", side_effect=fake_repair):
        result, _ = agent.respond({"grade": 8}, {"state": dict(state)}, long, "x=1 或 x=6")
    assert result["student_correct"] is False
    rows.append({"case": "leak_plus_verdict_repair", "text_input_tokens": sum(tokens(x) for x in requests),
                 "model_calls": len(requests), "verdict": False})
    output = {"method": "synthetic/offline; o200k_base text only; no API tokens or learning-outcome claim",
              "repo": str(Path(args.repo).resolve()), "cases": rows}
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
