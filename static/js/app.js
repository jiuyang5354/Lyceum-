import { capital, orderOfGrade, meanderURL, laurel, owlMark, icons, sticker, subjectIcon, columnGlyph, templeFront, owlOnColumn, pedimentURL, laurelMini, capitalPulse, art } from './svg.js';

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;
const GRADES = ['一年级', '二年级', '三年级', '四年级', '五年级', '六年级', '初一', '初二', '初三', '高一', '高二', '高三'];
const TEXTBOOKS = ['人教版', '北师大版', '苏教版', '沪教版', '部编版', '外研版'];
const ORDERS = {
  doric: { name: '多立克', en: 'Doric', band: '小学', range: [1, 6], note: '粗壮朴素，没有柱础。<br>像打地基的小学：慢慢来，多举生活里的例子。' },
  ionic: { name: '爱奥尼', en: 'Ionic', band: '初中', range: [7, 9], note: '柱头一对涡卷，比例更修长。<br>像初中：把每一步的道理讲透。' },
  corinthian: { name: '科林斯', en: 'Corinthian', band: '高中', range: [10, 12], note: '两层叶饰，最繁复也最精确。<br>像高中：讲通法，抠易错点。' },
};
const SUBJ = [
  ['Σ', '数学', '口算、方程、函数到导数，一步一步推'], ['Λ', '语文', '字词、古诗文、阅读理解；作文只引导不代写'],
  ['Ε', '英语', '语法、阅读、写作，中英结合讲'], ['Φ', '物理', '受力、电路、能量，先画情境再列式'],
  ['Χ', '化学', '方程式配平、计算、实验现象'], ['Β', '生物', '细胞、遗传、生态，概念之间的关系'],
  ['Η', '历史', '时间线、因果、材料题的答题思路'], ['Γ', '地理', '读图、气候、区域，联系生活'],
  ['Δ', '道德与法治', '观点、材料分析，学会自己组织语言'],
];
const GLYPH = Object.fromEntries(SUBJ.map(([g, n]) => [n, g])); GLYPH['科学'] = 'Θ'; GLYPH['其他'] = 'Ω'; GLYPH['信息技术'] = 'Ι';

const state = { profile: null, llm: false, model: '', session: null, msgs: [], image: null, busy: false, problemState: {}, route: 'home', tab: 'notebook', filter: '' };
let stage = null;

/* ---------------- 事件总线 + 小雅情绪状态机（见 DESIGN.md「小雅的情绪」） ----------------
   答疑流程只发事件，不直接摆弄小雅；情绪机把事件翻译成 等待 / 倾听 / 思考 / 提示 / 鼓励 / 庆祝，
   同时驱动三维小雅（stage.setMood）和右栏的文字标签。 */
const bus = new EventTarget();
const emit = (type, detail = {}) => bus.dispatchEvent(new CustomEvent(type, { detail }));
const on = (type, fn) => bus.addEventListener(type, (e) => fn(e.detail || {}));
const MOOD_LABEL = { wait: '等待', listen: '倾听', think: '思考', hint: '提示', encourage: '鼓励', celebrate: '庆祝' };
const mood = { cur: 'wait', timer: 0 };
function setMood(m, holdMs = 0, then = 'wait') {
  clearTimeout(mood.timer); mood.cur = m;
  if (stage) stage.setMood(m);
  const f = $('.owl-frame'); if (f) f.dataset.mood = m;
  const lab = $('#owlMood'); if (lab) lab.textContent = MOOD_LABEL[m];
  if (holdMs) mood.timer = setTimeout(() => setMood(then), holdMs);
}
on('compose:typing', () => { if (!state.busy && (mood.cur === 'wait' || mood.cur === 'listen')) setMood('listen', 2400); });
on('ask:send', () => setMood('listen', 520, 'think'));            // 先「听」半秒，再低头想
on('ask:stream', () => setMood('hint'));                            // 开始写：转向学生、一下一下点头
on('ask:verify', () => setMood('think'));                           // 代回检验
on('ask:rewrite', () => setMood('think', 700, 'hint'));             // 漏题拦截：收回、重想
on('ask:solved', () => setMood('celebrate', 1900));                 // 唯一的庆祝
on('ask:stuck', () => setMood('encourage', 1800));
on('hint:advance', () => setMood('hint', 1200));
on('ask:settle', () => setMood('wait'));
on('ask:error', () => setMood('encourage', 1600));
on('practice:start', () => setMood('think'));
on('practice:graded', () => setMood('encourage', 1800));

