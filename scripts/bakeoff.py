"""
모델 bake-off
- 같은 기사 하나를 여러 모델에 물려 3-렌즈 해석을 나란히 놓는다
- 두 단계다. freeze가 그날의 입력(기사 + 본문)을 파일로 얼리고, run이 그 파일을 읽어
  모델마다 해석을 만든다. 매번 새로 수집하면 모델이 아니라 그날 뉴스를 비교하게 된다
- 형식은 evaluate.check가 공짜로 가른다. 문장이 좋은지는 사람이 읽어야 하고, 그래서
  사람이 읽는 파일에는 모델 이름을 적지 않는다 (docs/evaluation.md)

    python scripts/bakeoff.py freeze
    python scripts/bakeoff.py run --models gemini:gemini-3.6-flash,groq
"""

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime

import daily_news as dn
import evaluate

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BAKEOFF_DIR = os.path.join(REPO_DIR, "bakeoff")
INPUTS_DIR = os.path.join(BAKEOFF_DIR, "inputs")
RESULTS_DIR = os.path.join(BAKEOFF_DIR, "results")

# 블라인드 읽기용 라벨. 모델 하나에 하나씩 고정으로 붙는다
LABELS = "ABCDEFGH"


def load_dotenv():
    """repo 루트의 .env를 읽어 환경변수로 올린다. 없으면 아무 일도 안 한다.

    이건 손으로 돌리는 실험 도구라 로컬에서 키를 받을 길이 필요하다. Actions에는 .env가
    없으니 그쪽에서는 그냥 지나간다. 이미 설정된 값은 덮지 않는다.
    라이브러리를 하나 더 붙일 만한 일이 아니다
    """
    path = os.path.join(REPO_DIR, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def today_iso():
    return datetime.now(dn.KST).strftime("%Y-%m-%d")


# ── 입력 얼리기 ──


def freeze(path):
    """그날의 기사와 본문을 파일로 얼린다.

    선별도 모델 호출이지만 비교 대상이 아니므로 한 모델로 한 번만 하고 그 결과를 고정한다.
    후보 목록이 모델마다 다르면 렌즈 문장이 아니라 기사 고르는 취향을 비교하게 된다
    """
    print("뉴스 수집 중...")
    counts = {
        "Hacker News": dn.fetch_hackernews_top(15),
        "GeekNews": dn.fetch_geeknews(),
        "Hugging Face Papers": dn.fetch_hf_papers(),
    }
    for name, items in counts.items():
        print(f"  {name} {len(items)}건")

    news = counts["Hacker News"] + counts["GeekNews"]
    if len(news) < dn.NEWS_COUNT:
        print("뉴스를 충분히 가져오지 못했습니다. 종료.", file=sys.stderr)
        sys.exit(1)

    print("선별 중...")
    selected = dn.select_ai_tech_news(news) + dn.select_papers(counts["Hugging Face Papers"])
    wanted = dn.NEWS_COUNT + dn.PAPER_COUNT
    if len(selected) < wanted:
        print(f"기사를 {wanted}개 선별하지 못했습니다 ({len(selected)}개). 종료.", file=sys.stderr)
        sys.exit(1)

    print("원문 가져오는 중...")
    for article in selected:
        if not article.get("body"):
            print(f"  {article['title'][:50]}")
            article["body"] = dn.fetch_article_body(article["url"])

    # 선별에 쓴 모델을 함께 남긴다. 나중에 결과만 보고 "이 기사들은 누가 골랐나"를
    # 되짚을 수 있어야 한다
    payload = {
        "date": today_iso(),
        "selector": dn.models_used[0] if dn.models_used else "-",
        "articles": [
            {k: a.get(k, "") for k in ("title", "url", "source", "body")} for a in selected
        ],
    }

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    with_body = sum(1 for a in payload["articles"] if a["body"])
    print(f"입력 {len(payload['articles'])}건 (본문 {with_body}건) → {path}")


# ── 비교 실행 ──


def parse_models(spec):
    """"gemini:gemini-3.6-flash,groq" 를 (provider, model) 목록으로.

    모델 이름을 생략하면 그 프로바이더의 기본 모델을 쓴다. 환경변수 쪽 모델 설정은
    여기서 읽지 않는다. 비교 실행에서 무엇을 불렀는지는 명령줄에만 적혀 있어야 한다
    """
    models = []
    for item in spec.split(","):
        item = item.strip()
        if not item:
            continue
        provider, _, model = item.partition(":")
        if provider not in dn.PROVIDERS:
            known = ", ".join(dn.PROVIDERS)
            raise SystemExit(f"모르는 프로바이더: {provider} (아는 것: {known})")
        models.append((provider, model or dn.PROVIDERS[provider][2]))
    if not models:
        raise SystemExit("--models가 비었다")
    return models


def load_inputs(paths):
    """얼린 입력 파일들을 읽어 기사 목록 하나로 편다"""
    articles = []
    for path in paths:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        for article in payload["articles"]:
            article["frozen_on"] = payload["date"]
            articles.append(article)
    if not articles:
        raise SystemExit("입력이 비었다. 먼저 freeze를 돌려라")
    return articles


def run(models, articles, delay):
    """기사마다 모델을 전부 돌린다.

    바깥이 기사, 안쪽이 모델이다. 같은 모델을 연달아 부르지 않게 되어 분당 토큰 한도에
    덜 걸린다. 한 칸이 죽어도 나머지는 남긴다. 429 하나에 그날 비교가 통째로 날아가면
    성공한 호출까지 버리는 셈이다
    """
    rows = []
    for i, article in enumerate(articles):
        print(f"[{i+1}/{len(articles)}] {article['title'][:60]}")
        for provider, model in models:
            name = f"{provider}:{model}"
            print(f"    {name}")
            record = {
                "article": i,
                "provider": provider,
                "model": model,
                "analysis": "",
                "error": "",
                "violations": [],
                "fillers": {},
            }
            try:
                # 재생성하지 않는다. 형식을 지키는 능력 자체가 비교 대상이라, 되먹여
                # 고치게 하면 모델 차이가 재시도 뒤로 숨는다. 운영 경로는 1회 재생성한다
                analysis = dn.generate_trilens(article, provider=provider, model=model)
                record["analysis"] = analysis
                record["violations"] = evaluate.check(analysis)
                record["fillers"] = evaluate.count_fillers(analysis)
                mark = "통과" if not record["violations"] else "; ".join(record["violations"])
                print(f"      {mark}")
            except Exception as e:
                record["error"] = f"{type(e).__name__}: {e}"
                print(f"      호출 실패: {record['error']}", file=sys.stderr)
            rows.append(record)
            if delay:
                time.sleep(delay)
    return rows


# ── 결과 쓰기 ──


def unique_path(directory, date, ext):
    """같은 날 두 번 돌려도 앞의 결과를 덮어쓰지 않는다"""
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{date}.{ext}")
    n = 2
    while os.path.exists(path):
        path = os.path.join(directory, f"{date}-{n}.{ext}")
        n += 1
    return path


def label_of(models):
    """모델마다 라벨 하나. 붙는 순서는 이름의 해시로 정한다.

    명령줄에 적은 순서대로 붙이면, 그 명령이 남아 있는 곳에서는 대응이 그대로 드러난다.
    첫 실행에서 실제로 그렇게 샜다. 라벨은 리포트 하나 안에서만 유효하고 후보가 바뀌면
    달라진다. 대응은 언제나 JSON에 있다
    """
    names = [f"{p}:{m}" for p, m in models]
    order = sorted(names, key=lambda n: hashlib.md5(n.encode()).hexdigest())
    return {n: LABELS[i] for i, n in enumerate(order)}


def render_report(models, articles, rows, date):
    """사람이 읽는 파일. 모델 이름은 여기 없다.

    라벨은 모델마다 고정이라 여러 기사를 가로질러 같은 모델을 따라 읽을 수 있고,
    표시 순서는 기사마다 한 칸씩 돌린다. 늘 같은 자리에 오는 출력이 좋아 보이는 것을
    막으려는 것이다
    """
    labels = label_of(models)
    by_article = {}
    for r in rows:
        by_article.setdefault(r["article"], []).append(r)

    n = len(models)
    calls = len(rows)
    failed = sum(1 for r in rows if r["error"])

    lines = [
        f"# 모델 비교 {date}",
        "",
        f"기사 {len(articles)}건 × 모델 {n}개 = 호출 {calls}건"
        + (f", 실패 {failed}건" if failed else "")
        + ".",
        "",
        "재생성 없이 첫 출력만 실었다. 라벨과 모델의 대응은 같은 이름의 JSON에 있다.",
        "",
        "| 라벨 | 형식 통과 | 호출 실패 | 반복 표현 |",
        "| --- | --- | --- | --- |",
    ]

    # 표는 라벨 순으로 읽는다. 모델 순으로 돌면 행 차례가 명령줄 순서를 다시 알려준다
    for name, label in sorted(labels.items(), key=lambda kv: kv[1]):
        provider, _, model = name.partition(":")
        mine = [r for r in rows if r["provider"] == provider and r["model"] == model]
        done = [r for r in mine if not r["error"]]
        passed = sum(1 for r in done if not r["violations"])
        fillers = {}
        for r in done:
            for k, v in r["fillers"].items():
                fillers[k] = fillers.get(k, 0) + v
        filler_text = ", ".join(f"{k} {v}" for k, v in fillers.items()) or "-"
        errors = len(mine) - len(done)
        lines.append(f"| {label} | {passed}/{len(done)} | {errors or '-'} | {filler_text} |")

    for i, article in enumerate(articles):
        body_len = len(article.get("body") or "")
        lines += [
            "",
            f"## {i+1}. {article['title']}",
            "",
            f"원문: <{article['url']}> ({article['source']}) · "
            + (f"본문 {body_len:,}자" if body_len else "본문 없음")
            + f" · {article.get('frozen_on', date)} 수집",
        ]
        # 표시 순서만 한 칸씩 돌린다. 라벨은 따라 움직인다
        shown = by_article.get(i, [])
        shown = shown[i % n:] + shown[:i % n] if shown else shown
        for r in shown:
            lines += ["", f"### {labels[r['provider'] + ':' + r['model']]}", ""]
            if r["error"]:
                lines.append(f"호출 실패: {r['error']}")
                continue
            lines.append(r["analysis"].strip())
            if r["violations"]:
                lines += ["", f"형식 위반: {'; '.join(r['violations'])}"]

    return "\n".join(lines).rstrip() + "\n"


def write_results(models, articles, rows, date):
    md_path = unique_path(RESULTS_DIR, date, "md")
    json_path = os.path.splitext(md_path)[0] + ".json"

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_report(models, articles, rows, date))

    # 기계가 읽는 쪽. 라벨-모델 대응표가 여기 있다. 본문은 담지 않는다. 공개 repo에
    # 남의 기사 전문을 커밋하는 것이 되고, 길이만 있으면 나중에 갈라 보는 데 충분하다
    payload = {
        "date": date,
        "labels": label_of(models),
        "articles": [
            {
                "title": a["title"],
                "url": a["url"],
                "source": a["source"],
                "body_chars": len(a.get("body") or ""),
                "frozen_on": a.get("frozen_on", date),
            }
            for a in articles
        ],
        "results": rows,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"결과 → {md_path}")
    print(f"     → {json_path}")
    return md_path


