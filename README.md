# Tri-Lens Daily News 🔍

매일 아침 8시(KST), AI/테크 뉴스 3개를 3가지 렌즈로 해석해서 이메일로 보내줍니다.

## 렌즈

- 🌐 **Everyone** — 누구나 이해할 수 있는 해석 (비유, 사례 중심)
- 💻 **Developers** — 개발자/엔지니어 관점 (기술 스택, 구현, 영향)
- 🔬 **Researchers** — 연구자/심화 관점 (논문, 이론적 맥락, 열린 문제)

## 비용

**0원.** Gemini 무료 API + GitHub Actions (public repo) + Gmail SMTP

## 뉴스 소스

- [Hacker News](https://news.ycombinator.com/) — 글로벌 테크 뉴스
- [GeekNews](https://news.hada.io/) — 한국 개발자 커뮤니티 뉴스

## 기술 스택

| 구성      | 선택                | 이유                                              |
| --------- | ------------------- | ------------------------------------------------- |
| 스케줄러  | GitHub Actions cron | 서버리스, 무료, 별도 인프라 불필요                |
| AI 모델   | Gemini 2.5 Flash    | 무료 티어 하루 250건으로 충분, 스케일업 경로 확보 |
| 배포 채널 | Gmail SMTP          | 추가 앱 설치 없이 누구나 수신 가능                |

## 커스터마이징

- `scripts/daily_news.py`에서 `NEWS_COUNT` 변경 → 뉴스 개수 조절
- `.github/workflows/daily-news.yml`의 cron 값 수정 → 발송 시간 변경
- `generate_trilens()` 함수의 프롬프트 수정 → 렌즈 변경/추가

## 알려진 제한사항

- **발송 시간이 정확하지 않음**: GitHub Actions cron은 정확한 시간을 보장하지 않습니다. 부하가 높은 시간대에는 5~30분 지연될 수 있으며, 이는 GitHub Actions의 구조적 한계입니다. ([GitHub 공식 문서 참고](https://docs.github.com/en/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows#schedule))
