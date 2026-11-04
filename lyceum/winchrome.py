"""Windows 无边框窗口的自绘标题栏接口（pywebview js_api）。

页面在 ?frame=custom 时画 34px 标题栏和四边四角的缩放热区，按钮和拖动都调这里：
minimize / toggle_max / close / is_max，拖动与缩放用 begin(edge) → step() → end()，
位置全按 GetCursorPos（物理像素）算，和 DPI 缩放无关。edge：2 = 标题栏拖动；10–17 = 左右上下与四角（同 Win32 HT* 编号）。
非 Windows 平台所有方法都是空操作。LYCEUM_FRAME=native 时不用无边框（launcher 判断）。
"""
import os
import sys

HT = {10, 11, 12, 13, 14, 15, 16, 17}
MIN_W, MIN_H = 1200, 760


def use_custom_frame(env=None, platform=None):
    """Windows 默认无边框 + 自绘标题栏；LYCEUM_FRAME=native 退回系统标题栏；mac / Linux 保持原生。"""
    env = os.environ if env is None else env
    platform = platform or sys.platform
    return platform.startswith("win") and (env.get("LYCEUM_FRAME") or "").strip().lower() != "native"


def frame_url(url, custom):
    return url + (("&" if "?" in url else "?") + "frame=custom") if custom else url


def own_hwnd(title):
    """本进程里标题为 title 的可见顶层窗口（不用 FindWindow，免得撞到同名的资源管理器窗口）。"""
    if sys.platform != "win32":
        return 0
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    pid, found = os.getpid(), []
    buf = ctypes.create_unicode_buffer(256)

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _):
        p = wintypes.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and u.IsWindowVisible(h):
            u.GetWindowTextW(h, buf, 256)
            if buf.value == title:
                found.append(h)
                return False
        return True
    u.EnumWindows(cb, 0)
    return found[0] if found else 0


class WinChrome:
    def __init__(self, title):
        self._title = title
        self._win = None
        self._restore = None
        self._op = None
        self._h = 0

    def bind(self, win):
        self._win = win

    def available(self):
        return sys.platform == "win32"

    def _hwnd(self):
        if sys.platform != "win32":
            return 0
        import ctypes
        if not self._h or not ctypes.windll.user32.IsWindow(self._h):
            self._h = own_hwnd(self._title)
        return self._h

    @staticmethod
    def _work_area(hwnd):
        import ctypes
        from ctypes import wintypes

        class MI(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]
        u = ctypes.windll.user32
        mi = MI()
        mi.cbSize = ctypes.sizeof(MI)
        u.GetMonitorInfoW(u.MonitorFromWindow(hwnd, 2), ctypes.byref(mi))
        return mi.rcWork

    @staticmethod
    def _rect(hwnd):
        import ctypes
        from ctypes import wintypes
        r = wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
        return r

    @staticmethod
    def _cursor():
        import ctypes
        from ctypes import wintypes
        pt = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y

    def is_max(self):
        h = self._hwnd()
        if not h:
            return False
        r, w = self._rect(h), self._work_area(h)
        return (r.left, r.top, r.right, r.bottom) == (w.left, w.top, w.right, w.bottom)

    def toggle_max(self):
        """无边框窗口用系统最大化会盖住任务栏，所以手动铺满当前屏幕的工作区；再点一次还原。"""
        h = self._hwnd()
        if not h:
            return False
        import ctypes
        u = ctypes.windll.user32
        if self.is_max():
            r = self._restore
            if not r:
                w = self._work_area(h)
                cw, ch = min(1440, w.right - w.left - 80), min(900, w.bottom - w.top - 80)
                r = (w.left + (w.right - w.left - cw) // 2, w.top + (w.bottom - w.top - ch) // 2, cw, ch)
            u.SetWindowPos(h, 0, *r, 0x0014)  # NOZORDER | NOACTIVATE
            return False
        r = self._rect(h)
        self._restore = (r.left, r.top, r.right - r.left, r.bottom - r.top)
        w = self._work_area(h)
        u.SetWindowPos(h, 0, w.left, w.top, w.right - w.left, w.bottom - w.top, 0x0014)
        return True

    def minimize(self):
        h = self._hwnd()
        if h:
            import ctypes
            ctypes.windll.user32.ShowWindow(h, 6)  # SW_MINIMIZE

    def close(self):
        if self._win is not None:
            self._win.destroy()

    def begin(self, edge=2):
        h = self._hwnd()
        if not h:
            return False
        edge = int(edge)
        if edge != 2 and (edge not in HT or self.is_max()):  # 最大化时没有缩放边
            self._op = None
            return False
        cx, cy = self._cursor()
        if edge == 2 and self.is_max() and self._restore:  # 最大化时拖标题栏：先还原到鼠标下面
            _, _, cw, ch = self._restore
            self._restore = (cx - cw // 2, cy - 16, cw, ch)
            self.toggle_max()
        r = self._rect(h)
        self._op = (edge, cx, cy, r.left, r.top, r.right, r.bottom)
        return True

    def step(self):
        op, h = self._op, self._hwnd()
        if not op or not h:
            return
        import ctypes
        edge, sx, sy, l, t, r, b = op
        cx, cy = self._cursor()
        dx, dy = cx - sx, cy - sy
        u = ctypes.windll.user32
        if edge == 2:
            u.SetWindowPos(h, 0, l + dx, t + dy, 0, 0, 0x0015)  # NOSIZE | NOZORDER | NOACTIVATE
            return
        try:
            sc = u.GetDpiForWindow(h) / 96
        except Exception:  # noqa: BLE001
            sc = 1
        l, t, r, b = resize_rect(edge, (l, t, r, b), dx, dy, int(MIN_W * sc), int(MIN_H * sc))
        u.SetWindowPos(h, 0, l, t, r - l, b - t, 0x0014)

    def end(self):
        op, self._op = self._op, None
        h = self._hwnd()
        if op and op[0] == 2 and h:  # 拖到屏幕顶边 = 最大化
            w = self._work_area(h)
            if self._cursor()[1] <= w.top + 1:
                r = self._rect(h)
                self._restore = (op[3], op[4], r.right - r.left, r.bottom - r.top)
                import ctypes
                ctypes.windll.user32.SetWindowPos(h, 0, w.left, w.top, w.right - w.left, w.bottom - w.top, 0x0014)
                return True
        return False


def resize_rect(edge, rect, dx, dy, mw, mh):
    """纯函数：按拖动的边 / 角和位移算新窗口矩形，不小于最小尺寸。"""
    l, t, r, b = rect
    if edge in (10, 13, 16):   # 左
        l = min(l + dx, r - mw)
    if edge in (11, 14, 17):   # 右
        r = max(r + dx, l + mw)
    if edge in (12, 13, 14):   # 上
        t = min(t + dy, b - mh)
    if edge in (15, 16, 17):   # 下
        b = max(b + dy, t + mh)
    return l, t, r, b
