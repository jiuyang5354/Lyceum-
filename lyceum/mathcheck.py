"""数学确定性校验（只用标准库：fractions + 自写递归下降解析器）。

思路来自 socratic-math-tutor 的「起草 → 验证 → 修正」状态机和 Openclaw-Study-Coach 的 SymPy check_answer
（两者代码都没有拷贝；前者无协议，只借思路）。没有 SymPy，就用有理数精确运算：
  - 解析：数字、单字母变量、+ - * / ^、括号、隐式乘法（2x、3(x+1)、(x+1)(x-2)），中文 / LaTeX 常见写法先归一化；
  - 方程的根：把候选值代回，两边差为 0；
  - 恒等（因式分解 / 化简是否等价）：在若干固定有理数点代入比较（多项式恒等检验，次数 < 点数时确定）。
能判的才判，判不了返回 None，交给模型。
"""
import re
from fractions import Fraction

POINTS = [Fraction(n, d) for n, d in ((2, 7), (-3, 5), (5, 3), (-7, 2), (11, 13), (13, 4), (-17, 9), (19, 11))]


class ParseError(ValueError):
    pass


def normalize(s):
    s = str(s or "")
    s = s.replace("$", "").replace("\\left", "").replace("\\right", "")
    s = re.sub(r"\\(?:dfrac|tfrac|frac)\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"((\1)/(\2))", s)
    s = re.sub(r"\\sqrt", "sqrt", s)
    rep = {"\\cdot": "*", "\\times": "*", "×": "*", "·": "*", "÷": "/", "\\div": "/", "−": "-", "–": "-", "—": "-",
           "＝": "=", "（": "(", "）": ")", "＋": "+", "－": "-", "²": "^2", "³": "^3", "{": "(", "}": ")", " ": "",
           "，": ",", "：": ":"}
    for a, b in rep.items():
        s = s.replace(a, b)
    return s


_TOK = re.compile(r"\d+(?:\.\d+)?|[a-zA-Z]|[-+*/^()]")


_FUNC = re.compile(r"sin|cos|tan|cot|log|ln|lg|sqrt|pi|abs|exp|mod")


def tokenize(s):
    s = normalize(s)
    if _FUNC.search(s):
        raise ParseError("含函数 / 常数，不判")
    pos, out = 0, []
    while pos < len(s):
        m = _TOK.match(s, pos)
        if not m:
            raise ParseError("无法识别：" + s[pos:pos + 5])
        out.append(m.group(0))
        pos = m.end()
    # 隐式乘法：2x、x(、)(、)x、x y
    res = []
    for t in out:
        if res:
            p = res[-1]
            if (p[0].isdigit() or p.isalpha() or p == ")") and (t[0].isdigit() and not p[0].isdigit() or t.isalpha() or t == "("):
                res.append("*")
        res.append(t)
    return res


class _P:
    def __init__(self, toks):
        self.t, self.i = toks, 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def eat(self, x=None):
        tok = self.peek()
        if tok is None or (x and tok != x):
            raise ParseError("缺少 " + (x or "表达式"))
        self.i += 1
        return tok

    def expr(self):
        node = self.term()
        while self.peek() in ("+", "-"):
            op = self.eat()
            node = (op, node, self.term())
        return node

    def term(self):
        node = self.unary()
        while self.peek() in ("*", "/"):
            op = self.eat()
            node = (op, node, self.unary())
        return node

    def unary(self):
        if self.peek() in ("+", "-"):
            op = self.eat()
            n = self.unary()
            return n if op == "+" else ("neg", n)
        return self.power()

    def power(self):
        base = self.atom()
        if self.peek() == "^":
            self.eat()
            return ("^", base, self.unary())
        return base

    def atom(self):
        tok = self.eat()
        if tok == "(":
            n = self.expr()
            self.eat(")")
            return n
        if tok[0].isdigit():
            return ("num", Fraction(tok))
        if tok.isalpha():
            return ("var", tok)
        raise ParseError("意外的符号 " + tok)


def parse(s):
    toks = tokenize(s)
    if not toks:
        raise ParseError("空表达式")
    p = _P(toks)
    n = p.expr()
    if p.peek() is not None:
        raise ParseError("多余的符号 " + p.peek())
    return n


def evaluate(node, env):
    k = node[0]
    if k == "num":
        return node[1]
    if k == "var":
        if node[1] not in env:
            raise ParseError("未知变量 " + node[1])
        return env[node[1]]
    if k == "neg":
        return -evaluate(node[1], env)
    a, b = evaluate(node[1], env), evaluate(node[2], env)
    if k == "+":
        return a + b
    if k == "-":
        return a - b
    if k == "*":
        return a * b
    if k == "/":
        if b == 0:
            raise ZeroDivisionError
        return a / b
    if k == "^":
        if b.denominator != 1 or abs(b) > 12:
            raise ParseError("只支持小整数指数")
        return a ** int(b)
    raise ParseError(k)


def variables(node, acc=None):
    acc = set() if acc is None else acc
    if node[0] == "var":
        acc.add(node[1])
    elif node[0] in ("neg",):
        variables(node[1], acc)
    elif node[0] not in ("num",):
        variables(node[1], acc)
        variables(node[2], acc)
    return acc


def equivalent(a, b):
    """两个表达式是否恒等（多点代入）。判不了返回 None。"""
    try:
        na, nb = parse(a), parse(b)
    except (ParseError, ZeroDivisionError, ValueError):
        return None
    vs = sorted(variables(na) | variables(nb))
    ok = 0
    for i, p in enumerate(POINTS):
        env = {v: POINTS[(i + j * 3) % len(POINTS)] + j for j, v in enumerate(vs)}
        try:
            if evaluate(na, env) != evaluate(nb, env):
                return False
            ok += 1
        except ZeroDivisionError:
            continue
        except ParseError:
            return None
    return True if ok >= 4 else None


def find_equation(text):
    """从题干里找出一个单变量方程 → (左, 右, 变量)；找不到返回 None。"""
    t = normalize(text)
    for m in re.finditer(r"([0-9a-zA-Z+\-*/^().]+)=([0-9a-zA-Z+\-*/^().]+)", t):
        lhs, rhs = m.group(1), m.group(2)
        try:
            vs = variables(parse(lhs)) | variables(parse(rhs))
        except (ParseError, ValueError):
            continue
        if len(vs) == 1:
            return lhs, rhs, vs.pop()
    return None


def is_root(lhs, rhs, var, value):
    try:
        env = {var: value}
        return evaluate(parse(lhs), env) == evaluate(parse(rhs), env)
    except (ParseError, ZeroDivisionError, ValueError):
        return None


_VAL = re.compile(r"(-?\s*\d+(?:\.\d+)?(?:\s*/\s*\d+)?)")


def parse_values(answer, var="x"):
    """「x=3 或 x=4」「x₁=3，x₂=-4」「3, 4」「x=1/2」→ {Fraction}。没有数值返回 None。"""
    a = normalize(answer).replace("₁", "1").replace("₂", "2")
    a = re.sub(r"\\?(或|和|且|or|and|;|；|、)", ",", a)
    a = re.sub(r"%s_?[12]?=" % re.escape(var), "", a)
    if re.search(r"[a-zA-Z]", a.replace(var, "")):
        return None
    vals = set()
    for m in _VAL.finditer(a):
        try:
            vals.add(Fraction(m.group(1).replace(" ", "")))
        except (ValueError, ZeroDivisionError):
            return None
    return vals or None


def check_roots(problem, answer):
    """题干里有单变量方程、答案是若干数值：返回 True（全是根且不缺不多）/ False / None（判不了）。
    「不缺」用的是：给出的值都是根，且个数等于在候选整数 / 简单分数范围里找到的根数。"""
    eq = find_equation(problem)
    if not eq:
        return None
    lhs, rhs, var = eq
    vals = parse_values(answer, var)
    if not vals:
        return None
    for v in vals:
        r = is_root(lhs, rhs, var, v)
        if r is None:
            return None
        if not r:
            return False
    roots = all_simple_roots(lhs, rhs, var)
    if roots is None:
        return True
    return vals == roots


def all_simple_roots(lhs, rhs, var):
    """在 -60..60 的整数和分母 ≤6 的分数里找根（覆盖中小学常见题）；表达式不可解析时 None。"""
    try:
        nl, nr = parse(lhs), parse(rhs)
    except (ParseError, ValueError):
        return None
    found = set()
    cands = {Fraction(n, d) for d in range(1, 7) for n in range(-60 * d, 60 * d + 1)}
    for c in cands:
        try:
            if evaluate(nl, {var: c}) == evaluate(nr, {var: c}):
                found.add(c)
        except ZeroDivisionError:
            continue
        except ParseError:
            return None
        if len(found) > 6:
            return None  # 恒等式之类，不判
    return found or None


def verify_answer(problem, student, reference=None):
    """批改用：先看方程的根；再看和标准答案是否恒等。返回 True / False / None。"""
    r = check_roots(problem, student)
    if r is not None:
        return r
    if reference:
        rs = parse_values(reference)
        ss = parse_values(student)
        if rs and ss:
            return rs == ss
        return equivalent(_rhs(student), _rhs(reference))
    return None


def _rhs(s):
    s = str(s or "")
    return s.split("=", 1)[1] if s.count("=") == 1 and re.match(r"\s*\$?[a-zA-Z]\s*=", s) else s
