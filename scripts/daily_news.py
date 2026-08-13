"""
Tri-Lens Daily News
- Hacker News + GeekNews에서 AI/테크 뉴스 상위 기사를 가져옴
- Gemini API로 3가지 렌즈(Everyone/Developers/Researchers)로 해석
- Gmail SMTP로 이메일 전송
"""

import os
import html
import json
import smtplib
import sys
import time
import requests
import feedparser
import evaluate
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ── 설정 ──
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
RECIPIENTS = os.environ["RECIPIENTS"].split(",")  # 쉼표로 구분된 이메일 목록
# 미설정 변수는 빈 문자열로 넘어오므로 get의 기본값이 아니라 or로 받는다
GEMINI_MODEL = os.environ.get("GEMINI_MODEL") or "gemini-3.6-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
# 뉴스 2건 + 논문 1건. 논문 자리를 고정해두지 않으면 제목 경쟁에서 뉴스가 늘 이겨서
# Researchers 렌즈에 줄 재료가 영영 안 들어온다
NEWS_COUNT = 2
PAPER_COUNT = 1
KST = timezone(timedelta(hours=9))


# ── 뉴스 수집 ──

# urllib3가 기본으로 재시도하는 메서드. POST는 멱등하지 않아 여기 없다
RETRY_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE", "PUT", "DELETE"})
RETRY_TOTAL = 3


def get_session(retry_post=False):
    """재시도 로직이 포함된 requests 세션 생성"""
    session = requests.Session()
    retries = Retry(
        total=RETRY_TOTAL,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=(RETRY_METHODS | {"POST"}) if retry_post else RETRY_METHODS,
    )
    session.mount("https://", HTTPAdapter(max_retries=retries))
    return session


def retries_used(resp):
    """이 응답을 받기까지 쓴 재시도 횟수와 그때 받은 상태 코드.

    재시도는 urllib3가 우리 코드 아래에서 조용히 처리하고 끝난 뒤 성공한 응답만
    넘겨준다. 몇 번 걸렸는지는 응답에 붙어 오는 이력에만 남으므로, 여기서 꺼내지
    않으면 간신히 성공한 날과 한 번에 성공한 날이 로그에서 구별되지 않는다
    """
    history = getattr(getattr(resp.raw, "retries", None), "history", None) or ()
    return len(history), [h.status for h in history if h.status]


def fetch_hackernews_top(limit=15):
    """Hacker News 상위 스토리 가져오기 (실패 시 빈 리스트 반환)"""
    session = get_session()
    try:
        top_ids = session.get(
            "https://hacker-news.firebaseio.com/v0/topstories.json", timeout=15
        ).json()[:limit]
    except Exception as e:
        print(f"  ⚠ HN 목록 가져오기 실패: {e}")
        return []

    stories = []
    for sid in top_ids:
        try:
            item = session.get(
                f"https://hacker-news.firebaseio.com/v0/item/{sid}.json", timeout=15
            ).json()
            if item and item.get("type") == "story" and item.get("url"):
                stories.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "score": item.get("score", 0),
                    "source": "Hacker News",
                })
        except Exception:
            continue  # 개별 항목 실패는 무시하고 다음으로
    return stories


def fetch_geeknews():
    """GeekNews RSS 피드 가져오기 (실패 시 빈 리스트 반환)"""
    try:
        feed = feedparser.parse("https://news.hada.io/rss")
        stories = []
        for entry in feed.entries[:15]:
            stories.append({
                "title": entry.get("title", ""),
                "url": entry.get("link", ""),
                "score": 0,
                "source": "GeekNews",
            })
        return stories
    except Exception as e:
        print(f"  ⚠ GeekNews 가져오기 실패: {e}")
        return []


