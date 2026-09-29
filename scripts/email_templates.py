"""Shared, network-free HTML email rendering for Daily Brief and Concept Radar."""

import html
from urllib.parse import urlsplit

import evaluate
import email_assets


FONT_STACK = "-apple-system,BlinkMacSystemFont,'Segoe UI','Apple SD Gothic Neo','Malgun Gothic',sans-serif"
INK = "#202536"
MUTED = "#646b7b"
LINE = "#e4e6ed"
INDIGO = "#4946b8"
VIOLET = "#7350a2"
PAPER_SOURCE = "Hugging Face Papers"
TEXT_STYLE = f"margin:0;font-size:16px;line-height:1.85;color:{INK};word-break:keep-all;word-wrap:break-word;"
LABEL_STYLE = "font-size:11px;font-weight:700;letter-spacing:1.4px;line-height:1.5;"
TABLE_ATTRS = 'role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0"'


def link_url(value):
    """Escape a source URL as an attribute; never render an active non-web URL."""
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() in {"https", "http"} and parsed.netloc:
            return html.escape(value, quote=True)
    except ValueError:
        pass
    return "#"


def model_names(models):
    return ", ".join(dict.fromkeys(m.split(":", 1)[-1] for m in models)) or "언어 모델"


def render_shell(*, edition, date_str, preview, content, models, radar=False, scope_note=""):
    """Only content is trusted, internally rendered HTML. All copy is escaped here."""
    accent = VIOLET if radar else INDIGO
    scope_html = (
        f'<p style="margin:0 0 8px;font-size:12px;line-height:1.8;color:{MUTED};">{html.escape(scope_note)}</p>'
        if scope_note else ""
    )
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tri-Lens · {html.escape(edition)} · {html.escape(date_str)}</title>
<style>
  body, table, td, a {{ -webkit-text-size-adjust:100%; -ms-text-size-adjust:100%; }}
  table {{ border-collapse:collapse; mso-table-lspace:0pt; mso-table-rspace:0pt; }}
  a:focus-visible {{ outline:2px solid {accent}; outline-offset:4px; }}
  @media screen and (max-width:600px) {{
    .outer {{ padding:0 !important; }}
    .gutter {{ padding-left:24px !important; padding-right:24px !important; }}
    .masthead {{ padding-top:28px !important; }}
    .edition-title {{ font-size:32px !important; }}
    .story-title {{ font-size:23px !important; }}
    .lens-block {{ padding:16px !important; }}
  }}
</style>
</head>
<body style="margin:0;padding:0;width:100%;background-color:#f2f3f7;">
<div aria-hidden="true" style="display:none!important;font-size:1px;line-height:1px;max-height:0;max-width:0;overflow:hidden;opacity:0;mso-hide:all;">{html.escape(preview)}</div>
<table {TABLE_ATTRS} bgcolor="#f2f3f7" style="background-color:#f2f3f7;">
<tr><td class="outer" align="center" style="padding:32px 12px;">
<!--[if mso]><table role="presentation" width="680" align="center" border="0" cellspacing="0" cellpadding="0"><tr><td><![endif]-->
<table {TABLE_ATTRS} align="center" bgcolor="#ffffff" style="max-width:680px;table-layout:fixed;background-color:#ffffff;font-family:{FONT_STACK};color:{INK};">
  <tr><td style="height:4px;background-color:{accent};font-size:0;line-height:0;">&nbsp;</td></tr>
  <tr><td class="gutter masthead" style="padding:40px 48px 0;">
    <div style="font-size:24px;line-height:1.2;font-weight:800;letter-spacing:-1px;">TRI<span style="color:{accent};">/</span>LENS</div>
    <div style="margin:28px 0 0;border-top:1px solid {LINE};padding-top:24px;{LABEL_STYLE}color:{accent};">{html.escape(date_str)}</div>
    <h1 class="edition-title" style="margin:10px 0 0;padding-bottom:26px;border-bottom:1px solid {INK};font-size:40px;line-height:1.15;letter-spacing:-1.5px;font-weight:800;color:{INK};">{html.escape(edition)}</h1>
  </td></tr>
  <tr><td class="gutter" style="padding:0 48px;word-wrap:break-word;">{content}</td></tr>
  <tr><td class="gutter" style="padding:24px 48px;background-color:#fafafd;">
    {scope_html}
    <p style="margin:0;font-size:11px;line-height:1.7;color:{MUTED};">AI 해석 · {html.escape(model_names(models))}</p>
  </td></tr>
