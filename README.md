# Tri-Lens Daily News

An automated pipeline that emails AI and tech news every morning, interpreted at three depths for three different readers.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
![Gemini](https://img.shields.io/badge/Gemini-2.5%20Flash-4285F4?logo=google&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-cron-2088FF?logo=githubactions&logoColor=white)
![Cost](https://img.shields.io/badge/Monthly%20cost-%240-success)

## Motivation

Filtering AI and tech news by hand across Hacker News and RSS feeds takes time every single morning, and the newsletters that do it for you are written for one audience. They are either too shallow to tell a developer anything actionable or too dense for someone outside the field.

The observation behind this project is that the gap is usually not the news, it is the framing. The same story matters differently to a general reader, an engineer, and a researcher. So rather than pick different stories per audience, this pipeline picks the same three stories and rewrites each one three ways.

## What It Does

Every morning it collects the top stories from Hacker News and GeekNews, asks Gemini to pick the three most relevant to AI and software, generates a three-lens interpretation of each, and emails the result in Korean.

- **Everyone** - everyday impact, no jargon
- **Developers** - stacks, implementation consequences
- **Researchers** - open problems and research direction

Each lens is capped at two sentences, and the prompt requires the three to differ in sentence structure so the reader is not shown the same paragraph three times.

## Architecture

```mermaid
graph TD
    A[GitHub Actions cron] -->|22:30 UTC / 07:30 KST| B(Hacker News API + GeekNews RSS)
    B -->|up to 30 candidates| C{Gemini: select 3}
    C -->|3 articles| D{Gemini: tri-lens prompt, one call per article}
    D -->|3-tier interpretation| E[Gmail SMTP]
    E -->|delivered around 08:00 KST| F(Recipients)
```

Four Gemini calls run per day: one to select, three to interpret. Everything lives in a single script with no database and no server.

## Tech Decisions

| Component | Choice | Why this over alternatives |
| --- | --- | --- |
| Scheduler | GitHub Actions cron | Serverless with no instance to keep alive, and free on a public repo. The tradeoff is that the schedule is best-effort, which is handled below |
| Model | Gemini 2.5 Flash | The free tier's 15 requests per minute covers four calls a day with room to spare, and the context window fits a full candidate list in one prompt |
| Delivery | Gmail SMTP | Email needs nothing installed and no account created. A web app or a bot would have put a step between the reader and the content |
| Storage | None | The pipeline is stateless by design. Adding a database would be the first thing to break in an unattended job, and nothing today needs to persist |

Monthly cost is $0. Every component sits inside a free tier at this volume.

## Prompt Engineering

Early versions produced the usual failure modes: a preamble before the answer ("Sure, I will translate this news for you"), and markdown syntax that Gmail rendered as literal asterisks.

The prompt was restructured around three techniques, following [Google's prompting guide](https://ai.google.dev/gemini-api/docs/prompting-strategies) and [Anthropic's best practices](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering):

- **XML tags** separate role, task, constraints, and output format so instructions do not bleed into each other
- **One-shot anchoring** with a full worked example fixes the tone and proves that the answer starts immediately, with no greeting
- **Negative constraints** ban markdown, ban a list of filler phrases that kept recurring, and hold each lens to exactly two sentences

## Results & Limitations

The pipeline ran for a stretch after 2026-04-06 at no cost. It is **not currently delivering**, and the more useful result is that nobody noticed when it stopped. That is the silent-failure gap below turning into an actual outage: with no alerting, an unattended job that quits looks exactly like an unattended job that works.

Beyond cost, **nothing has been measured**: there is no record of run successes and failures, no evaluation of whether the interpretations are faithful to the articles, and no reader feedback. The prompt constraints are enforced by the prompt alone, so a violation would ship.

Known gaps, all present in the current code:

- **Retries do not cover the model calls.** The retry-mounted session applies to news fetching only. `call_gemini` posts directly, so one transient 5xx from Gemini ends that morning's run.
- **The selection response is parsed strictly.** The model is asked for JSON and the reply goes to `json.loads` with no fallback, so a malformed answer stops the run rather than degrading to a default pick.
- **Failures are silent.** If fewer than three stories are collected the script returns without sending anything. There is no alert on any failure path, and the only signal is the Actions tab, which nobody opens while the mail appears to be arriving. This is the gap that let the pipeline stop unobserved.
- **No deduplication.** Hacker News and GeekNews regularly carry the same story, and nothing prevents it being selected twice.
- **Email HTML is unescaped.** Article titles and model output are interpolated straight into the template, so a title containing `<` or `&` renders wrong.
- **Delivery time is approximate.** GitHub Actions cron can lag 5 to 30 minutes under load. Triggering at 07:30 KST to land near 08:00 is a mitigation, not a guarantee.

## Getting Started

1. Get a [Gemini API key](https://aistudio.google.com/) (free, no credit card).
2. Create a [Gmail App Password](https://myaccount.google.com/apppasswords).
3. Fork this repo. Keep it public so Actions minutes stay free.
4. Add four secrets under Settings, Secrets, Actions:
   - `GEMINI_API_KEY`
   - `GMAIL_ADDRESS`
   - `GMAIL_APP_PASSWORD`
   - `RECIPIENTS` (comma-separated)
5. Open the Actions tab, run the workflow manually, and check your inbox.

## Roadmap

The limitations above set the order. Observability comes before measurement, and measurement before new capability, because a pipeline that can stop without telling anyone cannot support a claim about anything else.

- **Failure visibility**: alert when a run fails or skips, so an outage surfaces the day it happens rather than whenever someone thinks to check.
- **Evaluation before dispatch**: score each generated interpretation for faithfulness to the source article and for readability, and log the scores. This is what turns prompt changes into something with evidence behind them.
- **Deduplication**: collapse the same story arriving from both sources before selection.
- **Reader feedback**: a thumbs up or down in the email, stored somewhere light, to check whether the three-lens split is actually useful or just a nice idea.

## Status

Not currently delivering. The scheduled run stopped at an unconfirmed point after 2026-04-06 and the interruption went unnoticed. The code is intact and the workflow can be re-enabled; alerting is the prerequisite for calling it running again. Last reviewed 2026-08-11.

## License

MIT. See [LICENSE](LICENSE).
