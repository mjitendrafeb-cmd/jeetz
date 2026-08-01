# Codex Handoff — Multi-GH AI Newsletter (based on the 7:30 report)

## Objective

Extend this repository so the **7:30 AI-generated credit report** (`scripts/send_credit_report.py`)
can produce **multiple personalized newsletters — one per GH (Group Head)** — while:

- Using **ONE Anthropic API call per day** (never one call per GH — cost control).
- Reusing this repo's existing fetch pipeline, prompt logic, email sending, and GitHub Actions setup.
- Managing watchlist entities, users, emails, and S1–S5 enable/disable through the existing
  web console (`docs/team.html`) and `team.json` — same UX as the 7:40 team mail.

Do **not** rewrite from scratch. The logic is already built and battle-tested; your job is the
per-GH personalization layer.

---

## Repository map

| Path | What it is |
|---|---|
| `scripts/send_credit_report.py` | **The 7:30 report.** Fetches news, builds one big prompt, calls Anthropic API (model in `config.json`), produces newspaper-style S1–S5 report, emails it via Gmail SMTP with HTML body + attachment. Has a no-credits fallback (rule-based report) if the API fails. Also `_sync_watchlist_from_team()` regenerates `watchlist.txt` each run from `team.json` rows where `gh_name` contains "jitendra". |
| `scripts/fetch_news.py` | Aggregates all sources: RBI/SEBI RSS, Google News, BSE announcements, rating agencies (CareEdge/CRISIL/ICRA/India Ratings), Telegram channels, web scraping. `fetch_all_news(newsapi_key, apply_seen, per_company_cap)` returns list of raw item strings. Watchlist company items are tagged `[WATCHLIST — <Company Name>]`. `per_company_cap` default 3. |
| `scripts/fetch_bse.py`, `fetch_ratings.py`, `fetch_telegram.py`, `fetch_web.py` | Source-specific fetchers used by `fetch_news.py`. Don't modify. |
| `scripts/send_team_news.py` | **The 7:40 mail** — free, no-API, rule-based per-person digest. Contains reusable helpers: `_parse_item`, `_classify`, `_phrase`, `_match_companies`, `_acronym`, `_sig_words`, `_telegram_headline`, junk/geography filters. Reuse these for mechanical tag-matching; do NOT change its behavior. |
| `watchlist.txt` | One company name per line, `#` comments. Currently regenerated each 7:30 run from team.json (Jitendra's rows). **Your build changes this — see spec.** |
| `team.json` | Flat table: `{send_empty_mail, scheduled_enabled, rows:[{company, gh_name, analyst_name, rh_name, gh_email, analyst_email, rh_email, send_gh, send_analyst, send_rh, sections:["S1",...]}]}`. ~370 rows. Edited via `docs/team.html`. |
| `config.json` | 7:30 config: `model`, `recipients`, `sources` toggles, `custom_scrape_urls`, `daily_report_enabled`. |
| `docs/team.html` | GitHub-Pages management console. Reads/writes `team.json` + `config.json` via GitHub Contents API (user pastes a PAT). Excel import/export (SheetJS). Handles 409 stale-SHA conflicts. |
| `data/seen_headlines.json` | 7:30's cross-day dedup memory. `data/team_seen.json` is 7:40's (separate on purpose). |
| `data/last_sent.json` / `data/team_last_sent.json` | Once-per-day markers written by the workflows. |
| `.github/workflows/daily_credit_report.yml` | 7:30 workflow: staggered crons + gate step that waits until ~07:30 IST, checks `config.json.daily_report_enabled`, respects the once-per-day marker, supports `workflow_dispatch` with `force`. |
| `.github/workflows/team_news.yml` | 7:40 workflow (same pattern, 07:35+ IST gate). |

## Secrets (already configured in GitHub Actions — reuse as-is)

`ANTHROPIC_API_KEY`, `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `NEWSAPI_KEY`,
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION`, `GITHUB_TOKEN`.

Email is sent via Gmail SMTP (`smtp.gmail.com:465`, SSL) using `GMAIL_USER`/`GMAIL_APP_PASSWORD`.

---

## The 7:30 logic you must preserve

1. **Fetch** all news via `fetch_all_news()` (respects `config.json.sources`), dedup against
   `data/seen_headlines.json`.
2. **Prompt** (`_build_prompt` in `send_credit_report.py`) instructs Claude to write a
   newspaper-style report with sections:
   - **S1 — Watchlist News** (only companies on the watchlist; tag-driven)
   - **S2 — NBFC / FI Sector**
   - **S3 — RBI, SEBI & Regulations** (penalties/enforcement ALWAYS S3, never S2)
   - **S4 — Bond & Money Markets** (G-sec, CP, CD, T-bills, SDL, yields...)
   - **S5 — Macro** (IIP, GDP, inflation, Fed/ECB, crude — India-relevant only; drop other
     emerging-markets local news)
   - Cross-source dedup, credit implications per story, top-5 takeaways, LINKS rule
     (never emit `href="#"`; plain text when no URL).
3. **Send**: HTML email + attachment to `config.json.recipients`.
4. **Fallback**: if the Anthropic call fails (credits exhausted), a mechanical rule-based
   report is generated instead using helpers imported from `send_team_news.py`.
5. **Mark sent**: write `data/last_sent.json` and `data/seen_headlines.json`, commit/push
   with retry (rebase on conflict).

---

## Build spec: multi-GH newsletters

### Configuration (extend team.json, keep console-editable)

Every row in `team.json` already carries `company`, `gh_name`, `gh_email`, `send_gh`, and
`sections` (S1–S5 tick-boxes). Use these as the single source of truth:

- **A "newsletter" = one distinct `gh_name`** (case-insensitive, trimmed) that has at least one
  row with `send_gh: true` and a non-empty `gh_email`.
- That GH's **S1 watchlist** = all `company` values in their rows.
- That GH's **enabled sections** = union of the `sections` arrays across their rows
  (a GH with only `["S1"]` ticked gets S1 only; `["S1","S3","S5"]` gets those three).
- Optionally also support analyst/rh recipients the same way later — GH first.

### Generation (ONE API call)

1. Build the watchlist for fetching as the **union of all GHs' companies** (replaces the
   current Jitendra-only `_sync_watchlist_from_team`). Keep `per_company_cap=3`.
