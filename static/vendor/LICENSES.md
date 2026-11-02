# 第三方资源与协议

本目录里的文件都是本地打包的第三方资源，桌面版因此可以离线使用；网页版也从这里加载。

| 资源 | 版本 | 文件 | 协议 |
|---|---|---|---|
| three.js | r170 | `three.module.min.js`、`BufferGeometryUtils.js`（examples/jsm/utils） | MIT · Copyright © 2010–2024 three.js authors · https://github.com/mrdoob/three.js/blob/dev/LICENSE |
| KaTeX | 0.16.11 | `katex/`（含 auto-render 与 KaTeX 字体） | MIT · Copyright © 2013–2020 Khan Academy and other contributors · https://github.com/KaTeX/KaTeX/blob/main/LICENSE |
| Cormorant Garamond | — | `fonts/CormorantGaramond-*.woff2` | SIL Open Font License 1.1 · Christian Thalmann (Catharsis Fonts) |
| GFS Didot | — | `fonts/GFSDidot-greek.woff2` | SIL Open Font License 1.1 · Greek Font Society |
| JetBrains Mono | — | `fonts/JetBrainsMono-*.woff2` | SIL Open Font License 1.1 · JetBrains |

字体文件是 Google Fonts 分发的 woff2 子集（按 unicode-range 切分），原样再分发，未改字形。

**中文字体没有打包**：Noto Serif SC / Noto Sans SC 单个字重就有十几 MB，整套打进安装包不划算。
页面仍以非阻塞方式从 Google Fonts 加载它们（`media="print" onload`），连不上（离线、或网络访问不到 Google）时
自动回退到系统字体：衬线 Source Han Serif SC → Songti SC（macOS）→ SimSun / 宋体（Windows），
无衬线 PingFang SC（macOS）→ Microsoft YaHei / 微软雅黑（Windows）。