/* ---------------- 工具 ---------------- */
async function api(path, body) {
  const r = await fetch(path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {});
  const j = await r.json().catch(() => ({ error: '服务没有响应' }));
  if (!r.ok) throw new Error(j.error || '出错了');
  return j;
}
function toast(t, reward = false) { const d = document.createElement('div'); d.className = 'toast' + (reward ? ' reward' : ''); d.textContent = t; if (reward) d.insertAdjacentHTML('afterbegin', laurelMini('#f5f3ee')); document.body.appendChild(d); setTimeout(() => d.remove(), 2600); }
const sIco = (n) => `<span class="sico">${subjectIcon(n)}</span>`;
const GK = ['Α', 'Β', 'Γ', 'Δ', 'Ε', 'Ζ', 'Η', 'Θ'];
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
function handles(el) { if (!el.querySelector(':scope > i.h')) for (let i = 0; i < 4; i++) el.insertAdjacentHTML('afterbegin', '<i class="h"></i>'); }
function ago(ts) {
  const d = (Date.now() / 1000 - ts); if (d < 60) return '刚刚'; if (d < 3600) return Math.floor(d / 60) + ' 分钟前';
  if (d < 86400) return Math.floor(d / 3600) + ' 小时前'; const t = new Date(ts * 1000); return `${t.getMonth() + 1}月${t.getDate()}日`;
}
// 极简 Markdown（先保护公式）
function md(src) {
  const math = [];
  let s = String(src || '').replace(/\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]|\\\(([\s\S]+?)\\\)|\$([^\$\n]+?)\$/g, (m) => { math.push(m); return `\u0000${math.length - 1}\u0000`; });
  s = esc(s);
  const lines = s.split('\n'); const out = []; let list = null;
  const inline = (t) => t.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/`([^`]+)`/g, '<code>$1</code>');
  for (const raw of lines) {
    const l = raw.trimEnd();
    let m;
    if ((m = l.match(/^\s*[-*•]\s+(.*)/))) { if (list !== 'ul') { if (list) out.push(`</${list}>`); out.push('<ul>'); list = 'ul'; } out.push(`<li>${inline(m[1])}</li>`); continue; }
    if ((m = l.match(/^\s*(\d+)[.、)]\s+(.*)/))) { if (list !== 'ol') { if (list) out.push(`</${list}>`); out.push('<ol>'); list = 'ol'; } out.push(`<li>${inline(m[2])}</li>`); continue; }
    if (list) { out.push(`</${list}>`); list = null; }
    if ((m = l.match(/^#{1,4}\s+(.*)/))) { out.push(`<h4>${inline(m[1])}</h4>`); continue; }
    if ((m = l.match(/^&gt;\s?(.*)/))) { out.push(`<blockquote>${inline(m[1])}</blockquote>`); continue; }
    if (!l.trim()) { out.push(''); continue; }
    out.push(`<p>${inline(l)}</p>`);
  }
  if (list) out.push(`</${list}>`);
  // 公式后面紧跟的中文标点不另起一行
  return out.join('\n').replace(/\u0000(\d+)\u0000([，。；：！？、）」』”]?)/g, (_, i, p) => p ? `<span class="nb">${esc(math[+i])}${p}</span>` : esc(math[+i]));
}
function tex(el) {
  if (window.renderMathInElement) renderMathInElement(el, { delimiters: [{ left: '$$', right: '$$', display: true }, { left: '\\[', right: '\\]', display: true }, { left: '\\(', right: '\\)', display: false }, { left: '$', right: '$', display: false }], throwOnError: false });
}

/* ---------------- 三维舞台（懒加载，失败就静默降级） ---------------- */
async function ensureStage() {
  if (stage !== null) return stage;
  stage = false;
  try { const { Stage } = await import('./stage.js'); const s = new Stage(); if (s.ok) stage = s; } catch (e) { console.warn('3D 不可用', e); }
  return stage;
}
function setOrder(order) {
  $$('.order').forEach((b) => b.classList.toggle('on', b.dataset.order === order));
  const o = ORDERS[order];
  $('#orderNote').innerHTML = `<b>${o.name}柱式 · ${o.band}</b>${o.note}`;
  if (stage) stage.setOrder(order);
}

/* ---------------- 首页 ---------------- */
function initHome() {
  $$('[data-meander]').forEach((m) => { m.classList.add('meander'); m.style.backgroundImage = meanderURL('#1b2142'); });
  document.documentElement.style.setProperty('--pediment', pedimentURL('#1b2142'));
  $('#orders').innerHTML = Object.entries(ORDERS).map(([k, o]) => `<button class="order" data-order="${k}">${capital(k)}<span><b>${o.band} · ${o.name}</b><small>${o.en} · ${o.range[0] <= 6 ? o.range[0] + '–' + o.range[1] + ' 年级' : GRADES[o.range[0] - 1] + '–' + GRADES[o.range[1] - 1]}</small></span></button>`).join('');
  $$('.order').forEach((b) => { handles(b); b.onclick = () => setOrder(b.dataset.order); });
  $('#subjects').innerHTML = SUBJ.map(([g, n, d]) => `<div class="subject-row" data-s="${n}"><span class="gl">${subjectIcon(n)}</span><span class="nm">${n}<small class="gk">${g}</small></span><span class="ds">${d}</span><span class="ar">[→] 问一道${n}题</span></div>`).join('');
  $$('.subject-row').forEach((r) => r.onclick = () => { location.hash = '#/study'; setTimeout(() => { $('#input').value = `我有一道${r.dataset.s}题：`; $('#input').focus(); }, 60); });
  $('#ctaLaurel').innerHTML = templeFront('#1b2142');
  $('#howBtn').onclick = () => scrollTo({ top: innerHeight * 0.95, behavior: REDUCED ? 'auto' : 'smooth' });
  tex($('#hero'));
  // 滚动：平涂 → 半调 → 铜版
  const steps = $$('.story-step'), rail = $$('#rail i');
  let heroIdx = 0;
  const onScroll = () => {
    if (state.route !== 'home') return;
    const hero = $('#hero'); const total = hero.offsetHeight - (innerHeight - 68);
    const p = Math.min(1, Math.max(0, scrollY / Math.max(1, total)));
    if (stage) stage.setScroll(p);
    const idx = p < 0.13 ? 0 : p < 0.42 ? 1 : p < 0.7 ? 2 : 3;
    $('#heroCopy').style.opacity = idx === 0 ? 1 : 0; $('#heroCopy').style.pointerEvents = idx === 0 ? 'auto' : 'none';
    $('#stickers').style.opacity = idx === 0 ? 1 : 0; heroIdx = idx;
    $('#orders').style.opacity = idx === 0 ? 1 : 0; $('#orderNote').style.opacity = idx === 0 ? 1 : 0;
    steps.forEach((s, i) => s.classList.toggle('on', i + 1 === idx));
    rail.forEach((r, i) => r.classList.toggle('on', i === idx));
  };
  addEventListener('scroll', onScroll, { passive: true });
  onScroll();
  // 贴纸 + 「选中对象」框
  const sticky = $('.hero-sticky');
  // 首屏默认贴纸（星星、π、A+），首屏外淡出；点击空白处仍可再贴
  [[2, 41, 24, -12, .78], [0, 72.5, 15, 6, .72], [1, 93, 80, -8, .74]].forEach(([k, x, y, r, sc], i) => {
    const d = document.createElement('div'); d.className = 'sticker preset';
    d.style.left = x + '%'; d.style.top = y + '%'; d.style.setProperty('--r', r + 'deg'); d.style.setProperty('--s', sc);
    d.style.animationDelay = (600 + i * 120) + 'ms'; d.innerHTML = sticker(k);
    $('#stickers').appendChild(d);
  });
  sticky.addEventListener('click', (e) => {
    if (e.target.closest('a,button,.hero-copy,.story-step,.orders')) return;
    const r = sticky.getBoundingClientRect();
    const d = document.createElement('div'); d.className = 'sticker';
    d.style.left = (e.clientX - r.left) + 'px'; d.style.top = (e.clientY - r.top) + 'px';
    d.style.setProperty('--r', (Math.random() * 30 - 15).toFixed(1) + 'deg'); d.innerHTML = sticker();
    $('#stickers').appendChild(d); const all = $$('#stickers .sticker'); if (all.length > 10) all[0].remove();
    if (stage) stage.cheer();
  });
  let over = false;
  sticky.addEventListener('pointermove', (e) => {
    if (!stage) return; const o = stage.owlRect(); if (!o) return;
    const r = sticky.getBoundingClientRect(); const x = e.clientX - r.left, y = e.clientY - r.top;
    over = x > o.x - 30 && x < o.x + o.w + 30 && y > o.y - 30 && y < o.y + o.h + 30;
  });
  sticky.addEventListener('pointerleave', () => { over = false; });
  const sel = $('#owlSel');
  let lastY = -1;
  const tick = () => {
    if (state.route === 'home' && scrollY !== lastY) { lastY = scrollY; onScroll(); }
    if (state.route === 'home' && stage) {
      const o = stage.owlRect();
      if (o) { sel.style.left = o.x + 'px'; sel.style.top = o.y + 'px'; sel.style.width = o.w + 'px'; sel.style.height = o.h + 'px'; $('#owlDim').textContent = `${Math.round(o.w)} × ${Math.round(o.h)}`; }
      sel.classList.toggle('on', over || heroIdx === 0 || document.body.dataset.shot === 'sel');
    }
    requestAnimationFrame(tick);
  };
  tick();
}

/* ---------------- 年级选择 ---------------- */
function openOnboarding(force = false) {
  const m = $('#onb'); m.classList.remove('hidden');
  let g = state.profile?.grade || 0, tb = state.profile?.textbook || '人教版';
  $('#bands').innerHTML = Object.entries(ORDERS).map(([k, o]) => `<div class="band"><div class="band-h">${capital(k)}<span><b>${o.band}</b><small>${o.name} · ${o.en}</small></span></div>
    <div class="gbtns">${GRADES.slice(o.range[0] - 1, o.range[1]).map((n, i) => `<button class="gbtn" data-g="${o.range[0] + i}">${n}</button>`).join('')}</div></div>`).join('');
  $('#tbs').innerHTML = '<span class="mono" style="margin-right:6px">教材版本</span>' + TEXTBOOKS.map((t) => `<button data-tb="${t}">${t}</button>`).join('');
  const paint = () => {
    $$('.gbtn').forEach((b) => b.classList.toggle('on', +b.dataset.g === g));
    $$('#tbs button').forEach((b) => b.classList.toggle('on', b.dataset.tb === tb));
    $('#onbOk').disabled = !g;
  };
  $$('.gbtn').forEach((b) => { handles(b); b.onclick = () => { g = +b.dataset.g; paint(); setOrder(orderOfGrade(g)); }; });
  $$('#tbs button').forEach((b) => b.onclick = () => { tb = b.dataset.tb; paint(); });
  handles($('#onbOk'));
  $('#onbOk').onclick = async () => {
    const r = await api('/api/profile', { grade: g, textbook: tb });
    state.profile = r.profile; paintProfile(); m.classList.add('hidden');
  };
  paint();
}
function paintProfile() {
  const p = state.profile; if (!p) return;
  const order = orderOfGrade(p.grade);
  $('#pillText').textContent = `${GRADES[p.grade - 1]} · ${p.textbook}`;
  $('#pillIcon').innerHTML = capital(order);
  setOrder(order);
}

/* ---------------- 模型设置（key 只存本机；界面不回显完整 key） ---------------- */
const SET_ENV = { base_url: 'LYCEUM_BASE_URL', api_key: 'LYCEUM_API_KEY', model: 'LYCEUM_MODEL', vision_model: 'LYCEUM_VISION_MODEL' };
function paintMode(s) {
  state.llm = s.mode === 'model'; state.model = s.model;
  $('#modelTag').textContent = state.llm ? `模型 ${s.model}` : '离线演示模式';
  $('#setDot').classList.toggle('on', state.llm);
  $('#setBtn').title = state.llm ? `已接入模型 ${s.model}` : '离线演示模式 · 点这里填 API Key';
}
async function openSettings() {
  const m = $('#setModal'), f = $('#setForm');
  let s;
  try { s = await api('/api/settings'); } catch (e) { return toast(e.message); }
  const fill = (s) => {
    $('#setMode').innerHTML = s.mode === 'model' ? `现在：已接入模型 <b>${esc(s.model)}</b>` : '现在：<b>离线演示模式</b>，回复是固定的演示文字。';
    for (const k of Object.keys(SET_ENV)) {
      const inp = f.elements[k], lock = $('.lock', inp.parentElement), locked = s.locked.includes(k);
      inp.value = k === 'api_key' ? '' : (k === 'base_url' && s.source.base_url === 'default' ? '' : (k === 'model' && s.source.model === 'default' ? '' : s[k] || ''));
      inp.disabled = locked;
      lock.textContent = locked ? `由环境变量 ${SET_ENV[k]} 设置，这里改不了` : '';
    }
    f.elements.api_key.placeholder = s.key_set ? `已保存 ${s.key_hint} · 留空保持不变` : 'sk-…';
    $('#setClear').hidden = !(s.key_set && s.source.api_key === 'file');
  };
  fill(s);
  m.classList.remove('hidden');
  handles($('#setOk'));
  const close = () => { m.classList.add('hidden'); f.elements.api_key.value = ''; removeEventListener('keydown', onKey); };
  const onKey = (e) => { if (e.key === 'Escape') close(); };
  addEventListener('keydown', onKey);
  $('#setCancel').onclick = close;
  m.onclick = (e) => { if (e.target === m) close(); };
  const save = async (body) => {
    try { const r = await api('/api/settings', body); paintMode(r); fill(r); return r; } catch (e) { toast(e.message); }
  };
  $('#setClear').onclick = async () => { if (await save({ clear_key: true })) toast('已清除保存的 Key'); };
  f.onsubmit = async (e) => {
    e.preventDefault();
    const body = {};
    for (const k of Object.keys(SET_ENV)) { const inp = f.elements[k]; if (!inp.disabled) body[k] = inp.value.trim(); }
    const r = await save(body);
    if (r) { close(); toast(r.mode === 'model' ? `已保存 · 用模型 ${r.model}` : '已保存 · 离线演示模式'); }
  };
  setTimeout(() => (s.key_set ? f.elements.model : f.elements.api_key).focus(), 30);
}

/* ---------------- 答疑 ---------------- */
function aiMsgHTML(m, i) {
  const meta = m.meta || {};
  const chips = [];
  if (meta.subject) chips.push(`<span class="chip">${sIco(meta.subject)}${esc(meta.subject)}</span>`);
  if (meta.topic) chips.push(`<span class="chip">${esc(meta.topic)}</span>`);
  const stg = { clarify: '澄清题意', hint: meta.hint_level ? `提示 ${meta.hint_level} / 3` : '引导', check: '检查答案', solved: '做对了', full: '完整解法', redirect: '回到学习' }[meta.stage];
  if (stg) chips.push(`<span class="chip ${meta.stage === 'solved' ? 'ok' : meta.stage === 'full' ? 'solid' : 'blue'}">${meta.stage === 'solved' ? laurelMini() : ''}${stg}</span>`);
  if (meta.error) return `<div class="msg ai" data-i="${i}"><div class="av">${owlMark()}</div><div><div class="who"><b>小雅</b></div><div class="err-line">${art('broken')}<span class="em">${esc(m.content)}<small>这一轮没有记进记录，题目还在，可以放心重试。</small></span>${meta.retry ? '<button class="ghost" data-retry="1">[↻] 重试</button>' : ''}</div></div></div>`;
  return `<div class="msg ai" data-i="${i}"><div class="av">${owlMark()}</div><div><div class="who"><b>小雅</b>${chips.join('')}</div><div class="md">${md(m.content)}</div><div class="extra"></div></div></div>`;
}
function userMsgHTML(m) {
  return `<div class="msg user"><div class="bubble">${m.image ? `<img src="${esc(m.image)}" alt="题目图片">` : ''}${esc(m.content)}</div></div>`;
}
function renderChat() {
  const box = $('#chatInner');
  if (!state.msgs.length) {
    state.seen = 0;
    const ex = [['数学 · 初中', '解方程 x² − 5x + 6 = 0'], ['语文 · 古诗文', '“落霞与孤鹜齐飞，秋水共长天一色”好在哪里？'], ['物理 · 力学', '为什么人站在匀速上升的电梯里，感觉不到自己在动？'], ['语文 · 作文', '帮我写一篇《我的妈妈》，400 字']];
    box.innerHTML = `<div class="empty"><span class="mono">Ἐρώτημα · 提问</span><h2>今天想弄明白什么？</h2><p>打字、拍照都行。小雅不会直接给答案，但会一直陪你想到明白为止。</p>
      <div class="examples">${ex.map(([k, q]) => `<button class="ex-card"><span class="mono">${k}</span><span class="q">${esc(q)}</span></button>`).join('')}</div></div>`;
    $$('.ex-card', box).forEach((b) => b.onclick = () => { $('#input').value = $('.q', b).textContent; send(); });
  } else {
    box.innerHTML = state.msgs.map((m, i) => m.role === 'user' ? userMsgHTML(m) : aiMsgHTML(m, i)).join('');
    const els = $$(':scope > .msg', box);
    els.forEach((el, i) => { if (i >= (state.seen ?? 0)) el.classList.add('enter'); });   // 只让新来的那条落下，历史不重播
    state.seen = state.msgs.length;
    const L = state.laurel;
    if (L && els[L.i]) {                                    // 解出：桂冠描线，只画一次
      const md0 = $('.md', els[L.i]);
      if (md0) {
        md0.insertAdjacentHTML('beforebegin', `<div class="laurel-draw${L.drawn ? '' : ' go'}" aria-label="自己做出来了">${laurel('currentColor')}<span class="lt">ΑΡΙΣΤΑ · 自己想出来的</span></div>`);
        const ld = $('.laurel-draw', els[L.i]);
        $$('polyline, path', ld).forEach((p) => p.setAttribute('pathLength', '1'));
        $$('ellipse', ld).forEach((e, k) => e.style.setProperty('--i', k));
        L.drawn = true;
      }
    }
    tex(box);
    $$('[data-retry]', box).forEach((b) => b.onclick = retryLast);
    const last = [...$$('.msg.ai', box)].pop();
    if (last && !state.busy) addMsgActions(last);
  }
  paintInspector();
  requestAnimationFrame(() => { const sc = $('#chatScroll'); sc.scrollTop = sc.scrollHeight; });
}
function addMsgActions(el) {
  const ps = state.problemState || {};
  if (!state.session || !ps.subject || state.msgs[state.msgs.length - 1]?.meta?.error) return;
  const acts = [];
  if (ps.solved || ps.full_given) acts.push(['practice', '[*] 出两道变式题']);
  else { acts.push(['hint', '再给一点提示']); acts.push(['stuck', '我还是不会']); }
  const x = $('.extra', el);
  x.innerHTML = `<div class="msg-actions">${acts.map(([a, t]) => `<button class="${a === 'practice' ? 'sel sm' : 'ghost'}" data-a="${a}">${t}</button>`).join('')}</div>`;
  $$('button', x).forEach((b) => { if (b.classList.contains('sel')) handles(b); b.onclick = () => b.dataset.a === 'practice' ? practice() : send(b.dataset.a); });
}
function paintStrategy() {
  const sg = (state.problemState || {}).strategy; const bar = $('#stratBar');
  if (!sg || !sg.mode) { bar.classList.add('hidden'); bar.innerHTML = ''; return; }
  const name = sg.label || sg.subject || '';
  bar.innerHTML = `${name ? `<span class="gk">${GLYPH[sg.subject] || 'Ω'}</span><b>${esc(name)}</b><i class="sep"></i>` : ''}<span class="lbl">本科引导方式</span><span class="txt" title="${esc(sg.mode)}">${esc(sg.mode)}</span>`;
  bar.classList.remove('hidden');
}
function paintInspector() {
  paintStrategy();
  const ps = state.problemState || {};
  const prob = state.session?.problem;
  $('#probChips').innerHTML = ps.subject ? `<span class="chip">${sIco(ps.subject)}${esc(ps.subject)}</span>${ps.topic ? `<span class="chip">${esc(ps.topic)}</span>` : ''}` : '';
  const pt = $('#probText');
  pt.classList.toggle('empty-p', !prob); pt.innerHTML = prob ? md(prob) : '还没有题目。发一道题过来吧。'; tex(pt);
  const hl = ps.hint_level || 0;
  const prevHl = state.hintShown ?? hl, prevStuck = state.stuckShown ?? (ps.stuck || 0);
  $$('#steps .step').forEach((s, i) => {
    s.classList.toggle('on', i < hl);
    if (state.animHint && i >= prevHl && i < hl) { s.classList.remove('rise'); void s.offsetWidth; s.style.setProperty('--i', i - prevHl); s.classList.add('rise'); }
  });
  $('#stuckTxt').textContent = `卡住 ${Math.min(3, ps.stuck || 0)} / 3${(ps.stuck || 0) >= 3 ? ' · 可以看完整解法' : ''}`;
  if (state.animHint && (ps.stuck || 0) > prevStuck) { const st = $('#stuckTxt'); st.classList.remove('bump'); void st.offsetWidth; st.classList.add('bump'); }
  state.hintShown = hl; state.stuckShown = ps.stuck || 0; state.animHint = false;
  $('#solvedTxt').textContent = ps.solved ? (ps.full_given ? '已看完整解法' : '自己做出来了') : '';
}
function owlSay(t) { const el = $('#owlSay'); if (el.textContent === t) return; el.textContent = t; el.classList.remove('swap'); void el.offsetWidth; el.classList.add('swap'); }
async function loadSessions() {
  try {
    const { sessions } = await api('/api/sessions');
    $('#sessList').innerHTML = sessions.length ? sessions.map((s) => `<button class="sess ${state.session?.id === s.id ? 'on' : ''}" data-id="${s.id}"><span class="t">${esc(s.title || '未命名')}</span><span class="m">${esc(s.subject || '—')}${s.topic ? ' · ' + esc(s.topic) : ''} · ${ago(s.updated)}</span></button>`).join('')
      : '<p style="padding:8px 12px;color:var(--muted);font-size:14px">还没有问过题。</p>';
    $$('.sess').forEach((b) => b.onclick = () => { location.hash = '#/study/' + b.dataset.id; });
  } catch (e) { /* ignore */ }
}
async function openSession(id) {
  const fresh = () => { state.laurel = null; state.hintShown = undefined; state.stuckShown = undefined; state.animHint = false; };
  if (!id) { state.session = null; state.msgs = []; state.problemState = {}; fresh(); renderChat(); loadSessions(); return; }
  if (state.session?.id === +id && state.msgs.length) { renderChat(); return; }
  try {
    const r = await api('/api/sessions/' + id);
    state.session = r.session; state.msgs = r.messages; state.problemState = { ...(r.session.state || {}) };
    fresh(); state.seen = state.msgs.length; renderChat(); loadSessions();
  } catch (e) { toast(e.message); }
}
/* ---- 流式：fetch + ReadableStream 解析 SSE ---- */
const STREAM_IDLE_MS = 60000;   // 这么久一个事件都没来，算超时
class StreamFail extends Error { constructor(kind, msg) { super(msg); this.kind = kind; } }
async function streamChat(body, onEvent) {
  const ctrl = new AbortController(); let timer = 0;
  const arm = () => { clearTimeout(timer); timer = setTimeout(() => ctrl.abort(), STREAM_IDLE_MS); };
  arm();
  let r;
  try { r = await fetch('/api/chat/stream', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: ctrl.signal }); }
  catch (e) { clearTimeout(timer); throw new StreamFail(ctrl.signal.aborted ? 'timeout' : 'network', ctrl.signal.aborted ? '小雅太久没有回应（超时了）。' : '连不上学园的服务。'); }
  if (!r.ok || !(r.headers.get('content-type') || '').includes('event-stream')) {
    clearTimeout(timer); const j = await r.json().catch(() => ({})); throw new StreamFail('http', j.error || '出错了');
  }
  if (!r.body || !r.body.getReader) { clearTimeout(timer); throw new StreamFail('unsupported', ''); }
  const reader = r.body.getReader(); const dec = new TextDecoder(); let buf = ''; let end = null;
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      arm(); buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf('\n\n')) >= 0) {
        const raw = buf.slice(0, i); buf = buf.slice(i + 2);
        let ev = 'message'; const data = [];
        for (const line of raw.split('\n')) { if (line.startsWith('event:')) ev = line.slice(6).trim(); else if (line.startsWith('data:')) data.push(line.slice(5).trimStart()); }
        if (!data.length) continue;
        let d; try { d = JSON.parse(data.join('\n')); } catch { continue; }
        if (ev === 'done' || ev === 'error') end = ev;
        onEvent(ev, d);
      }
    }
  } catch (e) {
    if (e instanceof StreamFail) throw e;
    throw new StreamFail(ctrl.signal.aborted ? 'timeout' : 'dropped', ctrl.signal.aborted ? '小雅太久没有回应（超时了）。' : '连接断了，这条回复没有收完。');
  } finally { clearTimeout(timer); }
  if (!end) throw new StreamFail('dropped', '连接断了，这条回复没有收完。');
}
// 流式气泡：完整的段落（换行之前、公式已闭合）才用 md + KaTeX 渲染；正在写的那一行只出文字，公式先占位
const live = { raw: '', committed: null, raf: 0 };
const dollarsEven = (t) => (t.match(/(?<!\\)\$/g) || []).length % 2 === 0;
function tailHTML(t) {
  const parts = t.split(/(?<!\\)\$/); let h = '';
  parts.forEach((seg, i) => { if (i % 2) { if (seg !== '' || i < parts.length - 1) h += '<span class="math-wait">· · ·</span>'; } else h += esc(seg).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/\*\*/g, ''); });
  return h;
}
function paintLive() {
  live.raf = 0; const el = $('#live'); if (!el) return;
  const raw = live.raw; let cut = -1;
  for (let i = raw.lastIndexOf('\n'); i >= 0; i = raw.lastIndexOf('\n', i - 1)) { if (dollarsEven(raw.slice(0, i))) { cut = i; break; } if (i === 0) break; }
  const committed = cut >= 0 ? raw.slice(0, cut) : ''; const tail = cut >= 0 ? raw.slice(cut + 1) : raw;
  if (committed !== live.committed) { const d = $('.md-done', el); d.innerHTML = md(committed); tex(d); live.committed = committed; }
  $('.md-tail', el).innerHTML = `<p>${tailHTML(tail)}<span class="caret"></span></p>`;
  const sc = $('#chatScroll'); if (sc.scrollHeight - sc.scrollTop - sc.clientHeight < 160) sc.scrollTop = sc.scrollHeight;
}
// 用 setTimeout 而不是 rAF：三维舞台很重或标签页在后台时 rAF 会被大幅降频，字会一卡一卡地蹦
const schedulePaint = () => { if (!live.raf) live.raf = setTimeout(paintLive, 30); };
function openLive() {
  $('#thinking')?.remove(); if ($('#live')) return;
  live.raw = ''; live.committed = null;
  $('#chatInner').insertAdjacentHTML('beforeend', `<div class="msg ai streaming enter" id="live"><div class="av">${owlMark()}</div><div><div class="who"><b>小雅</b><span class="chip live" id="liveChip"><span class="cap-pulse">${capitalPulse()}</span><span id="liveTxt">正在写</span></span></div><div class="md"><div class="md-done"></div><div class="md-tail"></div></div></div></div>`);
  emit('ask:stream'); owlSay('我说一小步，剩下的你来。');
}

async function send(action) {
  if (state.busy) return;
  const input = $('#input'); const text = input.value.trim();
  if (!text && !state.image && !action) { input.focus(); return; }
  if (action && !state.session) { toast('先发一道题过来'); return; }
  const body = { session_id: state.session?.id, message: text, image: state.image, action };
  input.value = ''; autosize(); clearImage();
  return chatTurn(body);
}
function retryLast() {
  const f = state.lastFail; if (!f || state.busy) return;
  state.msgs.splice(-2, 2);           // 去掉失败的那条提问和报错，原样重发
  chatTurn(f.body);
}
async function chatTurn(body) {
  state.busy = true; $('#send').disabled = true;
  const shown = body.message || { hint: '再给一点提示', stuck: '我卡住了', full: '看完整解法' }[body.action] || '';
  const prevSession = state.session; const prevPS = state.problemState;
  state.msgs.push({ role: 'user', content: shown, image: body.image });
  renderChat();
  $('#chatInner').insertAdjacentHTML('beforeend', `<div class="msg ai enter" id="thinking"><div class="av">${owlMark()}</div><div class="thinking"><span class="cols"><i></i><i></i><i></i></span>小雅在想……</div></div>`);
  $('#chatScroll').scrollTop = 1e9;
  emit('ask:send', { image: !!body.image }); owlSay(body.image ? '我看看这张图……' : '嗯，我在听。');
  let r = null;
  const finish = (res) => { r = res; };
  try {
    try {
      await streamChat(body, (ev, d) => {
        if (ev === 'meta') {
          if (!state.session || state.session.id !== d.session_id) state.session = { id: d.session_id };
          if (d.image) state.msgs[state.msgs.length - 1].image = d.image;
          if (d.strategy) { state.problemState = { ...state.problemState, strategy: d.strategy }; paintStrategy(); }
        } else if (ev === 'delta') { openLive(); live.raw += d.text; schedulePaint(); }
        else if (ev === 'status' && d.state === 'verifying') { openLive(); $('#liveTxt').textContent = '代回检验'; owlSay('我把你的答案代回原题验一下。'); emit('ask:verify'); }
        else if (ev === 'status') {
          openLive(); $('#liveTxt').textContent = '换个说法'; owlSay('这句我换个说法，你自己来想。'); emit('ask:rewrite');
          if (!$('#live .rewrite-note')) $('#live .who').insertAdjacentHTML('afterend', '<div class="rewrite-note">刚才那句说得太直接了，小雅收回来，换成一个问题给你。</div>');
        }
        else if (ev === 'replace') { openLive(); live.raw = d.text; live.committed = null; $('#live').classList.add('replaced'); $('#liveTxt').textContent = '正在写'; schedulePaint(); emit('ask:stream'); }
        else if (ev === 'done') finish(d);
        else if (ev === 'error') throw new StreamFail('server', d.error || '出错了');
      });
    } catch (e) {
      if (e.kind !== 'unsupported') throw e;
      r = await api('/api/chat', body);          // 浏览器不支持流式：退回非流式接口
    }
    const last = state.msgs[state.msgs.length - 1]; if (r.image) last.image = r.image;
    if (!state.session || state.session.id !== r.session_id) state.session = { id: r.session_id };
    state.problemState = r.state || state.problemState;
    state.session.problem = r.problem ?? state.session.problem;
    const streamed = !!$('#live');
    state.msgs.push({ role: 'assistant', content: r.reply, meta: r.meta });
    if (streamed) state.seen = state.msgs.length;        // 流式气泡已经在场上，定稿时不再重播进入动画
    state.lastFail = null; state.animHint = true;
    history.replaceState(null, '', '#/study/' + r.session_id);
    const m = r.meta || {};
    const solved = m.stage === 'solved' || (m.student_correct === true && (r.state || {}).solved);
    if (solved) { state.laurel = { i: state.msgs.length - 1, drawn: false }; emit('ask:solved'); owlSay('对了！你自己想出来的。'); }
    else if (body.action === 'stuck' || m.student_correct === false) { emit('ask:stuck'); owlSay(m.student_correct === false ? '差一点。再看看哪一步。' : '卡住很正常，我们退一小步。'); }
    else if (m.stage === 'full') { emit('ask:stuck'); owlSay('这次看懂了，换一道自己试试？'); }
    else if ((m.hint_level || 0) > (prevPS.hint_level || 0)) { emit('hint:advance', { level: m.hint_level }); owlSay(`提示 ${m.hint_level} / 3。慢慢来。`); }
    else { emit('ask:settle'); owlSay(m.stage === 'redirect' ? '我们还是聊回学习吧～' : '你先说说看。'); }
  } catch (e) {
    // 出错 / 超时 / 断流：服务端什么都没写库，这里撤回半截回复，给重试按钮
    if (!prevSession) state.session = null;
    state.problemState = prevPS;
    state.lastFail = { body };
    state.msgs.push({ role: 'assistant', content: e.message || '出错了', meta: { error: true, retry: true } });
    emit('ask:error');
    owlSay(e.kind === 'timeout' ? '等太久了，点「重试」再来一次。' : '刚才没连上，点「重试」再来一次。');
  } finally {
    if (live.raf) clearTimeout(live.raf); live.raf = 0;
    state.busy = false; $('#send').disabled = false;
    if (mood.cur === 'think' || mood.cur === 'listen') emit('ask:settle');
    renderChat(); loadSessions();
  }
}
async function practice(fromMistake, fromSkill) {
  if (state.busy) return;
  if (!fromMistake && !fromSkill && !state.session) { toast('先讲一道题，才能出变式题'); return; }
  state.busy = true;
  const box = $('#chatInner');
  box.insertAdjacentHTML('beforeend', `<div class="msg ai enter" id="thinking"><div class="av">${owlMark()}</div><div class="thinking"><span class="cols"><i></i><i></i><i></i></span>小雅在出题……</div></div>`);
  $('#chatScroll').scrollTop = 1e9; emit('practice:start'); owlSay('换个数字、换个问法……');
  try {
    const r = fromMistake ? await api(`/api/mistakes/${fromMistake}/retry`, {}) : fromSkill ? await api(`/api/review/skill/${fromSkill}`, {}) : await api('/api/practice', { session_id: state.session.id, n: 3 });
    $('#thinking')?.remove();
    const greek = GK;
    const card = document.createElement('div'); card.className = 'msg ai enter';
    card.innerHTML = `<div class="av">${owlMark()}</div><div><div class="who"><b>小雅</b><span class="chip blue">变式练习</span>${r.topic ? `<span class="chip">${esc(r.topic)}</span>` : ''}</div>
      <div class="practice"><div class="practice-head"><b>换个样子，再来 ${r.questions.length} 道</b><span class="mono">${esc(r.subject || '')}</span></div><div class="meander"></div>
      ${r.questions.map((q, i) => `<div class="pq"><span class="n">${greek[i]}</span><div><div class="q md">${md(q.q)}</div><span class="inp"><input placeholder="写下你的答案" data-i="${i}"></span><div class="res hidden"></div></div></div>`).join('')}
      <div class="practice-foot"><span class="score"></span><button class="sel solid sm"><span class="br">[✓]</span>交给小雅批改</button></div></div></div>`;
    box.appendChild(card); $('.meander', card).style.backgroundImage = meanderURL('#1b2142'); tex(card); handles($('.practice-foot .sel', card));
    $('#chatScroll').scrollTop = 1e9; owlSay('做完点「批改」。');
    $('.practice-foot .sel', card).onclick = async (ev) => {
      const btn = ev.currentTarget; btn.disabled = true; btn.lastChild.textContent = '批改中……'; emit('practice:start');
      try {
        const g = await api('/api/grade', { practice_id: r.practice_id, answers: $$('input', card).map((x) => x.value) });
        g.results.forEach((res, i) => {
          const el = $$('.res', card)[i]; el.classList.remove('hidden'); el.classList.toggle('bad', !res.correct);
          el.innerHTML = `<b class="${res.correct ? 'ok' : 'no'}">${res.correct ? '✓ 对了' : '✗ 再看看'}</b> ${md(res.feedback)}${res.correct ? '' : `<div style="margin-top:6px;color:var(--muted)">参考答案：${esc(res.answer || '')}</div>`}`;
          $$('input', card)[i].disabled = true;
        });
        tex(card);
        const mv = g.mastery ? ` · 掌握度 ${pct(g.mastery.before)}% → ${pct(g.mastery.after)}%` : '';
        $('.score', card).innerHTML = `${g.right === g.total ? laurelMini() : ''}${g.right} / ${g.total}<small>${g.right === g.total ? '全对！' : '错的已放进错题本'}${mv}</small>`;
        btn.remove();
        emit('practice:graded', { all: g.right === g.total });   // 不放庆祝：桂冠描线只留给「自己解出」
        owlSay(g.right === g.total ? '全对。到期再对一次，才算真掌握。' : '错的那道已放进错题本，明天再练一次。');
      } catch (e) { toast(e.message); btn.disabled = false; btn.lastChild.textContent = '交给小雅批改'; emit('ask:error'); }
    };
  } catch (e) { $('#thinking')?.remove(); toast(e.message); emit('ask:error'); }
  finally { state.busy = false; if (mood.cur === 'think') emit('ask:settle'); }
}
function autosize() { const t = $('#input'); t.style.height = 'auto'; t.style.height = Math.min(180, t.scrollHeight) + 'px'; }
function clearImage() { state.image = null; $('#attach').classList.add('hidden'); $('#file').value = ''; }
function setImageFile(f) {
  if (!f || !f.type.startsWith('image/')) return;
  const img = new Image(); const url = URL.createObjectURL(f);
  img.onload = () => { // 压缩到 1600px 以内，省流量
    const k = Math.min(1, 1600 / Math.max(img.width, img.height));
    const c = document.createElement('canvas'); c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
    c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
    state.image = c.toDataURL('image/jpeg', 0.88); $('#attachImg').src = state.image; $('#attach').classList.remove('hidden'); URL.revokeObjectURL(url);
  };
  img.src = url;
}
function initStudy() {
  $('#imgBtn').insertAdjacentHTML('afterbegin', icons.image);
  $('#steps').innerHTML = ['方向', '方法', '最后一步'].map((t, i) => `<div class="step">${columnGlyph()}<span><b>${GK[i]}΄</b>${t}</span></div>`).join(''); $('#attachX').innerHTML = icons.close;
  handles($('#send')); handles($('#newChat')); handles($('#practiceBtn'));
  $('#send').onclick = () => send();
  $('#input').addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); } });
  $('#input').addEventListener('input', () => { autosize(); emit('compose:typing'); });
  $('#file').onchange = (e) => setImageFile(e.target.files[0]);
  $('#attachX').onclick = clearImage;
  $('#newChat').onclick = () => { location.hash = '#/study'; };
  $$('[data-act]').forEach((b) => b.onclick = () => send(b.dataset.act));
  $('#practiceBtn').onclick = () => practice();
  const chat = $('#chat');
  chat.addEventListener('dragover', (e) => { e.preventDefault(); chat.classList.add('drop-on'); });
  chat.addEventListener('dragleave', () => chat.classList.remove('drop-on'));
  chat.addEventListener('drop', (e) => { e.preventDefault(); chat.classList.remove('drop-on'); setImageFile(e.dataTransfer.files[0]); });
  addEventListener('paste', (e) => { if (state.route !== 'study') return; const f = [...(e.clipboardData?.files || [])][0]; if (f) setImageFile(f); });
}

/* ---------------- 列表进入 / 柱身填充 / 数字滚动 ---------------- */
function enterList(root, sel) {
  $$(sel, root).forEach((el, i) => { el.style.setProperty('--i', Math.min(i, 8)); el.classList.remove('stg'); void el.offsetWidth; el.classList.add('stg'); });
}
function countUp(el) {
  if (REDUCED) return;
  const tn = [...el.childNodes].find((n) => n.nodeType === 3 && /\d/.test(n.nodeValue)); if (!tn) return;
  const m = tn.nodeValue.match(/^(\D*)(\d+)([\s\S]*)$/); if (!m) return;
  const to = +m[2]; if (to < 2) return;
  const t0 = performance.now(), D = 640;
  tn.nodeValue = m[1] + '0' + m[3];
  const step = (now) => { const k = Math.min(1, (now - t0) / D), e = 1 - Math.pow(1 - k, 3); tn.nodeValue = m[1] + Math.round(to * e) + m[3]; if (k < 1) requestAnimationFrame(step); };
  requestAnimationFrame(step);
}
// 进入一个本子页时只演一次：错落进入 + 柱身填充 + 数字从 0 滚到位
function animateBook(lists) {
  if (!state.animBook) return; state.animBook = false;
  const body = $('#bookBody'); body.classList.remove('fill-in'); void body.offsetWidth; body.classList.add('fill-in');
  lists.forEach((sel) => enterList(body, sel));
  $$('#bookNums b, .ms-sum b, .mline .pct, .mastery .pct', document).forEach(countUp);
}

/* ---------------- 错题本 / 学习记录 ---------------- */
const STATUS = { mastered: '已掌握', consolidating: '待巩固', learning: '学习中', new: '未开始' };
const GKL = ['α', 'β', 'γ', 'δ', 'ε', 'ζ', 'η', 'θ', 'ι', 'κ', 'λ', 'μ', 'ν', 'ξ', 'ο', 'π', 'ρ', 'σ', 'τ', 'υ'];
const isoAdd = (iso, n) => { const d = new Date(iso + 'T00:00:00'); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
function fmtDay(iso, today) {
  if (!iso) return '—';
  if (today && iso < today) return '已到期';
  if (today && iso === today) return '今天';
  if (today && iso === isoAdd(today, 1)) return '明天';
  const [, m, d] = iso.split('-'); return `${+m}月${+d}日`;
}
const pct = (p) => Math.floor((p || 0) * 100);
const skKey = (subject, topic) => (subject || '其他') + '｜' + (topic || '');
// 掌握度条：横置的带凹槽柱身，85% 处一道掌握线
function mbar(p) {
  const w = pct(p);
  return `<span class="mbar" title="P(L) = ${(p || 0).toFixed(2)}，掌握线 0.85"><i style="width:${w}%"></i><b class="th"></b></span>`;
}
function nextTxt(sk, today) {
  const md = sk.mistakes_due || 0;
  if (sk.status === 'new') return md ? `<span class="due">今天复习</span> · ${md} 道错题到期` : '还没有练习记录';
  const due = sk.next_review && sk.next_review <= today;
  const head = due ? '<span class="due">今天复习</span>' : md ? `<span class="due">今天复习</span>（${md} 道错题到期）· 知识点 ${fmtDay(sk.next_review, today)}` : '下次复习 ' + fmtDay(sk.next_review, today);
  return `${head} · ${GK[sk.review_step || 0]}΄ 级（${sk.interval_days} 天）· 到期连对 ${Math.min(2, sk.review_streak || 0)}/2`;
}
// 知识点名的悬停提示：规范名 · 学科，合并进来的原标签，未归类说明
function skTitle(k) {
  if (!k) return '';
  const al = (k.aliases || []).filter((a) => a !== k.topic);
  return `${k.topic || '未分类'} · ${k.subject}${al.length ? '\n合并自：' + al.join('、') : ''}${k.canon === 0 ? '\n未归类：不在规范知识点表里，保留原标签' : ''}`;
}
// 「今日复习」统一口径：按知识点计（到期的知识点 + 有到期错题的知识点），错题另报道数
const dueLine = (rev) => `<b class="n">${rev.topics_due}</b> 个知识点，其中 <b class="n">${rev.mistakes_due}</b> 道错题到期`;
function masteryHead(sk, today) {
  if (!sk) return '';
  return `<div class="mastery ${sk.status}">${mbar(sk.p_l)}<div class="mrow"><span class="pct">${pct(sk.p_l)}<small>%</small></span><span class="st">${sk.status === 'mastered' ? laurelMini() : ''}${STATUS[sk.status]}</span></div><div class="mnext">${nextTxt(sk, today)}</div></div>`;
}
function mistakeCard(m, today) {
  const due = m.next_review && m.next_review <= today;
  const sched = m.mastered ? '已出本' : (due ? '<b class="due">今天复习</b>' : '下次复习 ' + fmtDay(m.next_review, today));
  return `<div class="mcard stele${due ? ' is-due' : ''}" data-id="${m.id}"><div class="q md">${md(m.question)}</div>
    <div class="row"><div><span>你的答案</span><div class="your">${esc(m.user_answer)}</div></div><div><span>参考答案</span><div>${esc(m.correct_answer || '见解析')}</div></div></div>
    <details><summary>看解析</summary><div class="md" style="margin-top:8px;font-size:15.5px">${md(m.explain)}</div></details>
    <div class="acts"><button class="sel sm" data-retry="${m.id}"><span class="br">[↻]</span>再练一次</button><button class="ghost" data-master="${m.id}" title="只算弱证据：到期再练一次答对才算数">${m.self_report ? '已自评会了' : '我会了'}</button>
      <span class="meta">${m.cause ? `错因 · ${esc(m.cause)}${m.misconception ? '（' + esc(m.misconception) + '）' : ''} · ` : ''}${sched} · ${m.source === '讲解' ? '看了完整解法' : '变式题做错'} · ${ago(m.created)}</span></div></div>`;
}
function bindBook(body) {
  $$('[data-f]', body).forEach((b) => b.onclick = () => { state.filter = b.dataset.f; state.animBook = true; renderBook(); });
  $$('[data-master]', body).forEach((b) => b.onclick = async () => { await api(`/api/mistakes/${b.dataset.master}/master`, {}); toast('记下了。自评只算弱证据，到期再练一次答对才算数'); renderBook(); });
  $$('[data-retry]', body).forEach((b) => { b.onclick = () => { location.hash = '#/study'; setTimeout(() => practice(+b.dataset.retry), 80); }; });
  $$('[data-rskill]', body).forEach((b) => { b.onclick = () => { location.hash = '#/study'; setTimeout(() => practice(null, +b.dataset.rskill), 80); }; });
  $$('.sel', body).forEach(handles);
}
async function renderBook() {
  const tab = state.tab;
  $$('.tabs button').forEach((b) => b.classList.toggle('on', b.dataset.tab === tab));
  if (tab === 'memory') return renderMemory();
  if (tab === 'growth') return renderGrowth();
  const [{ stats, sessions }, mast, rev] = await Promise.all([api('/api/stats'), api('/api/mastery'), api('/api/review/today')]);
  const today = mast.today;
  const skMap = Object.fromEntries(mast.skills.map((k) => [skKey(k.subject, k.topic), k]));
  const dueN = rev.topics_due;
  $('#bookTitle').textContent = tab === 'notebook' ? '错题本' : '学习记录'; $('.book-head .mono').textContent = 'Σημειώσεις · 记下来的，才是自己的';
  $('#bookSub').textContent = tab === 'notebook' ? '做错的变式题、看了完整解法才弄懂的题，都在这里。按学科和知识点排好，到期那天再练一次。' : '不比谁学得多，只看你是不是每天都来想一想。';
  $('#bookNums').innerHTML = tab === 'notebook'
    ? `<div><b class="blue">${dueN}</b><span>今日复习（知识点）</span></div><div><b>${stats.mistakes_open}</b><span>错题在本</span></div><div><b>${stats.mistakes_mastered}</b><span>已出本</span></div>`
    : `<div><b class="blue">${stats.streak}</b><span>连续学习（天）</span></div><div><b>${stats.skills_mastered}<small style="font-size:.4em"> / ${stats.skills_total}</small></b><span>知识点已掌握</span></div><div><b>${stats.active_days}</b><span>累计学习（天）</span></div>`;
  const body = $('#bookBody');
  if (tab === 'notebook') {
    const all = (await api('/api/mistakes')).mistakes;
    const subs = [...new Set(all.map((m) => m.subject))];
    let h = `<div class="filters"><button data-f="__today" class="today-f ${state.filter === '__today' ? 'on' : ''}"><span class="gkf">Σ</span>今日复习 ${dueN} 个知识点</button><button data-f="" class="${!state.filter ? 'on' : ''}">全部 ${all.length}</button>${subs.map((s) => `<button data-f="${esc(s)}" class="${state.filter === s ? 'on' : ''}">${sIco(s)}${esc(s)} ${all.filter((m) => m.subject === s).length}</button>`).join('')}</div>`;
    if (state.filter === '__today') {
      // 今日复习：按知识点分组，到期的错题 + 到期但没有到期错题的知识点
      const groups = {};
      rev.skills.forEach((k) => { (groups[skKey(k.subject, k.topic)] ||= { sk: k, ms: [] }); });
      rev.mistakes.forEach((m) => { const k = skKey(m.subject, m.topic); (groups[k] ||= { sk: skMap[k], ms: [] }).ms.push(m); });
      const d = new Date(today + 'T00:00:00');
      h += `<div class="today-head"><div><span class="mono">Σήμερον · 今日复习</span><h3>${d.getMonth() + 1}月${d.getDate()}日 · 周${'日一二三四五六'[d.getDay()]}</h3></div>
        <p>今天要复习 ${dueLine(rev)}。答错的明天再见；同一个知识点连续两次到期都答对、掌握度过 85%，才算真正掌握。</p></div>`;
      if (!Object.keys(groups).length) {
        h += `<div class="none">${art('sundial')}<h3>今天没有要复习的</h3><p>${rev.next_date ? '下一次复习：' + fmtDay(rev.next_date, today) : '做几道变式题，小雅会排好复习日期。'}</p></div>`;
      } else {
        h += Object.entries(groups).map(([k, g], gi) => { const [s, t] = k.split('｜'); return `<div class="topic-group"><div class="tg"><span class="gn">${GKL[gi] || gi + 1}΄</span><span class="gl">${subjectIcon(s)}</span><h3 title="${esc(skTitle(g.sk))}">${esc(t || '未分类')}</h3><span>${esc(s)}${g.ms.length ? ' · ' + g.ms.length + ' 道到期' : ''}</span>${masteryHead(g.sk, today)}</div><div>
          ${g.ms.map((m) => mistakeCard(m, today)).join('')}
          ${!g.ms.length && g.sk ? `<div class="mcard stele review-card is-due"><div class="q">到期复习这个知识点</div><p>没有到期的错题。小雅拿这个知识点最近的一道题当母题，再出两道新题；全对就升一级，间隔拉长。</p><div class="acts"><button class="sel sm" data-rskill="${g.sk.id}"><span class="br">[↻]</span>出两道题复习</button><span class="meta">上次复习 ${g.sk.last_review ? fmtDay(g.sk.last_review) : '—'}</span></div></div>` : ''}</div></div>`; }).join('');
      }
    } else {
      const mistakes = state.filter ? all.filter((m) => m.subject === state.filter) : all;
      if (!state.filter && dueN) {
        h += `<button class="today-strip" data-f="__today"><span class="gkf">Σήμερον</span><span class="t"><b>今日复习</b>${dueLine(rev)}</span><span class="ar">[→] 开始复习</span></button>`;
      }
      if (!mistakes.length) {
        h += `<div class="none">${art('stele')}<h3>石碑上还没有刻字</h3><p>做完变式题，做错的会自动记到这里；隔几天再练一次，会了就出本。</p><a class="sel solid" href="#/study" style="margin-top:20px"><span class="br">[→]</span>去问一道题</a></div>`;
      } else {
        const groups = {};
        mistakes.forEach((m) => { (groups[skKey(m.subject, m.topic)] ||= []).push(m); });
        h += Object.entries(groups).map(([k, ms]) => { const [s, t] = k.split('｜'); return `<div class="topic-group"><div class="tg"><span class="gl">${subjectIcon(s)}</span><h3 title="${esc(skTitle(skMap[k]))}">${esc(t || '未分类')}</h3><span>${esc(s)} · ${ms.length} 道</span>${masteryHead(skMap[k], today)}</div><div>${ms.map((m) => mistakeCard(m, today)).join('')}</div></div>`; }).join('');
      }
    }
    body.innerHTML = h; tex(body); bindBook(body);
    animateBook(['.topic-group', '.today-strip, .today-head', '.none']);
  } else {
    const max = Math.max(1, ...stats.by_subject.map((s) => s.n));
    const days = [...Array(7)].map((_, i) => { const d = new Date(Date.now() - (6 - i) * 86400000); return d; });
    const activeSet = new Set(); sessions.forEach((s) => activeSet.add(new Date(s.updated * 1000).toDateString()));
    const sks = mast.skills.filter((k) => k.n_obs > 0 || k.review_today).sort((a, b) => b.p_l - a.p_l);
    const cnt = (st) => sks.filter((k) => k.status === st).length;
    const mastery = `<div class="mastery-sec"><div class="ms-head"><div><span class="mono">Ἐπιστήμη · 知识点掌握度</span><h3>会了多少，由规则说了算</h3></div>
      <div class="ms-sum"><span><b>${cnt('mastered')}</b>已掌握</span><span><b>${cnt('consolidating')}</b>待巩固</span><span><b>${cnt('learning')}</b>学习中</span><span class="blue"><b>${rev.topics_due}</b>今日复习（知识点）</span></div></div>
      <p class="ms-rule">掌握度是 BKT 估计的「已经会了」的概率 P(L)。要 <b>P(L) ≥ 85%</b> 并且 <b>连续两次到期复习都答对</b> 才算掌握；复习间隔 1 → 2 → 4 → 7 → 15 → 30 天，答错回到 1 天。「我会了」只算弱证据。同一学科里说法不同的知识点按规范表合并成一个；「今日复习」按知识点计：自己到期的，加上有错题到期的。</p>
      ${sks.length ? `<div class="mlist">${sks.map((k, i) => `<div class="mitem ${k.status}" data-sk="${k.id}"><button class="mline"><span class="n">${GKL[i] || i + 1}΄</span><span class="nm" title="${esc(skTitle(k))}">${sIco(k.subject)}<span>${esc(k.topic || '未分类')}<small>${esc(k.subject)}${k.canon === 0 ? ' · 未归类' : ''}</small></span></span>${mbar(k.p_l)}<span class="pct">${pct(k.p_l)}<small>%</small></span><span class="st">${k.status === 'mastered' ? laurelMini() : ''}${STATUS[k.status]}</span><span class="nx">${nextTxt(k, today)}</span><span class="ev">记录 ${k.n_obs}</span></button><div class="evs hidden"></div></div>`).join('')}</div>`
        : '<p style="color:var(--muted)">做完变式题、或在答疑里自己做对一道题，这里就会出现第一个知识点。</p>'}</div>`;
    body.innerHTML = mastery + `<div class="rec-grid"><div><h4 class="mono" style="margin:0 0 6px">最近 7 天</h4><div class="week">${days.map((d) => `<i class="${activeSet.has(d.toDateString()) ? 'on' : ''}"><span>${'日一二三四五六'[d.getDay()]}</span></i>`).join('')}</div>
      <h4 class="mono" style="margin:40px 0 6px">各科提问</h4><div class="bars">${stats.by_subject.length ? stats.by_subject.map((s) => `<div class="bar"><span class="nm">${sIco(s.subject)}${esc(s.subject)}</span><span class="tr"><i style="width:${(s.n / max * 100).toFixed(0)}%"></i></span><span class="v">${s.n}</span></div>`).join('') : '<p style="color:var(--muted)">还没有记录。</p>'}</div></div>
      <div><h4 class="mono" style="margin:0 0 6px">最近问过的题</h4><div class="recent">${sessions.map((s) => `<a class="r" href="#/study/${s.id}"><span class="t">${esc(s.title || '未命名')}</span><span class="m">${esc(s.subject || '')} · ${ago(s.updated)}</span></a>`).join('') || '<p style="color:var(--muted)">还没有。</p>'}</div></div></div>`;
    $$('.mitem .mline', body).forEach((b) => b.onclick = () => toggleEvents(b.parentElement, today));
    animateBook(['.mitem', '.bars .bar', '.recent .r', '.week i']);
  }
}
// 单个知识点的事件历史（审计用）
async function toggleEvents(item, today) {
  const box = $('.evs', item);
  if (!box.classList.contains('hidden')) { box.classList.add('hidden'); item.classList.remove('open'); return; }
  const { skill, events } = await api(`/api/mastery/${item.dataset.sk}/events`);
  const pc = (v) => v == null ? '—' : pct(v) + '%';
  box.innerHTML = `<table><thead><tr><th>日期</th><th>证据</th><th>权重</th><th>P(L) 前 → 后</th><th>排程</th></tr></thead><tbody>${events.slice().reverse().map((e) => {
    const hm = new Date(e.ts * 1000).toLocaleTimeString('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hour12: false }); const d = e.day.slice(5).replace('-', '/');
    const delta = e.p_after - e.p_before; const sch = e.next_after ? `→ ${fmtDay(e.next_after)}${e.counted ? '（算一次到期复习）' : ''}` : '已出本';
    return `<tr><td>${d} <small>${hm}</small></td><td>${e.scope === 'mistake' ? '错题复习 · ' : ''}${esc(e.label)}${e.ref?.backfill ? ' <small>（迁移回放）</small>' : ''}${e.ref?.merged_from && e.ref.merged_from !== skill.topic ? ` <small>（合并自「${esc(e.ref.merged_from)}」）</small>` : ''}</td><td>${e.scope === 'mistake' ? '—' : e.weight}</td><td>${pc(e.p_before)} → <b class="${delta > 0.001 ? 'up' : delta < -0.001 ? 'down' : ''}">${pc(e.p_after)}</b></td><td>${sch}</td></tr>`;
  }).join('')}</tbody></table>`;
  box.classList.remove('hidden'); item.classList.add('open');
}


/* ---------------- 小雅记得的事（长期记忆：学生可看、改、删、清空） ---------------- */
const KIND_ORDER = ['misconception', 'weakness', 'stuck', 'strength', 'interest', 'preference', 'note'];
const KIND_GK = { misconception: 'Α', weakness: 'Β', stuck: 'Γ', strength: 'Δ', interest: 'Ε', preference: 'Ζ', note: 'Η' };
function srcTxt(src) {
  const s = (src || []).slice(-1)[0] || {};
  if (s.session_id) return `来自会话 #${s.session_id}`;
  if (s.practice_id) return `来自变式练习 #${s.practice_id}`;
  if (s.skill_id || s.skill_ids) return '来自掌握度记录';
  if (s.merged_ids) return `合并了 ${s.merged_ids.length} 条`;
  return '来自学习记录';
}
async function renderMemory() {
  const m = await api('/api/memory');
  $('#bookTitle').textContent = '小雅记得的事'; $('.book-head .mono').textContent = 'Μνήμη · 记住的是学习，不是你是谁';
  $('#bookSub').textContent = '小雅只记学习上的事：哪里还不稳、常卡在哪、喜欢怎样的讲法。不记名字、学校、住址、电话。每一条你都可以改、删，也可以全部清空。';
  $('#bookNums').innerHTML = `<div><b class="blue">${m.count}<small style="font-size:.4em"> / ${m.limits.items}</small></b><span>条记忆</span></div><div><b>${m.chars}<small style="font-size:.4em"> / ${m.limits.total}</small></b><span>字</span></div>`;
  const pref = Object.entries(m.pref_options).map(([k, o]) => `<div class="pref-row"><span class="mono">${esc(o.label)}</span><div class="seg">${o.options.map((x) => `<button data-pk="${k}" data-pv="${x.value}" class="${m.prefs[k] === x.value ? 'on' : ''}">${esc(x.label)}</button>`).join('')}</div></div>`).join('');
  const groups = KIND_ORDER.map((k) => [k, m.items.filter((i) => i.kind === k)]).filter(([, xs]) => xs.length);
  let h = `<div class="mem-prefs"><div><span class="mono">Τρόπος · 讲法偏好</span><p>小雅按这里的偏好调整讲法；你在答疑里说「讲详细点」「举个生活里的例子」，这里也会跟着变。</p></div><div>${pref}</div></div>`;
  if (!groups.length) h += `<div class="none">${art('amphora')}<h3>小雅还没记住什么</h3><p>多问几道题、做几组变式题，小雅会记下你哪里还不稳、常卡在哪。</p></div>`;
  h += groups.map(([k, xs]) => `<div class="mem-group"><div class="tg"><span class="gn">${KIND_GK[k]}΄</span><h3>${esc(m.kinds[k])}</h3><span>${xs.length} 条</span></div><div>
    ${xs.map((i) => `<div class="mem-item" data-mid="${i.id}"><div class="mt"><div class="tx">${esc(i.text)}</div>
      <div class="mm">${i.subject ? sIco(i.subject) + esc(i.subject) + (i.topic ? ' · ' + esc(i.topic) : '') + ' · ' : ''}把握 ${pct(i.confidence)}% · ${srcTxt(i.source)} · ${ago(i.updated)}${i.merged > 1 ? ` · 印证 ${i.merged} 次` : ''}${i.user_edited ? ' · <b>你改过</b>' : ''}</div></div>
      <div class="ma"><button class="ghost sm" data-medit="${i.id}">改</button><button class="ghost sm" data-mdel="${i.id}">删</button></div></div>`).join('')}</div></div>`).join('');
  h += `<div class="mem-foot"><p><b>边界</b> 最多 ${m.limits.items} 条、每条 ${m.limits.text} 字、合计 ${m.limits.total} 字。超了先把同一科的同类条目合并成一条，再按「重要 · 新近 · 把握」淘汰最不要紧的；你改过的最后才淘汰。删掉的条目不会从旧记录里再长回来。</p>
    <button class="sel sm" id="memClear"${m.count ? '' : ' disabled'}><span class="br">[×]</span>全部清空</button></div>`;
  const body = $('#bookBody'); body.innerHTML = h; $$('.sel', body).forEach(handles);
  animateBook(['.mem-group', '.none']);
  $$('[data-pk]', body).forEach((b) => b.onclick = async () => { await api('/api/memory/prefs', { [b.dataset.pk]: b.dataset.pv }); renderMemory(); });
  $$('[data-mdel]', body).forEach((b) => b.onclick = async () => { await api(`/api/memory/${b.dataset.mdel}/delete`, {}); toast('删掉了，小雅不会再从旧记录里记起它'); renderMemory(); });
  $$('[data-medit]', body).forEach((b) => b.onclick = () => {
    const it = b.closest('.mem-item'); const tx = $('.tx', it); const old = tx.textContent;
    tx.innerHTML = `<textarea rows="2" maxlength="${m.limits.text}">${esc(old)}</textarea>`; const ta = $('textarea', tx); ta.focus();
    b.textContent = '存'; b.onclick = async () => { try { await api(`/api/memory/${b.dataset.medit}/edit`, { text: ta.value }); toast('改好了'); } catch (e) { toast(e.message); } renderMemory(); };
  });
  const clr = $('#memClear'); if (clr) clr.onclick = async () => { if (!confirm('把小雅记得的事全部清空？清空后不能恢复。')) return; await api('/api/memory/clear', {}); toast('全部清空了'); renderMemory(); };
}

