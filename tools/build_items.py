"""生成 lyceum/items.json：题库 v1（全部可用确定性方法判分）。

每题都带 params，测试会用 params 独立复算答案，防止「答案写错但没人发现」。
只覆盖能用数值/分数判分的模板；作文、阅读这类主观题不进这个库。
"""
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from lyceum.itembank import prior  # 先验公式只有一处定义，避免两处分叉


def make(items, subject, band, topic, stem, answer, params, steps=1, ops=1, unit="", tags=()):
    items.append({"id": "%s-%03d" % (params["kind"], len(items) + 1), "subject": subject, "band": band,
                  "topic": topic, "stem": stem, "answer": str(answer), "unit": unit,
                  "steps": steps, "ops": ops, "params": params, "tags": list(tags)})


def build(seed=20261109):
    rnd = random.Random(seed)
    it = []

    # —— 小学数学 ——
    for _ in range(6):
        a, b = rnd.randint(2, 9), rnd.randint(2, 9)
        make(it, "数学", "primary", "表内乘法", "计算：%d × %d" % (a, b), a * b,
             {"kind": "mul", "a": a, "b": b})
    for _ in range(6):
        a, b = rnd.randint(20, 79), rnd.randint(10, 20)
        make(it, "数学", "primary", "100以内加减法", "计算：%d + %d" % (a, b), a + b,
             {"kind": "add", "a": a, "b": b})
    for _ in range(5):
        w, h = rnd.randint(3, 12), rnd.randint(2, 9)
        make(it, "数学", "primary", "周长", "一个长方形长 %d 厘米、宽 %d 厘米，周长是多少厘米？" % (w, h), 2 * (w + h),
             {"kind": "perimeter", "w": w, "h": h}, steps=2, ops=3, unit="厘米")

    # —— 初中数学 ——
    for _ in range(12):
        a, x, b = rnd.randint(2, 9), rnd.randint(2, 12), rnd.randint(1, 30)
        c = a * x + b
        make(it, "数学", "middle", "一元一次方程", "解方程：%dx + %d = %d" % (a, b, c), x,
             {"kind": "linear", "a": a, "b": b, "c": c})
    for _ in range(8):
        x, y = rnd.randint(1, 9), rnd.randint(1, 9)
        # x + y = s; x - y = d，问 x
        make(it, "数学", "middle", "二元一次方程组",
             "解方程组：x + y = %d，x − y = %d。求 x。" % (x + y, x - y), x,
             {"kind": "system2", "x": x, "y": y}, steps=2, ops=4)
    for _ in range(10):
        p, q = rnd.randint(1, 9), rnd.randint(1, 9)
        b, c = p + q, p * q
        make(it, "数学", "middle", "因式分解",
             "把 x² + %dx + %d 分解成 (x + p)(x + q)（p < q），求 p。" % (b, c), min(p, q),
             {"kind": "factor", "p": p, "q": q}, steps=2, ops=3)
    for _ in range(10):
        p, q = rnd.randint(1, 9), rnd.randint(1, 9)
        make(it, "数学", "middle", "一元二次方程",
             "解方程：x² − %dx + %d = 0，求较大的根。" % (p + q, p * q), max(p, q),
             {"kind": "quadratic", "p": p, "q": q}, steps=2, ops=4)
    for _ in range(8):
        a, b, c, d = rnd.randint(2, 6), rnd.randint(1, 9), rnd.randint(2, 5), rnd.randint(1, 9)
        make(it, "数学", "middle", "整式的乘法",
             "展开 (%dx + %d)(%dx + %d)，一次项系数是多少？" % (a, b, c, d), a * d + b * c,
             {"kind": "expand", "a": a, "b": b, "c": c, "d": d}, steps=3, ops=4)
    for t in [(3, 4), (6, 8), (5, 12), (8, 15), (7, 24), (9, 12)]:
        a, b = t
        make(it, "数学", "middle", "勾股定理",
             "直角三角形两条直角边分别是 %d 和 %d，斜边是多少？" % (a, b), int((a * a + b * b) ** 0.5),
             {"kind": "pythagoras", "a": a, "b": b}, steps=2, ops=3)
    for _ in range(8):
        den = rnd.choice([5, 7, 9, 11, 12])
        a, b = rnd.randint(1, den - 1), rnd.randint(1, den - 1)
        make(it, "数学", "middle", "分数加减法",
             "计算：%d/%d + %d/%d（结果写成最简分数）" % (a, den, b, den), "%d/%d" % (a + b, den),
             {"kind": "fracadd", "a": a, "b": b, "den": den}, steps=2, ops=2)
    for _ in range(6):
        price, off = rnd.choice([200, 300, 400, 500]), rnd.choice([10, 20, 25, 50])
        make(it, "数学", "middle", "百分数",
             "一件商品原价 %d 元，打 %d 折（即降价 %d%%）后是多少元？" % (price, 10 - off // 10, off),
             price * (100 - off) // 100, {"kind": "discount", "price": price, "off": off}, steps=2, ops=2, unit="元")
    for _ in range(6):
        w, h = rnd.randint(3, 15), rnd.randint(2, 12)
        make(it, "数学", "middle", "多边形的面积",
             "一个三角形的底是 %d 厘米、高是 %d 厘米，面积是多少平方厘米？" % (w, h), "%d/2" % (w * h) if (w * h) % 2 else w * h // 2,
             {"kind": "triarea", "w": w, "h": h}, steps=2, ops=2, unit="平方厘米")

    # —— 高中数学 ——
    for _ in range(6):
        a1, d, n = rnd.randint(1, 9), rnd.randint(2, 7), rnd.randint(5, 12)
        make(it, "数学", "high", "等差数列", "等差数列首项 %d、公差 %d，第 %d 项是多少？" % (a1, d, n), a1 + (n - 1) * d,
             {"kind": "ap", "a1": a1, "d": d, "n": n}, steps=2, ops=3)
    for _ in range(6):
        a1, q, n = rnd.randint(1, 4), rnd.randint(2, 3), rnd.randint(3, 6)
        make(it, "数学", "high", "等比数列", "等比数列首项 %d、公比 %d，第 %d 项是多少？" % (a1, q, n), a1 * q ** (n - 1),
             {"kind": "gp", "a1": a1, "q": q, "n": n}, steps=2, ops=3)
    from fractions import Fraction
    for s in (6, 7, 8, 9, 10, 11):
        ways = sum(1 for a in range(1, 7) for b in range(1, 7) if a + b == s)
        prob = Fraction(ways, 36)
        make(it, "数学", "high", "概率",
             "同时抛两枚均匀骰子，点数之和为 %d 的概率是多少？（写成分数）" % s,
             "%d/%d" % (prob.numerator, prob.denominator),
             {"kind": "dice", "sum": s, "ways": ways}, steps=3, ops=4)

    # —— 初中物理 ——
    for _ in range(6):
        r, i = rnd.choice([5, 10, 15, 20]), rnd.choice([0.2, 0.3, 0.5, 1.0])
        make(it, "物理", "middle", "欧姆定律", "一个 %s 欧的电阻，通过 %s 安的电流，两端电压是多少伏？" % (r, i),
             round(r * i, 2), {"kind": "ohm", "r": r, "i": i}, steps=2, ops=2, unit="伏")
    for _ in range(5):
        u, i = rnd.choice([3, 6, 12, 24]), rnd.choice([0.5, 1, 2])
        make(it, "物理", "middle", "电功率", "某用电器两端电压 %s 伏、电流 %s 安，电功率是多少瓦？" % (u, i),
             round(u * i, 2), {"kind": "power", "u": u, "i": i}, steps=2, ops=2, unit="瓦")
    for _ in range(5):
        m, v = rnd.choice([200, 400, 540, 800]), rnd.choice([100, 200, 250, 400])
        make(it, "物理", "middle", "质量与密度", "质量 %d 克、体积 %d 立方厘米，密度是多少克每立方厘米？" % (m, v),
             round(m / v, 2), {"kind": "density", "m": m, "v": v}, steps=2, ops=2, unit="克/立方厘米")
    for _ in range(5):
        f, s = rnd.choice([100, 200, 400]), rnd.choice([2, 4, 5])
        make(it, "物理", "middle", "压强", "压力 %d 牛，受力面积 %d 平方米，压强是多少帕？" % (f, s),
             round(f / s, 2), {"kind": "pressure", "f": f, "s": s}, steps=2, ops=2, unit="帕")

    # —— 初中化学 ——
    comps = [("H2O", {"H": 1, "O": 16}), ("CO2", {"C": 12, "O": 16}), ("NaCl", {"Na": 23, "Cl": 35.5}),
             ("CaCO3", {"Ca": 40, "C": 12, "O": 16}), ("NaOH", {"Na": 23, "O": 16, "H": 1}),
             ("H2SO4", {"H": 1, "S": 32, "O": 16})]
    for formula, atoms in comps:
        ar = "、".join("%s 的相对原子质量为 %s" % (k, v) for k, v in atoms.items())
        total = sum(atoms.values())
        make(it, "化学", "middle", "化学式与化合价", "已知 %s，%s 的相对分子质量是多少？" % (ar, formula), total,
             {"kind": "molarmass", "atoms": atoms}, steps=3, ops=3)
    # —— 高中化学 ——
    for _ in range(5):
        m, M = rnd.choice([4.4, 8.8, 16]), rnd.choice([44, 44, 32])
        make(it, "化学", "high", "物质的量", "质量 %s 克、摩尔质量 %s 克每摩尔的物质，物质的量是多少摩尔？" % (m, M),
             round(m / M, 3), {"kind": "amount", "m": m, "M": M}, steps=2, ops=2, unit="摩尔")

    for item in it:
        item["difficulty_prior"] = prior(item["band"], item["steps"], item["ops"])
    return it


def main():
    items = build()
    path = os.path.join(ROOT, "lyceum", "items.json")
    doc = {"version": 1,
           "note": "题库 v1：只收能用数值/分数确定性判分的题；答案可由 params 复算。",
           "items": items}
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print("wrote %d items -> %s" % (len(items), path))


if __name__ == "__main__":
    main()