2. Make **one** Anthropic call with the existing prompt, modified only as follows:
   - S1 must be **company-tagged**: instruct the model to emit each S1 story wrapped in a
     machine-parseable marker, e.g. `<!--S1:Company Exact Name-->` before each story block
     (or emit S1 as per-company subsections with an exact-name heading). The company name in
     the marker MUST be copied verbatim from the `[WATCHLIST — ...]` tag.
   - S2–S5 unchanged — they are shared content.
3. **Split mechanically in Python** (zero extra API cost):
   - Parse the AI output into S1-story blocks (keyed by company) + S2/S3/S4/S5 blocks.
   - For each GH: assemble their email = their S1 companies' stories + the shared S2–S5
     sections they have enabled. Skip empty S1 gracefully ("No watchlist news today" line).
   - Sanity-check company attribution with `_mentions_company()` from `send_team_news.py`
     (guards against the model mis-tagging; log + drop mismatches).
4. Send one email per GH via the existing SMTP helper. Subject like
   `Daily Credit Intelligence — <GH Name> — <date>`.
5. Keep the top-5 takeaways + full report as an attachment option (shared across GHs is fine).

### Backward compatibility (important)

- `config.json.recipients` (currently Jitendra) should continue to receive the **full report**
  (all companies' S1 + all sections) exactly as today — treat it as the "master" newsletter.
- The credits-exhausted fallback must also work per-GH (reuse the mechanical S1 matching
  from `send_team_news.py` — it already does per-person S1 splitting).
- The 7:40 team mail (`send_team_news.py`, `team_news.yml`) must remain untouched and
  continue to run independently.
- `data/seen_headlines.json` stays the single dedup memory for the 7:30 system (do not
  create per-GH memories — all GHs share one generation).

### Console (docs/team.html)

No schema change is strictly needed (gh_name/gh_email/send_gh/sections already exist).
Just update the info banner text to explain: "7:30 AI report: every distinct GH Name with
Send-GH ticked gets their own AI newsletter (their companies in S1, plus their ticked
S2–S5 sections). One API call covers everyone."

### Workflow

Reuse `daily_credit_report.yml` unchanged (same gate, same marker, same secrets). The
script change is internal.

### Testing before deploy

- Unit-test the splitter with a synthetic AI output containing tagged S1 blocks.
- Run `main()` end-to-end with `_send` mocked; assert one email per qualifying GH, correct
  S1 slicing, correct section filtering, master report unchanged.
- Verify `git diff` shows no changes to `send_team_news.py` or `team_news.yml`.

## Cost guardrail

At ~400 companies the single call costs roughly $0.50–$1.00/day (Sonnet pricing). If input
exceeds the prompt's char ceiling (`100000` in `send_credit_report.py`), raise the ceiling
rather than making multiple API calls; consider `per_company_cap=2` if input grows too large.
