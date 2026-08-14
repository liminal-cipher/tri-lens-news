"""
Tri-Lens Daily News
- Hacker News + GeekNews에서 AI/테크 뉴스 상위 기사를 가져옴
- 언어 모델로 3가지 렌즈(Everyone/Developers/Researchers)로 해석
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
import trafilatura
import evaluate
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ── 설정 ──
GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
RECIPIENTS = os.environ["RECIPIENTS"].split(",")  # 쉼표로 구분된 이메일 목록
# 미설정 변수는 빈 문자열로 넘어오므로 get의 기본값이 아니라 or로 받는다.
# 모델 API 키는 여기서 읽지 않는다. 실제로 부르는 프로바이더의 것만 확인한다 (_require_key)
LLM_PROVIDER = os.environ.get("LLM_PROVIDER") or "gemini"
# GEMINI_MODEL은 이전 이름이다. 이미 repo variable로 설정돼 있을 수 있어 계속 읽는다
LLM_MODEL = os.environ.get("LLM_MODEL") or os.environ.get("GEMINI_MODEL")
# 뉴스 2건 + 논문 1건. 논문 자리를 고정해두지 않으면 제목 경쟁에서 뉴스가 늘 이겨서
# Researchers 렌즈에 줄 재료가 영영 안 들어온다
NEWS_COUNT = 2
PAPER_COUNT = 1
KST = timezone(timedelta(hours=9))

# 자기를 밝히는 UA. 기본 python-requests UA는 위키백과 등에서 403이 나고, Chrome을 사칭하는
# 것보다 무엇이 왜 긁는지 알리는 쪽이 맞다
USER_AGENT = "tri-lens-news/1.0 (+https://github.com/liminal-cipher/tri-lens-news)"
# 30건을 재보니 중앙값 3120자, 최대 27409자였다. 긴 쪽은 잘라야 요점이 묻히지 않는다
MAX_BODY_CHARS = 6000
MIN_BODY_CHARS = 500


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


def fetch_article_body(url):
    """기사 원문에서 본문 텍스트를 뽑는다. 실패하면 빈 문자열.

    선별이 끝난 뒤 2건만 가져온다. 후보 30건을 미리 다 가져와 본문이 있는 것 위주로
    고르면 봇을 막는 사이트의 기사가 조용히 빠지는데, 그건 편집 방침을 기술 사정으로
    바꾸는 것이다
    """
    try:
        resp = requests.get(
            url, timeout=20, headers={"User-Agent": USER_AGENT}, allow_redirects=True
        )
        if resp.status_code != 200:
            print(f"      본문 실패: HTTP {resp.status_code}")
            return ""
        if "html" not in (resp.headers.get("Content-Type") or ""):
            print("      본문 실패: HTML이 아님")
            return ""
        text = (trafilatura.extract(resp.text) or "").strip()
    except Exception as e:
        print(f"      본문 실패: {type(e).__name__}")
        return ""

    if len(text) < MIN_BODY_CHARS:
        print(f"      본문 실패: 너무 짧음 ({len(text)}자)")
        return ""
    if len(text) > MAX_BODY_CHARS:
        text = text[:MAX_BODY_CHARS]
    return text


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


# ── 모델 프로바이더 ──

# 프로바이더마다 다른 것은 주소·헤더·보내는 모양·받는 모양 넷뿐이다. 아래 표에 한 항목을
# 더하면 호출하는 쪽 코드는 손대지 않아도 된다


def _require_key(name):
    """실제로 부르는 프로바이더의 키만 확인한다.

    모듈 최상단에서 전부 확인하면, Groq을 쓰지 않는 정기 실행이 GROQ_API_KEY가 없다는
    이유로 import 시점에 죽는다
    """
    key = os.environ.get(name)
    if not key:
        raise RuntimeError(f"{name}가 설정되지 않았다. 이 프로바이더를 쓰려면 필요하다")
    return key


def _gemini(model, prompt):
    """Gemini. 키를 URL 쿼리가 아니라 헤더로 보낸다.

    requests가 던지는 예외 메시지와 재시도 로그에는 URL이 통째로 들어간다. 키를 거기
    두면 실패할 때마다 따라 나가므로, 마스킹에 기대는 대신 헤더로 옮긴다
    """
    return (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        {"Content-Type": "application/json", "x-goog-api-key": _require_key("GEMINI_API_KEY")},
        {"contents": [{"parts": [{"text": prompt}]}]},
    )


def _openai_compatible(base, key_name):
    """Groq·OpenRouter 등이 공유하는 모양. 주소와 키 이름만 다르다"""

    def build(model, prompt):
        return (
            f"{base}/chat/completions",
            {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {_require_key(key_name)}",
            },
            {"model": model, "messages": [{"role": "user", "content": prompt}]},
        )

    return build


PROVIDERS = {
    # 이름: (요청 만들기, 응답에서 본문 꺼내기, 기본 모델)
    "gemini": (
        _gemini,
        lambda d: d["candidates"][0]["content"]["parts"][0]["text"],
        "gemini-3.6-flash",
    ),
    "groq": (
        _openai_compatible("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
        lambda d: d["choices"][0]["message"]["content"],
        # 한 번 실행이 7~9K 토큰이라 TPM 8K인 gpt-oss-120b는 가끔 넘긴다
        "llama-3.3-70b-versatile",
    ),
}

# 호출별로 쓴 재시도 횟수. 하루치를 모아 로그와 아카이브에 남긴다
model_retries = []
# 그날 실제로 부른 모델. 지금은 한 실행에 하나뿐이지만, 모델을 갈아끼운 날이
# 아카이브에서 구별되지 않으면 나중에 채점할 때 서로 다른 모델의 출력이 한 표본으로
# 뭉친다. 비교 실행처럼 한 실행에 여럿이 섞이는 경우도 그대로 남는다
models_used = []


def call_model(prompt, provider=None, model=None):
    """모델 호출. 프로바이더가 갈리는 자리는 여기 하나뿐이다"""
    provider = provider or LLM_PROVIDER
    if provider not in PROVIDERS:
        known = ", ".join(PROVIDERS)
        raise RuntimeError(f"모르는 프로바이더: {provider} (아는 것: {known})")
    build, extract, default_model = PROVIDERS[provider]
    # provider만 넘기고 model을 비우면 그 프로바이더의 기본값을 쓴다. 환경변수 쪽 모델은
    # 기본 프로바이더에만 해당한다. 안 그러면 groq에 gemini 모델 이름이 넘어간다
    model = model or (LLM_MODEL if provider == LLM_PROVIDER else None) or default_model
    url, headers, body = build(model, prompt)

    # 생성 호출은 부수효과가 없으므로 POST여도 재시도해 안전하다.
    # 재시도가 없던 동안 5xx 한 번에 그날 발송이 통째로 날아갔다
    session = get_session(retry_post=True)
    resp = session.post(url, headers=headers, json=body, timeout=60)

    used, codes = retries_used(resp)
    model_retries.append(used)
    models_used.append(f"{provider}:{model}")
    if used:
        seen = ", ".join(str(c) for c in codes) or "연결 오류"
        print(f"      재시도 {used}/{RETRY_TOTAL}회 후 성공 (받은 응답: {seen})")

    # 어떤 한도에 걸렸는지는 응답 본문에만 적혀 있다. raise_for_status가 던지는 메시지에는
    # 상태 코드와 URL뿐이라, 여기서 찍지 않으면 분당인지 하루치인지 토큰 한도인지 모른 채로
    # 추측하게 된다. 실제로 429를 두 번 맞고도 어느 한도인지 못 가렸다.
    # 본문에 키는 없다. 키는 헤더에만 있고 헤더는 찍지 않는다
    if not resp.ok:
        # 429 본문은 QuotaFailure와 RetryInfo가 붙어 400대보다 길다. 짧게 자르면
        # 정작 필요한 quota 이름이 잘려나간다
        print(f"      HTTP {resp.status_code}: {resp.text[:2000]}", file=sys.stderr)

    resp.raise_for_status()
    return extract(resp.json())


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

    text = call_model(prompt)
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
- 세 렌즈는 서로 다른 세 사람이 아니라 한 사람이 위에서 아래로 읽는다. 뒤 칸은 앞 칸을
  전제로 쓰고, 앞 칸에서 쉬운 말로 풀어둔 것을 뒤 칸에서 제 이름으로 부른다.
- 단 그것을 말로 알리지 마라. 앞 칸을 가리키지 말고 그 이름을 그냥 쓰기 시작하면 된다.
  "앞서 언급한", "앞의", "앞에서 말한", "방금 다룬", "이러한", "위에서 다룬" 같은
  지시 표현으로 렌즈를 시작하는 것을 금지한다. 독자는 세 줄 위를 이미 읽었다.
- Everyone: 전문 용어 없이 무슨 일인지. 일상 영향 중심.
- Developers: Everyone이 풀어 쓴 것에 이름을 붙이고, 어떻게 동작하는지와 쓸 때의 대가로 넘어간다.
- Researchers: 앞 두 칸을 전제로, 아직 안 풀린 것이나 갈라내지 못한 것을 짚는다.
- 전문 용어는 영어 원어로 적는다. 한글 음차 금지 (셀프 컨시스턴시 X, self-consistency O).
- 괄호 풀이는 그 분야를 모르면 못 알아볼 용어에만, 처음 나올 때 한 번만 붙인다.
  한 렌즈에 두 개를 넘기지 않는다. weight, GPU, VRAM, API처럼 이미 널리 쓰이는 말은 풀지 않는다.
- 같은 용어를 한 글 안에서 두 가지로 표기하지 않는다.
- "마치 ~처럼", "덕분에", "~될 것입니다" 패턴 반복 금지.
- 마크다운 문법(#, **, ```, - 등) 사용 금지. 순수 텍스트와 이모지만 사용.
</constraints>

<example>
기사: "OpenAI releases GPT-5"

🌐 Everyone
답을 바로 내놓지 않고 속으로 여러 번 따져본 뒤 가장 그럴듯한 것을 고르는 방식으로 바뀌었습니다. 그래서 계산이나 논리를 다루는 질문에서 틀리는 일이 눈에 띄게 줄었습니다.

💻 Developers
test-time compute(답을 만드는 시점에 연산을 더 쓰는 것)를 늘린 것이라, 응답이 늦어지고 토큰 비용이 붙는 대가가 따릅니다. 그래서 프로덕션에서는 요청마다 이 방식을 켤지 말지 고르는 라우팅이 사실상 필수가 됩니다.

🔬 Researchers
성능이 오른 것이 test-time compute 때문인지 사전학습 규모가 커진 덕인지가 아직 갈라지지 않았습니다. 두 요인을 분리하려면 같은 모델에서 연산량만 바꿔가며 재는 ablation이 필요합니다.
</example>

<output_format>
🌐 Everyone
(2문장)

💻 Developers
(2문장)

🔬 Researchers
(2문장)
</output_format>{retry_block}"""

    return call_model(prompt)


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

    # 푸터에 벤더 이름을 박아두면 모델을 바꾼 날부터 조용히 거짓이 된다. 그날 실제로
    # 부른 모델을 읽어서 쓴다. 프로바이더 접두사는 독자에게 의미가 없어 떼고 이름만 남긴다
    used = ", ".join(dict.fromkeys(m.split(":", 1)[-1] for m in models_used)) or "언어 모델"

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
            {html.escape(used)} + GitHub Actions로 매일 아침 자동 발송됩니다.
        </div>
    </div>"""
    return body


# ── 아카이브 ──

ARCHIVE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "archive")


def run_stats(reports, counts, sections):
    """그날 run이 어떻게 굴러갔는지 두 줄로 요약한다"""
    calls = len(model_retries)
    used = sum(model_retries)
    # 하루에 한 모델만 쓰면 이름 하나, 섞이면 쓴 순서대로 전부 적는다
    models = ", ".join(dict.fromkeys(models_used)) or "-"
    passed = sum(1 for r in reports if not r["violations"])
    regenerated = sum(1 for r in reports if r["regenerated"])
    with_body = sum(1 for article, _ in sections if (article.get("body") or "").strip())
    sourced = ", ".join(f"{name} {len(items)}건" for name, items in counts.items())
    return (
        f"후보: {sourced}. "
        f"본문 확보 {with_body}/{len(sections)}건.\n"
        f"{models} 호출 {calls}건, 재시도 {used}회 (건당 예산 {RETRY_TOTAL}회). "
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

    # 3. 뉴스 원문 본문 확보. 논문은 초록이 이미 붙어 있다
    print("원문 가져오는 중...")
    for article in selected:
        if article.get("body"):
            continue
        print(f"  {article['title'][:50]}")
        article["body"] = fetch_article_body(article["url"])

    # 4. 3-렌즈 해석 생성
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

    # 5. 발송 전 검증 결과 기록
    evaluate.write_summary(reports)

    # 6. 이메일 발송
    print("이메일 발송 중...")
    subject = f"☀️ Tri-Lens 모닝 뉴스 | {date_str}"
    html_body = build_html_email(date_str, sections)
    send_email(subject, html_body)

    # 7. 보낸 것만 남긴다. 발송이 실패한 날의 해석은 아무한테도 안 갔으므로 기록도 아니다
    stats = run_stats(reports, counts, sections)
    print(stats)
    write_archive(date_iso, date_str, sections, stats)
    print("완료!")


if __name__ == "__main__":
    main()