def fetch_hf_papers(limit=10):
    """Hugging Face Daily Papers (실패 시 빈 리스트 반환).

    사람이 추려 올린 것만 모이고 추천수가 붙는다. arXiv 원본 피드는 한 카테고리에서만
    하루 수백 편이 쏟아져 고를 근거가 없다.
    초록이 함께 오므로 이 소스는 원문을 따로 가져올 필요가 없다
    """
    session = get_session()
    try:
        items = session.get(
            "https://huggingface.co/api/daily_papers", timeout=20
        ).json()
    except Exception as e:
        print(f"  ⚠ HF Papers 가져오기 실패: {e}")
        return []

    papers = []
    for item in items:
        paper = item.get("paper") or {}
        title = (paper.get("title") or "").strip()
        paper_id = paper.get("id") or ""
        if not title or not paper_id:
            continue
        papers.append({
            "title": title,
            "url": f"https://arxiv.org/abs/{paper_id}",
            "score": paper.get("upvotes") or 0,
            "source": "Hugging Face Papers",
            "body": (paper.get("summary") or "").strip(),
        })

    papers.sort(key=lambda p: p["score"], reverse=True)
    return papers[:limit]


# ── Gemini API ──

# 호출별로 쓴 재시도 횟수. 하루치를 모아 로그와 아카이브에 남긴다
gemini_retries = []


def call_gemini(prompt):
    """Gemini API 호출 (공통 함수)"""
    # generateContent는 부수효과가 없으므로 POST여도 재시도해 안전하다.
    # 재시도가 없던 동안 5xx 한 번에 그날 발송이 통째로 날아갔다
    session = get_session(retry_post=True)
    resp = session.post(
        GEMINI_URL,
        headers={"Content-Type": "application/json"},
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=60,
    )

    used, codes = retries_used(resp)
    gemini_retries.append(used)
    if used:
        seen = ", ".join(str(c) for c in codes) or "연결 오류"
        print(f"      재시도 {used}/{RETRY_TOTAL}회 후 성공 (받은 응답: {seen})")

    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


def select_papers(papers):
    """논문은 모델에 묻지 않고 추천수 상위로 고른다.

    후보가 이미 사람 손으로 추려진 데다 추천수라는 신호가 붙어 있어서, 제목만 보고
    고르는 모델 호출을 하나 더 얹을 이유가 없다
    """
    return papers[:PAPER_COUNT]


def select_ai_tech_news(stories):
    """AI/테크 관련 뉴스 선별"""
    titles = "\n".join(
        [f"{i+1}. [{s['source']}] {s['title']}" for i, s in enumerate(stories)]
    )
    prompt = f"""다음 뉴스 제목 목록에서 AI, 머신러닝, 테크 산업, 소프트웨어 개발과 가장 관련 있는 뉴스 {NEWS_COUNT}개를 골라줘.

{titles}

같은 사건을 다룬 항목이 여러 개 있으면 그중 하나만 고르고 나머지는 버려라.

반드시 아래 JSON 형식으로만 응답해. 다른 텍스트 없이 JSON만:
[{{"index": 1}}, {{"index": 5}}]"""

    text = call_gemini(prompt)
    text = text.strip().removeprefix("```json").removesuffix("```").strip()
    selected = json.loads(text)

    # 모델이 같은 번호를 두 번 주면 같은 기사가 두 번 실린다. 범위 밖 번호로 자리가 비는
    # 경우도 있어서, 앞에서 잘라내지 않고 유효한 것만 필요한 수만큼 채울 때까지 훑는다
    result = []
    seen = set()
    for item in selected:
        idx = item["index"] - 1
        if 0 <= idx < len(stories) and idx not in seen:
            seen.add(idx)
            result.append(stories[idx])
        if len(result) == NEWS_COUNT:
            break
    return result


