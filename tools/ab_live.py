"""A/B：新提示词（含「每轮只问一个问题」）vs 旧提示词（去掉该行），同一批场景。

旧文本 = 新文本删掉那一行（已在 prompt-golden 上逐字节验证只有这一行差异）。
真实模型调用，rubric 打分，每臂 2 次采样。
"""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

CFG = os.path.join(os.environ.get("APPDATA", ""), "Lyceum", "config.json")
conf = json.load(open(CFG, encoding="utf-8"))
os.environ.update(LYCEUM_BASE_URL=conf["base_url"], LYCEUM_API_KEY=conf["api_key"], LYCEUM_MODEL=conf["model"])

from lyceum import llm, optimize, prompts  # noqa: E402

llm.BASE_URL, llm.API_KEY, llm.MODEL = conf["base_url"].rstrip("/"), conf["api_key"], conf["model"]
SAMPLES = 2


def ask(prompt, scenario):
    out = llm.chat([{"role": "system", "content": prompt},
                    {"role": "user", "content": scenario["turn"]}],
                   json_mode=True, temperature=0.4, max_tokens=700)
    return out.get("reply", "") if isinstance(out, dict) else ""


def main():
    rows = []
    for sc in optimize.SCENARIOS_EXT:
        new_p = optimize.prompt_for(sc)
        old_p = new_p.replace(prompts.STRATEGY_RULE + "\n", "", 1)
        assert old_p != new_p, sc["id"]
        vals = {"old": [], "new": []}
        for _ in range(SAMPLES):
            vals["old"].append(optimize.rubric_score(ask(old_p, sc), sc))   # 交替
            vals["new"].append(optimize.rubric_score(ask(new_p, sc), sc))
        old = round(sum(vals["old"]) / SAMPLES, 4)
        new = round(sum(vals["new"]) / SAMPLES, 4)
        rows.append({"scenario": sc["id"], "old": old, "new": new, "diff": round(new - old, 4)})
        print(json.dumps(rows[-1], ensure_ascii=False), flush=True)

    diffs = [r["diff"] for r in rows]
    pos = sum(1 for d in diffs if d > 0)
    neg = sum(1 for d in diffs if d < 0)
    doc = {"model": llm.MODEL, "metric": "rubric", "samples": SAMPLES, "scenarios": len(rows),
           "lift": round(sum(diffs) / len(diffs), 4), "improved": pos, "worsened": neg,
           "p_value": round(optimize._sign_test_p(pos, neg), 6), "rows": rows,
           "usage": {k: v for k, v in llm.USAGE.items() if isinstance(v, (int, float))}}
    with open("docs/optimize-ab.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    print(json.dumps({k: doc[k] for k in ("lift", "improved", "worsened", "p_value", "usage")}, ensure_ascii=False))


if __name__ == "__main__":
    t0 = time.time()
    main()
    print("elapsed %.0fs" % (time.time() - t0))
