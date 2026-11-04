"""OpenAI 兼容接口客户端（只用标准库）。
环境变量：
  LYCEUM_BASE_URL     默认 https://api.supergpt.dev/v1
  LYCEUM_API_KEY      必填；不填则进入离线演示模式（mock）
  LYCEUM_MODEL        默认 gpt-6.1-sol
  LYCEUM_VISION_MODEL 识图用，默认同 LYCEUM_MODEL
"""
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request

BASE_URL = os.environ.get("LYCEUM_BASE_URL", "https://api.supergpt.dev/v1").rstrip("/")
API_KEY = os.environ.get("LYCEUM_API_KEY", "")
MODEL = os.environ.get("LYCEUM_MODEL", "gpt-6.1-sol")
VISION_MODEL = os.environ.get("LYCEUM_VISION_MODEL", MODEL)
TIMEOUT = float(os.environ.get("LYCEUM_TIMEOUT", "120"))

USAGE = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0}
ROUTE = None        # 由 config.apply 填：自动选模型的配置（见 models.pick_model）；None = 固定用 MODEL / VISION_MODEL
USAGE_FILE = None   # 各模型调用次数与 token 的本地累计（数据目录 usage.json）
_tl = threading.local()
_ulock = threading.Lock()


def pick(task=None, vision=False):
    """这次调用用哪个模型。task 是 vision / strong / fast；没给就看 vision。"""
    from . import models
    role = task or ("vision" if vision else "main")
    if vision:
        role = "vision"
    cfg = dict(ROUTE or {}, model=MODEL)
    if not ROUTE:
        cfg["vision_model"] = VISION_MODEL if VISION_MODEL != MODEL else ""
    return models.pick_model(role, cfg) or MODEL


def candidates(task=None, vision=False):
    from . import models
    return models.chain(pick(task, vision), (ROUTE or {}).get("fallbacks"), VISION_MODEL if vision else MODEL)


def reset_last():
    _tl.model = None


def last_model():
    return getattr(_tl, "model", None)


def _estimate(messages):
    n = 0
    for m in messages or []:
        c = m.get("content")
        if isinstance(c, str):
            n += len(c)
        elif isinstance(c, list):
            n += sum(len(x.get("text") or "") for x in c if isinstance(x, dict)) + 800
    return max(1, n // 2)


def record_usage(model, prompt, completion, estimated=False, path=None):
    """按模型累计调用次数和 token（拿不到 usage 时用字数估计），写进 usage.json。"""
    path = path or USAGE_FILE
    with _ulock:
        bm = USAGE.setdefault("by_model", {})
        r = bm.setdefault(model, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "estimated": False})
        r["calls"] += 1
        r["prompt_tokens"] += int(prompt or 0)
        r["completion_tokens"] += int(completion or 0)
        r["estimated"] = r["estimated"] or bool(estimated)
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                disk = json.load(f)
            if not isinstance(disk, dict):
                disk = {}
        except (OSError, ValueError):
            disk = {}
        d = disk.setdefault(model, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "estimated": False})
        d["calls"] += 1
        d["prompt_tokens"] += int(prompt or 0)
        d["completion_tokens"] += int(completion or 0)
        d["estimated"] = d.get("estimated") or bool(estimated)
        try:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(disk, f, ensure_ascii=False, indent=1)
            os.replace(tmp, path)
        except OSError:
            pass


def usage_totals(path=None):
    path = path or USAGE_FILE
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def enabled():
    return bool(API_KEY)


class LLMError(Exception):
    pass


def _post(payload):
    req = urllib.request.Request(
        BASE_URL + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}",
                 # 部分中转挂了 Cloudflare，会拦 Python-urllib 默认 UA（error 1010）
                 "User-Agent": "Mozilla/5.0 (compatible; Lyceum/0.1)", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def chat(messages, *, json_mode=True, vision=False, temperature=0.4, max_tokens=1800, retries=1, task=None):
    """task：vision / strong / fast（自动选模型时用）。主模型出错依次换备用模型。"""
    models_ = candidates(task, vision)
    err = None
    for i, m in enumerate(models_):
        try:
            return _chat_one(m, messages, json_mode, temperature, max_tokens, retries)
        except LLMError as e:
            err = e
            if i == len(models_) - 1:
                raise
    raise err


chat_routed = chat  # 别名：有的测试会整体替换 llm.chat，路由测试用这个拿到原函数


