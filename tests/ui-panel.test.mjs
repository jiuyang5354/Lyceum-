import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const app = readFileSync(new URL('../static/js/app.js', import.meta.url), 'utf8');
const workspace = readFileSync(new URL('../static/js/workspace.js', import.meta.url), 'utf8');
const { panelVisibility } = await import('data:text/javascript;base64,' + Buffer.from(workspace).toString('base64'));
const panelSource = app.slice(app.indexOf('function initWorkspacePanels('), app.indexOf('/* ---------------- 列表进入'));
const sessionSource = app.slice(app.indexOf('async function loadSessions('), app.indexOf('async function openSession('));

// Exercise the real controller and registered click handlers; only the DOM/API
// boundary is stubbed. location deliberately dispatches no hashchange event.
function studyHarness({ narrow = true, hash = '#/study', session = null } = {}) {
  const nodes = new Map();
  const $ = (selector) => {
    if (!nodes.has(selector)) nodes.set(selector, {
      dataset: {}, attributes: {}, hidden: false,
      setAttribute(name, value) { this.attributes[name] = value; },
      contains() { return false; }, focus() {},
      addEventListener() {}, insertAdjacentHTML() {},
    });
    return nodes.get(selector);
  };
  const sessions = [{ id: 7, title: '原来的题', subject: '物理', updated: 1 }];
  const buttons = sessions.map((s) => ({ dataset: { id: String(s.id) } }));
  const location = { hash };
  const context = {
    $, $$: (selector) => selector === '.sess' ? buttons : [], location,
    state: { route: 'study', session }, document: { activeElement: null },
    matchMedia: () => ({ matches: narrow, addEventListener() {} }),
    localStorage: { getItem() { return null; }, setItem() {} },
    addEventListener() {}, panelVisibility,
    api: async () => ({ sessions }), esc: String, ago: () => '刚刚',
    icons: { image: '', close: '' }, columnGlyph: () => '', GK: [],
    handles() {}, clearImage() {},
  };
  const { loadSessions } = vm.runInNewContext(
    `let studyPanels; ${panelSource}\n${sessionSource}\ninitStudy(); ({ loadSessions });`, context);
  return { $, location, buttons, loadSessions };
}

function assertHistoryClosed($) {
  assert.equal($('#sessionSidebar').hidden, true, 'history drawer must close without hashchange');
  assert.equal($('#studyContext').hidden, true);
  assert.equal($('#panelShade').hidden, true, 'shade must not block the reading area');
  assert.equal($('#historyToggle').attributes['aria-expanded'], 'false');
}

test('new chat on #/study dismisses the narrow drawer even when the hash is unchanged', () => {
  const { $, location } = studyHarness();
  $('#historyToggle').onclick();
  assert.equal($('#sessionSidebar').hidden, false);
  assert.equal($('#panelShade').hidden, false);
  $('#newChat').onclick();
  assert.equal(location.hash, '#/study');
  assertHistoryClosed($);
});

test('selecting the current history session dismisses the narrow drawer without hashchange', async () => {
  const { $, location, buttons, loadSessions } = studyHarness({ hash: '#/study/7', session: { id: 7 } });
  await loadSessions();
  assert.match($('#sessList').innerHTML, /class="sess on" data-id="7"/);
  $('#historyToggle').onclick();
  assert.equal($('#sessionSidebar').hidden, false);
  assert.equal($('#panelShade').hidden, false);
  buttons[0].onclick();
  assert.equal(location.hash, '#/study/7');
  assertHistoryClosed($);
});

test('chat selection keeps both desktop panels visible and still updates the destination', async () => {
  const { $, location, buttons, loadSessions } = studyHarness({ narrow: false, hash: '#/study/1', session: { id: 1 } });
  await loadSessions();
  for (const [click, hash] of [[$('#newChat').onclick, '#/study'], [buttons[0].onclick, '#/study/7']]) {
    click();
    assert.equal(location.hash, hash);
    assert.equal($('#sessionSidebar').hidden, false);
    assert.equal($('#studyContext').hidden, false);
    assert.equal($('#panelShade').hidden, true);
    assert.equal($('#historyToggle').attributes['aria-expanded'], 'true');
  }
});

const baseCss = readFileSync(new URL('../static/css/app.css', import.meta.url), 'utf8');
const css = readFileSync(new URL('../static/css/workspace.css', import.meta.url), 'utf8');

