// 线稿：柱头（多立克/爱奥尼/科林斯）、回纹、桂冠、猫头鹰标志、贴纸、图标。全部自绘。
const S = (vb, body, cls = '') => `<svg viewBox="${vb}" class="${cls}" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;

function spiral(cx, cy, r0, turns, dir = 1) {
  const pts = []; const n = 70;
  for (let i = 0; i <= n; i++) {
    const t = i / n, a = dir * t * turns * Math.PI * 2 + Math.PI / 2, r = r0 * (1 - t * 0.82);
    pts.push(`${(cx + Math.cos(a) * r).toFixed(2)},${(cy + Math.sin(a) * r).toFixed(2)}`);
  }
  return `<polyline points="${pts.join(' ')}"/>`;
}
const flutes = (x1, x2, y1, y2, n) => {
  let s = '';
  for (let i = 1; i < n; i++) { const x = x1 + (x2 - x1) * i / n; s += `<line x1="${x.toFixed(1)}" y1="${y1}" x2="${(x + (i - n / 2) * 0.25).toFixed(1)}" y2="${y2}" stroke-width=".8"/>`; }
  return s;
};

export function capital(order) {
  if (order === 'doric') return S('0 0 100 100',
    `<rect x="14" y="16" width="72" height="11"/>
     <path d="M20 27 C 30 41, 70 41, 80 27"/>
     <path d="M27 38 H73"/><path d="M28 42 H72"/>
     <path d="M28 42 L30 98 M72 42 L70 98"/>${flutes(28, 72, 42, 98, 6)}`);
  if (order === 'ionic') return S('0 0 100 100',
    `<rect x="12" y="15" width="76" height="6"/>
     <path d="M12 21 C 20 23, 80 23, 88 21"/>
     ${spiral(19, 33, 11, 2.2, -1)}${spiral(81, 33, 11, 2.2, 1)}
     <path d="M19 22 C 40 27, 60 27, 81 22"/>
     <path d="M30 35 C 40 44, 60 44, 70 35"/>
     <path d="M30 46 H70"/><path d="M31 46 L33 98 M69 46 L67 98"/>${flutes(31, 69, 46, 98, 7)}`);
  // corinthian
  let leaves = '';
  for (let i = 0; i < 5; i++) { const x = 26 + i * 12; leaves += `<path d="M${x} 62 C ${x - 6} 52, ${x - 3} 44, ${x} 40 C ${x + 3} 44, ${x + 6} 52, ${x} 62 Z" stroke-width="1"/><path d="M${x} 61 V44" stroke-width=".7"/>`; }
  for (let i = 0; i < 4; i++) { const x = 32 + i * 12; leaves += `<path d="M${x} 48 C ${x - 6} 38, ${x - 3} 30, ${x} 26 C ${x + 3} 30, ${x + 6} 38, ${x} 48" stroke-width="1"/>`; }
  return S('0 0 100 100',
    `<path d="M10 12 Q 50 18 90 12 L 88 19 Q 50 24 12 19 Z"/>
     ${spiral(16, 24, 6, 1.6, -1)}${spiral(84, 24, 6, 1.6, 1)}
     <path d="M24 22 C 28 40, 30 54, 32 64 M76 22 C 72 40, 70 54, 68 64"/>
     ${leaves}
     <path d="M32 64 H68"/><path d="M33 66 L34 98 M67 66 L66 98"/>${flutes(33, 67, 66, 98, 6)}`);
}

export const orderOfGrade = (g) => g <= 6 ? 'doric' : (g <= 9 ? 'ionic' : 'corinthian');

export function meanderURL(color = '#1b2142') {
  const c = encodeURIComponent(color);
  const svg = `<svg xmlns='http://www.w3.org/2000/svg' width='28' height='14' viewBox='0 0 28 14'><g fill='none' stroke='${c}' stroke-width='1.2' stroke-linecap='square'><path d='M0 13.4 H28 M0 .6 H28'/><path d='M0 10.5 H17 V3.5 H5 V7.5 H12'/><path d='M21 10.5 V3.5 H28'/></g></svg>`;
  return `url("data:image/svg+xml;utf8,${svg.replace(/#/g, '%23').replace(/"/g, "'")}")`;
}

