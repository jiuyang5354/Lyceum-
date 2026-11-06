// Presentation decisions only; all study records remain server-owned.
export function homeSummary(sessions = [], review = null) {
  const valid = sessions.filter((s) => Number.isSafeInteger(s.id) && s.id > 0);
  const session = valid.slice().sort((a, b) => (Number(b.updated) || 0) - (Number(a.updated) || 0))[0] || null;
  const due = Number.isSafeInteger(review?.topics_due) && review.topics_due >= 0 ? review.topics_due : null;
  return { session, due, visible: Boolean(session || due > 0) };
}
export function panelVisibility({ narrow = false, history = false, context = false, focus = false }) {
  if (focus) return { history: false, context: false };
  return { history: Boolean(history), context: narrow ? Boolean(context && !history) : true };
}

export function studyCue(ps = {}) {
  if (ps.full_given) return { title: '看懂以后，自己试一次', text: '换一道变式题，把刚才的方法用出来。', action: 'practice' };
  if (ps.solved) return { title: '这一步，是你自己走出来的', text: '再做一道变式题，看看换个问法还会不会。', action: 'practice' };
  if (!ps.subject) return { title: '先把题目放在这里', text: '打字或上传图片，再说说你卡在哪一步。', action: 'input' };
  return { title: '先写出你的想法', text: '哪怕只有一步也可以。需要方向时，再取一个提示。', action: 'hint' };
}