</table>
<!--[if mso]></td></tr></table><![endif]-->
</td></tr></table>
</body>
</html>"""


def render_lenses(analysis):
    bodies, order = evaluate.split_lenses(analysis.strip())
    if order != list(evaluate.LENS_MARKERS) or not all(bodies.get(m) for m in order):
        text = html.escape(analysis.strip()).replace("\n", "<br>")
        return f'<div style="{TEXT_STYLE}">{text}</div>'

    blocks = []
    backgrounds = ("#eff5ff", "#edf7f4", "#fff5e9")
    for index, marker in enumerate(order):
        label = evaluate.LENS_NAMES[marker]
        icon = label.lower()
        colour = email_assets.icon_colour(icon)
        if index:
            blocks.append('<tr aria-hidden="true"><td height="12" style="height:12px;font-size:0;line-height:0;">&nbsp;</td></tr>')
        background = backgrounds[index]
        blocks.append(f"""
        <tr><td class="lens-block" bgcolor="{background}" style="padding:18px 20px;background-color:{background};">
          <h3 style="margin:0 0 8px;{LABEL_STYLE}color:{colour};"><img src="{email_assets.icon_cid(icon)}" width="16" height="16" alt="" aria-hidden="true" style="display:inline-block;width:16px;height:16px;margin-right:8px;vertical-align:-3px;border:0;">{label.upper()}</h3>
          <p style="{TEXT_STYLE}">{html.escape(bodies[marker])}</p>
        </td></tr>""")
    return f'<table {TABLE_ATTRS} style="table-layout:fixed;">{"".join(blocks)}</table>'


def render_daily(date_str, sections, models=()):
    articles = []
    for index, (article, analysis) in enumerate(sections, start=1):
        is_paper = article["source"] == PAPER_SOURCE
        accent = VIOLET if is_paper else INDIGO
        title = html.escape(article["title"])
        url = link_url(article["url"])
        source = html.escape(article["source"])
        border = f"border-bottom:1px solid {LINE};" if index < len(sections) else ""
        articles.append(f"""
        <div style="padding:30px 0 32px;{border}">
          <table {TABLE_ATTRS} style="table-layout:fixed;"><tr>
            <td width="48" valign="top" style="width:48px;font-size:28px;line-height:1;font-weight:400;letter-spacing:-1px;color:{accent};">{index:02d}</td>
            <td valign="middle" style="font-size:12px;line-height:1.6;color:{MUTED};">{source}</td>
          </tr></table>
          <h2 class="story-title" style="margin:18px 0 24px;font-size:26px;font-weight:700;line-height:1.4;letter-spacing:-.6px;word-break:keep-all;word-wrap:break-word;">
            <a href="{url}" style="color:{INK};text-decoration:none;">{title}</a>
          </h2>
          {render_lenses(analysis)}
          <div style="margin-top:16px;"><a href="{url}" aria-label="{title} 원문 읽기" style="display:inline-block;padding:12px 0;font-size:13px;font-weight:700;line-height:20px;color:{accent};text-decoration:underline;text-underline-offset:4px;">원문 읽기 &nbsp;↗</a></div>
        </div>""")

    return render_shell(
        edition="Daily Brief", date_str=date_str,
        preview=" · ".join(a["title"] for a, _ in sections),
        content="".join(articles), models=models,
    )


def render_radar(date_str, concepts, evidence, models=(), window_days=14):
    articles = []
    for index, concept in enumerate(concepts, start=1):
        links = []
        for idx in concept["evidence_indices"]:
            item = evidence[idx]
            links.append(f"""
            <li style="margin:0;padding:10px 0;border-top:1px solid {LINE};">
              <a href="{link_url(item['url'])}" style="font-size:13px;line-height:1.7;color:{VIOLET};text-decoration:underline;text-underline-offset:3px;">{html.escape(item['title'])} ↗</a>
              <span style="display:block;margin-top:3px;font-size:11px;line-height:1.6;color:{MUTED};">{html.escape(item['source'])}</span>
            </li>""")
        border = f"border-bottom:1px solid {LINE};" if index < len(concepts) else ""
        articles.append(f"""
        <div style="padding:30px 0 32px;{border}">
          <div style="font-size:28px;line-height:1;font-weight:400;letter-spacing:-1px;color:{VIOLET};">{index:02d}</div>
          <h2 class="story-title" style="margin:12px 0 22px;font-size:28px;line-height:1.35;font-weight:700;letter-spacing:-.7px;word-wrap:break-word;color:{INK};">{html.escape(concept['term'])}</h2>
          <table {TABLE_ATTRS} style="table-layout:fixed;"><tr><td style="padding:18px 20px;background-color:#f6f3fa;">
            <p style="{TEXT_STYLE}">{html.escape(concept['definition'])}</p>
          </td></tr></table>
          <h3 style="margin:24px 0 8px;font-size:13px;line-height:1.6;color:{VIOLET};">왜 지금</h3>
          <p style="{TEXT_STYLE}">{html.escape(concept['why_now'])}</p>
          <h3 style="margin:22px 0 8px;font-size:13px;line-height:1.6;color:{VIOLET};">실무에서</h3>
          <p style="{TEXT_STYLE}">{html.escape(concept['practical_relevance'])}</p>
          <h3 style="margin:26px 0 10px;{LABEL_STYLE}color:{MUTED};">근거</h3>
          <ul style="list-style:none;margin:0;padding:0;">{''.join(links)}</ul>
        </div>""")
    return render_shell(
        edition="Concept Radar", date_str=date_str,
        preview=" · ".join(c["term"] for c in concepts),
        content="".join(articles), models=models, radar=True,
        scope_note=f"최근 {window_days}일 표본 기준 · 업계 전체 통계 아님",
    )
