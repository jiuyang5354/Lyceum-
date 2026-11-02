"""把 Noto Serif SC（OFL）裁成常用字子集 woff2，放进 static/vendor/fonts/。

用法（需要 fonttools + brotli）：
    python tools/subset_cjk_font.py path/to/NotoSerifSC[wght].ttf [--level1 level-1.txt]

字集 = 《通用规范汉字表》一级字 3500（--level1 给出文件时）
     ∪ GB2312 一级字 3755（用 Python 的 gb2312 编码表生成）
     ∪ static/ 下 html/js/css 与 lyceum/taxonomy.json、lyceum/strategies.py 里出现的全部汉字
     ∪ 中文标点、全角符号（U+3000-303F、U+FF00-FFEF）、常用弯引号/破折号/省略号 ∪ ASCII。
可变字体按 CSS 实际用到的字重（500、600）实例化后再裁子集；输出的 unicode-range 由子集真实 cmap 生成，
写在 static/vendor/fonts/noto-serif-sc.css（被 fonts.css 引入）。
"""
import argparse, io, pathlib, re, sys
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer
from fontTools import subset

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "static" / "vendor" / "fonts"
WEIGHTS = (500, 600)
FAMILY = "Noto Serif SC"


def han(text):
    return {c for c in text if "\u3400" <= c <= "\u9fff" or "\uf900" <= c <= "\ufaff"}


def charset(level1):
    chars = set()
    if level1:
        chars |= han(pathlib.Path(level1).read_text(encoding="utf-8"))
    for hi in range(0xB0, 0xD8):
        for lo in range(0xA1, 0xFF):
            try:
                chars.add(bytes([hi, lo]).decode("gb2312"))
            except UnicodeDecodeError:
                pass
    srcs = [p for p in (ROOT / "static").rglob("*") if p.suffix in {".html", ".js", ".css", ".json"} and "vendor" not in p.parts]
    srcs += [ROOT / "lyceum" / "taxonomy.json", ROOT / "lyceum" / "strategies.py"]
    for p in srcs:
        chars |= han(p.read_text(encoding="utf-8", errors="ignore"))
    chars |= {chr(c) for c in range(0x20, 0x7F)}
    chars |= {chr(c) for c in range(0x3000, 0x3040)}  # 中文标点
    chars |= {chr(c) for c in range(0xFF01, 0xFF5F)} | {chr(c) for c in range(0xFFE0, 0xFFE7)}  # 全角
    chars |= set("·—–‘’“”…‰′″※№℃°±×÷√∞≈≠≤≥←→↑↓■□▲△●○◆◇★☆§")
    return chars


def ranges(cps):
    cps = sorted(cps); out = []; s = p = cps[0]
    for c in cps[1:]:
        if c == p + 1:
            p = c; continue
        out.append((s, p)); s = p = c
    out.append((s, p))
    return ", ".join(f"U+{a:X}" if a == b else f"U+{a:X}-{b:X}" for a, b in out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ttf"); ap.add_argument("--level1")
    a = ap.parse_args()
    chars = charset(a.level1)
    css = []
    for w in WEIGHTS:
        f = TTFont(a.ttf)
        f = instancer.instantiateVariableFont(f, {"wght": w}, updateFontNames=True)
        opts = subset.Options()
        opts.flavor = "woff2"; opts.layout_features = ["*"]; opts.name_IDs = ["*"]
        opts.name_languages = ["*"]; opts.notdef_outline = True; opts.hinting = False
        opts.desubroutinize = True
        sub = subset.Subsetter(opts)
        sub.populate(unicodes=[ord(c) for c in chars])
        sub.subset(f)
        out = OUT / f"NotoSerifSC-{w}-common.woff2"
        f.flavor = "woff2"; f.save(out)
        cmap = set(f.getBestCmap())
        han_n = sum(1 for c in cmap if 0x3400 <= c <= 0x9FFF or 0xF900 <= c <= 0xFAFF)
        print(f"{out.name}: {out.stat().st_size/1024/1024:.2f} MB, {len(cmap)} 码位（汉字 {han_n}）")
        css.append("@font-face{font-family:'%s';font-style:normal;font-weight:%d;font-display:swap;"
                   "src:local('Noto Serif SC %s'),url(/vendor/fonts/%s) format('woff2');unicode-range:%s;}"
                   % (FAMILY, w, "Medium" if w == 500 else "SemiBold", out.name, ranges(cmap)))
    (OUT / "noto-serif-sc.css").write_text(
        "/* Noto Serif SC 常用字子集（OFL 1.1），由 tools/subset_cjk_font.py 生成，勿手改。\n"
        "   子集外的字按 unicode-range 交给 Google Fonts / 系统宋体。 */\n" + "\n".join(css) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
