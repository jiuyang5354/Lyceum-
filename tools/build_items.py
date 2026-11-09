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

    # —— 第二批：初中代数的其余主干 ——
    for _ in range(8):
        a, b, c = rnd.choice([2, 3, 4, 5]), rnd.randint(1, 9), rnd.randint(10, 30)
        # a x + b < c 的最大整数解
        k = (c - b - 1) // a
        make(it, "数学", "middle", "不等式与不等式组",
             "解不等式：%dx + %d < %d，x 的最大整数值是多少？" % (a, b, c), k,
             {"kind": "ineq", "a": a, "b": b, "c": c}, steps=2, ops=3)
    for _ in range(8):
        a, b, c = rnd.randint(2, 9), rnd.randint(1, 5), rnd.randint(2, 6)
        make(it, "数学", "middle", "有理数的运算",
             "计算：−%d + %d × %d" % (a, b, c), -a + b * c, {"kind": "negops", "a": a, "b": b, "c": c}, steps=2, ops=2)
    for _ in range(6):
        a, b, x = rnd.choice([2, 3, 4]), rnd.choice([1, 3, 5]), rnd.choice([2, 3, 4])
        # (a x + b) / x at x → a + b/x
        val = a + Fraction(b, x)
        make(it, "数学", "middle", "分式",
             "当 x = %d 时，分式 (%dx + %d)/x 的值是多少？（写成分数或整数）" % (x, a, b),
             "%d/%d" % (val.numerator, val.denominator), {"kind": "fracval", "a": a, "b": b, "x": x},
             steps=2, ops=3)
    for _ in range(6):
        a, b = rnd.choice([2, 3, 5]), rnd.choice([2, 3, 5])
        make(it, "数学", "middle", "二次根式",
             "计算：√%d × √%d" % (a * a, b * b), a * b, {"kind": "sqrt", "a": a, "b": b}, steps=1, ops=2)
    for _ in range(6):
        a, b = rnd.randint(2, 12), rnd.choice([4, 9, 16, 25])
        make(it, "数学", "middle", "实数",
             "计算：|−%d| + √%d" % (a, b), a + int(b ** 0.5), {"kind": "real", "a": a, "b": b}, steps=2, ops=2)
    for _ in range(6):
        k, b, x = rnd.choice([2, 3, -2]), rnd.randint(1, 9), rnd.choice([2, 3, 4, 5])
        make(it, "数学", "middle", "一次函数",
             "一次函数 y = %dx + %d，当 x = %d 时 y 是多少？" % (k, b, x), k * x + b,
             {"kind": "linear_fn", "k": k, "b": b, "x": x}, steps=2, ops=2)
    for _ in range(6):
        k, x = rnd.choice([6, 12, 18, 24]), rnd.choice([2, 3, 4, 6])
        make(it, "数学", "middle", "反比例函数",
             "反比例函数 y = %d/x，当 x = %d 时 y 是多少？" % (k, x), Fraction(k, x),
             {"kind": "inv_fn", "k": k, "x": x}, steps=1, ops=1)
    for _ in range(6):
        a, h, k, x = rnd.choice([1, 2, -1]), rnd.randint(1, 4), rnd.randint(-4, 4), rnd.choice([0, 1, 2, 3])
        make(it, "数学", "middle", "二次函数",
             "二次函数 y = %d(x − %d)² + %d，当 x = %d 时 y 是多少？" % (a, h, k, x), a * (x - h) ** 2 + k,
             {"kind": "quad_fn", "a": a, "h": h, "k": k, "x": x}, steps=3, ops=4)
    for _ in range(6):
        a, b, c = 3, 4, 5
        scale = rnd.choice([2, 3, 4])
        make(it, "数学", "middle", "相似三角形",
             "两个相似三角形对应边之比为 3:%d，小三角形的一条边是 %d，大三角形的对应边是多少？" % (scale * 3, b),
             b * scale, {"kind": "similar", "b": b, "scale": scale}, steps=2, ops=2)
    for _ in range(6):
        opp, adj, hyp = rnd.choice([(3, 4, 5), (5, 12, 13), (8, 15, 17)])
        make(it, "数学", "middle", "锐角三角函数",
             "直角三角形中，对边 %d、邻边 %d、斜边 %d，sin 的值是多少？（写成分数）" % (opp, adj, hyp),
             "%d/%d" % (opp, hyp), {"kind": "trig", "opp": opp, "hyp": hyp}, steps=2, ops=2)
    for _ in range(6):
        r = rnd.choice([1, 2, 3, 4])
        make(it, "数学", "middle", "圆的性质",
             "半径 %d 厘米的圆，周长是多少厘米？（π 取 3.14）" % r, round(2 * 3.14 * r, 2),
             {"kind": "circum", "r": r}, steps=2, ops=2, unit="厘米")
    for _ in range(6):
        red, blue = rnd.randint(2, 5), rnd.randint(1, 4)
        make(it, "数学", "middle", "概率初步",
             "袋子里有 %d 个红球、%d 个蓝球，随机摸一个是红球的概率是多少？（写成分数）" % (red, blue),
             "%d/%d" % (red, red + blue), {"kind": "bag", "red": red, "blue": blue}, steps=2, ops=2)
    for _ in range(6):
        vals = [rnd.randint(60, 100) for _ in range(5)]
        make(it, "数学", "middle", "数据的分析",
             "五个数据 %s 的平均数是多少？" % "、".join(str(v) for v in vals), round(sum(vals) / 5, 2),
             {"kind": "mean", "vals": vals}, steps=2, ops=2)

    # —— 第二批：物理 ——
    for _ in range(6):
        s, t = rnd.choice([120, 240, 360, 600]), rnd.choice([2, 3, 4, 5])
        make(it, "物理", "middle", "机械运动",
             "物体在 %d 秒内运动了 %d 米，平均速度是多少米每秒？" % (t, s), round(s / t, 2),
             {"kind": "speed", "s": s, "t": t}, steps=2, ops=2, unit="米每秒")
    for _ in range(6):
        v = rnd.choice([0.001, 0.002, 0.004])
        make(it, "物理", "middle", "浮力",
             "物体排开水的体积是 %s 立方米，受到的浮力是多少牛？（ρ水=1000 千克每立方米，g 取 10）" % v,
             round(1000 * 10 * float(v), 2), {"kind": "buoyancy", "v": v}, steps=2, ops=3, unit="牛")
    for _ in range(6):
        f, s = rnd.choice([20, 50, 100]), rnd.choice([2, 3, 5])
        make(it, "物理", "middle", "功和机械能", "用 %d 牛的力沿力的方向移动 %d 米，做功多少焦？" % (f, s), f * s,
             {"kind": "work", "f": f, "s": s}, steps=2, ops=2, unit="焦")
    for _ in range(6):
        c, m, dt = 4200, rnd.choice([1, 2, 3]), rnd.choice([10, 20, 30])
        make(it, "物理", "middle", "内能", "质量 %d 千克的水温度升高 %d ℃，吸收的热量是多少焦？（c水=4200 焦每千克摄氏度）" % (m, dt),
             c * m * dt, {"kind": "heat", "c": c, "m": m, "dt": dt}, steps=2, ops=2, unit="焦")

    # —— 第二批：化学 ——
    for _ in range(6):
        solute, total = rnd.choice([10, 20, 25]), rnd.choice([50, 100, 200])
        make(it, "化学", "middle", "溶液",
             "%d 克溶质溶于水配成 %d 克溶液，溶质质量分数是多少？（百分比，保留一位小数）" % (solute, total),
             round(solute / total * 100, 1), {"kind": "massfrac", "solute": solute, "total": total}, steps=2, ops=2, unit="%")
    for _ in range(5):
        h2 = rnd.choice([4, 8, 12])
        # 2H2 + O2 -> 2H2O：m(H2)=2 → 18 g 水，按比例
        make(it, "化学", "middle", "根据化学方程式计算",
             "2H₂ + O₂ → 2H₂O。完全燃烧 %d 克氢气，生成多少克水？（H=1，O=16）" % h2, h2 * 9,
             {"kind": "eqcalc", "h2": h2}, steps=3, ops=4, unit="克")

    # —— 第三批：小学应用与几何 ——
    for _ in range(6):
        m = rnd.choice([1.5, 2.5, 3.2, 4.8])
        make(it, "数学", "primary", "单位换算", "%s 米等于多少厘米？" % m, int(m * 100),
             {"kind": "convert", "m": m}, steps=1, ops=1, unit="厘米")
    for _ in range(6):
        a, k = rnd.randint(2, 6), rnd.randint(2, 5)
        make(it, "数学", "primary", "比和比例", "若 a : b = %d : %d，且 a = %d，则 b 是多少？" % (a, a + k, a),
             a + k, {"kind": "ratio", "a": a, "k": k}, steps=2, ops=2)
    for _ in range(5):
        w, h, d = rnd.randint(2, 9), rnd.randint(2, 9), rnd.randint(2, 6)
        make(it, "数学", "primary", "长方体和正方体", "长 %d、宽 %d、高 %d 的长方体，体积是多少？" % (w, h, d),
             w * h * d, {"kind": "boxvol", "w": w, "h": h, "d": d}, steps=2, ops=3)
    for _ in range(5):
        r, h = rnd.choice([1, 2, 3]), rnd.choice([2, 4, 5])
        make(it, "数学", "primary", "圆柱与圆锥", "底面半径 %d、高 %d 的圆柱，体积是多少？（π 取 3.14）" % (r, h),
             round(3.14 * r * r * h, 2), {"kind": "cylvol", "r": r, "h": h}, steps=3, ops=4)
    for _ in range(6):
        heads, rabbits = rnd.randint(6, 12), rnd.randint(1, 4)
        chickens = heads - rabbits
        make(it, "数学", "primary", "鸡兔同笼",
             "笼子里鸡和兔共 %d 只，腿共 %d 条，兔有几只？" % (heads, chickens * 2 + rabbits * 4), rabbits,
             {"kind": "chicken", "heads": heads, "rabbits": rabbits}, steps=3, ops=4)
    for _ in range(6):
        length, gap = rnd.choice([20, 30, 40, 50]), rnd.choice([2, 4, 5])
        make(it, "数学", "primary", "植树问题", "一条 %d 米的路，每隔 %d 米种一棵树（两端都种），共种多少棵？" % (length, gap),
             length // gap + 1, {"kind": "trees", "length": length, "gap": gap}, steps=2, ops=3)
    for _ in range(6):
        v1, v2 = rnd.choice([40, 50, 60]), rnd.choice([20, 30, 40])
        s = rnd.choice([120, 180, 240])
        make(it, "数学", "primary", "行程问题", "两人相向而行，速度分别是 %d 和 %d，相距 %d，几小时相遇？" % (v1, v2, s),
             round(s / (v1 + v2), 2), {"kind": "travel", "v1": v1, "v2": v2, "s": s}, steps=2, ops=3, unit="小时")

    # —— 第三批：高中与物理 ——
    for _ in range(6):
        a = rnd.choice([1, 2, 3])
        make(it, "数学", "high", "集合", "集合 A = {1, 2, %d}，A 有多少个真子集？" % a, 2 ** 3 - 1,
             {"kind": "subset", "n": 3}, steps=2, ops=2)
    for _ in range(5):
        a, b = rnd.choice([3, 4, 5]), rnd.choice([2, 1, 3])
        make(it, "数学", "high", "复数", "复数 (%d + %di) + (%d − %di) 的实部是多少？" % (a, b, b, a), a + b,
             {"kind": "complex_add", "a": a, "b": b}, steps=2, ops=2)
    for _ in range(5):
        x, y = rnd.choice([2, 3, 4]), rnd.choice([1, 5, 6])
        make(it, "物理", "middle", "简单机械", "杠杆平衡时，动力臂 %d、阻力 %d、阻力臂 %d，动力是多少牛？" % (x * 10, y * 10, 10), round(y * 10 * 10 / (x * 10), 2),
             {"kind": "lever", "l1": x * 10, "f2": y * 10, "l2": 10}, steps=2, ops=3, unit="牛")
    for _ in range(5):
        f, v = rnd.choice([340, 680, 170]), rnd.choice([2, 4, 5])
        make(it, "物理", "middle", "声现象", "声音在空气中速度 %d 米每秒，%d 秒内传播多远？" % (f, v), f * v,
             {"kind": "sound", "v": f, "t": v}, steps=1, ops=2, unit="米")
    for _ in range(5):
        p, t = rnd.choice([500, 1000, 2000]), rnd.choice([2, 5, 10])
        make(it, "物理", "middle", "生活用电", "功率 %d 瓦的用电器工作 %d 小时，消耗多少千瓦时电能？" % (p, t),
             round(p * t / 1000, 2), {"kind": "kwh", "p": p, "t": t}, steps=2, ops=2, unit="千瓦时")

    # —— 第三批：补齐小数/实数/数列之外的主干，并加入生物、地理 ——
    # 小学数学
    for _ in range(6):
        b_, q = rnd.randint(3, 9), rnd.randint(2, 9)
        r = rnd.randint(1, b_ - 1)
        make(it, "数学", "primary", "有余数的除法", "计算：%d ÷ %d 的商是多少？" % (b_ * q + r, b_), q,
             {"kind": "divq", "a": b_ * q + r, "b": b_, "q": q}, steps=1, ops=1)
    for _ in range(6):
        w, h = rnd.randint(3, 12), rnd.randint(2, 9)
        make(it, "数学", "primary", "多边形的面积", "一个长方形长 %d 厘米、宽 %d 厘米，面积是多少平方厘米？" % (w, h), w * h,
             {"kind": "area_rect", "w": w, "h": h}, steps=2, ops=2, unit="平方厘米")
    for _ in range(5):
        m = rnd.randint(2, 9)
        make(it, "数学", "primary", "单位换算", "%d 米等于多少厘米？" % m, m * 100,
             {"kind": "unit_len", "m": m}, steps=1, ops=1, unit="厘米")
    for _ in range(5):
        mean = rnd.randint(20, 60)
        a, b_ = rnd.randint(5, 90), rnd.randint(5, 90)
        c = 3 * mean - a - b_
        if not 1 <= c <= 99:
            c = mean
            a, b_ = mean - 1, mean + 1
        make(it, "数学", "primary", "平均数", "三个数 %d、%d、%d 的平均数是多少？" % (a, b_, c), mean,
             {"kind": "avg3", "vals": [a, b_, c]}, steps=2, ops=3)
    for _ in range(4):
        h = rnd.randint(2, 5)
        make(it, "数学", "primary", "时间与钟表", "%d 小时等于多少分钟？" % h, h * 60,
             {"kind": "time_min", "h": h}, steps=1, ops=1, unit="分钟")
    for _ in range(5):
        pay, price = rnd.choice([5, 10, 20, 50]), rnd.randint(2, 8)
        make(it, "数学", "primary", "人民币", "付 %d 元买 %d 元的文具，应找回多少元？" % (pay, price), pay - price,
             {"kind": "change", "pay": pay, "price": price}, steps=2, ops=1, unit="元")
    for _ in range(5):
        v, t = rnd.choice([40, 50, 60, 80]), rnd.randint(2, 5)
        make(it, "数学", "primary", "行程问题", "汽车每小时行 %d 千米，%d 小时行多少千米？" % (v, t), v * t,
             {"kind": "trip_p", "v": v, "t": t}, steps=2, ops=2, unit="千米")

    # 初中数学补口
    for _ in range(6):
        a = rnd.randint(2, 9)
        make(it, "数学", "middle", "整式的乘法", "展开 (x + %d)(x − %d)，常数项是多少？" % (a, a), -a * a,
             {"kind": "sqdiff_const", "a": a}, steps=2, ops=3)
    for _ in range(5):
        a = rnd.randint(2, 9)
        make(it, "数学", "middle", "整式的乘法", "展开 (x + %d)²，一次项系数是多少？" % a, 2 * a,
             {"kind": "perfect_linear", "a": a}, steps=2, ops=3)
    for _ in range(5):
        c, n = rnd.choice([1.5, 2.5, 3.2, 4.8]), rnd.randint(3, 5)
        make(it, "数学", "middle", "实数", "%s × 10^%d 写成整数是多少？" % (c, n), int(Fraction(str(c)) * 10 ** n),
             {"kind": "scinot", "c": c, "n": n}, steps=2, ops=2)
    for _ in range(5):
        vals = rnd.sample(range(10, 99), 5)
        make(it, "数学", "middle", "数据的分析", "五个数据 %s 的中位数是多少？" % "、".join(map(str, vals)), sorted(vals)[2],
             {"kind": "median5", "vals": vals}, steps=2, ops=2)

    # 高中数学补口
    for _ in range(5):
        b_, k = rnd.choice([2, 3, 5]), rnd.randint(2, 4)
        make(it, "数学", "high", "对数函数", "log_%d(%d^%d) 的值是多少？" % (b_, b_, k), k,
             {"kind": "log", "b": b_, "k": k}, steps=2, ops=2)
    for _ in range(5):
        b_, k = rnd.choice([2, 3]), rnd.randint(2, 4)
        make(it, "数学", "high", "指数函数", "若 %d^x = %d，x 是多少？" % (b_, b_ ** k), k,
             {"kind": "exp_eq", "b": b_, "k": k}, steps=2, ops=2)
    for name, val in (("sin 30°", "1/2"), ("cos 60°", "1/2"), ("tan 45°", "1"), ("sin 90°", "1")):
        make(it, "数学", "high", "三角函数", "%s 的值是多少？（写成分数或整数）" % name, val,
             {"kind": "trig_special", "name": name}, steps=1, ops=1)
    from math import comb as _comb
    for _ in range(5):
        n, k = rnd.randint(4, 6), rnd.randint(2, 3)
        make(it, "数学", "high", "计数原理", "C(%d, %d) 的值是多少？" % (n, k), _comb(n, k),
             {"kind": "comb", "n": n, "k": k}, steps=2, ops=2)
    for _ in range(4):
        n, k = rnd.randint(4, 6), rnd.randint(2, 3)
        make(it, "数学", "high", "计数原理", "(1 + x)^%d 展开式中 x^%d 的系数是多少？" % (n, k), _comb(n, k),
             {"kind": "binom", "n": n, "k": k}, steps=3, ops=3)

    # 初中物理
    for _ in range(5):
        r1, r2 = rnd.choice([(2, 5), (5, 10), (4, 6), (3, 7)])
        make(it, "物理", "middle", "欧姆定律", "两个电阻 %d 欧和 %d 欧串联，总电阻是多少欧？" % (r1, r2), r1 + r2,
             {"kind": "series_r", "r1": r1, "r2": r2}, steps=1, ops=1, unit="欧")
    for _ in range(5):
        r1, r2 = rnd.choice([(6, 3), (4, 4), (12, 6), (10, 15), (9, 18)])
        make(it, "物理", "middle", "欧姆定律", "两个电阻 %d 欧和 %d 欧并联，总电阻是多少欧？（写成分数或整数）" % (r1, r2),
             str(Fraction(r1 * r2, r1 + r2)), {"kind": "parallel_r", "r1": r1, "r2": r2}, steps=2, ops=3, unit="欧")
    for _ in range(5):
        useful, total = rnd.choice([(600, 1000), (300, 400), (450, 600), (800, 1000)])
        make(it, "物理", "middle", "功和机械能", "有用功 %d 焦、总功 %d 焦，机械效率是多少？（百分比）" % (useful, total),
             useful * 100 // total, {"kind": "eff", "useful": useful, "total": total}, steps=2, ops=2, unit="%")

    # 高中物理
    for _ in range(5):
        a, t = rnd.choice([2, 4, 6]), rnd.randint(2, 4)
        make(it, "物理", "high", "匀变速直线运动", "物体从静止开始以 %d 米每二次方秒加速，%d 秒内位移是多少米？" % (a, t),
             Fraction(a * t * t, 2), {"kind": "accel_disp", "a": a, "t": t}, steps=2, ops=3, unit="米")
    for _ in range(5):
        m, v = rnd.randint(1, 5), rnd.randint(2, 6)
        make(it, "物理", "high", "机械能守恒", "质量 %d 千克的物体速度 %d 米每秒，动能是多少焦？" % (m, v),
             Fraction(m * v * v, 2), {"kind": "kinetic", "m": m, "v": v}, steps=2, ops=3, unit="焦")
    for _ in range(5):
        m, v = rnd.randint(1, 5), rnd.randint(2, 8)
        make(it, "物理", "high", "动量", "质量 %d 千克的物体速度 %d 米每秒，动量是多少千克米每秒？" % (m, v), m * v,
             {"kind": "momentum", "m": m, "v": v}, steps=1, ops=1, unit="千克米每秒")

    # 初中化学
    for _ in range(5):
        ma, mb = rnd.randint(4, 20), rnd.randint(8, 40)
        make(it, "化学", "middle", "质量守恒定律", "A 与 B 恰好完全反应生成 C。参加反应的 A 为 %d 克、B 为 %d 克，生成 C 多少克？" % (ma, mb),
             ma + mb, {"kind": "conserve", "ma": ma, "mb": mb}, steps=1, ops=1, unit="克")
    for formula, n_atoms in (("H2O", 3), ("CO2", 3), ("H2SO4", 7), ("Ca(OH)2", 5), ("CH4", 5), ("C6H12O6", 24)):
        make(it, "化学", "middle", "化学式与化合价", "一个 %s 分子共有多少个原子？" % formula, n_atoms,
             {"kind": "atoms_count", "formula": formula, "n": n_atoms}, steps=2, ops=3)

    # 高中化学
    for _ in range(5):
        n = rnd.choice([0.25, 0.5, 1, 2])
        make(it, "化学", "high", "物质的量", "%s 摩尔气体在标准状况下的体积是多少升？（Vm = 22.4 升每摩尔）" % n,
             round(float(n) * 22.4, 1), {"kind": "molar_vol", "n": n}, steps=2, ops=2, unit="升")
    for k in (1, 2, 3, 4, 5, 6):
        make(it, "化学", "high", "电离平衡", "某溶液中 c(H⁺) = 10^−%d 摩尔每升，pH 是多少？" % k, k,
             {"kind": "ph", "k": k}, steps=1, ops=1)

    # 生物
    for which, val in (("显性性状", "3/4"), ("隐性性状", "1/4")):
        make(it, "生物", "middle", "遗传与变异", "基因型 Aa × Aa 的两个亲本杂交，后代出现%s的概率是多少？" % which, val,
             {"kind": "gene", "which": which}, steps=2, ops=2)
    for obj in (4, 10, 40, 100):
        make(it, "生物", "middle", "显微镜的使用", "目镜 10×、物镜 %d×，显微镜的放大倍数是多少？" % obj, 10 * obj,
             {"kind": "microscope", "eye": 10, "obj": obj}, steps=1, ops=1, unit="倍")
    for base in (1000, 2000, 5000, 10000):
        make(it, "生物", "middle", "生态系统", "第一营养级同化能量 %d 千焦，按 10%% 传递效率，第二营养级获得多少千焦？" % base, base // 10,
             {"kind": "energy", "base": base}, steps=2, ops=2, unit="千焦")

    # 地理
    for _ in range(5):
        cm, den = rnd.randint(2, 6), rnd.choice([100000, 200000, 500000])
        make(it, "地理", "middle", "地球与地图", "比例尺 1:%d 的地图上量得 %d 厘米，实际距离是多少千米？" % (den, cm),
             cm * den // 100000, {"kind": "scale", "cm": cm, "den": den}, steps=2, ops=2, unit="千米")
    for _ in range(5):
        pop, area = rnd.choice([(200000, 2000), (500000, 4000), (800000, 5000)])
        make(it, "地理", "middle", "居民与聚落", "某地人口 %d 人、面积 %d 平方千米，人口密度是多少人每平方千米？" % (pop, area),
             pop // area, {"kind": "density_pop", "pop": pop, "area": area}, steps=2, ops=2, unit="人每平方千米")
    for _ in range(4):
        h = rnd.randint(2, 5)
        make(it, "地理", "middle", "天气与气候", "海拔每升高 100 米气温下降 0.6 ℃。升高 %d 百米，气温下降多少 ℃？" % h,
             round(0.6 * h, 1), {"kind": "lapse", "h": h}, steps=2, ops=2, unit="℃")
    for diff in (1, 2, 3, 4):
        make(it, "地理", "high", "地球运动", "东八区与东%d区的时差是多少小时？" % (8 + diff), diff,
             {"kind": "tz", "diff": diff}, steps=2, ops=1, unit="小时")
    for lat, decl in ((40, 0), (30, 10), (20, 0), (45, 15)):
        make(it, "地理", "high", "地球运动", "某地纬度 %d°N，太阳直射 %d°N，正午太阳高度是多少度？" % (lat, decl), 90 - abs(lat - decl),
             {"kind": "sun_alt", "lat": lat, "decl": decl}, steps=2, ops=2, unit="度")

    for n in (3, 4, 5, 6):
        make(it, "生物", "middle", "细胞分裂与分化", "一个细胞连续分裂 %d 次，能得到多少个细胞？" % n, 2 ** n,
             {"kind": "cell_split", "n": n}, steps=2, ops=2)
    for rate, minutes in ((16, 2), (18, 3), (20, 2), (15, 4)):
        make(it, "生物", "middle", "人体的呼吸", "呼吸频率 %d 次每分钟，%d 分钟呼吸多少次？" % (rate, minutes), rate * minutes,
             {"kind": "breath", "rate": rate, "min": minutes}, steps=1, ops=1, unit="次")
    for hr, minutes in ((70, 2), (75, 4), (80, 3), (60, 5)):
        make(it, "生物", "middle", "血液循环", "心率 %d 次每分钟，%d 分钟心脏跳动多少次？" % (hr, minutes), hr * minutes,
             {"kind": "heart", "hr": hr, "min": minutes}, steps=1, ops=1, unit="次")
    for base, step, n in ((100, 50, 3), (200, 100, 2), (500, 100, 4)):
        make(it, "地理", "middle", "等高线地形图", "等高距 %d 米，从 %d 米的山脚向上走过 %d 条等高线，海拔升高多少米？" % (step, base, n),
             step * n, {"kind": "contour", "step": step, "n": n}, steps=2, ops=2, unit="米")
    for hi, lo in ((28, 16), (30, 20), (25, 15), (32, 24)):
        make(it, "地理", "middle", "天气与气候", "某地七月均温 %d ℃、一月均温 %d ℃，气温年较差是多少 ℃？" % (hi, lo), hi - lo,
             {"kind": "annual_range", "hi": hi, "lo": lo}, steps=1, ops=1, unit="℃")

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
