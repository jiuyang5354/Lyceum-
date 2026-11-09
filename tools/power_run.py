"""功效实验：同一候选在 54 条场景上的配对评估，分两半并行跑，再合并。

用法：python tools/power_run.py A|B
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

CFG = os.path.join(os.environ.get("APPDATA", ""), "Lyceum", "config.json")
conf = json.load(open(CFG, encoding="utf-8"))
os.environ.update(LYCEUM_BASE_URL=conf["base_url"], LYCEUM_API_KEY=conf["api_key"], LYCEUM_MODEL=conf["model"])

from lyceum import llm, optimize  # noqa: E402

llm.BASE_URL, llm.API_KEY, llm.MODEL = conf["base_url"].rstrip("/"), conf["api_key"], conf["model"]
CAND = sys.argv[2] if len(sys.argv) > 2 else "one_question_only"


def live_runner(prompt, scenario):
    out = llm.chat([{"role": "system", "content": prompt},
                    {"role": "user", "content": scenario["turn"]}],
                   json_mode=True, temperature=0.4, max_tokens=700)
    return {"reply": out.get("reply", "") if isinstance(out, dict) else ""}


setattr(live_runner, "synthetic", False)


def main():
    half = 0 if sys.argv[1] == "A" else 1
    scs = optimize.SCENARIOS_EXT
    mid = (len(scs) + 1) // 2
    part = scs[:mid] if half == 0 else scs[mid:]
    cand = next(c for c in optimize.CANDIDATES if c["id"] == CAND)
    r = optimize.evaluate(cand, runner=live_runner, scenarios=part, metric="rubric", samples=2)
    doc = {"half": sys.argv[1], "candidate": CAND, "results": r,
           "usage": {k: v for k, v in llm.USAGE.items() if isinstance(v, (int, float))}}
    path = "scratch/power-%s-%s.json" % (CAND, sys.argv[1])
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    print(json.dumps({"half": sys.argv[1], "lift": r["lift"], "p": r["p_value"],
                      "z": r.get("z_p_value"), "imp": r["improved"], "wor": r["worsened"],
                      "n": r["scenarios"], "usage": doc["usage"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