/* ---------------- 小雅的成长（自进化：只读 + 回滚） ---------------- */
async function renderGrowth() {
  const g = await api('/api/growth');
  $('#bookTitle').textContent = '小雅的成长'; $('.book-head .mono').textContent = 'Αὔξησις · 每讲完一道题，复盘一次';
  $('#bookSub').textContent = '每讲完一道题，小雅都会复盘：哪种问法让你自己做了出来。它只调整「怎么问」，不改原则；每一次调整都有版本，可以退回。';
  $('#bookNums').innerHTML = `<div><b class="blue">v${g.version}</b><span>当前策略版本</span></div><div><b>${g.episodes.length}</b><span>最近复盘</span></div><div><b>${g.lessons.filter((l) => l.ready).length}</b><span>成形的经验</span></div>`;
  const bar = (v) => `<span class="tr"><i style="width:${Math.round(v * 100)}%"></i></span>`;
  const lessons = g.lessons.length ? g.lessons.slice(0, 8).map((l, i) => `<div class="gr-row"><span class="n">${GKL[i] || i + 1}΄</span><span class="t">${sIco(l.subject)}${esc(l.subject)} · ${esc(l.stuck_type)}卡点 → 「${esc(l.tactic)}」${l.ready ? '' : '<small>（样本不足 3 次，还没用上）</small>'}</span>${bar(l.rate)}<span class="v">${l.wins}/${l.n}</span></div>`).join('') : '<p class="dim">还没有复盘。讲完第一道题后，这里会出现第一条经验。</p>';
  const strat = g.strategies.length ? g.strategies.map((s) => `<div class="gr-strat"><h4>${sIco(s.subject)}${esc(s.subject)}</h4>${['tactic', 'pace'].map((p) => `<div class="gr-param"><span class="mono">${p === 'tactic' ? '追问方式' : '提示推进'}</span>${s.params[p].arms.map((a) => `<div class="gr-arm${a.disabled ? ' off' : ''}${s.params[p].current === a.arm ? ' cur' : ''}"><span class="t">${esc(a.label)}${s.params[p].current === a.arm ? ' <b>· 当前</b>' : ''}${a.disabled ? ' <small>已停用</small>' : ''}</span>${bar(a.mean)}<span class="v">${pct(a.mean)}% · 观察 ${a.n}</span></div>`).join('')}</div>`).join('')}</div>`).join('') : '<p class="dim">还没有按学科分出的策略。</p>';
  const eps = g.episodes.slice(0, 6).map((e) => `<div class="gr-ep"><span class="d">${ago(e.ts)}</span><span class="t">${esc(e.summary)}${e.var_total ? ` · 变式 ${e.var_right}/${e.var_total}` : ''}</span><span class="v">v${e.version}</span></div>`).join('') || '<p class="dim">还没有。</p>';
  const vers = g.versions.slice(0, 6).map((v) => `<div class="gr-ver${v.id === g.version ? ' cur' : ''}"><span class="n">v${v.id}</span><span class="t">${esc(v.reason)}<small>${ago(v.ts)} · ${{ reflect: '复盘', rollback: '回滚', human: '人工', system: '初始' }[v.author] || esc(v.author)}</small></span>${v.id === g.version ? '<span class="mono">当前</span>' : `<button class="ghost sm" data-rb="${v.id}">回滚到这里</button>`}</div>`).join('');
  const rules = g.rules.length ? `<table class="gr-rules"><thead><tr><th>候选规则</th><th>来源例子</th><th>影子命中</th><th>误报率</th><th>状态</th></tr></thead><tbody>${g.rules.map((r) => `<tr><td><code>${esc(r.pattern)}</code></td><td>${esc(r.example)}</td><td>${r.hits}</td><td>${r.fp_rate == null ? '—' : pct(r.fp_rate) + '%'}</td><td>${{ shadow: '影子模式', approved: '已人工批准', rejected: '已驳回' }[r.status]}</td></tr>`).join('')}</tbody></table>` : '<p class="dim">没有候选规则。</p>';
  const body = $('#bookBody');
  body.innerHTML = `<div class="gr-grid"><section><div class="gr-h"><span class="mono">Ἐμπειρία · 最近学到的经验</span><h3>哪种问法对你有效</h3></div>${lessons}
      <div class="gr-h" style="margin-top:44px"><span class="mono">Ἀνασκόπησις · 最近复盘</span><h3>每道题讲完之后</h3></div>${eps}</section>
    <section><div class="gr-h"><span class="mono">Στρατηγική · 当前策略变体</span><h3>按学科自动挑选</h3></div>${strat}</section></div>
    <div class="gr-h" style="margin-top:48px"><span class="mono">Ἱστορία · 版本记录</span><h3>每一次调整都能退回</h3></div><div class="gr-vers">${vers}</div>
    <div class="gr-h" style="margin-top:48px"><span class="mono">Σκιά · 候选规则（影子模式）</span><h3>只统计，不上线</h3></div><p class="gr-note">漏题拦截的新模式先在影子模式里看命中和误报，永远不会自动生效。</p>${rules}
    <div class="gr-guard"><span class="mono">Φύλακες · 永远不改的护栏</span><ul>${g.protected.map((p) => `<li>${esc(p)}</li>`).join('')}</ul><p>复盘用的是${g.reflector === 'llm' ? '模型摘要（奖励与统计仍由规则计算）' : '离线规则（不调模型）'}。</p></div>`;
  animateBook(['.gr-row', '.gr-strat', '.gr-ep', '.gr-ver']);
  $$('[data-rb]', body).forEach((b) => b.onclick = async () => { if (!confirm(`把小雅的策略退回到 v${b.dataset.rb}？（会新建一个版本，历史都保留）`)) return; const r = await api('/api/growth/rollback', { version: +b.dataset.rb }); toast(`已回滚，当前 v${r.version}`); renderGrowth(); });
}

