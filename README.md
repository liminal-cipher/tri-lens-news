# Tri-Lens Daily News

An automated pipeline that delivers AI/tech news every morning, interpreted through three depth levels. In a field that moves daily, everyone needs to keep up — but not everyone needs the same depth. Tri-Lens serves the same article at three levels so each reader gets the insight that matters to them.

## What it does

Every morning at 8:00 KST, it collects top stories from Hacker News and GeekNews, selects 3 AI/tech-relevant articles via Gemini API, generates three-tier interpretations, and emails the result in Korean.

- 🌐 **Everyone** — No jargon, everyday impact
- 💻 **Developers** — Technical stacks, implementation implications
- 🔬 **Researchers** — Academic context, open problems

## How it works

```
GitHub Actions (cron, daily)
  → Hacker News API + GeekNews RSS
  → Gemini API: select 3 AI/tech articles
  → Gemini API: generate 3-lens interpretation per article
  → Gmail SMTP: send to recipients
```

## Tech stack

| Component | Choice                       | Why                                           |
| --------- | ---------------------------- | --------------------------------------------- |
| Scheduler | GitHub Actions cron          | Serverless, no infra to manage                |
| AI Model  | Gemini 2.5 Flash (free tier) | 12 calls/day vs 250/day limit — room to scale |
| Delivery  | Gmail SMTP                   | Universal, no app install needed              |

Monthly cost: **$0**

## Prompt engineering

The prompt uses a research-backed structure ([Google's prompting guide](https://ai.google.dev/gemini-api/docs/prompting-strategies), [Anthropic's best practices](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering)):

- **XML tags** to separate role, task, constraints, example, and output format
- **One few-shot example** to anchor tone and structure
- **Explicit constraints** — sentence count, banned patterns, no markdown syntax

## Known limitations

- **Cron timing is approximate**: GitHub Actions cron can delay 5–30 min under load. The job triggers at 7:30 KST to compensate.
- **No link preview in email**: News URLs are plain text links; rendering depends on the email client.

## Setup

1. Get a [Gemini API key](https://aistudio.google.com/) (free, no credit card)
2. Create a [Gmail App Password](https://myaccount.google.com/apppasswords)
3. Fork this repo (keep it **public** for free Actions minutes)
4. Add 4 secrets in Settings → Secrets → Actions:
   - `GEMINI_API_KEY`
   - `GMAIL_ADDRESS`
   - `GMAIL_APP_PASSWORD`
   - `RECIPIENTS` (comma-separated emails)
5. Go to Actions tab → Run workflow → Check your inbox
