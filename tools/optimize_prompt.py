"""跑一次离线提示词评估，把决策写进 JSON。

用法：
    python tools/optimize_prompt.py --out optimize-report.json
    python tools/optimize_prompt.py --candidate restate_first --out one.json

注意：默认 runner 是离线 mock，报告里 synthetic=true。它只证明门禁和管线可用，
不代表真实模型或真实学生的效果。接真实模型时替换 lyceum.optimize 里的 runner，
并把它标记成 synthetic=false。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lyceum import optimize, prompts  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description="评估一个提示词候选（离线、可审计）")
    ap.add_argument("--candidate", help="候选 id；不给就逐个评估并取第一个被接受的")
    ap.add_argument("--out", default="optimize-report.json")
    ap.add_argument("--require-guard", help="冻结的受保护面指纹；不匹配就拒绝")
    args = ap.parse_args(argv)

    if args.candidate:
        cand = next((c for c in optimize.CANDIDATES if c["id"] == args.candidate), None)
        if cand is None:
            ap.error("未知候选：%s（可用：%s）" % (args.candidate, ", ".join(c["id"] for c in optimize.CANDIDATES)))
        result = optimize.evaluate(cand, locked_guard=args.require_guard)
    else:
        result = optimize.propose(locked_guard=args.require_guard)

    if not result:
        ap.error("没有可评估的候选")
    optimize.report(result, args.out)
    print(json.dumps({"decision": result["decision"], "accept": result["accept"],
                      "candidate": result["candidate"], "lift": result["lift"],
                      "ci": [result["ci_low"], result["ci_high"]],
                      "synthetic": result["synthetic"], "out": args.out}, ensure_ascii=False))
    print("guard=%s" % prompts.guard_fingerprint()[:16])


if __name__ == "__main__":
    main()
