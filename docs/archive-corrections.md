# Archive Corrections

Reviewed 2026-10-28. The files under `archive/` preserve generated output as
recorded at the time. Read the corrections below alongside those records;
the original text has not been silently replaced or sent again.

This is an editorial review and a small set of source checks, not a factual
audit of every linked article. Corrections to wording do not validate the
surrounding technical claims. The [evaluation plan](evaluation.md) distinguishes
these findings from a measured faithfulness score.

## Confirmed Corrections

| Record and location | Recorded problem | Correction or evidence |
| --- | --- | --- |
| [2026-08-27](../archive/2026-08-27.md), item 2, Everyone | `구름 저장소` is a literal translation in a cloud-storage context. | Read as `클라우드 저장소`. |
| [2026-09-05](../archive/2026-09-05.md), item 2, Developers | `작업을 분율하고` uses the noun for a proportion as a verb for dividing work. | Read as `작업을 나누고`. |
| [2026-09-22](../archive/2026-09-22.md), item 3, Researchers | `구증하려면` is a typo. | Read as `검증하려면`. |
| [2026-09-26](../archive/2026-09-26.md), item 1, Developers | `Base64 암호화` confuses encoding with encryption. | Read as `Base64 인코딩`. The [Python documentation](https://docs.python.org/3/library/base64.html) defines reversible binary-to-text encoding, not confidentiality protection. This does not verify the incident's other details. |
| [2026-10-07](../archive/2026-10-07.md), item 1, source URL | The URL has a trailing backslash. | Use the [Mistral Large 4 announcement](https://mistral.ai/news/mistral-large-4/), retrieved during this review. |
| [2026-10-08](../archive/2026-10-08.md), item 2, Everyone | `전문 보트` and `대표 보트` refer to software bots, not boats. | Read as `전문 봇` and `대표 봇`. |
| [2026-10-13](../archive/2026-10-13.md), item 1, Developers | `가득 채기 때문에` is missing a syllable. | Read as `가득 채우기 때문에`. |
| [2026-10-13](../archive/2026-10-13.md), item 2, Researchers | `아빌레이션(ablation)` is a misspelling. | Read as `구성 요소 제거(ablation) 실험`. |
| [2026-10-15](../archive/2026-10-15.md), item 1, Researchers | `체인‑오브‑씽크(Chain‑of‑Thought)` mismatches the English term. | Read as `사고 사슬(Chain‑of‑Thought)`. |
| [2026-10-19](../archive/2026-10-19.md), item 1, Everyone | `머리속에서` is misspelt. | Read as `머릿속에서`. |
| [2026-10-20](../archive/2026-10-20.md), item 3, Developers | `관찰(새로운 렌더링 이미지) 을` separates the Korean particle. | Read as `관찰(새로운 렌더링 이미지)을`. |
| [2026-10-21](../archive/2026-10-21.md), item 3, Everyone | `영상이나 소리를 볼 때` applies seeing to sound. | Read as `영상을 보거나 소리를 들을 때`. |
| [2026-10-24](../archive/2026-10-24.md), item 3, Developers | The raw `<OBJ>` token can be interpreted as HTML in Markdown. | Read the literal code token `<OBJ>`; use inline code when quoting it in Markdown. The email renderer separately escapes HTML. |
| [2026-10-27](https://github.com/liminal-cipher/tri-lens-news/blob/d9c63ec7a3b1c15053eb07751aa9b1caf8c2890d/archive/2026-10-27.md), item 1, Developers | The price denominator is a token instead of a million tokens. | The [original announcement](https://openai.com/index/introducing-gpt-6-1-terra/) states $1 input, $0.05 cached input and $5 output per **million tokens**. These are the announcement's prices, not a future pricing guarantee. |

## Interpretation Problems Requiring Further Review

- [2026-09-05](../archive/2026-09-05.md), item 1, Developers: `구현 속도를 대폭
  낮추지만` contradicts the surrounding productivity claim. `구현 시간을
  줄이지만` would express that intended direction, but the claimed improvement
  itself still needs source verification.
- [2026-09-20](../archive/2026-09-20.md), item 1: Everyone implies no concern
  about external storage, while Developers describes direct communication with
  nine providers. Self-hosting the interface does not establish provider
  retention behaviour. Similar unconditional privacy claims occur in other
  local-tool summaries, including [2026-08-15](../archive/2026-08-15.md).
- [2026-10-14](../archive/2026-10-14.md), item 2: `추가 비용 없이` conflicts with
  the same item's description of payments to device owners. The cost boundary
  needs clarification against the source before asserting that inference is free.
- [2026-10-22](../archive/2026-10-22.md), item 3: Developers and Researchers
  are in English despite the Korean-output instruction. The format checker
  does not check language; a checked translation remains pending.
- [2026-10-24](../archive/2026-10-24.md), item 1: the headline is about a
  full-duplex speech model, but all three lenses discuss a privacy policy.
  Treat this interpretation as off-topic. The retained archive does not show
  whether extraction or generation caused the mismatch, so a replacement
  requires retrieving and checking the intended source.

Historical output can also contain unsupported causal claims or proposed
research limitations presented as established facts. Those need source-level
adjudication; a plausible explanation or a passing format check is insufficient.

Generated records also retain mixed English spellings, such as `generalization`
and `quantization`. New editorial prose uses Australian spelling where these
are ordinary terms. Exact titles, identifiers and the historical output remain
unchanged; their preservation is not a claim that every archived sentence
follows the current editorial convention.
