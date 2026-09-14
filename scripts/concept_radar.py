"""
Tri-Lens Concept Radar
- 최근 14일의 고신호 Hacker News 기사, 현재 GeekNews 피드, 실제 발송 archive를 표본으로 삼음
- 반복되거나 새롭게 등장한 AI engineering 용어 1~3개를 주간 단위로 추림
- 원문/아카이브 근거로 개념을 설명하고 Gmail SMTP로 발송
"""

import html
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import daily_news


WINDOW_DAYS = 14
HISTORY_DAYS = 90
HN_MIN_POINTS = 30
HN_LIMIT = 250
MAX_TERMS = 3
MAX_EVIDENCE_PER_TERM = 3
MAX_ARCHIVE_EXCERPT_CHARS = 900

ROOT_DIR = Path(__file__).resolve().parent.parent
ARCHIVE_DIR = ROOT_DIR / "archive"
CONCEPT_DIR = ROOT_DIR / "concepts"

ARCHIVE_SECTION = re.compile(
    r"^## \d+\. (.+?)\n+원문: <([^>]+)> \(([^)]+)\)\n+(.*?)(?=^## \d+\.|^---$|\Z)",
    re.MULTILINE | re.DOTALL,
)
CONCEPT_HEADING = re.compile(r"^## (.+?)\s*$", re.MULTILINE)


def fetch_hn_recent(now=None):
    """최근 WINDOW_DAYS 동안 일정 점수 이상을 받은 HN story 제목을 가져온다."""
    now = now or datetime.now(daily_news.KST)
    since = int((now - timedelta(days=WINDOW_DAYS)).timestamp())
    session = daily_news.get_session()
    try:
        resp = session.get(
            "https://hn.algolia.com/api/v1/search_by_date",
            params={
                "tags": "story",
                "numericFilters": f"created_at_i>{since},points>={HN_MIN_POINTS}",
                "hitsPerPage": HN_LIMIT,
            },
            headers={"User-Agent": daily_news.USER_AGENT},
            timeout=20,
        )
        resp.raise_for_status()
        hits = resp.json().get("hits") or []
    except Exception as e:
        print(f"  ⚠ HN 최근 기사 가져오기 실패: {e}", file=sys.stderr)
        return []

    stories = []
    for hit in hits:
        title = (hit.get("title") or "").strip()
        url = (hit.get("url") or "").strip()
        if not title or not url:
            continue
        stories.append(
            {
                "title": title,
                "url": url,
                "source": "Hacker News",
                "score": hit.get("points") or 0,
                "date": (hit.get("created_at") or "")[:10],
                "excerpt": "",
            }
        )

    stories.sort(key=lambda x: x["score"], reverse=True)
    return stories[:HN_LIMIT]


def read_recent_archive(now=None):
    """최근 발송 archive를 Radar 표본으로 읽는다."""
    now = now or datetime.now(daily_news.KST)
    items = []
    for back in range(WINDOW_DAYS):
        date_iso = (now - timedelta(days=back)).strftime("%Y-%m-%d")
        path = ARCHIVE_DIR / f"{date_iso}.md"
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for title, url, source, analysis in ARCHIVE_SECTION.findall(text):
            excerpt = " ".join(analysis.split())[:MAX_ARCHIVE_EXCERPT_CHARS]
            items.append(
                {
                    "title": title.strip(),
                    "url": url.strip(),
                    "source": f"Delivered digest / {source.strip()}",
                    "score": 0,
                    "date": date_iso,
                    "excerpt": excerpt,
                }
            )
    return items


def current_geeknews():
    """현재 GeekNews RSS를 Radar 표본 모양으로 맞춘다."""
    result = []
    for story in daily_news.fetch_geeknews():
        result.append({**story, "date": "", "excerpt": ""})
    return result