export function laurel(color = 'currentColor') {
  let leaves = '', stem = '';
  for (const side of [-1, 1]) {
    const pts = [];
    for (let i = 0; i <= 9; i++) {
      const t = i / 9, ang = side < 0 ? 100 + t * 72 : 80 - t * 72, rad = ang * Math.PI / 180;
      const x = 110 + 42 * Math.cos(rad), y = 40 + 42 * Math.sin(rad);
      pts.push(`${x.toFixed(1)},${y.toFixed(1)}`);
      if (i === 0) continue;
      for (const k of [-1, 1]) {
        const off = 6 * k, lx = 110 + (42 + off) * Math.cos(rad), ly = 40 + (42 + off) * Math.sin(rad);
        const rot = ang + (side < 0 ? 0 : 180) + k * side * 32;
        leaves += `<ellipse cx="${lx.toFixed(1)}" cy="${ly.toFixed(1)}" rx="2.8" ry="7" transform="rotate(${rot.toFixed(1)} ${lx.toFixed(1)} ${ly.toFixed(1)})"/>`;
      }
    }
    stem += `<polyline points="${pts.join(' ')}"/>`;
  }
  return `<svg class="laurel" viewBox="56 30 108 66" fill="none" stroke="${color}" stroke-width="1.1" aria-hidden="true">${stem}${leaves}<path d="M106 83 L100 92 M114 83 L120 92"/></svg>`;
}

export function owlMark(fill = '#2951e6') {
  return `<svg viewBox="0 0 32 32" aria-hidden="true"><path d="M7 7 L10 11 Q16 8 22 11 L25 7 L26 19 Q26 29 16 29 Q6 29 6 19 Z" fill="${fill}" stroke="#1b2142" stroke-width="1.2" stroke-linejoin="round"/>
  <circle cx="12" cy="16" r="3.6" fill="#fff" stroke="#1b2142" stroke-width="1.1"/><circle cx="20" cy="16" r="3.6" fill="#fff" stroke="#1b2142" stroke-width="1.1"/>
  <circle cx="12.6" cy="16.3" r="1.5" fill="#1b2142"/><circle cx="20.6" cy="16.3" r="1.5" fill="#1b2142"/>
  <path d="M15 20 L16 22 L17 20 Z" fill="#f6d34a" stroke="#1b2142" stroke-width=".9" stroke-linejoin="round"/></svg>`;
}

export const icons = {
  image: S('0 0 24 24', '<rect x="3" y="5" width="18" height="14"/><circle cx="9" cy="10" r="1.8"/><path d="M4 18 L10 13 L14 16 L17 13 L20 16"/>'),
  close: S('0 0 24 24', '<path d="M6 6 L18 18 M18 6 L6 18"/>'),
};