def generate_trilens(article, violations=None):
    """하나의 기사에 대해 3-렌즈 해석 생성.

    violations가 있으면 직전 출력이 어긴 제약을 프롬프트에 되먹여 재생성한다
    """
    # 본문이 있으면 넣는다. 없으면 모델은 제목만 보고 쓰게 되고, 그건 해석이 아니라 추측이다
    body = (article.get("body") or "").strip()
    body_block = f"\n기사 본문:\n{body}" if body else ""

    retry_block = ""
    if violations:
        joined = "\n".join(f"- {v}" for v in violations)
        retry_block = f"""

<previous_attempt_errors>
직전 출력이 아래 제약을 어겼다. 같은 실수를 반복하지 마라.
{joined}
</previous_attempt_errors>"""

    prompt = f"""<role>
너는 AI/테크 뉴스 해석 봇이다.
</role>

<task>
아래 기사를 3단계 렌즈(Everyone, Developers, Researchers)로 해석하라.
기사 제목: {article['title']}
기사 URL: {article['url']}{body_block}
</task>

<constraints>
- 서두, 인사말, 요약 문장 금지. 바로 🌐부터 시작.
- 각 렌즈 정확히 2문장. 높임말(합니다/습니다) 사용.
- Everyone: 전문 용어 없이. 일상 영향 중심.
- Developers: 구체적 기술명/스택 포함. 구현 관점.
- Researchers: 관련 연구 방향 또는 열린 문제 제시.
- "마치 ~처럼", "덕분에", "~될 것입니다" 패턴 반복 금지.
- 세 렌즈가 서로 다른 문장 구조를 사용할 것.
- 마크다운 문법(#, **, ```, - 등) 사용 금지. 순수 텍스트와 이모지만 사용.
</constraints>

<example>
기사: "OpenAI releases GPT-5"

🌐 Everyone
AI 챗봇이 이제 더 복잡한 질문에도 정확하게 답할 수 있게 되었습니다. 고객 상담, 교육, 의료 분야에서 사람 수준의 응답이 가능해지면서 일상적으로 접하는 AI 서비스 품질이 눈에 띄게 달라질 것으로 보입니다.

💻 Developers
컨텍스트 윈도우가 1M 토큰으로 확장되면서 RAG 파이프라인 설계가 단순해집니다. 다만 API 비용이 기존 대비 2배 이상이라 프로덕션 배포 시 캐싱 전략과 모델 라우팅 설계가 필수적입니다.

🔬 Researchers
GPT-5의 추론 성능 향상이 단순 스케일링에서 비롯된 것인지 아키텍처 변경에서 온 것인지가 핵심 질문입니다. 특히 chain-of-thought 없이도 수학 추론이 개선되었다는 점은 implicit reasoning 메커니즘에 대한 후속 연구가 필요한 부분입니다.
</example>

<output_format>
🌐 Everyone
(2문장)

💻 Developers
(2문장)

🔬 Researchers
(2문장)
</output_format>{retry_block}"""

    return call_gemini(prompt)


# ── 이메일 전송 ──

FONT_STACK = "-apple-system,BlinkMacSystemFont,'Segoe UI','Apple SD Gothic Neo',sans-serif"
PAPER_SOURCE = "Hugging Face Papers"


def render_lenses(analysis):
    """세 렌즈를 각각의 블록으로 그린다.

    규격을 벗어난 출력이면 원문을 그대로 보여준다. 발송을 막지 않기로 한 이상,
    깨진 출력도 읽을 수 있는 형태로는 나가야 한다
    """
    bodies, order = evaluate.split_lenses(analysis.strip())
    usable = len(order) == len(evaluate.LENS_MARKERS) and all(bodies.get(m) for m in order)

    if not usable:
        text = html.escape(analysis.strip()).replace("\n", "<br>")
        return f'<div style="font-size:15px;line-height:1.75;color:#1f2328;">{text}</div>'

    blocks = []
    for i, marker in enumerate(order):
        label = evaluate.LENS_NAMES[marker]
        text = html.escape(bodies[marker])
        gap = "0" if i == len(order) - 1 else "0 0 18px 0"
        blocks.append(
            f'<div style="margin:{gap};padding:0 0 0 14px;border-left:3px solid #d0d7de;">'
            f'<div style="font-size:12px;font-weight:700;letter-spacing:.06em;'
            f'text-transform:uppercase;color:#656d76;margin:0 0 6px 0;">'
            f'{marker} {label}</div>'
            f'<div style="font-size:15px;line-height:1.75;color:#1f2328;">{text}</div>'
            f'</div>'
        )
    return "".join(blocks)