def merge_samples(*groups):
    """같은 URL은 하나로 합친다. archive 항목을 먼저 넘기면 richer excerpt가 남는다."""
    result = []
    seen = set()
    for group in groups:
        for item in group:
            key = daily_news.normalize_url(item["url"])
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
    return result


def recent_terms(now=None):
    """최근 HISTORY_DAYS 안에 이미 Radar로 보낸 용어."""
    now = now or datetime.now(daily_news.KST)
    terms = []
    for back in range(HISTORY_DAYS):
        path = CONCEPT_DIR / f"{(now - timedelta(days=back)).strftime('%Y-%m-%d')}.md"
        if not path.exists():
            continue
        terms.extend(t.strip() for t in CONCEPT_HEADING.findall(path.read_text(encoding="utf-8")))
    return list(dict.fromkeys(terms))


def _strip_json_fence(text):
    text = text.strip()
    if text.startswith("```json"):
        text = text[len("```json") :]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _sample_block(samples):
    lines = []
    for i, item in enumerate(samples, start=1):
        meta = item["source"]
        if item.get("date"):
            meta += f" · {item['date']}"
        if item.get("score"):
            meta += f" · {item['score']} points"
        lines.append(f"{i}. [{meta}] {item['title']}")
        if item.get("excerpt"):
            lines.append(f"   발송 해석: {item['excerpt']}")
    return "\n".join(lines)


def nominate_terms(samples, covered_terms):
    """제목/발송 해석 표본에서 Radar 후보를 고른다."""
    covered = ", ".join(covered_terms) if covered_terms else "없음"
    prompt = f"""<role>
너는 AI engineering vocabulary scout다. 뉴스 자체를 요약하지 말고, 최근 기술 대화에서 알아두면 좋은 재사용 가능한 개념어를 찾는다.
</role>

<sample_scope>
아래 목록은 최근 {WINDOW_DAYS}일의 Hacker News 고신호 story, 현재 GeekNews RSS, 그리고 같은 기간 실제 발송된 Tri-Lens digest에서 모은 표본이다. 이 표본은 업계 전체의 완전한 통계가 아니다.
</sample_scope>

<task>
아래 표본에서 이번 주에 알아둘 가치가 있는 AI/ML/software engineering 용어를 0~{MAX_TERMS}개 고른다.
</task>

<constraints>
- 회사명, 제품명, 모델명, 버전명, 단일 뉴스 사건은 고르지 않는다.
- 다른 기사와 문서에서도 다시 쓰일 수 있는 개념, 아키텍처 패턴, 평가/운영 용어여야 한다.
- AI, LLM, agent, RAG, GPU, API, transformer, prompt engineering, fine-tuning, inference처럼 이미 너무 넓고 기본적인 말은 제외한다.
- 최근 표본에서 둘 이상의 독립 항목에 반복되면 우선한다.
- 한 항목에서만 보여도, 그 항목이 일반화 가능한 새 용어를 명시적으로 다루고 있고 실무 대화에서 다시 만날 가능성이 높으면 후보가 될 수 있다.
- 제목이나 발송 해석에 근거가 없는 용어를 모델 지식만으로 추가하지 않는다.
- 지난 {HISTORY_DAYS}일 안에 이미 Radar에서 다룬 용어는 반복하지 않는다: {covered}
- 억지로 개수를 채우지 않는다. 가치 있는 용어가 없으면 []를 반환한다.
</constraints>

<candidates>
{_sample_block(samples)}
</candidates>

<output_format>
JSON 배열만 출력한다. 각 항목은 아래 모양이다.
[{{"term":"agent harness","evidence_indices":[12,44]}}]
term은 검색 가능한 영어 원어로 쓰고, evidence_indices는 위 candidates의 1-based 번호만 쓴다.
</output_format>"""

    raw = daily_news.call_model(prompt)
    data = json.loads(_strip_json_fence(raw))
    if not isinstance(data, list):
        raise ValueError("Radar 후보 출력이 JSON 배열이 아니다")

    result = []
    seen_terms = set()
    for row in data:
        if not isinstance(row, dict):
            continue
        term = str(row.get("term") or "").strip()
        indices = row.get("evidence_indices") or []
        if not term or term.lower() in seen_terms or not isinstance(indices, list):
            continue
        valid = []
        for value in indices:
            try:
                idx = int(value)
            except (TypeError, ValueError):
                continue
            if 1 <= idx <= len(samples) and idx not in valid:
                valid.append(idx)
        if not valid:
            continue
        seen_terms.add(term.lower())
        result.append({"term": term, "evidence_indices": valid[:MAX_EVIDENCE_PER_TERM]})
        if len(result) == MAX_TERMS:
            break
    return result