// 贴纸：平涂 + 墨线 + 白边，像三渲二的贴纸
const STICK = [
  (c) => `<svg width="84" height="84" viewBox="0 0 84 84"><circle cx="42" cy="42" r="36" fill="#fff" stroke="#1b2142" stroke-width="1.5"/><circle cx="42" cy="42" r="30" fill="${c}" stroke="#1b2142" stroke-width="1.2"/><text x="42" y="54" text-anchor="middle" font-family="Cormorant Garamond, serif" font-size="36" fill="#fff">π</text></svg>`,
  (c) => `<svg width="96" height="64" viewBox="0 0 96 64"><rect x="4" y="4" width="88" height="56" rx="28" fill="#fff" stroke="#1b2142" stroke-width="1.5"/><rect x="10" y="10" width="76" height="44" rx="22" fill="#f6d34a" stroke="#1b2142" stroke-width="1.2"/><text x="48" y="41" text-anchor="middle" font-family="Cormorant Garamond, serif" font-size="26" font-style="italic" fill="#1b2142">A+</text></svg>`,
  (c) => `<svg width="80" height="80" viewBox="0 0 80 80"><path d="M40 4 L49 29 L76 30 L55 46 L62 73 L40 58 L18 73 L25 46 L4 30 L31 29 Z" fill="#fff" stroke="#1b2142" stroke-width="1.5" stroke-linejoin="round"/><path d="M40 14 L46 32 L65 33 L50 44 L55 63 L40 52 L25 63 L30 44 L15 33 L34 32 Z" fill="${c}" stroke="#1b2142" stroke-width="1.1" stroke-linejoin="round"/></svg>`,
  (c) => `<svg width="84" height="84" viewBox="0 0 84 84"><rect x="6" y="6" width="72" height="72" fill="#fff" stroke="#1b2142" stroke-width="1.5"/><rect x="12" y="12" width="60" height="60" fill="#e6ebfb" stroke="#1b2142" stroke-width="1.1"/><text x="42" y="56" text-anchor="middle" font-family="Cormorant Garamond, serif" font-size="40" fill="#2951e6">Ω</text></svg>`,
  (c) => `<svg width="84" height="84" viewBox="0 0 84 84"><circle cx="42" cy="42" r="36" fill="#fff" stroke="#1b2142" stroke-width="1.5"/><circle cx="42" cy="42" r="30" fill="#fff" stroke="#1b2142" stroke-width="1.1"/><path d="M28 43 L38 53 L57 32" stroke="${c}" stroke-width="6" fill="none" stroke-linecap="square"/></svg>`,
  (c) => `<svg width="96" height="60" viewBox="0 0 96 60"><path d="M6 8 H90 V44 H54 L42 56 L40 44 H6 Z" fill="#fff" stroke="#1b2142" stroke-width="1.5" stroke-linejoin="round"/><text x="48" y="33" text-anchor="middle" font-family="Noto Serif SC, serif" font-size="17" fill="#1b2142">想一想</text></svg>`,
  (c) => `<svg width="84" height="84" viewBox="0 0 84 84"><circle cx="42" cy="42" r="36" fill="#fff" stroke="#1b2142" stroke-width="1.5"/><circle cx="42" cy="42" r="30" fill="${c}" stroke="#1b2142" stroke-width="1.2"/><text x="42" y="53" text-anchor="middle" font-family="Cormorant Garamond, serif" font-size="30" fill="#fff">√x</text></svg>`,
];
let si = 0;
export function sticker() { const s = STICK[si % STICK.length]('#2951e6'); si++; return s; }