def build_html_email(date_str, sections):
    """HTML 이메일 본문 생성"""
    articles_html = ""
    for i, (article, analysis) in enumerate(sections):
        # 제목도 모델 출력도 그대로 신뢰할 수 없다. 반드시 이스케이프를 거친다
        title = html.escape(article["title"])
        url = html.escape(article["url"])
        source = html.escape(article["source"])
        is_paper = article["source"] == PAPER_SOURCE
        badge = "#8250df" if is_paper else "#0969da"

        articles_html += f"""
        <div style="margin:0 0 28px 0;padding:20px;background:#f6f8fa;border:1px solid #e1e4e8;border-radius:10px;">
            <div style="font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:{badge};margin:0 0 10px 0;">
                {source}
            </div>
            <div style="margin:0 0 16px 0;">
                <a href="{url}" style="font-size:18px;font-weight:700;line-height:1.4;color:#0969da;text-decoration:none;">
                    {i+1}. {title}
                </a>
            </div>
            {render_lenses(analysis)}
        </div>"""

    # 받은편지함 목록에 제목 옆으로 보이는 미리보기 문구
    preview = html.escape(" · ".join(a["title"] for a, _ in sections))

    body = f"""
    <div style="display:none;max-height:0;overflow:hidden;opacity:0;">{preview}</div>
    <div style="max-width:640px;margin:0 auto;padding:8px;font-family:{FONT_STACK};">
        <div style="padding:20px 0 16px 0;border-bottom:2px solid #1f2328;margin:0 0 24px 0;">
            <div style="font-size:22px;font-weight:800;color:#1f2328;">☀️ Tri-Lens 모닝 뉴스</div>
            <div style="margin:8px 0 0 0;color:#656d76;font-size:13px;">
                {date_str} · 같은 소식, 세 가지 깊이
            </div>
        </div>
        {articles_html}
        <div style="padding:16px 0 8px 0;border-top:1px solid #e1e4e8;color:#8c959f;font-size:12px;line-height:1.6;">
            Gemini API + GitHub Actions로 매일 아침 자동 발송됩니다.
        </div>
    </div>"""
    return body


# ── 아카이브 ──

ARCHIVE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "archive")


def run_stats(reports, counts, sections):
    """그날 run이 어떻게 굴러갔는지 두 줄로 요약한다"""
    calls = len(gemini_retries)
    used = sum(gemini_retries)
    passed = sum(1 for r in reports if not r["violations"])
    regenerated = sum(1 for r in reports if r["regenerated"])
    with_body = sum(1 for article, _ in sections if (article.get("body") or "").strip())
    sourced = ", ".join(f"{name} {len(items)}건" for name, items in counts.items())
    return (
        f"후보: {sourced}. "
        f"본문 확보 {with_body}/{len(sections)}건.\n"
        f"Gemini 호출 {calls}건, 재시도 {used}회 (건당 예산 {RETRY_TOTAL}회). "
        f"검증 {passed}/{len(reports)} 통과, 재생성 {regenerated}건."
    )


def write_archive(date_iso, date_str, sections, stats):
    """발송한 내용을 archive/YYYY-MM-DD.md 에 남긴다.

    파이프라인이 만든 결과물은 지금까지 메일로만 나가고 아무 데도 남지 않았다.
    나중에 해석 품질을 평가하려면 채점할 뭉치가 있어야 하고, 그 뭉치가 여기다
    """
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    path = os.path.join(ARCHIVE_DIR, f"{date_iso}.md")

    parts = [f"# {date_str}", ""]
    for i, (article, analysis) in enumerate(sections):
        parts += [
            f"## {i+1}. {article['title']}",
            "",
            f"원문: <{article['url']}> ({article['source']})",
            "",
            analysis.strip(),
            "",
        ]

    # run 로그는 90일 뒤 사라진다. 그날 파이프라인이 어떤 상태였는지는 여기에만 영구히 남는다
    parts += ["---", "", stats]

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts).rstrip() + "\n")
    print(f"아카이브 기록 → archive/{date_iso}.md")

    # 커밋 메시지에 쓰도록 날짜를 워크플로로 넘긴다
    env_path = os.environ.get("GITHUB_ENV")
    if env_path:
        with open(env_path, "a", encoding="utf-8") as f:
            f.write(f"ARCHIVE_DATE={date_iso}\n")


