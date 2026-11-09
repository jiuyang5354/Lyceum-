/* 设置页（分栏）：通用 / 外观 / 模型 / 对话选模型 / 学习 / 记忆 / 数据与关于。
   界面偏好即点即生效并存进 config.json（同时缓存到 localStorage，下次打开首屏就对）；
   模型相关点「保存设置」才写入。密钥只显示末四位，留空 = 不改。 */
import { t, applyLang } from './i18n.js';

let D = null;           // app.js 传进来的依赖：api, toast, esc, handles, state, openOnboarding
let S = null;           // 最近一次 /api/settings
let tab = 'model';
const TABS = [['general', '通用', 'Γενικά'], ['look', '外观', 'Ὄψις'], ['model', '模型', 'Μοντέλο'], ['route', '对话选模型', 'Ὁδός'],
  ['learn', '学习', 'Μάθησις'], ['memory', '记忆', 'Μνήμη'], ['data', '数据与关于', 'Ἀρχεῖον']];
const TAGN = { vision: '识图', reasoning: '推理', fast: '快速' };
const SET_ENV = { base_url: 'LYCEUM_BASE_URL', api_key: 'LYCEUM_API_KEY', model: 'LYCEUM_MODEL', vision_model: 'LYCEUM_VISION_MODEL',
  preset: 'LYCEUM_PRESET', route_mode: 'LYCEUM_ROUTE', fast_model: 'LYCEUM_FAST_MODEL', strong_model: 'LYCEUM_STRONG_MODEL', fallbacks: 'LYCEUM_FALLBACK_MODELS' };
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const sysDark = matchMedia('(prefers-color-scheme: dark)');

export function applyUi(ui) {
  ui = ui || {};
  const h = document.documentElement;
  const dark = ui.theme === 'dark' || (ui.theme === 'system' && sysDark.matches);
  h.dataset.theme = dark ? 'dark' : 'light';
  h.dataset.grain = ui.grain === false ? 'off' : 'on';
  h.dataset.motion = ui.reduce_motion ? 'reduce' : 'auto';
  h.dataset.font = ui.font === 'large' ? 'large' : 'normal';
  h.dataset.three = ui.three_d === false ? 'off' : 'on';
  try { localStorage.setItem('lyceum.ui', JSON.stringify(ui)); } catch (e) { /* 隐私模式 */ }
  applyLang(ui.lang);
  window.__lyUi = ui;
}
sysDark.addEventListener?.('change', () => { if ((window.__lyUi || {}).theme === 'system') applyUi(window.__lyUi); });

export function paintMode(s) {
  const st = D.state;
  st.llm = s.mode === 'model'; st.model = s.model;
  $('#modelTag').textContent = st.llm ? `${t('模型')} ${s.model}${s.route_mode === 'auto' ? ' · ' + t('自动') : ''}` : t('离线演示模式');
  $('#setDot').classList.toggle('on', st.llm);
  $('#setBtn').title = st.llm ? `已接入模型 ${s.model}` : '离线演示模式 · 点这里填 API Key';
}

export function initSettings(deps) {
  D = deps;
  initShortcuts();
}

const seg = (name, val, opts) => `<div class="sseg" data-seg="${name}">${opts.map(([v, l]) => `<button type="button" data-v="${v}" class="${String(val) === String(v) ? 'on' : ''}">${t(l)}</button>`).join('')}</div>`;
const row = (k, sub, ctl, note = '') => `<div class="srow"><div class="sk"><b>${t(k)}</b>${sub ? `<small class="latin">${sub}</small>` : ''}${note ? `<em>${note}</em>` : ''}</div><div class="sc">${ctl}</div></div>`;
const tagChips = (tags) => (tags || []).map((g) => `<span class="mtag ${g}">${t(TAGN[g])}</span>`).join('');
function lockNote(k) { return (S.locked || []).includes(k) ? `<em class="lock">由环境变量 ${SET_ENV[k]} 设置，这里改不了</em>` : ''; }
function inp(k, ph = '', type = 'text', list = '') {
  const locked = (S.locked || []).includes(k);
  let v = S[k] || '';
  if (k === 'api_key') v = '';
  if ((k === 'base_url' || k === 'model') && S.source && S.source[k] === 'default') v = '';
  return `<input class="sinp" name="${k}" type="${type}" spellcheck="false" autocomplete="${type === 'password' ? 'new-password' : 'off'}" placeholder="${D.esc(ph)}" value="${D.esc(v)}" ${list ? `list="${list}"` : ''} ${locked ? 'disabled' : ''}>${lockNote(k)}`;
}