// CSS contracts, not a layout engine: the parent browser checks actual geometry.
function declarations(source, selector) {
  return [...source.replace(/\/\*[\s\S]*?\*\//g, '').matchAll(/([^{}]+)\{([^{}]*)\}/g)]
    .filter(([, selectors]) => selectors.trim().split(/\s*,\s*/).includes(selector))
    .map(([, , body]) => body).join(';');
}
function mediaBlock(source, query) {
  const start = source.indexOf('@media ' + query);
  assert.notEqual(start, -1, `Missing media query: ${query}`);
  const open = source.indexOf('{', start);
  let depth = 1, end = open + 1;
  while (depth && end < source.length) {
    if (source[end] === '{') depth++;
    if (source[end] === '}') depth--;
    end++;
  }
  assert.equal(depth, 0);
  return source.slice(open + 1, end - 1);
}

test('narrow history overrides the legacy mobile hide without defeating [hidden]', () => {
  const legacyMobile = mediaBlock(baseCss, '(max-width: 860px)');
  assert.match(declarations(legacyMobile, '.side'), /display:\s*none\s*;/);
  const drawer = declarations(mediaBlock(css, '(max-width: 1050px)'), '.study > .side');
  assert.match(drawer, /display:\s*flex\s*;/, 'open history must override legacy .side display:none');
  assert.doesNotMatch(drawer, /display:[^;]*!important/, '[hidden] must win when the drawer closes');
  assert.match(declarations(css, '[hidden]'), /display:\s*none\s*!important\s*;/);
});

test('375px record layout constrains long titles and wraps intact metadata', async () => {
  const title = '流式切题测试：为什么天空是蓝色的？';
  const body = {};
  const responses = {
    '/api/stats': {
      stats: { by_subject: [], streak: 1, skills_mastered: 0, skills_total: 0, active_days: 1 },
      sessions: [{ id: 7, title, subject: '物理', updated: 1 }],
    },
    '/api/mastery': { today: '2026-01-02', skills: [] },
    '/api/review/today': { topics_due: 0 },
  };
  const renderSource = app.slice(app.indexOf('async function renderBook('), app.indexOf('// 写作体检：形式维度当场算'));
  const reviewSource = app.slice(app.indexOf('function reviewBrief('), app.indexOf('function mistakeCard('));
  const renderBook = vm.runInNewContext(`(${renderSource.trim()})`, {
    $: (selector) => selector === '#bookBody' ? body : {}, $$: () => [],
    state: { tab: 'record' },
    api: async (path) => { assert.ok(path in responses, path); return responses[path]; },
    reviewBrief: vm.runInNewContext(`(${reviewSource.trim()})`),
    esc: String, ago: () => '11月7日', bindBook() {}, bindWriting() {}, writingPanel: () => '', animateBook() {},
  });
  await renderBook();
  assert.ok(body.innerHTML.includes(`<a class="r" href="#/study/7"><span class="t">${title}</span><span class="m">物理 · 11月7日</span></a>`));
  assert.match(declarations(mediaBlock(css, '(max-width: 860px)'), '.rec-grid'),
    /grid-template-columns:\s*minmax\(0,\s*1fr\)\s*;/, 'mobile grid must not use a min-content track floor');
  assert.match(declarations(css, '.rec-grid > *'), /min-width:\s*0\s*;/);
  const phone = mediaBlock(css, '(max-width: 600px)');
  assert.match(declarations(phone, '.recent .r'), /flex-direction:\s*column\s*;/,
    'title and metadata need separate lines on phones');
  const text = declarations(baseCss + '\n' + css, '.recent .r .t');
  assert.match(text, /overflow:\s*hidden\s*;/);
  assert.match(text, /text-overflow:\s*ellipsis\s*;/);
  assert.match(text, /white-space:\s*nowrap\s*;/);
  const metadata = declarations(phone, '.recent .r .m');
  assert.match(metadata, /white-space:\s*normal\s*;/);
  assert.match(metadata, /overflow-wrap:\s*anywhere\s*;/);
  assert.doesNotMatch(declarations(baseCss + '\n' + css, '.recent .r .m'),
    /display:\s*none|overflow:\s*hidden|text-overflow:\s*ellipsis/);
});