/* ---------- 学科图标：古希腊线稿意象，统一 1.5px 墨线（不随尺寸缩放） ---------- */
const I = (body) => `<svg viewBox="0 0 24 24" class="si" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><g vector-effect="non-scaling-stroke">${body.replace(/<(path|circle|ellipse|rect|line|polyline)/g, '<$1 vector-effect="non-scaling-stroke"')}</g></svg>`;
const SUBJECT_ICONS = {
  // 数学：圆规（欧几里得）
  '数学': I('<circle cx="12" cy="4.2" r="1.5"/><path d="M11.3 5.6 L6.2 20"/><path d="M12.7 5.6 L17.8 20"/><path d="M7.9 15.4 Q12 17.6 16.1 15.4"/>'),
  // 语文：卷轴
  '语文': I('<path d="M6.5 4 V20 M17.5 4 V20"/><path d="M5 4 H8 M5 20 H8 M16 4 H19 M16 20 H19"/><path d="M6.5 6.5 H17.5 M6.5 17.5 H17.5"/><path d="M9.5 10 H14.5 M9.5 13 H13.5"/>'),
  // 英语：羽毛笔
  '英语': I('<path d="M19.5 3.5 C12 5 7.5 10 6 20"/><path d="M19.5 3.5 C19 10.5 14 14.5 8.2 15"/><path d="M10.2 10.6 L14.6 8.6 M8.9 13.2 L12.4 12.1"/><path d="M4 20.5 H10"/>'),
  // 物理：杠杆（阿基米德）
  '物理': I('<path d="M3 14.2 L21 9.2"/><path d="M12 11.7 L9 17.5 H15 Z"/><rect x="16.6" y="5.6" width="3.4" height="3.4" transform="rotate(-15.5 18.3 7.3)"/><path d="M3 20.5 H21"/>'),
  // 化学：双耳瓶
  '化学': I('<path d="M10 3 H14"/><path d="M10.6 3 V6.2 C6.3 8 6.2 14.6 9 17.6 L10 20.5 H14 L15 17.6 C17.8 14.6 17.7 8 13.4 6.2 V3"/><path d="M10.6 7.2 C8.2 7.6 7.4 5.2 8.6 4.6 M13.4 7.2 C15.8 7.6 16.6 5.2 15.4 4.6"/><path d="M8 12 H16"/>'),
  // 生物：橄榄枝
  '生物': I('<path d="M5 20 C9 15 13 10 19 4"/><ellipse cx="9" cy="13.2" rx="1.2" ry="3" transform="rotate(-60 9 13.2)"/><ellipse cx="9.4" cy="17.4" rx="1.2" ry="3" transform="rotate(30 9.4 17.4)"/><ellipse cx="13.2" cy="8.8" rx="1.2" ry="3" transform="rotate(-55 13.2 8.8)"/><ellipse cx="13.8" cy="12.6" rx="1.2" ry="3" transform="rotate(35 13.8 12.6)"/><circle cx="17.6" cy="9" r="1.3"/>'),
  // 历史：石柱
  '历史': I('<path d="M5.5 4 H18.5 M7 6.5 H17"/><path d="M8 6.5 V18 M16 6.5 V18 M10.7 6.5 V18 M13.3 6.5 V18"/><path d="M7 18 H17 M5 20.5 H19"/>'),
  // 地理：天球
  '地理': I('<circle cx="12" cy="10" r="6.5"/><ellipse cx="12" cy="10" rx="6.5" ry="2.2"/><path d="M7.4 5.4 L16.6 14.6"/><path d="M12 16.5 V20 M8 20.5 H16"/>'),
  // 道德与法治 / 政治：天平
  '道德与法治': I('<path d="M12 3.5 V19.5 M8 20.5 H16 M4.5 7 H19.5"/><path d="M4.5 7 L2.8 13 M4.5 7 L6.2 13 M19.5 7 L17.8 13 M19.5 7 L21.2 13"/><path d="M2.5 13 Q4.5 15.6 6.5 13 Z M17.5 13 Q19.5 15.6 21.5 13 Z"/>'),
  // 科学：浑天仪（简）
  '科学': I('<circle cx="12" cy="11" r="7"/><ellipse cx="12" cy="11" rx="7" ry="2.6" transform="rotate(-25 12 11)"/><circle cx="12" cy="11" r="1.4"/>'),
  // 信息技术：蜡板与尖笔
  '信息技术': I('<rect x="4" y="5" width="14" height="12"/><path d="M7 9 H15 M7 12 H13"/><path d="M15 21 L21 8"/>'),
  '其他': I('<circle cx="12" cy="12" r="7.5"/><path d="M12 7.5 V16.5 M7.5 12 H16.5"/>'),
};
SUBJECT_ICONS['政治'] = SUBJECT_ICONS['道德与法治'];
export const subjectIcon = (name) => SUBJECT_ICONS[name] || SUBJECT_ICONS['其他'];

// 提示进度：一根小柱子（柱头/柱身凹槽/柱础），三根并排 = 方向 / 方法 / 最后一步
export function columnGlyph() {
  return `<svg viewBox="0 0 40 72" class="cg" fill="none" stroke="currentColor" stroke-width="1.2" aria-hidden="true">
    <rect class="fill" x="11" y="12" width="18" height="50" stroke="none"/>
    <rect x="6" y="3" width="28" height="5"/><path d="M8 8 Q20 14 32 8"/><path d="M10 12 H30"/>
    <path d="M11 12 V62 M29 12 V62"/><path d="M15.5 13 V61 M20 13 V61 M24.5 13 V61" stroke-width=".7"/>
    <path d="M9 62 H31"/><rect x="6" y="64" width="28" height="5"/></svg>`;
}