function pane() {
  const e = D.esc, ui = S.ui || {};
  const det = S.detected_labeled || [];
  const dl = `<datalist id="mlist">${det.map((m) => `<option value="${e(m.id)}">${e(m.tags.map((g) => TAGN[g]).join(' · '))}</option>`).join('')}</datalist>`;
  if (tab === 'general') {
    const keys = [['Ctrl + ,', '打开设置'], ['Ctrl + N', '新题'], ['Ctrl + 1 – 4', '首页 / 答疑 / 错题本 / 学习记录'], ['Ctrl + /', '聚焦输入框'], ['Esc', '关闭弹窗']];
    return row('界面语言', 'Language', seg('lang', ui.lang || 'zh', [['zh', '中文'], ['en', 'English']]), t('只翻译界面文字，小雅回答仍按题目语言。')) +
      row('快捷键', 'Shortcuts', `<dl class="keys">${keys.map(([k, v]) => `<dt><kbd>${k}</kbd></dt><dd>${t(v)}</dd>`).join('')}</dl>`, 'macOS 上 Ctrl 换成 ⌘');
  }
  if (tab === 'look') {
    const onoff = (n, v) => seg(n, v === false ? 'false' : 'true', [['true', '开'], ['false', '关']]);
    return row('主题', 'Theme', seg('theme', ui.theme || 'light', [['light', '浅色'], ['dark', '深色'], ['system', '跟随系统']])) +
      row('首页 3D 小雅', 'Three-D', onoff('three_d', ui.three_d), '关掉后首页不显示三维小雅，更省电；切换后自动刷新页面') +
      row('纸纹', 'Grain', onoff('grain', ui.grain)) +
      row('减弱动效', 'Motion', seg('reduce_motion', ui.reduce_motion ? 'true' : 'false', [['false', '关'], ['true', '开']]), '打开后忽略系统设置，一律减少动画') +
      row('字号', 'Size', seg('font', ui.font || 'normal', [['normal', '标准'], ['large', '大']]));
  }
  if (tab === 'model') {
    const ps = S.presets || [];
    return `${dl}<p class="set-mode">${S.mode === 'model' ? `现在：已接入模型 <b>${e(S.model)}</b>` : '现在：<b>离线演示模式</b>，回复是固定的演示文字。'}</p>` +
      row('服务商', 'Provider', `<select class="sinp" name="preset" ${(S.locked || []).includes('preset') ? 'disabled' : ''}>${ps.map((p) => `<option value="${p.id}" ${p.id === S.preset ? 'selected' : ''}>${e(p.name)}</option>`).join('')}</select>`, '选一个会填好接口地址和默认模型，密钥要自己填') +
      row('接口地址', 'Base URL', inp('base_url', S.defaults?.base_url || 'https://…/v1', 'url')) +
      row('密钥', 'API Key', `${inp('api_key', S.key_set ? `已保存 ${S.key_hint} · 留空保持不变` : 'sk-…', 'password')}${S.key_set && S.source.api_key === 'file' ? `<button type="button" class="link" id="sKeyClr">${t('清除密钥')}</button>` : ''}`) +
      row('主模型', 'Model', `${inp('model', S.defaults?.model || '', 'text', 'mlist')}<div class="sbtns"><button type="button" class="ghost" id="sProbe">[⌕] ${t('自动识别模型')}</button><button type="button" class="ghost" id="sTest">[⇄] ${t('测试连接')}</button><span class="sres" id="sRes"></span></div>`,
        '用上面填的（还没保存的）地址和密钥请求 /models；测试连接会真发一次很短的请求') +
      `<div class="mlist" id="sModels">${det.length ? modelList(det) : ''}</div>` +
      row('备用模型', 'Fallback', inp('fallbacks', '逗号分隔，主模型出错时依次换', 'text'), '例如 deepseek-chat, qwen-plus');
  }
  if (tab === 'route') {
    const pv = S.route_preview || {};
    const role = (k, label, sub, tag) => row(label, sub, `${inp(k, t('留空自动挑'), 'text', 'mlist')}<small class="pv">${S.route_mode === 'auto' ? '会用' : '固定模式用'}：<b>${e(pv[tag] || S.model)}</b></small>`);
    return `${dl}` + row('选模型方式', 'Routing', seg('route_mode', S.route_mode || 'fixed', [['auto', '自动'], ['fixed', '固定']]), '自动：按这一轮要做的事换模型；固定：都用主模型（拍照识题用识图模型）') +
      `<ol class="rules"><li><b>拍照识题</b>（带图片）→ 识图模型</li><li><b>批改、出变式题、完整解法、作文</b> → 推理模型</li><li><b>普通提示轮</b> → 快速模型</li><li>没有对应能力的模型时，退回主模型；出错时依次换备用模型</li></ol>` +
      role('vision_model', '识图模型', 'Vision', 'vision') + role('strong_model', '推理模型', 'Reasoning', 'strong') + role('fast_model', '快速模型', 'Fast', 'fast') +
      `<p class="set-note">留空时从「自动识别模型」的结果里按名称标签挑；标签是按模型名猜的，不一定准，可以手动指定。答疑区每条回复右下角会用小字标出实际用的模型。</p>`;
  }
  if (tab === 'learn') {
    const p = D.state.profile;
    return row('年级与教材', 'Grade', `<span class="sval">${p ? e(`${p.grade} 年级 · ${p.textbook}`) : '还没选'}</span><button type="button" class="ghost" id="sGrade">${t('修改年级与教材')}</button>`) +
      `<div id="sPrefs"><p class="set-note">读取中…</p></div>`;
  }
  if (tab === 'memory') {
    return `<p class="set-note">小雅记住的是学习上的事（哪里容易卡、喜欢哪种讲法），不记你是谁。可以随时查看、修改、删除。</p>` +
      `<div class="sbig"><button type="button" class="sel" data-go="memory"><span class="br">[→]</span>${t('打开「小雅记得的事」')}</button><button type="button" class="sel" data-go="growth"><span class="br">[→]</span>${t('打开「小雅的成长」')}</button></div>`;
  }
  // data
  const u = S.usage || {};
  const us = Object.entries(u).sort((a, b) => b[1].calls - a[1].calls);
  return row('数据目录', 'Folder', `<code class="sval">${e(S.data_dir || '')}</code>`) +
    row('导出备份', 'Export', `<a class="ghost btnlike" id="sExport" href="/api/backup" download>[↓] ${t('导出备份')}</a><label class="chk"><input type="checkbox" id="sExpKey"> ${t('备份里包含密钥')}</label>`, '学习库 + 设置（zip）；默认不含密钥，上传的题图不进备份') +
    row('导入备份', 'Import', `<label class="ghost btnlike">[↑] ${t('导入备份')}<input type="file" id="sImport" accept=".zip" hidden></label>`, '会覆盖现在的学习记录；备份里没有密钥就保留现在的') +
    row('清空学习数据', 'Reset', `<button type="button" class="ghost danger" id="sClear">${t('清空学习数据')}</button>`, '会话、错题、掌握度、记忆、成长规则全部删除，年级与教材保留') +
    row('版本', 'Version', `<span class="sval">Lyceum 学园 v${e(S.version || '')}</span><button type="button" class="ghost" id="sUpd">${t('检查更新')}</button><span class="sres" id="sUpdRes"></span>`, '只查 GitHub Releases 有没有新版，不会自动下载安装') +
    row('用量统计', 'Usage', us.length ? `<table class="utab"><tr><th>模型</th><th>调用</th><th>输入</th><th>输出</th></tr>${us.map(([m, r]) => `<tr><td>${e(m)}</td><td>${r.calls}</td><td>${r.prompt_tokens}</td><td>${r.completion_tokens}${r.estimated ? '*' : ''}</td></tr>`).join('')}</table>` : '<span class="sval">还没有调用过模型</span>', 'token 数来自接口返回；带 * 的含按字数估计');
}

