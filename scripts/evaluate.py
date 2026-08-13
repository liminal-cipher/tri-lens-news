"""
발송 전 검증
- 생성된 3-렌즈 해석이 프롬프트 제약을 지켰는지 확인한다
- LLM 판정이 아니라 결정적 규칙이다. 호출 비용이 0이고 같은 입력에 같은 결과가 나온다
- 원문 대조(faithfulness)는 여기서 하지 않는다. 파이프라인이 모델에 제목만 넘기므로
  대조할 본문이 애초에 없다
"""

import os
import re

LENS_MARKERS = ("🌐", "💻", "🔬")
LENS_NAMES = {"🌐": "Everyone", "💻": "Developers", "🔬": "Researchers"}
SENTENCES_PER_LENS = 2

# 프롬프트가 금지한 마크다운 문법. 순수 텍스트만 나와야 Gmail이 그대로 렌더한다
MARKDOWN_MARKERS = ("**", "##", "```")

# 프롬프트가 반복을 금지한 표현. 한 번 쓰인 것은 위반이 아니므로 개수만 세어 기록한다
FILLER_PATTERNS = ("마치", "덕분에", "될 것입니다")

# 마침표 뒤에 공백이나 문장 끝이 와야 문장 경계로 센다. "0.739" 같은 소수는 걸리지 않는다
SENTENCE_END = re.compile(r"[.!?](?=\s|$)")


def split_lenses(analysis):
    """해석 텍스트를 렌즈별 본문으로 쪼갠다. 등장 순서를 함께 돌려준다"""
    bodies = {}
    order = []
    current = None
    for line in analysis.splitlines():
        line = line.strip()
        if not line:
            continue
        marker = next((m for m in LENS_MARKERS if line.startswith(m)), None)
        if marker:
            current = marker
            bodies[marker] = []
            order.append(marker)
            continue
        if current:
            bodies[current].append(line)
    return {m: " ".join(lines) for m, lines in bodies.items()}, order


def check(analysis):
    """제약 위반 목록을 돌려준다. 빈 목록이면 통과"""
    violations = []
    text = analysis.strip()

    if not text.startswith(LENS_MARKERS[0]):
        violations.append("서두가 붙었다 (🌐로 시작하지 않음)")

    bodies, order = split_lenses(text)

    missing = [LENS_NAMES[m] for m in LENS_MARKERS if m not in bodies]
    if missing:
        violations.append(f"렌즈 누락: {', '.join(missing)}")

    if order and order != [m for m in LENS_MARKERS if m in bodies]:
        violations.append("렌즈 순서가 다르다")

    for marker in LENS_MARKERS:
        if marker not in bodies:
            continue  # 누락은 위에서 이미 잡았다
        body = bodies[marker]
        # 머리말만 있고 본문이 없는 출력을 통과시키지 않는다. 빈 문자열을 falsy로 걸러내면
        # 0문장으로 세는 게 아니라 검사 자체를 건너뛰어 빈 해석이 그대로 발송된다
        if not body:
            violations.append(f"{LENS_NAMES[marker]} 본문이 비었다")
            continue
        count = len(SENTENCE_END.findall(body))
        if count != SENTENCES_PER_LENS:
            violations.append(f"{LENS_NAMES[marker]} {count}문장 (2문장이어야 함)")

    found = [m for m in MARKDOWN_MARKERS if m in text]
    if found:
        violations.append(f"마크다운 문법: {', '.join(found)}")

    return violations


def count_fillers(analysis):
    """반복 금지 표현의 등장 횟수. 위반이 아니라 추이를 보기 위한 수치다"""
    return {p: analysis.count(p) for p in FILLER_PATTERNS if analysis.count(p)}


def _cell(text):
    """마크다운 표 칸. 제목에 든 파이프가 열을 늘리지 않게 막는다"""
    return text.replace("|", "\\|")


def write_summary(reports):
    """run 로그와 Actions job summary에 검증 결과를 남긴다"""
    passed = sum(1 for r in reports if not r["violations"])
    print(f"검증: {passed}/{len(reports)}건 통과")
    for r in reports:
        mark = "통과" if not r["violations"] else "위반 " + "; ".join(r["violations"])
        print(f"  - {r['title'][:60]}: {mark}")

    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return

    lines = [
        "## 발송 전 검증",
        "",
        f"{passed}/{len(reports)}건이 프롬프트 제약을 통과했다.",
        "",
        "| 기사 | 결과 | 재생성 | 반복 표현 |",
        "| --- | --- | --- | --- |",
    ]
    for r in reports:
        result = "통과" if not r["violations"] else "; ".join(r["violations"])
        fillers = ", ".join(f"{k} {v}" for k, v in r["fillers"].items()) or "-"
        lines.append(
            f"| {_cell(r['title'][:60])} | {_cell(result)} |"
            f" {'예' if r['regenerated'] else '아니오'} | {fillers} |"
        )
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
