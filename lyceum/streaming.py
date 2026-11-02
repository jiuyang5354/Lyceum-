"""流式输出的三件小工具（纯标准库、无网络，方便单测）：

  sse(event, data)   拼一条 text/event-stream 事件
  ReplyExtractor     模型按 JSON 模式边生成边吐字：从半截 JSON 里增量解出 "reply" 字段的文字，
                     并在 reply 开始时解析出它前面的字段（subject / stage / hint_level …）
  SentenceGate       漏题拦截的缓冲区：按句子边界切，整句过检测才放行；检测到漏题就关闸，之后一个字也不放
"""
import json
import re


def sse(event, data):
    body = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {body}\n\n".encode("utf-8")


class ReplyExtractor:
    KEY = re.compile(r'"reply"\s*:\s*"')

    def __init__(self):
        self.raw = ""
        self.mode = None          # None=还没判断 / json / text（模型没按 JSON 输出，整段都是回复）
        self.pos = None           # reply 字符串在 raw 里的起点
        self.closed = False
        self.out = ""             # 已解出的 reply 文字
        self.meta = {}            # reply 之前的字段

    @property
    def started(self):
        return self.mode == "text" or self.pos is not None

    def feed(self, chunk):
        """喂进一块原始输出，返回新解出的 reply 文字（可能为空串）。"""
        self.raw += chunk
        if self.mode is None:
            s = self.raw.lstrip()
            if not s:
                return ""
            self.mode = "json" if s[0] in "{`" else "text"
        if self.mode == "text":
            self.out += chunk
            return chunk
        if self.closed:
            return ""
        if self.pos is None:
            m = self.KEY.search(self.raw)
            if not m:
                return ""
            self.pos = m.end()
            self.meta = self._prefix_meta(self.raw[:m.start()])
        before = len(self.out)
        self._decode()
        return self.out[before:]

    def _decode(self):
        s, i, buf = self.raw, self.pos, []
        while i < len(s):
            c = s[i]
            if c == '"':
                self.closed = True
                i += 1
                break
            if c == "\\":
                if i + 1 >= len(s):
                    break                       # 转义符被切在块尾：等下一块
                e = s[i + 1]
                if e == "u":
                    if i + 6 > len(s):
                        break
                    try:
                        cp = int(s[i + 2:i + 6], 16)
                    except ValueError:
                        cp = 0xFFFD
                    if 0xD800 <= cp < 0xDC00:   # 代理对
                        if i + 12 > len(s):
                            break
                        lo = int(s[i + 8:i + 12], 16) if s[i + 6:i + 8] == "\\u" else 0xDC00
                        buf.append(chr(0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00)))
                        i += 12
                        continue
                    buf.append(chr(cp))
                    i += 6
                    continue
                buf.append({"n": "\n", "t": "\t", "r": "", "b": "", "f": "", '"': '"', "\\": "\\", "/": "/"}.get(e, e))
                i += 2
                continue
            buf.append(c)
            i += 1
        self.out += "".join(buf)
        self.pos = i

    @staticmethod
    def _prefix_meta(prefix):
        t = re.sub(r"^\s*```(?:json)?", "", prefix).strip().rstrip(",").strip()
        if not t.startswith("{"):
            return {}
        try:
            return json.loads(t + "}")
        except Exception:
            meta = {}
            for k in ("subject", "stage", "intent", "topic"):
                m = re.search(rf'"{k}"\s*:\s*"([^"]*)"', t)
                if m:
                    meta[k] = m.group(1)
            m = re.search(r'"hint_level"\s*:\s*(\d)', t)
            if m:
                meta["hint_level"] = int(m.group(1))
            m = re.search(r'"student_correct"\s*:\s*(true|false|null)', t)
            if m:
                meta["student_correct"] = {"true": True, "false": False}.get(m.group(1))
            return meta


# 句子边界：中文句末标点、换行；英文 . ! ? 后面跟空白
_BOUND = re.compile(r"[。！？；\n]|[.!?](?=\s)")


class SentenceGate:
    """direct=True 时直接放行；否则按句子边界缓冲，check(累计文本) 返回空串才放行这一句。
    公式（$…$）没闭合时不在里面切句。"""

    def __init__(self, check, direct=False):
        self.check, self.direct = check, direct
        self.released, self.pending = "", ""
        self.leak = ""

    def feed(self, text):
        if self.leak:
            return ""
        if self.direct:
            self.released += text
            return text
        self.pending += text
        cut = -1
        for m in _BOUND.finditer(self.pending):
            end = m.end()
            if (self.released + self.pending[:end]).count("$") % 2 == 0:
                cut = end
        if cut < 0:
            return ""
        return self._try(self.pending[:cut], cut)

    def flush(self):
        if self.leak or self.direct or not self.pending:
            return ""
        return self._try(self.pending, len(self.pending))

    def _try(self, piece, cut):
        hit = self.check(self.released + piece)
        if hit:
            self.leak = hit
            return ""
        self.released += piece
        self.pending = self.pending[cut:]
        return piece