/* ---------------- 路由 ---------------- */
// 页面切换：额枋三道线描过去（≤ 400ms），新页淡入并上移 8px
function pageWipe(view) {
  const w = $('#archWipe'), W = innerWidth;            // viewBox 跟视口同宽：pathLength=1 的虚线才按整条线算
  w.setAttribute('viewBox', `0 0 ${W} 7`);
  [0.5, 3, 5.5].forEach((y, i) => w.children[i].setAttribute('d', `M0 ${y} H${W}`));
  w.classList.remove('go'); void w.getBoundingClientRect(); w.classList.add('go');
  clearTimeout(pageWipe.t); pageWipe.t = setTimeout(() => w.classList.remove('go'), 420);
  view.classList.remove('enter'); void view.offsetWidth; view.classList.add('enter');
}
// 焦点手柄：一个全局框，键盘焦点之间滑过去（clipo 的「选中对象」）
function initFocusRing() {
  const ring = document.createElement('div'); ring.className = 'focus-ring'; ring.innerHTML = '<i></i><i></i><i></i><i></i>';
  document.body.appendChild(ring); document.documentElement.classList.add('ring');
  let cur = null;
  const place = () => { if (!cur) return; const r = cur.getBoundingClientRect(), pad = 4; ring.style.width = r.width + pad * 2 + 'px'; ring.style.height = r.height + pad * 2 + 'px'; ring.style.transform = `translate(${r.left - pad}px, ${r.top - pad}px)`; };
  addEventListener('focusin', (e) => {
    const el = e.target;
    if (!el.matches || !el.matches(':focus-visible') || el.matches('textarea, input')) { cur = null; ring.classList.remove('on'); return; }
    const glide = ring.classList.contains('on'); cur = el;
    if (!glide) { ring.style.transition = 'none'; place(); void ring.offsetWidth; ring.style.transition = ''; } else place();
    ring.classList.add('on');
  });
  addEventListener('focusout', () => setTimeout(() => { const a = document.activeElement; if (!a || a === document.body || !a.matches(':focus-visible')) { cur = null; ring.classList.remove('on'); } }, 0));
  addEventListener('scroll', place, { passive: true, capture: true }); addEventListener('resize', place);
}

