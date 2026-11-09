import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
const app = readFileSync(new URL('../static/js/app.js', import.meta.url), 'utf8');
const escLine = app.split('\n').find((l) => l.startsWith('const esc = ')).slice(12).replace(/;$/, '');
const esc = vm.runInNewContext('(' + escLine + ')');
const reviewSource = app.slice(app.indexOf('function reviewBrief('), app.indexOf('function mistakeCard('));
const reviewBrief = vm.runInNewContext('(' + reviewSource.trim() + ')', { fmtDay: String, esc });
test('the review brief shows what to practise next and why', () => {
  const brief = reviewBrief({ topics_due: 1, mistakes_due: 0, skills: [{ id: 9 }], mistakes: [],
    next: { subject: '数学', topic: '整式的乘法', reason: '整式的乘法 还没稳（0.60 < 0.85），先补这一步再看 因式分解' } }, '2026-01-02');
  assert.match(brief, /下一步/);
  assert.match(brief, /整式的乘法/);
  assert.match(brief, /先补这一步再看/);
  assert.equal((brief.match(/整式的乘法/g) || []).length, 1, "知识点名不应重复出现");
  assert.doesNotMatch(reviewBrief({ topics_due: 0, mistakes_due: 0 }, '2026-01-02'), /下一步/);
  assert.doesNotMatch(reviewBrief({ topics_due: 0, mistakes_due: 0, next: { topic: '<img onerror=x>' } }, '2026-01-02'), /<img/);
});

test('the review action opens an actual due exercise rather than linking to itself', () => {
  assert.match(reviewBrief({ topics_due: 1, mistakes_due: 1, mistakes: [{ id: 8 }], skills: [] }, '2026-01-02'), /data-retry="8"/);
  assert.match(reviewBrief({ topics_due: 1, mistakes_due: 0, mistakes: [], skills: [{ id: 9 }] }, '2026-01-02'), /data-rskill="9"/);
  assert.match(reviewBrief({ topics_due: 0, mistakes_due: 0 }, '2026-01-02'), /href="#\/study"/);
});

const source = app.slice(app.indexOf('function mistakeCard('), app.indexOf('function bindBook('));
const card = vm.runInNewContext('(' + source.trim() + ')', { esc, md: esc, fmtDay: String, ago: () => '刚刚' });

test('a review card keeps reference answer inside a closed disclosure', () => {
  const html = card({ id: 4, question: '计算1+1', user_answer: '3', correct_answer: 'REFERENCE_42', explain: '说明', next_review: '2026-01-01' }, '2026-01-02');
  const disclosure = html.match(/<details([^>]*)>([\s\S]*?)<\/details>/);
  assert.ok(disclosure);
  assert.match(disclosure[2], /REFERENCE_42/);
  assert.doesNotMatch(disclosure[1], /\bopen\b/);
  assert.ok(html.indexOf('3') < html.indexOf('<details'));
  assert.match(html, /data-retry="4"/);
});

test('answer disclosure escapes student and reference text', () => {
  const html = card({ id: 4, question: '题目', user_answer: '<script>x</script>', correct_answer: '<img src=x>', explain: '说明' }, '2026-01-02');
  assert.doesNotMatch(html, /<script>|<img src=x>/);
  assert.match(html, /&lt;img src=x&gt;/);
});
