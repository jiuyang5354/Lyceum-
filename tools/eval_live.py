"""用本机已配置的模型跑离线评估场景（真实模型调用，不是 mock）。

只读：不写数据库、不改代码、不联网上传任何学生数据。
输出：每个候选的 decision / lift / p / improved / worsened，以及 token 用量。
"""
import json
import os
import sys
import time

SAMPLES = int(os.environ.get("LYCEUM_EVAL_SAMPLES", "2"))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

CFG = os.path.join(os.environ.get("APPDATA", ""), "Lyceum", "config.json")
conf = json.load(open(CFG, encoding="utf-8"))
os.environ["LYCEUM_BASE_URL"] = conf["base_url"]
os.environ["LYCEUM_API_KEY"] = conf["api_key"]
os.environ["LYCEUM_MODEL"] = conf["model"]

from lyceum import llm, optimize  # noqa: E402

llm.BASE_URL = conf["base_url"].rstrip("/")
llm.API_KEY = conf["api_key"]
llm.MODEL = conf["model"]


def live_runner(prompt, scenario):
    """把系统提示词交给真实模型，取回它的 reply。"""
    out = llm.chat(
        [{"role": "system", "content": prompt},
         {"role": "user", "content": scenario["turn"]}],
        json_mode=True, temperature=0.4, max_tokens=700,
    )
    reply = out.get("reply") if isinstance(out, dict) else None
    return {"reply": reply if isinstance(reply, str) else json.dumps(out, ensure_ascii=False),
            "stage": (out or {}).get("stage", "") if isinstance(out, dict) else ""}


setattr(live_runner, "synthetic", False)  # 真实模型调用


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    out_path = sys.argv[2] if len(sys.argv) > 2 else "docs/optimize-live.json"
    cands = [c for c in optimize.CANDIDATES if not only or c["id"] == only]
    results, t0 = [], time.time()
    before = {k: v for k, v in llm.USAGE.items() if isinstance(v, (int, float))}
    for c in cands:
        started = time.time()  # noqa: F841
        try:
            r = optimize.evaluate(c, runner=live_runner, metric="rubric",
                                  samples=SAMPLES, scenarios=optimize.SCENARIOS_EXT)
        except Exception as e:  # noqa: BLE001
            r = {"candidate": c["id"], "decision": "error", "error": f"{type(e).__name__}: {e}"}
        r["seconds"] = round(time.time() - started, 1)
        results.append(r)
        print(json.dumps({k: r.get(k) for k in
                          ("candidate", "decision", "accept", "lift", "p_value",
                           "improved", "worsened", "scenarios", "seconds", "error")},
                         ensure_ascii=False), flush=True)
    usage = {k: llm.USAGE.get(k, 0) - v for k, v in before.items()}
    doc = {"model": llm.MODEL, "metric": "rubric", "samples": SAMPLES, "base_url": llm.BASE_URL, "synthetic": False,
           "scenario_source": "hand-written fixtures (not student data)",
           "guard": __import__("lyceum.prompts", fromlist=["x"]).guard_fingerprint(),
           "usage": usage, "elapsed_s": round(time.time() - t0, 1), "results": results}
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    print(json.dumps({"usage": usage, "elapsed_s": doc["elapsed_s"], "out": out_path}, ensure_ascii=False))


if __name__ == "__main__":
    main()
