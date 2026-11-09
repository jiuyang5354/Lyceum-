"""学习周报：给家长/老师看的一页纸，只读、离线、自包含。

为什么是「导出文件」而不是「分享链接」
  桌面版只监听 127.0.0.1，链接发给别人打不开；把报告渲染成一个自包含的 HTML，
  家长用浏览器打开、打印成 PDF 都行，不需要装任何东西、也不上传任何数据。

只放**已经存在的事实**：提问数、覆盖学科、新增错题、掌握度变化、写作评阅。
不重新打分、不做预测；拿不到的数据写「—」，不编。
"""
import html
import time

WINDOW_DAYS = 7
WINDOW = WINDOW_DAYS * 86400


def week(db, now=None):
    """汇总最近 7 天的学习事实。返回纯 dict，方便测试与以后换渲染层。"""
    now = time.time() if now is None else float(now)
    start = now - WINDOW
    prof = db.get_profile() or {}
    sessions = db.q("SELECT COUNT(*) AS n FROM sessions WHERE updated >= ?", (start,), one=True)["n"]
    messages = db.q("SELECT COUNT(*) AS n FROM messages WHERE created >= ?", (start,), one=True)["n"]
    subjects = db.q("SELECT subject, COUNT(*) AS n FROM sessions WHERE updated >= ? AND subject IS NOT NULL "
                    "GROUP BY subject ORDER BY n DESC", (start,))
    new_mistakes = db.q("SELECT COUNT(*) AS n FROM mistakes WHERE created >= ?", (start,), one=True)["n"]
    fixed = db.q("SELECT COUNT(*) AS n FROM mistakes WHERE mastered_at IS NOT NULL AND mastered_at >= ?",
                 (start,), one=True)["n"]
    skills = db.q("SELECT subject, topic, p_l, n_obs FROM skills WHERE updated >= ? ORDER BY p_l ASC, topic",
                  (start,))
    due = sum(1 for row in db.mastery_list() if row.get("review_today"))
    writing = [w for w in db.writing_history(None, 8) if (w.get("created") or 0) >= start]
    return {"from": start, "to": now, "days": WINDOW_DAYS,
            "nickname": (prof.get("nickname") or "").strip(),
            "grade": prof.get("grade"), "textbook": prof.get("textbook") or "",
            "sessions": sessions, "messages": messages, "subjects": subjects,
            "new_mistakes": new_mistakes, "fixed_mistakes": fixed,
            "skills": skills, "due": due, "writing": writing}


def _fmt_day(ts):
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def _pct(v):
    return "—" if v is None else "%d%%" % round(float(v) * 100)


def render(data):
    """渲染成自包含 HTML。所有外部文本一律转义，不引外链、不执行脚本。"""
    esc = html.escape
    who = data.get("nickname") or ("%s 年级" % data["grade"] if data.get("grade") else "同学")
    subs = data.get("subjects") or []
    subs_txt = "、".join("%s %d 次" % (esc(s["subject"] or "未分科"), s["n"]) for s in subs) or "—"
    skills = data.get("skills") or []
    rows = "".join(
        "<tr><td>%s</td><td>%s</td><td class=\"num\">%s</td><td class=\"num\">%d</td></tr>"
        % (esc(s["subject"] or ""), esc(s["topic"] or "未分类"), _pct(s["p_l"]), int(s["n_obs"] or 0))
        for s in skills[:8]) or "<tr><td colspan=\"4\" class=\"empty\">这周还没有新的掌握度变化</td></tr>"
    writing = data.get("writing") or []
    w_txt = "、".join("%s %s/%s" % (esc(w["subject"] or ""), w["total"], w["max"]) for w in writing[:4]) or "—"
    lowest = skills[0] if skills else None
    focus = ("这周最该补的是「%s · %s」（掌握度 %s）。" % (esc(lowest["subject"] or ""), esc(lowest["topic"] or ""),
                                                 _pct(lowest["p_l"]))) if lowest else "这周还没有足够的数据判断卡点。"
    return """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>学习周报 · %(who)s</title>
<style>
  :root { color-scheme: light; }
  body { margin: 0; padding: 40px 24px; background: #f6f4ef; color: #1d201f;
         font: 15px/1.65 "Noto Serif SC", "Songti SC", Georgia, serif; }
  .sheet { max-width: 760px; margin: 0 auto; background: #fffdf8; border: 1px solid #e2ded2;
           padding: 40px 44px 32px; }
  h1 { font-size: 26px; margin: 0 0 4px; letter-spacing: .02em; }
  .sub { color: #6b6f6a; font-size: 13px; margin-bottom: 28px; }
  .kpi { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1px; background: #e2ded2;
         border: 1px solid #e2ded2; margin-bottom: 28px; }
  .kpi div { background: #fffdf8; padding: 14px 12px; }
  .kpi b { display: block; font: 500 26px/1.2 Georgia, serif; color: #2f5d50; }
  .kpi span { font-size: 12px; color: #6b6f6a; }
  h2 { font-size: 15px; margin: 26px 0 8px; letter-spacing: .08em; color: #2f5d50;
       text-transform: uppercase; font-family: ui-monospace, Menlo, monospace; }
  table { width: 100%%; border-collapse: collapse; font-size: 14px; }
  th, td { text-align: left; padding: 6px 8px; border-bottom: 1px dashed #e2ded2; }
  th { font-weight: 500; color: #6b6f6a; font-size: 12px; }
  td.num { text-align: right; font-variant-numeric: tabular-nums; }
  td.empty { color: #6b6f6a; text-align: center; padding: 14px; }
  .note { margin-top: 26px; padding-top: 14px; border-top: 1px solid #e2ded2;
          color: #6b6f6a; font-size: 12px; }
  @media print { body { background: #fff; padding: 0 } .sheet { border: 0 } }
</style></head><body>
<div class="sheet">
  <h1>学习周报 · %(who)s</h1>
  <p class="sub">%(from)s 至 %(to)s · %(days)d 天%(textbook)s</p>
  <div class="kpi">
    <div><b>%(sessions)d</b><span>提问次数</span></div>
    <div><b>%(messages)d</b><span>对话轮数</span></div>
    <div><b>%(new_mistakes)d</b><span>新增错题</span></div>
    <div><b>%(fixed)d</b><span>订正/掌握</span></div>
  </div>
  <h2>这周练了什么</h2>
  <p>%(subs)s。今日到期复习 <b>%(due)d</b> 个知识点。</p>
  <h2>掌握度变化</h2>
  <table><thead><tr><th>学科</th><th>知识点</th><th class="num">掌握度</th><th class="num">证据</th></tr></thead>
  <tbody>%(rows)s</tbody></table>
  <h2>写作评阅</h2>
  <p>%(writing)s</p>
  <h2>下一步</h2>
  <p>%(focus)s</p>
  <p class="note">本报告由 Lyceum 在本地生成，不含 API Key、不含完整对话原文；掌握度是 BKT 估计的概率，
  不是考试成绩。生成时间 %(now)s。</p>
</div></body></html>
""" % {"who": esc(who), "from": _fmt_day(data["from"]), "to": _fmt_day(data["to"]),
       "days": int(data["days"]), "textbook": (" · " + esc(data["textbook"])) if data.get("textbook") else "",
       "sessions": int(data["sessions"]), "messages": int(data["messages"]),
       "new_mistakes": int(data["new_mistakes"]), "fixed": int(data["fixed_mistakes"]),
       "subs": subs_txt, "due": int(data["due"]), "rows": rows, "writing": w_txt, "focus": focus,
       "now": time.strftime("%Y-%m-%d %H:%M", time.localtime(data["to"]))}
