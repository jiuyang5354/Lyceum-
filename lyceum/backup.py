"""备份导出 / 导入、清空学习数据、检查更新（只用标准库）。

备份 zip：lyceum.db（用 sqlite 在线备份拿一致快照）+ config.json（默认去掉 api_key）+ manifest.json。
上传的题目图片不进备份（体积大，且只是对话里的附图）。
"""
import io
import json
import os
import re
import sqlite3
import tempfile
import time
import urllib.request
import zipfile

REPO = "jiuyang5354/Lyceum-"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases/latest"
MAX_BACKUP = 200 * 1024 * 1024
KEEP_ON_CLEAR = ("profile",)  # 清空学习数据时保留年级与教材


def export_zip(conn, config_raw, version, include_key=False):
    """conn：正在用的 sqlite 连接；config_raw：config.json 的原始 dict。返回 zip 的 bytes。"""
    cfg = dict(config_raw or {})
    if not include_key:
        cfg.pop("api_key", None)
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        dst = sqlite3.connect(tmp)
        with dst:
            conn.backup(dst)
        dst.close()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(tmp, "lyceum.db")
            z.writestr("config.json", json.dumps(cfg, ensure_ascii=False, indent=2))
            z.writestr("manifest.json", json.dumps({"app": "Lyceum", "version": version, "created": int(time.time()),
                                                    "has_key": bool(include_key and cfg.get("api_key"))}, ensure_ascii=False))
        return buf.getvalue()
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def read_zip(data):
    """校验备份包，返回 (db_bytes, config_dict, manifest)。"""
    if len(data) > MAX_BACKUP:
        raise ValueError("备份文件太大")
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("不是 Lyceum 备份文件（zip 打不开）")
    names = set(z.namelist())
    if "lyceum.db" not in names or "manifest.json" not in names:
        raise ValueError("不是 Lyceum 备份文件（缺少 lyceum.db / manifest.json）")
    man = json.loads(z.read("manifest.json") or b"{}")
    if man.get("app") != "Lyceum":
        raise ValueError("不是 Lyceum 备份文件")
    db = z.read("lyceum.db")
    if not db.startswith(b"SQLite format 3\x00"):
        raise ValueError("备份里的数据库已损坏")
    cfg = json.loads(z.read("config.json") or b"{}") if "config.json" in names else {}
    return db, (cfg if isinstance(cfg, dict) else {}), man


def import_zip(conn, data_dir, data, config_mod):
    """用备份覆盖当前学习库（在线 restore，不用重启），配置合并：备份里没有 key 就保留现在的 key。"""
    db_bytes, cfg, man = read_zip(data)
    fd, tmp = tempfile.mkstemp(suffix=".db")
    with os.fdopen(fd, "wb") as f:
        f.write(db_bytes)
    try:
        src = sqlite3.connect(tmp)
        try:
            src.execute("PRAGMA schema_version").fetchone()
            with conn:
                src.backup(conn)
        finally:
            src.close()
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    cur = config_mod.load_raw(data_dir)
    merged = {k: v for k, v in cfg.items() if k in config_mod.FIELDS or k in ("ui", "detected")}
    if not merged.get("api_key") and cur.get("api_key"):
        merged["api_key"] = cur["api_key"]
    config_mod.write_json(data_dir, merged)
    return {"version": man.get("version"), "created": man.get("created"), "key_restored": bool(cfg.get("api_key"))}


def clear_learning(conn, keep=KEEP_ON_CLEAR):
    """删掉所有学习记录（会话、错题、掌握度、记忆、成长规则……），保留年级与教材。返回清掉的表。"""
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    done = []
    with conn:
        for t in tables:
            if t in keep:
                continue
            conn.execute(f'DELETE FROM "{t}"')
            done.append(t)
        try:
            conn.execute("DELETE FROM sqlite_sequence")
        except sqlite3.Error:
            pass
    return done


# ---------------- 检查更新 ----------------
def _vtuple(v):
    nums = re.findall(r"\d+", v or "")
    return tuple(int(x) for x in nums[:3]) + (0,) * (3 - len(nums[:3]))


def newer(latest, current):
    return _vtuple(latest) > _vtuple(current)


def _fetch_json(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "Lyceum-update-check", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def check_update(current, fetch=None):
    """查 GitHub Releases latest：只返回是否有新版和下载链接，不下载、不安装。"""
    try:
        rel = (fetch or _fetch_json)(RELEASES_API)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "current": current, "error": "查不到更新：" + str(e)[:120]}
    tag = str(rel.get("tag_name") or "").lstrip("vV")
    assets = rel.get("assets") or []
    exe = next((a.get("browser_download_url") for a in assets if str(a.get("name", "")).lower().endswith(".exe")), None)
    dmg = next((a.get("browser_download_url") for a in assets if str(a.get("name", "")).lower().endswith(".dmg")), None)
    return {"ok": True, "current": current, "latest": tag, "newer": bool(tag) and newer(tag, current),
            "url": rel.get("html_url") or f"https://github.com/{REPO}/releases/latest", "exe": exe, "dmg": dmg,
            "notes": str(rel.get("body") or "")[:600]}


# ---------------- 下载安装包 ----------------
# 只允许从 GitHub 的发布域名下载：URL 来自 Releases API，但仍然校验，
# 避免「把任意 URL 交给服务器去取」变成 SSRF 或落地可执行文件的通道。
ALLOWED_HOSTS = ("github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com")
MAX_INSTALLER = 400 * 1024 * 1024


def safe_installer_url(url):
    """校验下载地址；不合法就抛 ValueError。"""
    from urllib.parse import urlparse
    p = urlparse(str(url or ""))
    if p.scheme != "https":
        raise ValueError("安装包地址必须是 https")
    if (p.hostname or "").lower() not in ALLOWED_HOSTS:
        raise ValueError("安装包不在 GitHub 发布域名上：%s" % (p.hostname or "?"))
    if not p.path.lower().endswith(".exe"):
        raise ValueError("不是 Windows 安装包")
    return url


def download_installer(url, dest_dir, opener=None, on_progress=None, timeout=60):
    """把安装包流式写到 dest_dir，返回 {path, name, bytes}。

    边下边写，超过 MAX_INSTALLER 立即中止；on_progress(got, total) 供界面显示进度。
    """
    safe_installer_url(url)
    os.makedirs(dest_dir, exist_ok=True)
    name = os.path.basename(url.split("?")[0]) or "Lyceum-Setup.exe"
    dest = os.path.join(dest_dir, name)
    op = opener or urllib.request.build_opener()
    req = urllib.request.Request(url, headers={"User-Agent": "Lyceum-updater"})
    got = 0
    with op.open(req, timeout=timeout) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            got += len(chunk)
            if got > MAX_INSTALLER:
                f.close()
                try:
                    os.remove(dest)
                except OSError:
                    pass
                raise ValueError("安装包超过 %d MB，已中止" % (MAX_INSTALLER // 1024 // 1024))
            f.write(chunk)
            if on_progress:
                on_progress(got, total)
    return {"path": dest, "name": name, "bytes": got}