// 正立面线稿：山花 + 四柱（CTA、空状态用）
export function templeFront(color = 'currentColor') {
  let cols = '';
  for (let i = 0; i < 4; i++) { const x = 34 + i * 34; cols += `<path d="M${x} 50 V96 M${x + 12} 50 V96" /><path d="M${x + 4} 51 V95 M${x + 8} 51 V95" stroke-width=".6"/><path d="M${x - 2} 48 H${x + 14}"/>`; }
  return `<svg class="temple-front" viewBox="0 0 200 112" fill="none" stroke="${color}" stroke-width="1.1" aria-hidden="true">
    <path d="M18 34 L100 8 L182 34 Z"/><path d="M30 32 L100 13 L170 32"/>
    <path d="M16 34 H184 M20 40 H180 M22 46 H178"/>${cols}
    <path d="M24 96 H176 M18 101 H182 M12 106 H188"/></svg>`;
}

// 空状态 / 加载：小雅站在一根线稿柱子上
export function owlOnColumn() {
  return `<svg class="owl-col" viewBox="0 0 120 170" fill="none" stroke="#1b2142" stroke-width="1.2" aria-hidden="true">
    <g transform="translate(36 6) scale(1.5)">
      <path d="M7 7 L10 11 Q16 8 22 11 L25 7 L26 19 Q26 29 16 29 Q6 29 6 19 Z" fill="#2951e6" stroke-linejoin="round"/>
      <circle cx="12" cy="16" r="3.6" fill="#fff"/><circle cx="20" cy="16" r="3.6" fill="#fff"/>
      <circle cx="12.6" cy="16.3" r="1.5" fill="#1b2142" stroke="none"/><circle cx="20.6" cy="16.3" r="1.5" fill="#1b2142" stroke="none"/>
      <path d="M15 20 L16 22 L17 20 Z" fill="#f6d34a" stroke-linejoin="round" stroke-width=".8"/></g>
    <rect x="28" y="52" width="64" height="8"/><path d="M32 60 Q60 70 88 60"/><path d="M36 66 H84"/>
    <path d="M38 66 V150 M82 66 V150"/><path d="M45.3 67 V149 M52.6 67 V149 M60 67 V149 M67.3 67 V149 M74.6 67 V149" stroke-width=".6"/>
    <path d="M34 150 H86"/><rect x="26" y="153" width="68" height="8"/><path d="M14 165 H106"/></svg>`;
}

// 低山花（石碑 stele 卡片顶），拉伸用
export function pedimentURL(color = '#1b2142') {
  const c = encodeURIComponent(color);
  const svg = `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 400 16' preserveAspectRatio='none'><g fill='none' stroke='${c}' stroke-width='1' vector-effect='non-scaling-stroke'><path vector-effect='non-scaling-stroke' d='M0 15.5 L200 1 L400 15.5'/><path vector-effect='non-scaling-stroke' d='M24 15.5 L200 4.6 L376 15.5' stroke-opacity='.35'/></g></svg>`;
  return `url("data:image/svg+xml;utf8,${svg.replace(/#/g, '%23').replace(/"/g, "'")}")`;
}

// 奖励时刻用的小桂冠（只在答对 / 全对 / 我会了 时出现）
export function laurelMini(color = '#2951e6') {
  let l = '', stem = '';
  for (const side of [-1, 1]) {
    const pts = [];
    for (let k = 0; k <= 4; k++) {
      const th = (100 + k * 28) * Math.PI / 180, r = 7.6;
      let x = 12 + r * Math.cos(th), y = 12.5 + r * Math.sin(th);
      if (side > 0) x = 24 - x;
      pts.push(`${x.toFixed(2)},${y.toFixed(2)}`);
      if (k === 0) continue;
      const tang = (100 + k * 28 + 90);
      const rot = side < 0 ? tang + 28 : 180 - tang - 28;
      l += `<ellipse cx="${x.toFixed(2)}" cy="${y.toFixed(2)}" rx="1.15" ry="2.6" transform="rotate(${rot.toFixed(1)} ${x.toFixed(2)} ${y.toFixed(2)})" fill="${color}" fill-opacity=".14"/>`;
    }
    stem += `<polyline points="${pts.join(' ')}"/>`;
  }
  return `<svg class="laurel-mini" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="1.1" stroke-linecap="round" aria-hidden="true">${stem}${l}<path d="M10.6 20.4 L9.6 22 M13.4 20.4 L14.4 22"/></svg>`;
}

