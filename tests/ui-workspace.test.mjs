import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
const path = new URL('../static/js/workspace.js', import.meta.url);
const ui = await import('data:text/javascript;base64,' + Buffer.from(existsSync(path) ? readFileSync(path, 'utf8') : '').toString('base64'));

test('panel visibility preserves a reading area and one narrow drawer', () => {
  assert.equal(typeof ui.panelVisibility, 'function');
  assert.deepEqual(ui.panelVisibility({ narrow: false, history: true, focus: false }), { history: true, context: true });
  assert.deepEqual(ui.panelVisibility({ narrow: false, history: true, focus: true }), { history: false, context: false });
  assert.deepEqual(ui.panelVisibility({ narrow: true, history: true, context: true }), { history: true, context: false });
  assert.deepEqual(ui.panelVisibility({ narrow: true, history: false, context: true }), { history: false, context: true });
});

test('study cue distinguishes an independent solution from viewing the answer', () => {
  assert.equal(typeof ui.studyCue, 'function');
  assert.equal(ui.studyCue({}).title, '先把题目放在这里');
  assert.equal(ui.studyCue({ subject: '数学', hint_level: 1 }).title, '先写出你的想法');
  assert.equal(ui.studyCue({ solved: true }).action, 'practice');
  assert.equal(ui.studyCue({ solved: true, full_given: true }).title, '看懂以后，自己试一次');
});

test('home summary uses actual latest session and never invents zero on missing review', () => {
  assert.equal(typeof ui.homeSummary, 'function');
  const sessions = [{ id: 1, title: '<img>', updated: 5 }, { id: 2, title: '最近一道题', updated: 20 }];
  const before = structuredClone(sessions);
  assert.deepEqual(ui.homeSummary(sessions, { topics_due: 3 }), { session: sessions[1], due: 3, visible: true });
  assert.deepEqual(sessions, before);
  assert.equal(ui.homeSummary(sessions, null).due, null);
  assert.equal(ui.homeSummary([], { topics_due: 0 }).visible, false);
  assert.equal(ui.homeSummary([], { topics_due: 2 }).visible, true);
  assert.equal(ui.homeSummary([{ id: 'bad', updated: 30 }], null).session, null);
});
