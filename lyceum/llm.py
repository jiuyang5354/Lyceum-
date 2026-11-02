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
import time
import urllib.error
import urllib.request

BASE_URL = os.environ.get("LYCEUM_BASE_URL", "https://api.supergpt.dev/v1").rstrip("/")
API_KEY = os.environ.get("LYCEUM_API_KEY", "")
MODEL = os.environ.get("LYCEUM_MODEL", "gpt-6.1-sol")
VISION_MODEL = os.environ.get("LYCEUM_VISION_MODEL", MODEL)
TIMEOUT = float(os.environ.get("LYCEUM_TIMEOUT", "120"))

USAGE = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0}


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


def chat(messages, *, json_mode=True, vision=False, temperature=0.4, max_tokens=1800, retries=1):
    payload = {
        "model": VISION_MODEL if vision else MODEL,
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


def chat_stream(messages, *, json_mode=True, vision=False, temperature=0.4, max_tokens=1800):
    """生成器：逐块 yield 模型输出的文本增量。上游报错 / 超时 / 断流抛 LLMError。
    TIMEOUT 对每次读 socket 生效，所以上游卡住不出字也会超时。"""
    payload = {"model": VISION_MODEL if vision else MODEL, "messages": messages, "temperature": temperature,
               "max_tokens": max_tokens, "stream": True}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
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
    done = False
    USAGE["calls"] += 1
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
                for ch in obj.get("choices") or []:
                    piece = (ch.get("delta") or {}).get("content")
                    if piece:
                        yield piece
                    if ch.get("finish_reason"):
                        done = True
    except LLMError:
        raise
    except Exception as e:
        raise LLMError("流式连接中断：" + str(e)[:200])
    if not done:
        raise LLMError("流式连接中断：上游没有发结束标记")