function modelList(list) {
  return `<p class="mhead">识别到 ${list.length} 个模型 · 标签按名称猜测 · 点一下设为主模型</p><div class="mgrid">${list.slice(0, 120).map((m) => `<button type="button" class="mitem" data-m="${D.esc(m.id)}"><span>${D.esc(m.id)}</span>${tagChips(m.tags)}</button>`).join('')}</div>`;
}

function paint() {
  const box = $('#setx');
  box.innerHTML = `<aside class="snav"><span class="mono">Ρυθμίσεις · ${t('设置')}</span><h2>${t('设置')}</h2>${TABS.map(([k, l, g]) => `<button type="button" data-tab="${k}" class="${k === tab ? 'on' : ''}"><span>${t(l)}</span><small class="latin">${g}</small></button>`).join('')}</aside>
    <form class="spane" id="setForm" autocomplete="off"><h3>${t(TABS.find((x) => x[0] === tab)[1])}</h3><div class="sbody">${pane()}</div>
    ${['model', 'route'].includes(tab) ? `<div class="set-foot"><span class="set-note">只保存在这台电脑的数据目录（config.json），不会上传。</span><span class="sp"></span><button type="submit" class="sel solid" id="setOk"><span class="br">[✓]</span>${t('保存设置')}</button></div>` : ''}
    <button type="button" class="sclose" id="setCancel" title="关闭" aria-label="关闭">×</button></form>`;
  $$('.sel', box).forEach(D.handles);
  bind(box);
}