// 页面纸纹：程序生成（feTurbulence），印刷颗粒感，极淡
export function paperGrainURL() {
  const svg = `<svg xmlns='http://www.w3.org/2000/svg' width='260' height='260'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='2' stitchTiles='stitch' seed='7'/><feColorMatrix values='0 0 0 0 .09  0 0 0 0 .10  0 0 0 0 .14  0 0 0 1.6 -.55'/></filter><rect width='100%' height='100%' filter='url(#n)'/></svg>`;
  return `url("data:image/svg+xml;utf8,${svg.replace(/#/g, '%23').replace(/"/g, "'")}")`;
}

// ---------- 第四版：流式柱头 / 空状态与错误的线稿小图（1.2px 墨线 + 一处钴蓝） ----------
// 柱头：顶板 + 馒头形 + 柱颈；.glow 是顶板下的一道蓝光，流式时呼吸
export function capitalPulse() {
  return `<svg viewBox="0 0 32 24" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true">
    <rect class="glow" x="3" y="7" width="26" height="3" fill="#2951e6" stroke="none"/>
    <rect x="2" y="2" width="28" height="5"/><path d="M5 10 Q16 17 27 10"/><path d="M8 15 H24 M10 15 V23 M22 15 V23 M16 16 V23" stroke-width="1"/></svg>`;
}
const ART = {
  // 错题本空：一块还没刻字的石碑
  stele: `<svg viewBox="0 0 88 96" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round" aria-hidden="true">
    <path d="M18 22 L44 8 L70 22 Z"/><path d="M26 21 L44 12 L62 21" stroke-opacity=".4"/>
    <rect x="20" y="22" width="48" height="58"/><path d="M28 36 H60" stroke="#2951e6"/><path d="M28 44 H52 M28 52 H56" stroke-opacity=".25" stroke-dasharray="2 3"/>
    <path d="M16 80 H72 M12 86 H76 M6 92 H82"/></svg>`,
  // 今天没有要复习：日晷，影子落在下一格
  sundial: `<svg viewBox="0 0 88 96" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round" aria-hidden="true">
    <ellipse cx="44" cy="58" rx="34" ry="12"/><path d="M10 58 V66 Q44 86 78 66 V58" />
    <path d="M44 58 L44 26 L60 58" /><path d="M44 58 L22 52" stroke="#2951e6" stroke-width="1.6"/>
    <path d="M20 58 L16 60 M30 64 L28 67 M44 66 V70 M58 64 L60 67 M68 58 L72 60" stroke-opacity=".5"/>
    <path d="M14 90 H74"/></svg>`,
  // 记忆为空：一只空着的双耳瓶
  amphora: `<svg viewBox="0 0 88 96" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round" aria-hidden="true">
    <path d="M36 8 H52 M38 8 V18 Q22 26 24 50 Q26 72 44 84 Q62 72 64 50 Q66 26 50 18 V8"/>
    <path d="M38 20 Q26 18 28 34 M50 20 Q62 18 60 34"/><path d="M27 44 H61" stroke="#2951e6"/><path d="M26 52 H62" stroke-opacity=".35"/>
    <path d="M38 84 L36 90 H52 L50 84"/></svg>`,
  // 出错：一根断开的柱子，上半截落在地上
  broken: `<svg viewBox="0 0 88 96" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" aria-hidden="true">
    <path d="M22 90 H66 M26 84 H62 V90"/><path d="M30 84 V44 L36 40 L42 46 L48 39 L54 45 L58 42 V84"/>
    <path d="M37 50 V82 M44 50 V82 M51 50 V82" stroke-width="1" stroke-opacity=".5"/>
    <path d="M60 30 L80 40 L74 52 L54 42 Z" stroke="#2951e6"/></svg>`,
};
export const art = (k) => `<span class="art">${ART[k] || ART.stele}</span>`;