def hydrate_evidence(samples, nominations):
    """후보가 가리킨 기사만 원문을 가져온다. archive 항목은 이미 발송 해석을 쓴다."""
    hydrated = {}
    needed = sorted({idx for row in nominations for idx in row["evidence_indices"]})
    for idx in needed:
        item = dict(samples[idx - 1])
        text = item.get("excerpt") or ""
        if not text:
            print(f"  근거 원문 가져오는 중: {item['title'][:60]}")
            text = daily_news.fetch_article_body(item["url"])
        item["evidence_text"] = text
        hydrated[idx] = item
    return hydrated


def explain_terms(nominations, evidence):
    """선별된 용어를 원문/발송 해석 근거로 검증하고 설명한다."""
    blocks = []
    for row in nominations:
        blocks.append(f"TERM: {row['term']}")
        for idx in row["evidence_indices"]:
            item = evidence[idx]
            body = (item.get("evidence_text") or "").strip()
            if not body:
                body = "(본문을 확보하지 못해 제목만 근거로 사용할 수 있음)"
            blocks += [
                f"EVIDENCE {idx}: {item['title']}",
                f"SOURCE: {item['source']} / {item['url']}",
                f"TEXT: {body}",
            ]
        blocks.append("")

    prompt = f"""<role>
너는 Tri-Lens Concept Radar 편집자다. 사용자가 AI engineering 대화에서 새 용어를 처음 듣고 멈추지 않도록, 근거가 있는 개념만 짧게 설명한다.
</role>

<task>
아래 후보 용어와 근거를 검토해 실제로 근거가 충분한 항목만 남기고 한국어로 설명한다.
</task>

<constraints>
- definition: 용어 자체의 뜻을 한 문장으로 설명한다.
- why_now: 왜 이번 표본에서 이 용어를 지금 집어야 하는지 1~2문장으로 설명한다.
- practical_relevance: 개발자나 AI/ML 엔지니어가 이 말을 어디서 만나고 무엇을 구분할 때 유용한지 한 문장으로 쓴다.
- 표본을 업계 전체 통계처럼 과장하지 않는다. 반복을 말할 때는 '최근 표본에서'처럼 범위를 밝힌다.
- 근거가 제목뿐이고 일반 개념인지 확신할 수 없거나, 단순 제품/마케팅 명칭에 가깝다면 그 항목은 버린다.
- evidence_indices는 제공된 번호 중 실제 설명을 뒷받침하는 것만 남긴다.
- 모델 지식으로 근거를 새로 만들어내지 않는다.
- 가치 있는 항목이 하나도 없으면 []를 반환한다.
</constraints>

<evidence>
{chr(10).join(blocks)}
</evidence>

<output_format>
JSON 배열만 출력한다.
[{{
  "term":"agent harness",
  "definition":"...",
  "why_now":"...",
  "practical_relevance":"...",
  "evidence_indices":[12,44]
}}]
</output_format>"""

    raw = daily_news.call_model(prompt)
    data = json.loads(_strip_json_fence(raw))
    if not isinstance(data, list):
        raise ValueError("Radar 설명 출력이 JSON 배열이 아니다")

    allowed = {row["term"].lower(): row for row in nominations}
    result = []
    for row in data:
        if not isinstance(row, dict):
            continue
        term = str(row.get("term") or "").strip()
        key = term.lower()
        if key not in allowed:
            continue
        definition = str(row.get("definition") or "").strip()
        why_now = str(row.get("why_now") or "").strip()
        practical = str(row.get("practical_relevance") or "").strip()
        if not (definition and why_now and practical):
            continue
        allowed_indices = set(allowed[key]["evidence_indices"])
        indices = []
        for value in row.get("evidence_indices") or []:
            try:
                idx = int(value)
            except (TypeError, ValueError):
                continue
            if idx in allowed_indices and idx in evidence and idx not in indices:
                indices.append(idx)
        if not indices:
            continue
        result.append(
            {
                "term": term,
                "definition": definition,
                "why_now": why_now,
                "practical_relevance": practical,
                "evidence_indices": indices[:MAX_EVIDENCE_PER_TERM],
            }
        )
        if len(result) == MAX_TERMS:
            break
    return result


