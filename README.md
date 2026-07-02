# Daily Credit Intelligence Report

An automated daily credit-news briefing for a BFSI credit analyst. Every morning
(Mon–Sat, targeting ~7:30 AM IST) it fetches Indian financial/credit news from
regulators, rating agencies, exchanges, quality press, and Telegram channels,
has Claude organise it into 5 analyst-grade sections with credit implications,
and emails it as a newspaper-style report. A weekly digest goes out Friday
afternoons.

## What arrives in your inbox

| When | What |
|------|------|
| Mon–Sat ~7:30 AM IST | **Daily report** — email with Top 5 Credit Takeaways + full 5-section newspaper attachment (S1 Watchlist · S2 NBFC/FI · S3 Regulations · S4 Bond Markets · S5 Macro) |
| Friday ~4:00 PM IST | **Weekly digest** — top themes, regulatory actions, rating actions, sector heat map |

---

## ⚙️ Everything is controlled from `config.json` and `watchlist.txt`

Edit either file directly on GitHub (web or mobile app: open the file → pencil
icon → change → **Commit changes** to `main`). The next report picks the change
up automatically — no other steps.

### Add / remove an email recipient

In `config.json`:

```json
"recipients": [
    "jitendra.meghrajani@gmail.com",
    "another.person@example.com"
]
```

Add or delete lines in that list (keep commas between entries). Every address
listed gets the report.

### Add / remove a news website

In `config.json`, `custom_scrape_urls` — any news page URL works; headlines are
scraped and filtered for credit relevance:

```json
"custom_scrape_urls": [
    "https://bfsi.economictimes.indiatimes.com/",
    "https://www.livemint.com/industry/banking"
]
```

### Turn whole source groups on/off

In `config.json`, set `true`/`false` in `"sources"` (RBI, SEBI, Google News,
Telegram, web scraper…) or fine-grained per-site in `"web_sources"` (CareEdge,
CRISIL, ICRA, BSE, NSE, FIMMDA…).

### Add / remove a Telegram channel

In `config.json`, `"telegram_channels"` — use the public @handle:

```json
"telegram_channels": ["@bank_nbfc_fintech", "@livemint"]
```

### Add / remove a watchlist company

`watchlist.txt` — one company per line, `#` lines are comments. Watchlist
companies always lead Section 1 of the report.

---

## How the 7:30 AM scheduling works

GitHub's built-in cron is unreliable on small repos (it fired 8–15 hours late
here). The fix in `.github/workflows/daily_credit_report.yml`:

- The workflow wakes **every hour** (`23 * * * *`).
- A 5-second **gate step** checks: past 07:15 IST? not Sunday? not already sent
  today (`data/last_sent.json`)? Only then does the full report run.
- After a successful send, the marker file is updated so later ticks skip.

Even when GitHub delays individual ticks, ticks queued from earlier hours keep
landing all morning, so the first one through the gate delivers close to 7:30.
If a day's delivery is late, it self-heals — the next tick through the gate
still sends that day's report.

**Manual run any time:** repo → Actions → *Daily Credit Intelligence Report* →
Run workflow (choose `weekly: true` for a digest). Manual runs always send,
even if today's report already went out.

### Optional: exact-to-the-minute delivery

For guaranteed 7:30 sharp, have a free external scheduler (e.g. cron-job.org)
POST to the GitHub API at 01:50 UTC Mon–Sat:

- URL: `https://api.github.com/repos/mjitendrafeb-cmd/jeetz/actions/workflows/daily_credit_report.yml/dispatches`
- Headers: `Authorization: Bearer <PAT with workflow scope>`, `Accept: application/vnd.github+json`
- Body: `{"ref":"main","inputs":{"force":"false"}}`

(`force:false` means it respects the once-per-day marker, so the hourly
fallback never double-sends.)

## Architecture

```
.github/workflows/daily_credit_report.yml   hourly tick + gate + report job
config.json                                 ← control panel (recipients, sources)
watchlist.txt                               ← rated entities / companies to track
scripts/
  send_credit_report.py                     orchestrator: fetch → Claude → email
  fetch_news.py                             RBI, SEBI, Google News, watchlist
  fetch_web.py                              rating agencies, BSE/NSE, custom URLs
  fetch_telegram.py                         Telegram channels (Telethon)
  fetch_ratings.py / fetch_bse.py           rating actions, BSE announcements
data/
  seen_headlines.json                       5-day dedup memory
  last_sent.json                            once-per-day send marker
```

Secrets (repo → Settings → Secrets → Actions): `GMAIL_USER`,
`GMAIL_APP_PASSWORD`, `ANTHROPIC_API_KEY`, `TELEGRAM_API_ID`,
`TELEGRAM_API_HASH`, `TELEGRAM_SESSION`, optional `NEWSAPI_KEY`.
