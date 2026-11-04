/* 桌面版无边框窗口的自绘标题栏（只在 ?frame=custom 时出现；浏览器打开的网页版不显示）。
   左：小雅 + 「Lyceum 学园」；中：拖动区（双击最大化 / 还原）；右：最小化、最大化还原、关闭。
   四边四角是缩放热区，最大化时隐藏。窗口控制走 pywebview js_api（见 lyceum/winchrome.py）。 */
import { owlMark } from './svg.js';

const ICON = {
  min: '<svg viewBox="0 0 10 10" aria-hidden="true"><path d="M1 5.5h8"/></svg>',
  max: '<svg viewBox="0 0 10 10" aria-hidden="true"><rect x="1" y="1" width="8" height="8"/></svg>',
  res: '<svg viewBox="0 0 10 10" aria-hidden="true"><rect x="1" y="3" width="6" height="6"/><path d="M3 3V1h6v6H7"/></svg>',
  cls: '<svg viewBox="0 0 10 10" aria-hidden="true"><path d="M1.5 1.5l7 7M8.5 1.5l-7 7"/></svg>',
};

export function initTitlebar() {
  if (new URLSearchParams(location.search).get('frame') !== 'custom') return false;
  const root = document.documentElement;
  root.classList.add('framed');
  const bar = document.createElement('div');
  bar.className = 'titlebar';
  bar.innerHTML = `<div class="tb-brand"><span class="tb-owl">${owlMark()}</span><b>Lyceum</b><span>学园</span></div>
    <div class="tb-drag" id="tbDrag"></div>
    <div class="tb-btns"><button type="button" id="tbMin" title="最小化" aria-label="最小化">${ICON.min}</button><button type="button" id="tbMax" title="最大化" aria-label="最大化">${ICON.max}</button><button type="button" id="tbCls" class="cls" title="关闭" aria-label="关闭">${ICON.cls}</button></div>`;
  document.body.prepend(bar);
  for (const e of [10, 11, 12, 13, 14, 15, 16, 17]) {
    const d = document.createElement('div'); d.className = 'wrs'; d.dataset.e = e; document.body.appendChild(d);
  }
  const call = async (name, ...a) => { try { const api = window.pywebview && window.pywebview.api; return api && api[name] ? await api[name](...a) : undefined; } catch (e) { return undefined; } };
  const maxIcon = (m) => { root.classList.toggle('wmax', !!m); const b = document.getElementById('tbMax'); b.innerHTML = m ? ICON.res : ICON.max; b.title = m ? '还原' : '最大化'; b.setAttribute('aria-label', b.title); };
  const toggle = async () => maxIcon(await call('toggle_max'));
  document.getElementById('tbMin').onclick = () => call('minimize');
  document.getElementById('tbMax').onclick = toggle;
  document.getElementById('tbCls').onclick = () => call('close');
  /* 拖动 / 缩放：按下 begin，移动时每帧最多一次 step（上一次没回来就不发），松开 end */
  let on = false, down = false, busy = false, raf = 0;
  addEventListener('mouseup', () => { down = false; }, true);
  const step = () => { raf = 0; if (!on || busy) return; busy = true; Promise.resolve(call('step')).finally(() => { busy = false; }); };
  const move = () => { if (on && !raf) raf = requestAnimationFrame(step); };
  const up = async () => { if (!on) return; on = false; removeEventListener('mousemove', move, true); removeEventListener('mouseup', up, true); if (await call('end')) maxIcon(true); };
  const start = async (edge) => {
    down = true; const ok = await call('begin', edge); if (!ok) return;
    if (!down) { call('end'); return; }
    on = true; addEventListener('mousemove', move, true); addEventListener('mouseup', up, true); if (edge === 2) maxIcon(false);
  };
  const drag = (e) => { if (e.button === 0 && e.detail === 1 && !e.target.closest('button')) { e.preventDefault(); start(2); } };
  document.getElementById('tbDrag').addEventListener('mousedown', drag);
  bar.querySelector('.tb-brand').addEventListener('mousedown', drag);
  bar.addEventListener('dblclick', (e) => { if (!e.target.closest('button')) toggle(); });
  document.querySelectorAll('.wrs').forEach((el) => el.addEventListener('mousedown', (e) => { if (e.button === 0) { e.preventDefault(); start(+el.dataset.e); } }));
  addEventListener('pywebviewready', async () => maxIcon(await call('is_max')));
  addEventListener('resize', () => { clearTimeout(window.__wm); window.__wm = setTimeout(async () => maxIcon(await call('is_max')), 150); });
  return true;
}
