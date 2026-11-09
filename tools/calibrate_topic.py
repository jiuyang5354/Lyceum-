"""校准「语义切题」：用构造样例测模型是否按设计判，而不是自说自话。

这不是人工标注集。每条样例的 expect 是按判定标准**构造**出来的（label_source=constructed），
所以它只能回答一个问题：模型在这套设计下是否稳定、证据是否可核；
它不能证明教学效果，也不能替代老师打分。

用法：
  python tools/calibrate_topic.py                    # 读默认样例，真实模型调用
  python tools/calibrate_topic.py --dry              # 只校验样例格式，不调模型
  python tools/calibrate_topic.py --out scratch/topic-cal.json --workers 4

样例格式（JSONL）：
  {"task": "...", "text": "...", "subject": "语文|英语", "band": "primary|middle|high",
   "expect": "on_topic|partial|off_topic", "label_source": "constructed|human", "note": "..."}
把 label_source 改成 human 就能接老师标注，代码不用动。
"""
import argparse
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lyceum import writing  # noqa: E402

LABELS = ("on_topic", "partial", "off_topic")
DEFAULT_DATA = os.path.join(ROOT, "tests", "fixtures", "topic-cases.jsonl")


def load_cases(path):
    """读样例并校验；坏行直接报错，不静默跳过。"""
    cases = []
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError as exc:
                raise ValueError("第 %d 行不是 JSON：%s" % (n, exc))
            for key in ("task", "text", "expect"):
                if not str(row.get(key) or "").strip():
                    raise ValueError("第 %d 行缺少 %s" % (n, key))
            if row["expect"] not in LABELS:
                raise ValueError("第 %d 行的 expect 不在 %s 里" % (n, "|".join(LABELS)))
            cases.append(row)
    return cases


def summarize(rows):
    """纯函数：给每行 {expect, got}，算准确率、混淆矩阵、证据命中率。"""
    rows = list(rows)
    n = len(rows)
    ok = sum(1 for r in rows if r.get("got") == r.get("expect"))
    matrix = {e: Counter() for e in LABELS}
    for r in rows:
        got = r.get("got")
        matrix.setdefault(r.get("expect"), Counter())[got or "error"] += 1
    per_label = {}
    for label in LABELS:
        total = sum(matrix.get(label, Counter()).values())
        hit = matrix.get(label, Counter()).get(label, 0)
        per_label[label] = {"n": total, "hit": hit,
                            "recall": round(hit / total, 3) if total else None}
    evidence = [r for r in rows if r.get("evidence")]
    evidence_ok = sum(1 for r in evidence if r.get("evidence_ok"))
    lat = [r["latency"] for r in rows if isinstance(r.get("latency"), (int, float))]
    return {"n": n, "ok": ok, "accuracy": round(ok / n, 3) if n else None,
            "per_label": per_label, "matrix": {k: dict(v) for k, v in matrix.items()},
            "evidence_n": len(evidence),
            "evidence_rate": round(evidence_ok / len(evidence), 3) if evidence else None,
            "latency_avg": round(sum(lat) / len(lat), 2) if lat else None,
            "mismatches": [{"task": r["task"][:24], "expect": r["expect"], "got": r.get("got"),
                            "why": r.get("why", "")} for r in rows if r.get("got") != r.get("expect")]}


def _configure_llm(config_path):
    """真实调用：从本机 config.json 取地址/模型，值不打印、不落盘。"""
    conf = json.load(open(config_path, encoding="utf-8"))
    from lyceum import llm
    llm.BASE_URL = str(conf.get("base_url", "")).rstrip("/")
    llm.API_KEY = str(conf.get("api_key", ""))
    llm.MODEL = str(conf.get("model", ""))
    if not llm.API_KEY:
        raise SystemExit("config.json 里没有 api_key，无法做真实校准")
    return llm


def run(cases, llm, workers=4):
    def one(case):
        t = time.time()
        topic, why = writing.semantic_topic(case["text"], case["task"], case.get("subject", "语文"),
                                            case.get("band", "middle"), chat=llm.chat)
        dt = round(time.time() - t, 2)
        if not topic:
            return {"task": case["task"], "expect": case["expect"], "got": None,
                    "latency": dt, "why": why}
        return {"task": case["task"], "expect": case["expect"], "got": topic["verdict"],
                "evidence": topic["evidence"],
                "evidence_ok": topic["evidence"].replace(" ", "") in case["text"].replace(" ", ""),
                "latency": dt, "why": topic["reason"]}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return list(pool.map(one, cases))


def main(argv=None):
    ap = argparse.ArgumentParser(description="校准写作「语义切题」")
    ap.add_argument("--data", default=DEFAULT_DATA)
    ap.add_argument("--out", default="")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry", action="store_true", help="只校验样例，不调用模型")
    ap.add_argument("--config", default=os.path.join(os.environ.get("APPDATA", ""), "Lyceum", "config.json"))
    args = ap.parse_args(argv)

    cases = load_cases(args.data)
    if args.limit:
        cases = cases[:args.limit]
    dist = Counter(c["expect"] for c in cases)
    sources = Counter(c.get("label_source", "constructed") for c in cases)
    print("样例 %d 条 · %s · 标签来源 %s" % (len(cases), dict(dist), dict(sources)))
    if args.dry:
        print("dry-run：格式校验通过，未调用模型")
        return 0

    llm = _configure_llm(args.config)
    rows = run(cases, llm, args.workers)
    summary = summarize(rows)
    print("准确率 %s（%d/%d）· 证据命中 %s · 平均 %.2fs"
          % (summary["accuracy"], summary["ok"], summary["n"], summary["evidence_rate"],
             summary["latency_avg"] or 0))
    for label, st in summary["per_label"].items():
        print("  %-9s 召回 %s（%d/%d）" % (label, st["recall"], st["hit"], st["n"]))
    for m in summary["mismatches"]:
        print("  ✗ %s：期望 %s，得到 %s — %s" % (m["task"], m["expect"], m["got"], m["why"]))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump({"data": os.path.basename(args.data), "synthetic": False,
                       "labels": dict(sources), "summary": summary, "rows": rows},
                      fh, ensure_ascii=False, indent=1)
        print("写入 %s" % args.out)
    return 0 if summary["accuracy"] and summary["accuracy"] >= 0.8 else 2


if __name__ == "__main__":
    raise SystemExit(main())