function collect() {
  const f = $('#setForm'), body = {};
  for (const k of Object.keys(SET_ENV)) { const el = f.elements[k]; if (el && !el.disabled) body[k] = el.value.trim(); }
  return body;
}

async function save(body, quiet) {
  try { S = await D.api('/api/settings', body); paintMode(S); if (!quiet) D.toast(t('已保存')); return S; } catch (e) { D.toast(e.message); }
}

function bind(box) {
  $$('.snav [data-tab]', box).forEach((b) => b.onclick = () => { stash(); tab = b.dataset.tab; paint(); });
  $('#setCancel', box).onclick = closeSettings;
  $$('.sseg', box).forEach((g) => g.onclick = async (ev) => {
    const b = ev.target.closest('button'); if (!b) return;
    const name = g.dataset.seg; let v = b.dataset.v;
    $$('button', g).forEach((x) => x.classList.toggle('on', x === b));
    if (name === 'route_mode') { draft.route_mode = v; return; }
    if (['three_d', 'grain', 'reduce_motion'].includes(name)) v = v === 'true';
    const prev3d = (S.ui || {}).three_d;
    const r = await save({ ui: { [name]: v } }, true);
    if (r) { applyUi(r.ui); paint(); if (name === 'three_d' && prev3d !== v) setTimeout(() => location.reload(), 250); }
  });
  const f = $('#setForm', box);
  f.onsubmit = async (e) => {
    e.preventDefault();
    const r = await save(Object.assign(collect(), draft.route_mode ? { route_mode: draft.route_mode } : {}));
    if (r) { draft = {}; paint(); }
  };
  const pre = f.elements.preset;
  if (pre) pre.onchange = () => {
    const p = (S.presets || []).find((x) => x.id === pre.value); if (!p || p.id === 'custom') return;
    if (!f.elements.base_url.disabled) f.elements.base_url.value = p.base_url;
    if (!f.elements.model.disabled) f.elements.model.value = p.model;
  };
  const clr = $('#sKeyClr', box); if (clr) clr.onclick = async () => { if (await save({ clear_key: true }, true)) { D.toast('已清除保存的密钥'); paint(); } };
  const res = $('#sRes', box);
  const conn = () => ({ base_url: f.elements.base_url?.value.trim() || '', api_key: f.elements.api_key?.value.trim() || '' });
  const probe = $('#sProbe', box); if (probe) probe.onclick = async () => {
    res.textContent = '识别中…'; res.className = 'sres';
    try {
      const r = await D.api('/api/settings/models', conn());
      res.textContent = `找到 ${r.models.length} 个`; res.className = 'sres ok';
      $('#sModels').innerHTML = modelList(r.models); bindModels();
      $('#mlist').innerHTML = r.models.map((m) => `<option value="${D.esc(m.id)}">${m.tags.map((g) => TAGN[g]).join(' · ')}</option>`).join('');
      S.detected_labeled = r.models;
    } catch (e) { res.textContent = e.message; res.className = 'sres bad'; }
  };
  const test = $('#sTest', box); if (test) test.onclick = async () => {
    res.textContent = '连接中…'; res.className = 'sres';
    try { const r = await D.api('/api/settings/test', Object.assign(conn(), { model: f.elements.model.value.trim() })); res.textContent = `连通 · ${r.model}`; res.className = 'sres ok'; } catch (e) { res.textContent = e.message; res.className = 'sres bad'; }
  };
  bindModels();
  const g = $('#sGrade', box); if (g) g.onclick = () => { closeSettings(); D.openOnboarding(true); };
  if (tab === 'learn') loadPrefs();
  $$('[data-go]', box).forEach((b) => b.onclick = () => { closeSettings(); location.hash = '#/' + b.dataset.go; });
  const ek = $('#sExpKey', box); if (ek) ek.onchange = () => { $('#sExport').href = '/api/backup' + (ek.checked ? '?key=1' : ''); };
  const im = $('#sImport', box); if (im) im.onchange = () => {
    const file = im.files[0]; if (!file) return;
    if (!confirm('导入会覆盖现在的学习记录，确定吗？')) { im.value = ''; return; }
    const rd = new FileReader();
    rd.onload = async () => { try { await D.api('/api/backup/import', { zip: rd.result }); D.toast('备份已导入'); setTimeout(() => location.reload(), 600); } catch (e) { D.toast(e.message); } };
    rd.readAsDataURL(file);
  };
  const cl = $('#sClear', box); if (cl) cl.onclick = async () => {
    if (!confirm('清空全部学习数据？会话、错题、掌握度、记忆都会删除。')) return;
    if (!confirm('再确认一次：清空后不能恢复（建议先导出备份）。')) return;
    try { await D.api('/api/data/clear', { confirm: 'CLEAR' }); D.toast('学习数据已清空'); setTimeout(() => location.reload(), 600); } catch (e) { D.toast(e.message); }
  };
  const up = $('#sUpd', box); if (up) up.onclick = async () => {
    const o = $('#sUpdRes'); o.textContent = '查询中…';
    try {
      const r = await D.api('/api/update');
      if (!r.ok) { o.textContent = r.error; return; }
      if (!r.newer) { o.textContent = `已是最新（最新 v${D.esc(r.latest || r.current)}）`; return; }
      o.innerHTML = `有新版 v${D.esc(r.latest)} · <button type="button" class="ghost" id="sUpdGo">下载并安装</button>
        <a href="${D.esc(r.url)}" target="_blank" rel="noopener">说明</a> <span id="sUpdP" class="sres"></span>`;
      $('#sUpdGo').onclick = () => startUpdateDownload(o);
    } catch (e) { o.textContent = e.message; }
  };
}

