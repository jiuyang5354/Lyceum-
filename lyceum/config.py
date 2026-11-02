"""模型设置与数据目录（只用标准库）。

读取优先级：环境变量 > 数据目录里的 config.json > 内置默认值。
config.json 只存在本机数据目录（桌面版是 %APPDATA%\\Lyceum 或 ~/Library/Application Support/Lyceum），
不上传、不进仓库；接口和界面都不回显完整 key。
"""
import json
import os
import sys
import tempfile

FIELDS = ("base_url", "api_key", "model", "vision_model")
ENV = {"base_url": "LYCEUM_BASE_URL", "api_key": "LYCEUM_API_KEY",
       "model": "LYCEUM_MODEL", "vision_model": "LYCEUM_VISION_MODEL"}
DEFAULTS = {"base_url": "https://api.supergpt.dev/v1", "api_key": "", "model": "gpt-6.1-sol", "vision_model": ""}
LIMITS = {"base_url": 300, "api_key": 400, "model": 120, "vision_model": 120}
FILENAME = "config.json"
APP = "Lyceum"


def default_data_dir(platform=None, env=None, home=None):
    """桌面版的数据目录：Windows %APPDATA%\\Lyceum，macOS ~/Library/Application Support/Lyceum，
    其他系统 $XDG_DATA_HOME/lyceum（默认 ~/.local/share/lyceum）。"""
    platform = platform or sys.platform
    env = os.environ if env is None else env
    home = home or os.path.expanduser("~")
    if platform.startswith("win"):
        base = env.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
        return os.path.join(base, APP)
    if platform == "darwin":
        return os.path.join(home, "Library", "Application Support", APP)
    base = env.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    return os.path.join(base, APP.lower())


def resolve_data_dir(env=None, platform=None, home=None):
    """LYCEUM_DATA 有值就用它，否则用系统的用户数据目录。"""
    env = os.environ if env is None else env
    return env.get("LYCEUM_DATA") or default_data_dir(platform, env, home)


def path(data_dir):
    return os.path.join(data_dir, FILENAME)


def load_file(data_dir):
    """读 config.json；没有或坏了都当空配置。只留认识的字段。"""
    try:
        with open(path(data_dir), encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {k: str(raw[k]).strip() for k in FIELDS if isinstance(raw.get(k), str) and raw[k].strip()}


def effective(data_dir, env=None):
    """返回 (值, 来源)。来源是 env / file / default。"""
    env = os.environ if env is None else env
    stored = load_file(data_dir)
    vals, src = {}, {}
    for k in FIELDS:
        e = (env.get(ENV[k]) or "").strip()
        if e:
            vals[k], src[k] = e, "env"
        elif stored.get(k):
            vals[k], src[k] = stored[k], "file"
        else:
            vals[k], src[k] = DEFAULTS[k], "default"
    vals["base_url"] = vals["base_url"].rstrip("/")
    if not vals["vision_model"]:
        vals["vision_model"] = vals["model"]
    return vals, src


def mask(key):
    """界面只显示 key 的开头三位和末尾四位。"""
    if not key:
        return ""
    if len(key) <= 8:
        return "•" * len(key)
    return key[:3] + "…" + key[-4:]


def validate(updates):
    out = {}
    for k, v in (updates or {}).items():
        if k not in FIELDS or v is None:
            continue
        if not isinstance(v, str):
            raise ValueError(f"{k} 应该是文字")
        v = v.strip()
        if len(v) > LIMITS[k]:
            raise ValueError(f"{k} 太长了")
        if any(c in v for c in "\r\n\t"):
            raise ValueError(f"{k} 里不能有换行")
        if k == "base_url" and v and not v.startswith(("http://", "https://")):
            raise ValueError("API 地址要以 http:// 或 https:// 开头")
        out[k] = v
    return out


def save(data_dir, updates, clear_key=False):
    """合并写入 config.json。updates 里没给（或 None）的字段保持原样；给了空字符串表示清掉这一项。
    api_key 留空不会清掉已保存的 key，要清必须 clear_key=True。写文件用临时文件替换，权限 600。"""
    upd = validate(updates)
    cur = load_file(data_dir)
    for k, v in upd.items():
        if k == "api_key" and not v:
            continue
        if v:
            cur[k] = v
        else:
            cur.pop(k, None)
    if clear_key:
        cur.pop("api_key", None)
    os.makedirs(data_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".config-", dir=data_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cur, f, ensure_ascii=False, indent=2)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path(data_dir))
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return cur


def public(data_dir, env=None):
    """给前端看的设置：不含完整 key。"""
    vals, src = effective(data_dir, env)
    return {
        "base_url": vals["base_url"], "model": vals["model"],
        "vision_model": vals["vision_model"] if src["vision_model"] != "default" else "",
        "key_set": bool(vals["api_key"]), "key_hint": mask(vals["api_key"]),
        "source": src, "locked": [k for k in FIELDS if src[k] == "env"],
        "mode": "model" if vals["api_key"] else "offline",
        "defaults": {k: DEFAULTS[k] for k in ("base_url", "model")},
    }


def apply(llm_mod, data_dir, env=None):
    """把生效配置写进 llm 模块的全局量（llm 原本只读环境变量）。"""
    vals, _ = effective(data_dir, env)
    llm_mod.BASE_URL = vals["base_url"]
    llm_mod.API_KEY = vals["api_key"]
    llm_mod.MODEL = vals["model"]
    llm_mod.VISION_MODEL = vals["vision_model"]
    return vals
