/* 界面固定文案的中英字典。只翻界面（导航、按钮、标题、设置页），模型回答的语言不变。
   用法：t('设置') 取当前语言；applyLang('en') 把页面里命中字典的文字节点换掉，再切回 zh 时还原。 */
const EN = {
  '首页': 'Home', '答疑': 'Study', '错题本': 'Mistakes', '学习记录': 'Progress', '设置': 'Settings', '选择年级': 'Choose grade',
  '小雅记得的事': 'What Ya remembers', '小雅的成长': 'How Ya grows', '新题': 'New question', '发送': 'Send',
  '再给一点提示': 'One more hint', '我卡住了': "I'm stuck", '看完整解法': 'Full solution', '出几道变式题': 'Practice variants',
  '取消': 'Cancel', '保存': 'Save', '关闭': 'Close', '重试': 'Retry', '就这样，开始': "That's it, start",
  '离线演示模式': 'Offline demo', '最小化': 'Minimize', '最大化': 'Maximize', '还原': 'Restore',
  // 设置页
  '通用': 'General', '外观': 'Appearance', '模型': 'Model', '对话选模型': 'Model routing', '学习': 'Learning', '记忆': 'Memory', '数据与关于': 'Data & About',
  '界面语言': 'Interface language', '只翻译界面文字，小雅回答仍按题目语言。': 'Only the interface is translated; Ya still answers in the question’s language.',
  '快捷键': 'Shortcuts', '打开设置': 'Open settings', '答疑页': 'Study page', '首页 / 答疑 / 错题本 / 学习记录': 'Home / Study / Mistakes / Progress',
  '聚焦输入框': 'Focus the input', '关闭弹窗': 'Close dialog',
  '主题': 'Theme', '浅色': 'Light', '深色': 'Dark', '跟随系统': 'System', '首页 3D 小雅': '3D owl on home', '纸纹': 'Paper grain',
  '减弱动效': 'Reduce motion', '字号': 'Text size', '标准': 'Standard', '大': 'Large', '开': 'On', '关': 'Off',
  '服务商': 'Provider', '接口地址': 'Base URL', '密钥': 'API key', '主模型': 'Main model', '识图模型': 'Vision model',
  '自动识别模型': 'Detect models', '测试连接': 'Test connection', '备用模型': 'Fallback models', '清除密钥': 'Clear key',
  '选模型方式': 'Model selection', '自动': 'Auto', '固定': 'Fixed', '快速模型': 'Fast model', '推理模型': 'Reasoning model',
  '识图': 'Vision', '推理': 'Reasoning', '快速': 'Fast', '留空自动挑': 'Empty = auto pick',
  '年级与教材': 'Grade & textbook', '修改年级与教材': 'Change grade & textbook', '提示节奏': 'Hint style',
  '打开「小雅记得的事」': 'Open “What Ya remembers”', '打开「小雅的成长」': 'Open “How Ya grows”',
  '数据目录': 'Data folder', '导出备份': 'Export backup', '导入备份': 'Import backup', '清空学习数据': 'Clear learning data',
  '版本': 'Version', '检查更新': 'Check for updates', '用量统计': 'Usage', '备份里包含密钥': 'Include API key in backup',
  '保存设置': 'Save settings', '已保存': 'Saved',
};
let LANG = 'zh';
const orig = new WeakMap();
export function t(s) { return LANG === 'en' ? (EN[s] || s) : s; }
export function lang() { return LANG; }

function walk(root) {
  const tw = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => (n.parentElement && !n.parentElement.closest('.md, .msg, textarea, input, script, style, [data-noi18n]') ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT),
  });
  const list = []; let n; while ((n = tw.nextNode())) list.push(n);
  for (const node of list) {
    const raw = orig.has(node) ? orig.get(node) : node.nodeValue;
    const key = raw.trim();
    if (!key || !(key in EN)) continue;
    if (!orig.has(node)) orig.set(node, raw);
    node.nodeValue = LANG === 'en' ? raw.replace(key, EN[key]) : raw;
  }
  root.querySelectorAll?.('[title],[aria-label],[placeholder]').forEach((el) => {
    for (const a of ['title', 'aria-label', 'placeholder']) {
      const k = 'i18n' + a.replace('-', ''); const v = el.dataset[k] ?? el.getAttribute(a);
      if (v == null || !(v.trim() in EN)) continue;
      el.dataset[k] = v; el.setAttribute(a, LANG === 'en' ? EN[v.trim()] : v);
    }
  });
}
let mo = null;
export function applyLang(l) {
  LANG = l === 'en' ? 'en' : 'zh';
  document.documentElement.lang = LANG === 'en' ? 'en' : 'zh-CN';
  walk(document.body);
  if (LANG === 'en' && !mo) {
    mo = new MutationObserver((ms) => { for (const m of ms) m.addedNodes.forEach((n) => { if (n.nodeType === 1) walk(n); }); });
    mo.observe(document.body, { childList: true, subtree: true });
  } else if (LANG === 'zh' && mo) { mo.disconnect(); mo = null; }
}
