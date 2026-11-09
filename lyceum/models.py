"""服务商预设、模型能力标签、对话自动选模型（纯函数，只用标准库）。

- PRESETS：只写各家的 OpenAI 兼容 base URL 和一个默认模型，不含任何 key。
- tags(model_id)：按名称启发式打能力标签 vision（识图）/ reasoning（推理）/ fast（快速）。
- route_task(...)：一轮对话该用哪个「角色」：vision / strong / fast。
- pick_model(role, cfg)：角色 → 具体模型（自动模式按设置的角色模型或已检测列表的标签挑，没有就退回主模型）。
- probe / test：用表单里的地址和密钥请求 /models 和发一次最小对话（只在用户点按钮时调用；fetch 可注入，测试用 mock）。
"""
import json
import re
import urllib.error
import urllib.request

PRESETS = [
    {"id": "openai", "name": "OpenAI", "base_url": "https://api.openai.com/v1", "model": "gpt-4.1-mini"},
    {"id": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    {"id": "qwen", "name": "通义千问", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
    {"id": "zhipu", "name": "智谱", "base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4-flash"},
    {"id": "kimi", "name": "Kimi", "base_url": "https://api.moonshot.cn/v1", "model": "moonshot-v1-8k"},
    {"id": "siliconflow", "name": "硅基流动", "base_url": "https://api.siliconflow.cn/v1", "model": "deepseek-ai/DeepSeek-V3"},
    {"id": "openrouter", "name": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "model": "openai/gpt-4o-mini"},
    {"id": "ollama", "name": "Ollama 本地", "base_url": "http://127.0.0.1:11434/v1", "model": "qwen2.5:7b"},
    {"id": "custom", "name": "自定义 OpenAI 兼容", "base_url": "", "model": ""},
]
PRESET_IDS = tuple(p["id"] for p in PRESETS)
ROLES = ("vision", "strong", "fast")
ROLE_TAG = {"vision": "vision", "strong": "reasoning", "fast": "fast"}

# 不是对话模型的：嵌入、语音、画图、审核、重排
_NOT_CHAT = re.compile(r"embed|whisper|tts|speech|audio|dall-?e|image-|imagen|stable-?diff|flux|moderation|rerank|bge-|"
                       r"text-similarity|davinci-00|babbage|sora|realtime|transcribe", re.I)
_VISION = re.compile(r"vision|(^|[-_/:.])vl([-_/:.]|$)|-vl|qvq|4o|gpt-4\.1|gpt-4-turbo|gpt-5|gpt-6|gemini|claude-3|claude-(sonnet|opus|haiku)-4|"
                     r"claude-[4-9]|glm-4v|glm-4\.[15]v|llava|pixtral|minicpm-v|internvl|omni|moonshot-v1-[0-9]+k-vision|kimi-latest|"
                     r"llama-3\.2-(11|90)b|llama-4|grok-(2-)?vision|grok-4|step-1v|doubao.*vision", re.I)
_REASON = re.compile(r"(^|[-_/:.])o[1345]([-_/:.]|$)|r1|reason|think|qwq|qvq|opus|sonnet|gpt-5(?!.*(mini|nano))|gpt-6|"
                     r"(^|[-_/])pro([-_/:.]|$)|-max|glm-4\.[56]|glm-z1|k2|deepseek-v3|qwen3-(235|max)|grok-[34](?!.*mini)|gemini-2\.5-pro|large", re.I)
_FAST = re.compile(r"mini|nano|flash|haiku|turbo|lite|small|air|instant|speed|(^|[-_:/])(0\.5|1\.5|1|3|4|7|8)b([-_:.]|$)|"
                   r"chat$|deepseek-chat|qwen-plus|moonshot-v1-8k|gpt-3\.5", re.I)


def preset(pid):
    return next((p for p in PRESETS if p["id"] == pid), None)


def is_chat(model_id):
    return bool(model_id) and not _NOT_CHAT.search(model_id)


def tags(model_id):
    """名称启发式标签，按 vision / reasoning / fast 顺序返回。不保证准确，界面上标「按名称猜测」。"""
    m = (model_id or "").strip()
    out = []
    if not m:
        return out
    if _VISION.search(m):
        out.append("vision")
    fast = bool(_FAST.search(m))
    if _REASON.search(m) and not re.search(r"mini|nano|flash|lite|haiku|air", m, re.I):
        out.append("reasoning")
    if fast:
        out.append("fast")
    return out


def parse_models(data):
    """/v1/models 的返回 → 去重排序的对话模型 id 列表。兼容 {"data":[{"id":..}]}、{"models":[..]}、纯列表。"""
    items = data
    if isinstance(data, dict):
        items = data.get("data") or data.get("models") or []
    ids = []
    for it in items or []:
        mid = it.get("id") or it.get("name") or it.get("model") if isinstance(it, dict) else it
        if isinstance(mid, str) and mid.strip() and is_chat(mid.strip()) and mid.strip() not in ids:
            ids.append(mid.strip())
    return sorted(ids, key=str.lower)


def labeled(ids):
    return [{"id": i, "tags": tags(i)} for i in ids]


# ---------------- 自动路由 ----------------
ESSAY_RE = re.compile(r"作文|范文|习作|写一篇|仿写|续写|读后感|观后感|日记|演讲稿|周记|essay|composition", re.I)


def route_task(image=False, action=None, text="", allow_full=False, kind="chat"):
    """这一轮该用哪个角色。
    带图片（拍照识题）→ vision；批改 / 出变式题 / 完整解法 / 作文 → strong；其余普通提示轮 → fast。"""
    if image:
        return "vision"
    if kind in ("grade", "variants"):
        return "strong"
    if action == "full" or allow_full:
        return "strong"
    if ESSAY_RE.search(text or ""):
        return "strong"
    return "fast"


def _from_detected(role, detected):
    tag = ROLE_TAG[role]
    cands = [d for d in detected if tag in tags(d)]
    if role == "strong":  # 推理模型里优先不带「快速」标签的
        cands.sort(key=lambda d: "fast" in tags(d))
    if role == "fast":    # 快速模型里优先不带推理标签的
        cands.sort(key=lambda d: "reasoning" in tags(d))
    return cands[0] if cands else ""


def pick_model(role, cfg):
    """角色 → 模型。cfg: model（主模型）、vision_model（可空）、route_mode auto|fixed、
    roles {vision, strong, fast}（手动指定，可空）、detected [已检测模型 id]。
    固定模式：识图用 vision_model（没填就主模型），其余都用主模型。
    自动模式：手动指定 > 已检测列表里有对应标签的 > 识图退回 vision_model > 主模型。"""
    main = cfg.get("model") or ""
    vis = cfg.get("vision_model") or ""
    if cfg.get("route_mode") != "auto" or role not in ROLES:
        return (vis or main) if role == "vision" else main
    roles = cfg.get("roles") or {}
    if roles.get(role):
        return roles[role]
    if role == "vision" and vis:
        return vis
    if role == "vision":
        # 识图优先主模型：现在的多模态主模型自己就能看图。
        # 万一它不支持，chat() 会按 chain 里的备份依次重试（见 vision_backups）。
        return main
    det = [d for d in (cfg.get("detected") or []) if isinstance(d, str)]
    return _from_detected(role, det) or main


def vision_backups(cfg, exclude=()):
    """识图失败时的候选：已检测模型里按名称带 vision 标签的那些（可能为空）。"""
    det = [d for d in (cfg.get("detected") or []) if isinstance(d, str)]
    return [d for d in det if "vision" in tags(d) and d not in set(exclude)]


def chain(primary, fallbacks, main="", extras=()):
    """主模型出错时依次换：本次选中的 → 备用模型 → 备份模型 → 主模型。去重、去空。"""
    out = []
    for m in [primary, *(fallbacks or []), *(extras or []), main]:
        m = (m or "").strip()
        if m and m not in out:
            out.append(m)
    return out


def split_list(s):
    return [x.strip() for x in re.split(r"[,，\s]+", s or "") if x.strip()]


# ---------------- 探测 / 测试（只在用户点击时） ----------------
UA = "Mozilla/5.0 (compatible; Lyceum/0.2)"


def _http(url, key, body=None, timeout=20):
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}：{e.read().decode('utf-8', 'ignore')[:200]}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"连不上：{e.reason}")


def probe(base_url, key, fetch=None):
    """请求 {base}/models，返回 [{id, tags}]。"""
    base = (base_url or "").rstrip("/")
    if not base.startswith(("http://", "https://")):
        raise ValueError("接口地址要以 http:// 或 https:// 开头")
    data = (fetch or _http)(base + "/models", key)
    return labeled(parse_models(data))


def test(base_url, key, model, fetch=None):
    """发一次最小对话，确认地址、密钥、模型都能用。返回 {ok, model, reply}。"""
    base = (base_url or "").rstrip("/")
    if not base.startswith(("http://", "https://")):
        raise ValueError("接口地址要以 http:// 或 https:// 开头")
    if not model:
        raise ValueError("先填一个模型")
    data = (fetch or _http)(base + "/chat/completions", key,
                            {"model": model, "messages": [{"role": "user", "content": "回复 OK"}], "max_tokens": 8, "temperature": 0})
    try:
        reply = (data["choices"][0]["message"].get("content") or "").strip()
    except Exception:
        raise RuntimeError("返回格式不像 OpenAI 兼容接口")
    return {"ok": True, "model": data.get("model") or model, "reply": reply[:40]}