async function startUpdateDownload(o) {
  const go = $('#sUpdGo', o), p = $('#sUpdP', o);
  go.disabled = true; p.textContent = '准备下载…';
  try { await D.api('/api/update/download', {}); } catch (e) { p.textContent = e.message; go.disabled = false; return; }
  const mb = (n) => (n / 1048576).toFixed(1);
  const timer = setInterval(async () => {
    let s;
    try { s = await D.api('/api/update/progress'); } catch (e) { return; }
    if (s.error) { clearInterval(timer); p.textContent = s.error; go.disabled = false; return; }
    if (s.running) {
      p.textContent = s.total ? `下载中 ${Math.round(s.got / s.total * 100)}%（${mb(s.got)}/${mb(s.total)} MB）` : `下载中 ${mb(s.got)} MB`;
      return;
    }
    clearInterval(timer);
    if (!s.path) { p.textContent = '下载没有完成'; go.disabled = false; return; }
    p.textContent = '下载完成';
    go.textContent = '立即安装'; go.disabled = false;
    go.onclick = async () => {
      go.disabled = true;
      try { await D.api('/api/update/install', { path: s.path }); p.textContent = '安装程序已启动，按提示完成后重新打开'; }
      catch (e) { p.textContent = e.message; go.disabled = false; }
    };
  }, 500);
}

