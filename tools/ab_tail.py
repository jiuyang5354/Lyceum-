"""A/B：把追问规则放到生产位置（紧贴「当前状态」之前）后，是否复现 54 场景上的效应。

new = agent 现在的提示词；old = 去掉那一块。每臂 2 次采样，分两半并行。
用法：python tools/ab_tail.py A|B
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

CFG = os.path.join(os.environ.get("APPDATA", ""), "Lyceum", "config.json")
conf = json.load(open(CFG, encoding="utf-8"))
os.environ.update(LYCEUM_BASE_URL=conf["base_url"], LYCEUM_API_KEY=conf["api_key"], LYCEUM_MODEL=conf["model"])

from lyceum import llm, optimize, prompts  # noqa: E402

llm.BASE_URL, llm.API_KEY, llm.MODEL = conf["base_url"].rstrip("/"), conf["api_key"], conf["model"]
BLOCK = prompts.FOLLOWUP_RULE + "\n\n"


def ask(prompt, scenario):
    out = llm.chat([{"role": "system", "content": prompt},
                    {"role": "user", "content": scenario["turn"]}],
                   json_mode=True, temperature=0.4, max_tokens=700)
    return out.get("reply", "") if isinstance(out, dict) else ""


def main():
    half = 0 if sys.argv[1] == "A" else 1
    scs = optimize.SCENARIOS_EXT
    mid = (len(scs) + 1) // 2
    part = scs[:mid] if half == 0 else scs[mid:]
    rows = []
    for sc in part:
        new_p = optimize.prompt_for(sc)
        old_p = new_p.replace(BLOCK, "", 1)
        assert old_p != new_p, sc["id"]
        vals = {"old": [], "new": []}
        for _ in range(2):
            vals["old"].append(optimize.rubric_score(ask(old_p, sc), sc))
            vals["new"].append(optimize.rubric_score(ask(new_p, sc), sc))
        rows.append({"scenario": sc["id"],
                     "old": round(sum(vals["old"]) / 2, 4),
                     "new": round(sum(vals["new"]) / 2, 4)})
        rows[-1]["diff"] = round(rows[-1]["new"] - rows[-1]["old"], 4)
        print(json.dumps(rows[-1], ensure_ascii=False), flush=True)

    path = "scratch/abtail-%s.json" % sys.argv[1]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"half": sys.argv[1], "rows": rows,
                   "usage": {k: v for k, v in llm.USAGE.items() if isinstance(v, (int, float))}}, f,
                  ensure_ascii=False, indent=2)
    print(json.dumps({"half": sys.argv[1], "rows": len(rows)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
