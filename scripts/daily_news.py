"""
Tri-Lens Daily News
- Hacker News + GeekNews에서 AI/테크 뉴스 상위 기사를 가져옴
- Gemini API로 3가지 렌즈(Everyone/Developers/Researchers)로 해석
- Gmail SMTP로 이메일 전송
"""

import os
import json
import smtplib
import time
import requests
import feedparser
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
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
NEWS_COUNT = 3
KST = timezone(timedelta(hours=9))


# ── 뉴스 수집 ──

def get_session():
    """재시도 로직이 포함된 requests 세션 생성"""
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
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
    resp = requests.post(
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

    result = []
    for item in selected[:NEWS_COUNT]:
        idx = item["index"] - 1
        if 0 <= idx < len(stories):
            result.append(stories[idx])
    return result


def generate_trilens(article):
    """하나의 기사에 대해 3-렌즈 해석 생성"""
    prompt = f"""너는 AI/테크 뉴스 해석 봇이야. 아래 기사를 3가지 난이도 렌즈로 해석해줘.

기사 제목: {article['title']}
기사 URL: {article['url']}

다음 3가지 렌즈로 각각 2-3문장씩 한국어로 해석해:

1. 🌐 Everyone (누구나 이해할 수 있는 해석)
- 기술 배경 없는 사람도 "아, 이게 왜 중요하구나" 알 수 있게
- 일상생활이나 사회에 미치는 영향 중심
- 전문 용어 없이, 비유나 사례로 설명

2. 💻 Developers (개발자/엔지니어 관점)
- 기술적으로 무엇이 바뀌는지, 어떤 스택에 영향이 있는지
- "실제로 구현하려면?" 또는 "내 코드/워크플로우에 어떤 영향?"
- 구체적 기술명, 라이브러리, 아키텍처 언급 가능

3. 🔬 Researchers (연구자/심화 관점)
- 이 뉴스의 학술적·이론적 맥락과 의미
- 관련 논문, 선행 연구, 기술적 한계점
- 향후 연구 방향이나 열린 문제 제시

형식:

🌐 Everyone
(해석)

💻 Developers
(해석)

🔬 Researchers
(해석)"""

    return call_gemini(prompt)


# ── 이메일 전송 ──

def build_html_email(date_str, sections):
    """HTML 이메일 본문 생성"""
    articles_html = ""
    for i, (article, analysis) in enumerate(sections):
        # 줄바꿈을 <br>로, 렌즈 이모지를 볼드 처리
        analysis_html = analysis.replace("\n", "<br>")

        articles_html += f"""
        <div style="margin-bottom:32px; padding:20px; background:#f8f9fa; border-radius:8px;">
            <h3 style="margin:0 0 8px 0; color:#1a1a1a;">
                {i+1}. {article['title']}
            </h3>
            <p style="margin:0 0 16px 0;">
                <a href="{article['url']}" style="color:#0066cc; font-size:14px;">
                    원문 보기 ({article['source']})
                </a>
            </p>
            <div style="font-size:15px; line-height:1.7; color:#333;">
                {analysis_html}
            </div>
        </div>"""

    html = f"""
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
    return html


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
        print("뉴스를 충분히 가져오지 못했습니다. 종료.")
        return

    # 2. AI/테크 뉴스 선별
    print("AI/테크 뉴스 선별 중...")
    selected = select_ai_tech_news(all_stories)
    print(f"  선별: {len(selected)}개")

    # 3. 3-렌즈 해석 생성
    print("3-렌즈 해석 생성 중...")
    sections = []
    for i, article in enumerate(selected):
        print(f"  [{i+1}/{len(selected)}] {article['title']}")
        analysis = generate_trilens(article)
        sections.append((article, analysis))

    # 4. 이메일 발송
    print("이메일 발송 중...")
    subject = f"☀️ Tri-Lens 모닝 뉴스 | {date_str}"
    html_body = build_html_email(date_str, sections)
    send_email(subject, html_body)
    print("완료!")


if __name__ == "__main__":
    main()