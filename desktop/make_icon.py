"""用 Pillow 画小雅猫头鹰图标，导出 icon.png / lyceum.ico / lyceum.icns / lyceum.svg。
造型和网页里的 owlMark（static/js/svg.js）一致：32×32 的路径放大重绘，纸白底 + 墨线外框。
    python desktop/make_icon.py
"""
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "assets")
PAPER, INK, BLUE, YELLOW, WHITE = "#f5f3ee", "#1b2142", "#2951e6", "#f6d34a", "#ffffff"
N = 1024  # 画布
S = 2     # 超采样


def quad(p0, c, p1, n=24):
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * c[0] + t * t * p1[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * c[1] + t * t * p1[1]) for t in (i / n for i in range(1, n + 1))]


def body_path():
    # M7 7 L10 11 Q16 8 22 11 L25 7 L26 19 Q26 29 16 29 Q6 29 6 19 Z
    pts = [(7, 7), (10, 11)]
    pts += quad((10, 11), (16, 8), (22, 11))
    pts += [(25, 7), (26, 19)]
    pts += quad((26, 19), (26, 29), (16, 29))
    pts += quad((16, 29), (6, 29), (6, 19))
    return pts


def render():
    W = N * S
    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad, r = int(W * .04), int(W * .2)
    lw = int(W * .022)
    d.rounded_rectangle([pad, pad, W - pad, W - pad], r, fill=PAPER, outline=INK, width=lw)
    # owl 32 单位 → 画布中间 ~78%
    k = W * .78 / 26          # 路径实际跨度 x 6..26、y 7..29
    ox = W / 2 - 16 * k
    oy = W / 2 - 18.6 * k
    T = lambda p: (ox + p[0] * k, oy + p[1] * k)  # noqa: E731
    stroke = int(1.2 * k * .9)
    d.polygon([T(p) for p in body_path()], fill=BLUE, outline=INK, width=stroke)
    for cx in (12, 20):
        c = T((cx, 16)); rr = 3.6 * k
        d.ellipse([c[0] - rr, c[1] - rr, c[0] + rr, c[1] + rr], fill=WHITE, outline=INK, width=int(1.1 * k * .9))
        c = T((cx + .6, 16.3)); rr = 1.5 * k
        d.ellipse([c[0] - rr, c[1] - rr, c[0] + rr, c[1] + rr], fill=INK)
    d.polygon([T((15, 20)), T((16, 22)), T((17, 20))], fill=YELLOW, outline=INK, width=int(.9 * k * .9))
    return img.resize((N, N), Image.LANCZOS)


SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect x="1" y="1" width="30" height="30" rx="6.4" fill="#f5f3ee" stroke="#1b2142" stroke-width=".7"/>
<g transform="translate(16 15.4) scale(.94) translate(-16 -18)"><path d="M7 7 L10 11 Q16 8 22 11 L25 7 L26 19 Q26 29 16 29 Q6 29 6 19 Z" fill="#2951e6" stroke="#1b2142" stroke-width="1.2" stroke-linejoin="round"/>
<circle cx="12" cy="16" r="3.6" fill="#fff" stroke="#1b2142" stroke-width="1.1"/><circle cx="20" cy="16" r="3.6" fill="#fff" stroke="#1b2142" stroke-width="1.1"/>
<circle cx="12.6" cy="16.3" r="1.5" fill="#1b2142"/><circle cx="20.6" cy="16.3" r="1.5" fill="#1b2142"/>
<path d="M15 20 L16 22 L17 20 Z" fill="#f6d34a" stroke="#1b2142" stroke-width=".9" stroke-linejoin="round"/></g></svg>
"""


def main():
    os.makedirs(OUT, exist_ok=True)
    img = render()
    img.save(os.path.join(OUT, "icon.png"))
    img.save(os.path.join(OUT, "lyceum.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    img.save(os.path.join(OUT, "lyceum.icns"))
    with open(os.path.join(OUT, "lyceum.svg"), "w", encoding="utf-8") as f:
        f.write(SVG)
    print("icons →", OUT)


if __name__ == "__main__":
    main()