def build_html_email(date_str, concepts, evidence):
    cards = []
    for concept in concepts:
        links = []
        for idx in concept["evidence_indices"]:
            item = evidence[idx]
            title = html.escape(item["title"])
            url = html.escape(item["url"], quote=True)
            source = html.escape(item["source"])
            links.append(
                f'<li style="margin:0 0 6px 0;"><a href="{url}" style="color:#0969da;text-decoration:none;">{title}</a> '
                f'<span style="color:#8c959f;">— {source}</span></li>'
            )
        cards.append(
            f"""
        <div style="margin:0 0 24px 0;padding:20px;background:#f6f8fa;border:1px solid #e1e4e8;border-radius:10px;">
            <div style="font-size:20px;font-weight:800;color:#1f2328;margin:0 0 14px 0;">{html.escape(concept['term'])}</div>
            <div style="font-size:12px;font-weight:700;color:#656d76;margin:0 0 4px 0;">한 줄 정의</div>
            <div style="font-size:15px;line-height:1.75;color:#1f2328;margin:0 0 14px 0;">{html.escape(concept['definition'])}</div>
            <div style="font-size:12px;font-weight:700;color:#656d76;margin:0 0 4px 0;">왜 지금</div>
            <div style="font-size:15px;line-height:1.75;color:#1f2328;margin:0 0 14px 0;">{html.escape(concept['why_now'])}</div>
            <div style="font-size:12px;font-weight:700;color:#656d76;margin:0 0 4px 0;">실무에서</div>
            <div style="font-size:15px;line-height:1.75;color:#1f2328;margin:0 0 14px 0;">{html.escape(concept['practical_relevance'])}</div>
            <div style="font-size:12px;font-weight:700;color:#656d76;margin:0 0 6px 0;">근거</div>
            <ul style="font-size:13px;line-height:1.5;margin:0;padding-left:20px;">{''.join(links)}</ul>
        </div>"""
        )

    preview = html.escape(" · ".join(c["term"] for c in concepts))
    used = ", ".join(dict.fromkeys(m.split(":", 1)[-1] for m in daily_news.models_used)) or "언어 모델"
    return f"""
    <div style="display:none;max-height:0;overflow:hidden;opacity:0;">{preview}</div>
    <div style="max-width:640px;margin:0 auto;padding:8px;font-family:{daily_news.FONT_STACK};">
        <div style="padding:20px 0 16px 0;border-bottom:2px solid #1f2328;margin:0 0 24px 0;">
            <div style="font-size:22px;font-weight:800;color:#1f2328;">🧭 Tri-Lens Concept Radar</div>
            <div style="margin:8px 0 0 0;color:#656d76;font-size:13px;">{date_str} · 최근 {WINDOW_DAYS}일 표본에서 건질 개념어</div>
        </div>
        {''.join(cards)}
        <div style="padding:16px 0 8px 0;border-top:1px solid #e1e4e8;color:#8c959f;font-size:12px;line-height:1.6;">
            이 Radar는 업계 전체 통계가 아니라 Hacker News·GeekNews·실제 발송 digest의 표본을 읽습니다.<br>
            {html.escape(used)} + GitHub Actions로 주 1회 자동 발송됩니다.
        </div>
    </div>"""


