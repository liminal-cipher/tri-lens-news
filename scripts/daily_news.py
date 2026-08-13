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
NEWS_COUNT = 3
KST = timezone(timedelta(hours=9))


# ── 뉴스 수집 ──

# urllib3가 기본으로 재시도하는 메서드. POST는 멱등하지 않아 여기 없다
RETRY_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE", "PUT", "DELETE"})


def get_session(retry_post=False):
    """재시도 로직이 포함된 requests 세션 생성"""
    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=(RETRY_METHODS | {"POST"}) if retry_post else RETRY_METHODS,
    )
    session.mount("https://", HTTPAdapter(max_retries=retries))
    return session


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


# ── Gemini API ──

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
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


def select_ai_tech_news(stories):
    """AI/테크 관련 뉴스 3개 선별"""
    titles = "\n".join(
        [f"{i+1}. [{s['source']}] {s['title']}" for i, s in enumerate(stories)]
    )
    prompt = f"""다음 뉴스 제목 목록에서 AI, 머신러닝, 테크 산업, 소프트웨어 개발과 가장 관련 있는 뉴스 {NEWS_COUNT}개를 골라줘.

{titles}

반드시 아래 JSON 형식으로만 응답해. 다른 텍스트 없이 JSON만:
[{{"index": 1}}, {{"index": 5}}, {{"index": 12}}]"""

    text = call_gemini(prompt)
    text = text.strip().removeprefix("```json").removesuffix("```").strip()
    selected = json.loads(text)

    # 모델이 같은 번호를 두 번 주면 같은 기사가 두 번 실린다. 범위 밖 번호로 자리가 비는
    # 경우도 있어서, 앞에서 3개를 자르지 않고 유효한 것만 3개 채울 때까지 훑는다
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
기사 URL: {article['url']}
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

def build_html_email(date_str, sections):
    """HTML 이메일 본문 생성"""
    articles_html = ""
    for i, (article, analysis) in enumerate(sections):
        # 제목도 모델 출력도 그대로 신뢰할 수 없다. 이스케이프를 먼저 하고 줄바꿈을 <br>로
        # 바꾼다. 순서가 뒤바뀌면 방금 넣은 <br>까지 이스케이프된다
        analysis_html = html.escape(analysis).replace("\n", "<br>")
        title = html.escape(article["title"])
        url = html.escape(article["url"])
        source = html.escape(article["source"])

        articles_html += f"""
        <div style="margin-bottom:32px; padding:20px; background:#f8f9fa; border-radius:8px;">
            <h3 style="margin:0 0 8px 0; color:#1a1a1a;">
                {i+1}. {title}
            </h3>
            <p style="margin:0 0 16px 0;">
                <a href="{url}" style="color:#0066cc; font-size:14px;">
                    원문 보기 ({source})
                </a>
            </p>
            <div style="font-size:15px; line-height:1.7; color:#333;">
                {analysis_html}
            </div>
        </div>"""

    body = f"""
    <div style="max-width:640px; margin:0 auto; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
        <div style="padding:24px 0; border-bottom:3px solid #1a1a1a; margin-bottom:24px;">
            <h1 style="margin:0; font-size:24px;">☀️ Tri-Lens 모닝 뉴스</h1>
            <p style="margin:8px 0 0 0; color:#666; font-size:14px;">
                {date_str} | 같은 뉴스, 세 가지 깊이
            </p>
        </div>
        {articles_html}
        <div style="padding:16px 0; border-top:1px solid #ddd; color:#999; font-size:12px;">
            Powered by Tri-Lens | Gemini API + GitHub Actions<br>
            매일 아침 자동 발송됩니다.
        </div>
    </div>"""
    return body


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
    print(f"=== Tri-Lens Daily News === {date_str}")

    # 1. 뉴스 수집
    print("뉴스 수집 중...")
    hn_stories = fetch_hackernews_top(15)
    gn_stories = fetch_geeknews()
    all_stories = hn_stories + gn_stories
    print(f"  HN {len(hn_stories)}개 + GN {len(gn_stories)}개")

    if len(all_stories) < 3:
        print("뉴스를 충분히 가져오지 못했습니다. 종료.", file=sys.stderr)
        sys.exit(1)

    # 2. AI/테크 뉴스 선별
    print("AI/테크 뉴스 선별 중...")
    selected = select_ai_tech_news(all_stories)
    print(f"  선별: {len(selected)}개")

    # 선별이 비면 헤더와 푸터만 든 메일이 나간다. 수집 단계와 같은 기준으로 여기서 멈춘다
    if len(selected) < NEWS_COUNT:
        print(
            f"기사를 {NEWS_COUNT}개 선별하지 못했습니다 ({len(selected)}개). 종료.",
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
    print("완료!")


if __name__ == "__main__":
    main()