function bindModels() {
  $$('.mitem').forEach((b) => b.onclick = () => { const m = $('#setForm').elements.model; if (m && !m.disabled) { m.value = b.dataset.m; D.toast('主模型设为 ' + b.dataset.m + '，记得保存'); } });
}

async function loadPrefs() {
  const box = $('#sPrefs'); if (!box) return;
  try {
    const r = await D.api('/api/memory');
    box.innerHTML = Object.entries(r.pref_options || {}).map(([k, d]) => row(k === 'depth' ? '提示节奏' : d.label, k === 'depth' ? 'Pace' : 'Style',
      seg('p_' + k, r.prefs[k], d.options.map((o) => [o.value, o.label])))).join('');
    $$('.sseg', box).forEach((g) => g.onclick = async (ev) => {
      const b = ev.target.closest('button'); if (!b) return;
      $$('button', g).forEach((x) => x.classList.toggle('on', x === b));
      try { await D.api('/api/memory/prefs', { [g.dataset.seg.slice(2)]: b.dataset.v }); D.toast(t('已保存')); } catch (e) { D.toast(e.message); }
    });
  } catch (e) { box.innerHTML = `<p class="set-note">${D.esc(e.message)}</p>`; }
}

let draft = {};
function stash() { // 切分栏时保留没保存的模型表单
  const f = $('#setForm'); if (!f) return;
  for (const k of Object.keys(SET_ENV)) { const el = f.elements[k]; if (el && !el.disabled && k !== 'api_key') S[k] = el.value.trim(); }
  if (draft.route_mode) S.route_mode = draft.route_mode;
}

let onKey = null;
export async function openSettings(which) {
  try { S = await D.api('/api/settings'); } catch (e) { return D.toast(e.message); }
  if (which) tab = which;
  draft = {};
  paint();
  $('#setModal').classList.remove('hidden');
  onKey = (e) => { if (e.key === 'Escape') closeSettings(); };
  addEventListener('keydown', onKey);
  $('#setModal').onclick = (e) => { if (e.target.id === 'setModal') closeSettings(); };
}
export function closeSettings() {
  $('#setModal').classList.add('hidden');
  if (onKey) removeEventListener('keydown', onKey);
}

function initShortcuts() {
  addEventListener('keydown', (e) => {
    if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
    const k = e.key;
    const go = (h) => { e.preventDefault(); closeSettings(); location.hash = h; };
    if (k === ',') { e.preventDefault(); openSettings(); }
    else if (k === 'n' || k === 'N') { e.preventDefault(); closeSettings(); location.hash = '#/study'; setTimeout(() => { const b = document.getElementById('newChat'); if (b) b.click(); document.getElementById('input')?.focus(); }, 60); }
    else if (k === '1') go('#/');
    else if (k === '2') go('#/study');
    else if (k === '3') go('#/notebook');
    else if (k === '4') go('#/record');
    else if (k === '/') { e.preventDefault(); location.hash = '#/study'; setTimeout(() => document.getElementById('input')?.focus(), 60); }
  });
}
