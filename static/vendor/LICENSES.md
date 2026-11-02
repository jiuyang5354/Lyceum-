# 第三方资源与协议

本目录里的文件都是本地打包的第三方资源，桌面版因此可以离线使用；网页版也从这里加载。

| 资源 | 版本 | 文件 | 协议 |
|---|---|---|---|
| three.js | r170 | `three.module.min.js`、`BufferGeometryUtils.js`（examples/jsm/utils） | MIT · Copyright © 2010–2024 three.js authors · https://github.com/mrdoob/three.js/blob/dev/LICENSE |
| KaTeX | 0.16.11 | `katex/`（含 auto-render 与 KaTeX 字体） | MIT · Copyright © 2013–2020 Khan Academy and other contributors · https://github.com/KaTeX/KaTeX/blob/main/LICENSE |
| Cormorant Garamond | — | `fonts/CormorantGaramond-*.woff2` | SIL Open Font License 1.1 · Christian Thalmann (Catharsis Fonts) |
| GFS Didot | — | `fonts/GFSDidot-greek.woff2` | SIL Open Font License 1.1 · Greek Font Society |
| JetBrains Mono | — | `fonts/JetBrainsMono-*.woff2` | SIL Open Font License 1.1 · JetBrains |
| Noto Serif SC（思源宋体） | 2.003（google/fonts 可变字体） | `fonts/NotoSerifSC-500-common.woff2`、`fonts/NotoSerifSC-600-common.woff2`、`fonts/noto-serif-sc.css` | SIL Open Font License 1.1 · © 2017-2024 Adobe（Google 发布） · 全文见 `fonts/OFL-NotoSerifSC.txt` |

字体文件是 Google Fonts 分发的 woff2 子集（按 unicode-range 切分），原样再分发，未改字形。

**中文衬线字体（标题）打包了常用字子集**：Noto Serif SC 可变字体按页面实际用到的字重 500、600 实例化后，
用 fonttools（`tools/subset_cjk_font.py`）裁成子集：《通用规范汉字表》一级字 3500 ∪ GB2312 一级字 3755 ∪ 前端文件与
taxonomy.json / strategies.py 里出现的全部汉字（共 3884 个汉字）+ 中文标点 + 全角符号 + ASCII，每个字重约 0.73 MB。
这是对原字体的子集化修改，OFL 允许修改与再分发（该字体的 OFL 未声明保留字体名，内部名称沿用原文件），协议全文随附，不单独售卖。
`@font-face` 用 unicode-range 限定在子集码位内，子集外的生僻字继续由 Google Fonts（联网时）或系统宋体
（Source Han Serif SC → Songti SC → SimSun）补上。

**正文中文无衬线体（Noto Sans SC）没有打包**：正文字号小、无衬线体之间差别不大，离线时回退 PingFang SC（macOS）/
Microsoft YaHei 微软雅黑（Windows）观感接近；联网时仍从 Google Fonts 非阻塞加载（`media="print" onload`）。