def _chat_one(model, messages, json_mode, temperature, max_tokens, retries):
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    last = None
    for attempt in range(retries + 1):
        try:
            data = _post(payload)
            break
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")[:400]
            last = LLMError(f"HTTP {e.code}: {body}")
            if e.code == 400 and "response_format" in payload:
                payload.pop("response_format")  # 有些中转不支持 json_object
                continue
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(2 + attempt * 3)
                continue
            raise last
        except Exception as e:  # 超时 / 网络
            last = LLMError(str(e))
            if attempt < retries:
                time.sleep(2)
                continue
            raise last
    else:
        raise last
    u = data.get("usage") or {}
    USAGE["calls"] += 1
    USAGE["prompt_tokens"] += u.get("prompt_tokens", 0) or 0
    USAGE["completion_tokens"] += u.get("completion_tokens", 0) or 0
    USAGE["cached_tokens"] += ((u.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0)
    text = data["choices"][0]["message"].get("content") or ""
    _tl.model = model
    record_usage(model, u.get("prompt_tokens") or _estimate(messages), u.get("completion_tokens") or max(1, len(text) // 2),
                 estimated=not u)
    return parse_json(text) if json_mode else text


def parse_json(text):
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        return json.loads(t)
    except Exception:
        m = re.search(r"\{.*\}", t, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    return {"reply": text}


# ---------------- 流式（stream=true，逐块产出文本） ----------------
def _open_stream(payload):
    req = urllib.request.Request(
        BASE_URL + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}",
                 "User-Agent": "Mozilla/5.0 (compatible; Lyceum/0.1)", "Accept": "text/event-stream"},
        method="POST",
    )
    return urllib.request.urlopen(req, timeout=TIMEOUT)


def chat_stream(messages, *, json_mode=True, vision=False, temperature=0.4, max_tokens=1800, task=None):
    """生成器：逐块 yield 模型输出的文本增量。上游报错 / 超时 / 断流抛 LLMError。
    TIMEOUT 对每次读 socket 生效，所以上游卡住不出字也会超时。
    连接还没建立就失败时依次换备用模型；已经开始出字后断流不再换（前端可重试）。"""
    models_ = candidates(task, vision)
    for i, m in enumerate(models_):
        payload = {"model": m, "messages": messages, "temperature": temperature, "max_tokens": max_tokens, "stream": True}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            r = _open_with_fallback_format(payload)
            break
        except LLMError:
            if i == len(models_) - 1:
                raise
    _tl.model = payload["model"]
    yield from _read_stream(r, payload, messages)


def _open_with_fallback_format(payload):
    try:
        try:
            r = _open_stream(payload)
        except urllib.error.HTTPError as e:
            if e.code == 400 and "response_format" in payload:
                payload.pop("response_format")
                r = _open_stream(payload)
            else:
                raise
    except urllib.error.HTTPError as e:
        raise LLMError(f"HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:400]}")
    except Exception as e:
        raise LLMError(str(e))
    return r


def _read_stream(r, payload, messages):
    done = False
    USAGE["calls"] += 1
    got = {"p": 0, "c": 0, "chars": 0}
    try:
        with r:
            for raw in r:
                line = raw.decode("utf-8", "ignore").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    done = True
                    break
                try:
                    obj = json.loads(data)
                except Exception:
                    continue
                if obj.get("error"):
                    raise LLMError(str(obj["error"])[:300])
                u = obj.get("usage") or {}
                USAGE["prompt_tokens"] += u.get("prompt_tokens", 0) or 0
                USAGE["completion_tokens"] += u.get("completion_tokens", 0) or 0
                got["p"] = u.get("prompt_tokens") or got["p"]
                got["c"] = u.get("completion_tokens") or got["c"]
                for ch in obj.get("choices") or []:
                    piece = (ch.get("delta") or {}).get("content")
                    if piece:
                        got["chars"] += len(piece)
                        yield piece
                    if ch.get("finish_reason"):
                        done = True
    except LLMError:
        raise
    except Exception as e:
        raise LLMError("流式连接中断：" + str(e)[:200])
    if not done:
        raise LLMError("流式连接中断：上游没有发结束标记")
    record_usage(payload["model"], got["p"] or _estimate(messages), got["c"] or max(1, got["chars"] // 2), estimated=not got["c"])