# ── CLI ──


def main():
    # 이건 로컬에서 손으로 돌리는 도구다. Windows 콘솔 기본 코드페이지(cp949)는 이모지를
    # 못 찍어서, 기사 제목에 하나만 들어가도 실험이 출력 단계에서 통째로 죽는다
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")

    # 키는 호출 직전에 읽히므로(_require_key) import 순서를 신경 쓸 필요가 없다
    load_dotenv()

    parser = argparse.ArgumentParser(description="모델 bake-off")
    sub = parser.add_subparsers(dest="command", required=True)

    p_freeze = sub.add_parser("freeze", help="그날의 입력을 파일로 얼린다")
    p_freeze.add_argument("--out", default=None)

    p_run = sub.add_parser("run", help="얼린 입력으로 모델을 비교한다")
    p_run.add_argument("--models", required=True, help="쉼표 목록. 예: gemini,groq:llama-3.3-70b-versatile")
    p_run.add_argument("--inputs", nargs="*", default=None, help="얼린 입력 파일. 비우면 bakeoff/inputs 전부")
    p_run.add_argument("--delay", type=float, default=0, help="호출 사이 대기 초. 분당 토큰 한도가 빡빡할 때")

    args = parser.parse_args()
    date = today_iso()

    if args.command == "freeze":
        freeze(args.out or os.path.join(INPUTS_DIR, f"{date}.json"))
        return

    paths = args.inputs
    if not paths:
        if not os.path.isdir(INPUTS_DIR):
            raise SystemExit(f"{INPUTS_DIR}가 없다. 먼저 freeze를 돌려라")
        paths = sorted(
            os.path.join(INPUTS_DIR, f) for f in os.listdir(INPUTS_DIR) if f.endswith(".json")
        )

    models = parse_models(args.models)
    articles = load_inputs(paths)
    print(f"입력 {len(articles)}건, 모델 {len(models)}개 → 호출 {len(articles) * len(models)}건")
    rows = run(models, articles, args.delay)
    write_results(models, articles, rows, date)


if __name__ == "__main__":
    main()
