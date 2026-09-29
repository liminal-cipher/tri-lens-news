"""Render delivered archives locally, without credentials, network calls or mail."""

import argparse
import html
import re
from pathlib import Path

import email_templates
import email_assets


ROOT_DIR = Path(__file__).resolve().parent.parent
DAILY_SECTION = re.compile(
    r"^## \d+\. (.+?)\n+원문: <([^>]+)> \(([^)]+)\)\n+(.*?)(?=^## \d+\.|^---$|\Z)",
    re.MULTILINE | re.DOTALL,
)
RADAR_SECTION = re.compile(r"^## (.+?)\n+(.*?)(?=^## |^---$|\Z)", re.MULTILINE | re.DOTALL)
EVIDENCE_LINK = re.compile(r"^- \[(.+)\]\((\S+)\) — (.+)$", re.MULTILINE)


def read_archive(path):
    text = path.read_text(encoding="utf-8")
    heading = re.search(r"^# (.+)$", text, re.MULTILINE)
    if not heading:
        raise ValueError(f"Archive date heading missing: {path}")
    return heading.group(1).strip(), text


def load_daily(path):
    date_str, text = read_archive(path)
    sections = [
        ({"title": title.strip(), "url": url.strip(), "source": source.strip()}, analysis.strip())
        for title, url, source, analysis in DAILY_SECTION.findall(text)
    ]
    if not sections or len(sections) != len(re.findall(r"^## ", text, re.MULTILINE)):
        raise ValueError(f"Incomplete or unrecognised daily archive: {path}")
    model_match = re.search(r"^(.+?) 호출 \d+건", text, re.MULTILINE)
    models = model_match.group(1).split(", ") if model_match else []
    return date_str, sections, models


def load_radar(path):
    date_str, text = read_archive(path)
    concepts, evidence = [], {}
    for term, body in RADAR_SECTION.findall(text):
        concept = {"term": term.strip(), "evidence_indices": []}
        for label, key in (("한 줄 정의", "definition"), ("왜 지금", "why_now"), ("실무에서", "practical_relevance")):
            field = re.search(rf"\*\*{label}:\*\*\s*(.*?)(?=\n\n\*\*|\n###|\Z)", body, re.DOTALL)
            if not field or not field.group(1).strip():
                raise ValueError(f"Missing {label} in {term}: {path}")
            concept[key] = field.group(1).strip()
        for title, url, source in EVIDENCE_LINK.findall(body):
            idx = len(evidence) + 1
            evidence[idx] = {"title": title, "url": url, "source": source}
            concept["evidence_indices"].append(idx)
        if not concept["evidence_indices"]:
            raise ValueError(f"Missing evidence in {term}: {path}")
        concepts.append(concept)
    if not concepts:
        raise ValueError(f"No concepts found: {path}")
    model_match = re.search(r"모델: (.+)\.$", text, re.MULTILINE)
    models = model_match.group(1).split(", ") if model_match else []
    window = re.search(r"최근 (\d+)일", text)
    if not window:
        raise ValueError(f"Missing sampling window: {path}")
    return date_str, concepts, evidence, models, int(window.group(1))


def latest_archive(directory):
    files = sorted(directory.glob("????-??-??.md"))
    if not files:
        raise ValueError(f"No delivered archives in {directory}")
    return files[-1]


def render_viewer(daily_name, radar_name):
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tri-Lens · Email Preview</title>
<style>
  * {{ box-sizing:border-box; }}
  body {{ margin:0;background:#e9ebf1;color:#202536;font-family:{email_templates.FONT_STACK}; }}
  header {{ background:white;border-bottom:1px solid #dfe2eb;padding:20px 28px; }}
  .toolbar {{ display:flex;gap:24px;align-items:center;flex-wrap:wrap;max-width:1200px;margin:auto; }}
  h1 {{ margin:0 auto 0 0;font-size:18px;letter-spacing:-.5px; }}
  h1 span {{ color:#4946b8; }}
  h1 small {{ margin-left:10px;font-size:12px;letter-spacing:0;font-weight:400;color:#646b7b; }}
  label {{ font-size:12px;color:#646b7b;display:flex;align-items:center;gap:8px; }}
  select,a {{ font:inherit; }}
  select {{ padding:8px;border:1px solid #dfe2eb;border-radius:6px;color:#202536;background:white; }}
  a {{ color:#4946b8;font-size:13px;text-underline-offset:4px; }}
  .hint {{ max-width:1200px;margin:14px auto 0;font-size:12px;line-height:1.7;color:#646b7b; }}
  main {{ padding:24px 12px; }}
  iframe {{ display:block;width:760px;max-width:100%;height:calc(100vh - 180px);min-height:480px;margin:0 auto;border:1px solid #dfe2eb;background:white;box-shadow:0 12px 36px #20253612; }}
  @media(max-width:600px) {{ header {{ padding:18px; }} .toolbar {{ gap:12px; }} h1 {{ width:100%; }} main {{ padding:12px 0; }} iframe {{ height:calc(100vh - 220px);border:0; }} }}
</style>
</head>
<body>
<header>
  <div class="toolbar">
    <h1>TRI<span>/</span>LENS <small>Email preview</small></h1>
    <label>에디션 <select id="edition"><option value="daily.html">Daily Brief</option><option value="radar.html">Concept Radar</option></select></label>
    <label>화면 <select id="size"><option value="760">Desktop</option><option value="390">Mobile · 390px</option><option value="320">Small · 320px</option></select></label>
    <a id="open" href="daily.html" target="_blank" rel="noopener">메일만 열기 ↗</a>
  </div>
  <p class="hint">발송된 아카이브로 보는 로컬 미리보기 · Daily: {html.escape(daily_name)} · Radar: {html.escape(radar_name)}<br>실제 메일은 전송되지 않습니다. 메일 앱과 다크 모드에서는 표시가 달라질 수 있습니다.</p>
</header>
<main><iframe id="preview" title="Daily Brief 이메일 미리보기" src="daily.html"></iframe></main>
<script>
  const edition = document.getElementById('edition');
  const preview = document.getElementById('preview');
  edition.addEventListener('change', () => {{
    preview.src = edition.value;
    preview.title = edition.options[edition.selectedIndex].text + ' 이메일 미리보기';
    document.getElementById('open').href = edition.value;
  }});
  document.getElementById('size').addEventListener('change', event => {{
    preview.style.width = event.target.value + 'px';
  }});
</script>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--daily", type=Path, help="Daily archive markdown (default: latest)")
    parser.add_argument("--radar", type=Path, help="Concept archive markdown (default: latest)")
    parser.add_argument("--output-dir", type=Path, default=ROOT_DIR / "preview", help="Generated HTML directory")
    args = parser.parse_args()
    try:
        daily_path = args.daily or latest_archive(ROOT_DIR / "archive")
        radar_path = args.radar or latest_archive(ROOT_DIR / "concepts")
        daily = email_assets.preview_html(email_templates.render_daily(*load_daily(daily_path)))
        radar = email_assets.preview_html(email_templates.render_radar(*load_radar(radar_path)))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in (
        ("daily.html", daily), ("radar.html", radar),
        ("index.html", render_viewer(daily_path.name, radar_path.name)),
    ):
        (args.output_dir / name).write_text(content, encoding="utf-8")
    print(f"Preview: {(args.output_dir / 'index.html').resolve()}")


if __name__ == "__main__":
    main()