def write_archive(date_iso, date_str, concepts, evidence, counts):
    CONCEPT_DIR.mkdir(exist_ok=True)
    path = CONCEPT_DIR / f"{date_iso}.md"
    parts = [
        f"# {date_str}",
        "",
        f"> 최근 {WINDOW_DAYS}일 표본에서 반복되거나 새롭게 등장한 AI engineering 용어. 업계 전체 빈도 통계가 아니라 탐색용 Radar다.",
        "",
    ]
    for concept in concepts:
        parts += [
            f"## {concept['term']}",
            "",
            f"**한 줄 정의:** {concept['definition']}",
            "",
            f"**왜 지금:** {concept['why_now']}",
            "",
            f"**실무에서:** {concept['practical_relevance']}",
            "",
            "### 근거",
            "",
        ]
        for idx in concept["evidence_indices"]:
            item = evidence[idx]
            parts.append(f"- [{item['title']}]({item['url']}) — {item['source']}")
        parts.append("")

    models = ", ".join(dict.fromkeys(daily_news.models_used)) or "-"
    parts += [
        "---",
        "",
        f"표본: Hacker News {counts['hn']}건, GeekNews {counts['geeknews']}건, delivered archive {counts['archive']}건. 모델: {models}.",
    ]
    path.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    print(f"Concept Radar 기록 → concepts/{date_iso}.md")

    env_path = os.environ.get("GITHUB_ENV")
    if env_path:
        with open(env_path, "a", encoding="utf-8") as f:
            f.write(f"RADAR_DATE={date_iso}\n")


def main():
    now = datetime.now(daily_news.KST)
    date_str = now.strftime("%Y년 %m월 %d일")
    date_iso = now.strftime("%Y-%m-%d")
    print(f"=== Tri-Lens Concept Radar === {date_str}")

    print("주간 표본 수집 중...")
    archive_items = read_recent_archive(now)
    hn_items = fetch_hn_recent(now)
    geek_items = current_geeknews()
    samples = merge_samples(archive_items, hn_items, geek_items)
    print(f"  delivered archive {len(archive_items)}건")
    print(f"  Hacker News {len(hn_items)}건")
    print(f"  GeekNews {len(geek_items)}건")
    print(f"  URL 중복 제거 후 {len(samples)}건")

    if not samples:
        print("표본을 하나도 가져오지 못했습니다. 종료.", file=sys.stderr)
        sys.exit(1)

    covered = recent_terms(now)
    print(f"최근 {HISTORY_DAYS}일 Radar 기등록 용어 {len(covered)}개")

    print("개념 후보 선별 중...")
    nominations = nominate_terms(samples, covered)
    if not nominations:
        print("이번 주에 새로 보낼 만한 개념어가 없습니다. 메일을 보내지 않습니다.")
        return
    for row in nominations:
        print(f"  {row['term']} ← {row['evidence_indices']}")

    print("근거 확인 중...")
    evidence = hydrate_evidence(samples, nominations)

    print("개념 설명 생성 중...")
    concepts = explain_terms(nominations, evidence)
    if not concepts:
        print("근거 확인 뒤 남은 개념어가 없습니다. 메일을 보내지 않습니다.")
        return

    print("이메일 발송 중...")
    subject = f"🧭 Tri-Lens Concept Radar | {date_str}"
    daily_news.send_email(subject, build_html_email(date_str, concepts, evidence))

    counts = {"hn": len(hn_items), "geeknews": len(geek_items), "archive": len(archive_items)}
    write_archive(date_iso, date_str, concepts, evidence, counts)
    print("완료!")


if __name__ == "__main__":
    main()
