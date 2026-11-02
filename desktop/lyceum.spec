# -*- mode: python ; coding: utf-8 -*-
# PyInstaller（onedir）：  pyinstaller desktop/lyceum.spec --noconfirm
# 产物：dist/Lyceum/Lyceum.exe（Windows）· dist/Lyceum.app（macOS）
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

HERE = SPECPATH  # noqa: F821  —— PyInstaller 注入
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)
from lyceum import __version__ as VERSION  # noqa: E402

WIN = sys.platform.startswith("win")
MAC = sys.platform == "darwin"
ICON = os.path.join(HERE, "assets", "lyceum.ico" if WIN else "lyceum.icns")

a = Analysis(  # noqa: F821
    [os.path.join(HERE, "launcher.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(ROOT, "static"), "static"),
        (os.path.join(ROOT, "lyceum", "taxonomy.json"), "lyceum"),
    ],
    # server 是 launcher 里 importlib 动态导入的，静态分析看不到
    hiddenimports=["server"] + collect_submodules("lyceum"),
    excludes=["tkinter", "_tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Lyceum",
    console=False,          # 窗口程序，不弹黑框
    icon=ICON,
    upx=False,              # UPX 压过的 exe 更容易被杀毒软件误报
    disable_windowed_traceback=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Lyceum")  # noqa: F821

if MAC:
    app = BUNDLE(  # noqa: F821
        coll,
        name="Lyceum.app",
        icon=ICON,
        bundle_identifier="io.github.jiuyang5354.lyceum",
        version=VERSION,
        info_plist={
            "CFBundleDisplayName": "Lyceum 学园",
            "CFBundleName": "Lyceum",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
        },
    )