def send_email(subject, html_body):
    """Gmail SMTP로 이메일 전송"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = ", ".join(RECIPIENTS)
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, RECIPIENTS, msg.as_string())
    print(f"이메일 전송 완료 → {', '.join(RECIPIENTS)}")


# ── 메인 ──

def main():
    now = datetime.now(KST)
    date_str = now.strftime("%Y년 %m월 %d일")
    date_iso = now.strftime("%Y-%m-%d")
    print(f"=== Tri-Lens Daily News === {date_str}")

    # 1. 수집
    print("뉴스 수집 중...")
    counts = {
        "Hacker News": fetch_hackernews_top(15),
        "GeekNews": fetch_geeknews(),
        "Hugging Face Papers": fetch_hf_papers(),
    }
    for name, items in counts.items():
        print(f"  {name} {len(items)}건")

    # 소스 하나가 0건이어도 나머지로 메일이 나간다. 그 자체는 맞는 동작이지만, 아무 말도
    # 없으면 소스가 영영 죽어도 알 길이 없다. 열 주 동안 몰랐던 장애와 같은 모양이다
    dead = [name for name, items in counts.items() if not items]
    if dead:
        print(f"  ⚠ 0건인 소스: {', '.join(dead)}", file=sys.stderr)

    news = counts["Hacker News"] + counts["GeekNews"]
    papers = counts["Hugging Face Papers"]

    if len(news) < NEWS_COUNT:
        print("뉴스를 충분히 가져오지 못했습니다. 종료.", file=sys.stderr)
        sys.exit(1)

    # 2. 선별
    print("선별 중...")
    selected = select_ai_tech_news(news) + select_papers(papers)
    for article in selected:
        print(f"  [{article['source']}] {article['title'][:55]}")

    # 선별이 비면 헤더와 푸터만 든 메일이 나간다. 수집 단계와 같은 기준으로 여기서 멈춘다
    wanted = NEWS_COUNT + PAPER_COUNT
    if len(selected) < wanted:
        print(
            f"기사를 {wanted}개 선별하지 못했습니다 ({len(selected)}개). 종료.",
            file=sys.stderr,
        )
        sys.exit(1)

    # 3. 3-렌즈 해석 생성
    print("3-렌즈 해석 생성 중...")
    sections = []
    reports = []
    for i, article in enumerate(selected):
        print(f"  [{i+1}/{len(selected)}] {article['title']}")
        analysis = generate_trilens(article)

        # 제약 위반은 한 번만 되먹여 재생성한다. 그래도 어기면 기록하고 그대로 보낸다.
        # 해석 하나가 규격에서 벗어난 것이 그날 메일을 통째로 거르는 것보다 낫다
        violations = evaluate.check(analysis)
        regenerated = bool(violations)
        if violations:
            print(f"      제약 위반 {len(violations)}건, 재생성: {'; '.join(violations)}")
            analysis = generate_trilens(article, violations)
            violations = evaluate.check(analysis)
            if violations:
                print(f"      재생성 후에도 위반: {'; '.join(violations)}")

        reports.append({
            "title": article["title"],
            "violations": violations,
            "regenerated": regenerated,
            "fillers": evaluate.count_fillers(analysis),
        })
        sections.append((article, analysis))

    # 4. 발송 전 검증 결과 기록
    evaluate.write_summary(reports)

    # 5. 이메일 발송
    print("이메일 발송 중...")
    subject = f"☀️ Tri-Lens 모닝 뉴스 | {date_str}"
    html_body = build_html_email(date_str, sections)
    send_email(subject, html_body)

    # 6. 보낸 것만 남긴다. 발송이 실패한 날의 해석은 아무한테도 안 갔으므로 기록도 아니다
    stats = run_stats(reports, counts, sections)
    print(stats)
    write_archive(date_iso, date_str, sections, stats)
    print("완료!")


if __name__ == "__main__":
    main()