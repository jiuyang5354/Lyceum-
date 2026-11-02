"""Lyceum 学园 · 桌面版启动器。

在一个空闲端口（只绑 127.0.0.1）的线程里起现有的 server.py，再用 pywebview 开原生窗口
（Windows 用 WebView2 / EdgeChromium，macOS 用 WKWebView）。关掉窗口，服务随之退出。

数据目录：LYCEUM_DATA 有值就用它；否则 Windows %APPDATA%\\Lyceum，macOS ~/Library/Application Support/Lyceum，
Linux ~/.local/share/lyceum。首次启动自动建库。模型设置存在数据目录的 config.json（只在本机）。

    python desktop/launcher.py                   # 开窗口
    python desktop/launcher.py --headless-check  # 不开窗口：起服务、把首页引用到的静态资源全部取一遍，验证离线可用
"""
import argparse
import json
import os
import re
import sys
import tempfile
import threading
import urllib.error
import urllib.request

FROZEN = getattr(sys, "frozen", False)
ROOT = getattr(sys, "_MEIPASS", None) if FROZEN else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lyceum import config as cfgmod  # noqa: E402

TITLE = "Lyceum 学园"
from lyceum import __version__ as VERSION  # noqa: E402
# 允许的外部地址：只有中文网页字体（Google Fonts，非阻塞加载；离线时回退系统字体）
ALLOWED_EXTERNAL = ("https://fonts.googleapis.com", "https://fonts.gstatic.com")


def _redirect_std(data_dir, name="lyceum.log"):
    """打包成窗口程序后没有控制台，stdout/stderr 是 None，写日志会抛错；改写到数据目录的 lyceum.log。"""
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        os.makedirs(data_dir, exist_ok=True)
        f = open(os.path.join(data_dir, name), "a", encoding="utf-8", buffering=1)
    except OSError:
        f = open(os.devnull, "w", encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = f
    if sys.stderr is None:
        sys.stderr = f


def prepare_data_dir(env=None):
    """确定数据目录并通过 LYCEUM_DATA 交给 server.py（server 在 import 时读取）。"""
    env = os.environ if env is None else env
    d = cfgmod.resolve_data_dir(env)
    os.makedirs(d, exist_ok=True)
    env["LYCEUM_DATA"] = d
    return d


def start_server():
    """import server（建库、读配置），在随机空闲端口起服务线程。返回 (srv, url, server 模块)。"""
    import importlib
    if "server" in sys.modules:  # 同一进程里第二次起（测试）：按新的 LYCEUM_DATA 重新加载
        server = importlib.reload(sys.modules["server"])
    else:
        server = importlib.import_module("server")  # 必须在 LYCEUM_DATA 设好之后
    srv = server.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, name="lyceum-http", daemon=True)
    t.start()
    return srv, f"http://127.0.0.1:{port}", server


# ---------------- 自检：不开窗口 ----------------
_REF = [
    re.compile(r'''(?:src|href)\s*=\s*["']([^"'#]+)["']'''),
    re.compile(r'''url\(\s*["']?([^"')]+)["']?\s*\)'''),
    re.compile(r'''(?:import|from)\s*\(?\s*["']([^"']+)["']'''),
    re.compile(r'''"imports"\s*:\s*\{([^}]*)\}'''),
]


def _get(url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=10) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read()


def _refs(text, base):
    out = []
    for i, rx in enumerate(_REF):
        for m in rx.finditer(text):
            v = m.group(1)
            if i == 3:  # importmap
                out += re.findall(r'"[^"]+"\s*:\s*"([^"]+)"', v)
                continue
            out.append(v)
    res = []
    for v in out:
        v = v.strip()
        if not v or v.startswith(("data:", "blob:", "#", "mailto:", "javascript:")) or "${" in v:
            continue
        if v.startswith(("http://", "https://", "//")):
            res.append(v)
        elif v.startswith("/"):
            res.append(v)
        elif re.match(r"^[\w./-]+\.(js|mjs|css|woff2?|ttf|png|svg|ico|webp|jpe?g)(\?[^\s]*)?$", v):
            v = v.split("?")[0]
            res.append(os.path.normpath(os.path.join(os.path.dirname(base), v)).replace("\\", "/"))
        # 其余（裸模块名 three、普通文字）略过
    return res