async function route() {
  const h = location.hash.replace(/^#\/?/, '');
  const [r, id] = h.split('/');
  const BOOK = ['notebook', 'record', 'memory', 'growth'];
  const name = r === 'study' ? 'study' : BOOK.includes(r) ? 'notebook' : 'home';
  if (BOOK.includes(r)) state.tab = r;
  const changed = state.route !== name; state.route = name;
  if (name === 'notebook' && (changed || state.lastTab !== state.tab)) state.animBook = true;
  state.lastTab = state.tab;
  $$('.view').forEach((v) => v.classList.toggle('hidden', v.id !== 'v-' + name));
  if (changed && !REDUCED) pageWipe($('#v-' + name));
  $$('.nav-links a').forEach((a) => a.classList.toggle('on', a.dataset.r === (name === 'notebook' ? (state.tab === 'notebook' ? 'notebook' : 'record') : name)));
  await ensureStage();
  if (stage) {
    stage.setMood(mood.cur);
    if (name === 'home') stage.mount($('#stageHome'), 'hero');
    else if (name === 'study') stage.mount($('#stageOwl'), 'owl');
  }
  if (changed) scrollTo(0, 0);
  if (name === 'study') { await openSession(id ? +id : null); }
  if (name === 'notebook') renderBook().catch((e) => toast(e.message));
  if (name === 'home') dispatchEvent(new Event('scroll'));
}

async function boot() {
  $('#brandMark').innerHTML = owlMark();
  $$('.sel').forEach(handles);
  initHome(); initStudy(); initFocusRing();
  $$('.tabs button').forEach((b) => b.onclick = () => { location.hash = '#/' + b.dataset.tab; });
  $('#gradePill').onclick = () => openOnboarding(true);
  $('#setBtn').onclick = openSettings;
  $('#modelTag').onclick = openSettings; $('#modelTag').style.cursor = 'pointer';
  try {
    const p = await api('/api/profile'); state.profile = p.profile; state.llm = p.llm; state.model = p.model;
    paintMode({ mode: p.llm ? 'model' : 'offline', model: p.model });
  } catch (e) { toast('连不上本地服务'); }
  addEventListener('hashchange', route);
  await route();
  if (state.profile) paintProfile(); else { setOrder('doric'); openOnboarding(); }
}
boot();