def headless_check(verbose=True):
    """在临时数据目录起服务，爬首页引用的全部本地资源。返回 (ok, 报告 dict)。"""
    tmp = tempfile.mkdtemp(prefix="lyceum-check-")
    os.environ["LYCEUM_DATA"] = tmp
    if sys.stdout is None or sys.stderr is None:  # 打包后的窗口程序：输出写到 LYCEUM_CHECK_LOG（CI 读它）
        log = os.environ.get("LYCEUM_CHECK_LOG")
        _redirect_std(os.path.dirname(log) if log else tmp, os.path.basename(log) if log else "lyceum.log")
    for k in cfgmod.ENV.values():
        os.environ.pop(k, None)  # 自检永远是离线演示模式，不碰真实模型
    srv, url, server = start_server()
    report = {"url": url, "data_dir": tmp, "fetched": [], "external": [], "errors": []}
    try:
        seen, queue = set(), ["/"]
        while queue:
            p = queue.pop(0)
            if p in seen:
                continue
            seen.add(p)
            try:
                st, ct, body = _get(url + p)
            except urllib.error.HTTPError as e:
                report["errors"].append(f"{p} → HTTP {e.code}")
                continue
            report["fetched"].append({"path": p, "type": ct.split(";")[0], "bytes": len(body)})
            if p.endswith((".js", ".mjs")) and "javascript" not in ct:
                report["errors"].append(f"{p} 的 Content-Type 是 {ct}，ES module 会被拒绝")
            if p == "/" or p.endswith((".html", ".css", ".js", ".mjs")):
                base = "/index.html" if p == "/" else p
                for r in _refs(body.decode("utf-8", "ignore"), base):
                    if r.startswith(("http", "//")):
                        if r not in report["external"]:
                            report["external"].append(r)
                    elif r not in seen:
                        queue.append(r)
        bad_ext = [e for e in report["external"]
                   if not e.startswith(ALLOWED_EXTERNAL) and "w3.org" not in e and not e.startswith("http://127.")]
        # three.js 里有一两处文档链接字符串，不是加载；只拦 html/css 里引用的外部资源
        bad_ext = [e for e in bad_ext if not re.search(r"threejs\.org|github\.com|mozilla\.org|khronos\.org", e)]
        if bad_ext:
            report["errors"].append("从网络加载的资源：" + ", ".join(bad_ext))
        for need in ("/vendor/three.module.min.js", "/vendor/katex/katex.min.js", "/vendor/fonts/fonts.css", "/js/app.js", "/css/app.css"):
            if need not in seen:
                report["errors"].append(f"首页没有引用到 {need}")
        st, _, body = _get(url + "/api/profile")
        prof = json.loads(body)
        if prof.get("llm"):
            report["errors"].append("自检应处于离线演示模式")
        st, _, body = _get(url + "/api/settings")
        s = json.loads(body)
        if s.get("mode") != "offline" or "api_key" in s:
            report["errors"].append("/api/settings 返回不对")
        if not os.path.isfile(os.path.join(tmp, "lyceum.db")):
            report["errors"].append("没有自动建库")
    finally:
        srv.shutdown()
        server.db.conn.close()
    ok = not report["errors"]
    if verbose:
        total = sum(f["bytes"] for f in report["fetched"])
        print(f"[headless-check] {url}  资源 {len(report['fetched'])} 个，共 {total / 1024:.0f} KB")
        for f in report["fetched"]:
            print(f"  200  {f['type']:<22} {f['bytes']:>9}  {f['path']}")
        print("  外部引用（允许，非阻塞）：", report["external"] or "无")
        print("[headless-check]", "OK" if ok else "失败：\n  " + "\n  ".join(report["errors"]))
    return ok, report


# ---------------- 开窗口 ----------------
def run_window():
    data_dir = prepare_data_dir()
    _redirect_std(data_dir)
    import webview  # pywebview

    srv, url, server = start_server()
    print(f"{TITLE} {VERSION} → {url} · 数据 {data_dir} · {server.mode_line()}", flush=True)
    webview.create_window(TITLE, url, width=1440, height=900, min_size=(1200, 760), resizable=True,
                          background_color="#F5F3EE", text_select=True)
    gui = "edgechromium" if sys.platform.startswith("win") else None
    try:
        webview.start(gui=gui, debug=False)
    finally:  # 窗口关了：停服务、关库
        srv.shutdown()
        try:
            server.db.conn.close()
        except Exception:
            pass


def main(argv=None):
    ap = argparse.ArgumentParser(description=TITLE)
    ap.add_argument("--headless-check", action="store_true", help="不开窗口，验证服务和静态资源")
    ap.add_argument("--version", action="store_true")
    a = ap.parse_args(argv)
    if a.version:
        print(VERSION)
        return 0
    if a.headless_check:
        ok, _ = headless_check()
        return 0 if ok else 1
    run_window()
    return 0


if __name__ == "__main__":
    sys.exit(main())
