#!/usr/bin/env python3
"""
Daily Credit Intelligence Report — newspaper webpage + email notification.
1. Fetches live news from all configured sources.
2. Sends to Claude API which generates full credit analysis as HTML body.
3. Wraps in a full newspaper-style webpage saved to docs/index.html.
4. Commits & pushes to main so GitHub Pages auto-publishes it.
5. Sends a brief email with a "View online" link.

Reads env vars: GMAIL_USER, GMAIL_APP_PASSWORD, ANTHROPIC_API_KEY, NEWSAPI_KEY (optional).
"""

import os
import json
import subprocess
import smtplib
import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import anthropic

from fetch_news import fetch_all_news

_PAGES_URL = "https://mjitendrafeb-cmd.github.io/jeetz/"


def _load_config() -> dict:
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, "config.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


_FALLBACK_RECIPIENT = "Jitendra.Meghrajani@careedge.in"


def _get_recipients() -> list[str]:
    cfg = _load_config()
    if cfg.get("recipients"):
        return cfg["recipients"]
    if cfg.get("recipient"):
        return [cfg["recipient"]]
    return [_FALLBACK_RECIPIENT]


# ---------------------------------------------------------------------------
# Prompt builder — Claude outputs the article body only (no page wrapper)
# ---------------------------------------------------------------------------

def _build_prompt(news_text: str, day_str: str, date_str: str) -> str:
    return f"""You are a Credit Rating Intelligence Agent at CareEdge Ratings.
Today is {day_str}, {date_str}.

NEWS ITEMS — each tagged by source (e.g. [WATCHLIST — Company], [RBI], [NBFC], [Macro]).
URLs follow "| URL:" at the end of each item.
ALL items are from the last 48 hours only.

{news_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
USE items that affect: Rating outlook · Liquidity · Funding · Asset quality · Capitalisation · Governance
SKIP items about: Product launches · CSR · Awards · Stock tips · Generic business news
WATCHLIST items tagged [WATCHLIST — Company] are HIGHEST PRIORITY — always listed first.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT — NEWSPAPER BODY HTML (no page wrapper, no markdown)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

This will be inserted into a full webpage. You have access to real CSS via <style> tags.
Output ONLY the article body — no <html>/<head>/<body> tags.

════════════════════════
PART A — BREAKING TICKER + LEAD GRID
════════════════════════

First output a breaking-news ticker with the single top headline:
<div class="ticker">
  <span class="ticker-label">&#9642; BREAKING</span>
  <span class="ticker-text">ONE LINE SUMMARY OF TOP STORY</span>
</div>

Then a 3-column lead grid (watchlist story gets the wide left column):
<section class="lead-grid">
  <article class="lead-main">
    <p class="art-tag">WATCHLIST · COMPANY or SECTION</p>
    <h2 class="art-headline">Full headline of the lead story</h2>
    <p class="art-body">2-3 sentence factual summary.</p>
    <div class="credit-box red">
      <p class="credit-label">&#9888; CREDIT IMPLICATION</p>
      <p class="credit-text">2-3 sentences on rating/liquidity/asset quality impact.</p>
    </div>
    <p class="art-footer"><a href="ACTUAL_URL" target="_blank" class="read-more">Read full story &#8594;</a> <span class="source-tag">Source Name</span></p>
  </article>

  <div class="lead-side">
    <article class="lead-secondary">
      <p class="art-tag">SECTION TAG</p>
      <h3 class="art-headline-sm">Headline story 2</h3>
      <p class="art-body-sm">1-2 sentence summary.</p>
      <div class="credit-box amber">
        <p class="credit-text-sm">Credit implication in 1-2 sentences.</p>
      </div>
      <p class="art-footer"><a href="ACTUAL_URL" target="_blank" class="read-more">Read more &#8594;</a> <span class="source-tag">Source</span></p>
    </article>
    <article class="lead-secondary bottom">
      <p class="art-tag">SECTION TAG</p>
      <h3 class="art-headline-sm">Headline story 3</h3>
      <p class="art-body-sm">1-2 sentence summary.</p>
      <div class="credit-box green">
        <p class="credit-text-sm">Credit implication in 1-2 sentences.</p>
      </div>
      <p class="art-footer"><a href="ACTUAL_URL" target="_blank" class="read-more">Read more &#8594;</a> <span class="source-tag">Source</span></p>
    </article>
  </div>
</section>

════════════════════════
PART B — 5 SECTION PAGES
════════════════════════
For each section output a block. Include ALL items NOT already in Part A leads. Show all 5 sections.

Section routing:
  S1 — [WATCHLIST — CompanyName] items ONLY
  S2 — NBFC, HFC, Banking, Broking, Fintech, MFI, rating actions
  S3 — RBI, SEBI, NHB regulatory items
  S4 — Bonds, CP, Securitisation, FIMMDA, CCIL market items
  S5 — Macro: GDP, CPI, IIP, forex, fiscal deficit, US Fed, global

Section structure:
<section class="news-section">
  <div class="section-header s1">&#9733; SECTION 1 — MY RATED ENTITIES &amp; WATCHLIST</div>
  <!-- use class s1/s2/s3/s4/s5 for colour -->
  <div class="article-grid">
    <article class="grid-card">
      <p class="art-tag">SOURCE</p>
      <h4 class="card-headline"><a href="URL" target="_blank">Headline text</a></h4>
      <p class="card-summary">1-sentence credit-focused summary.</p>
      <p class="card-angle">Credit angle tag phrase</p>
    </article>
    <!-- repeat for each article, no limit -->
  </div>
</section>

Empty section: <p class="empty-section">No news in this category today.</p>

Section header classes: s1=red, s2=amber, s3=navy, s4=green, s5=purple

════════════════════════
PART C — TOP 5 BRIEFING BAR
════════════════════════
<section class="briefing-bar">
  <div class="briefing-header">&#9679; TODAY'S TOP 5 CREDIT BRIEFING</div>
  <div class="briefing-grid">
    <div class="briefing-item">
      <span class="brief-num">01</span>
      <p class="brief-topic">S1 / TOPIC</p>
      <p class="brief-text">One sharp credit insight sentence.</p>
    </div>
    <div class="briefing-item">
      <span class="brief-num">02</span>
      <p class="brief-topic">S2 / TOPIC</p>
      <p class="brief-text">One sharp credit insight sentence.</p>
    </div>
    <div class="briefing-item">
      <span class="brief-num">03</span>
      <p class="brief-topic">S3 / TOPIC</p>
      <p class="brief-text">One sharp credit insight sentence.</p>
    </div>
    <div class="briefing-item">
      <span class="brief-num">04</span>
      <p class="brief-topic">S4 / TOPIC</p>
      <p class="brief-text">One sharp credit insight sentence.</p>
    </div>
    <div class="briefing-item">
      <span class="brief-num">05</span>
      <p class="brief-topic">S5 / TOPIC</p>
      <p class="brief-text">One sharp credit insight sentence.</p>
    </div>
  </div>
</section>

CRITICAL:
- Use ACTUAL URLs from "| URL:" in input — never leave placeholder text. Omit <a> entirely if no URL.
- Do NOT output <html>/<head>/<body> tags, page wrapper, or CSS — the wrapper provides it.
- Output Parts A, B, C in order. Nothing else."""


# ---------------------------------------------------------------------------
# Claude API call
# ---------------------------------------------------------------------------

def generate_report(news_text: str, today: datetime.date, api_key: str) -> str:
    day_str = today.strftime("%A")
    date_str = today.strftime("%d %B %Y")

    if len(news_text) > 30000:
        news_text = news_text[:30000] + "\n[...truncated for length]"

    prompt = _build_prompt(news_text, day_str, date_str)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=12000,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text
    except Exception as exc:
        print(f"[generate_report] Claude API error: {exc}")
        return f'<div class="error-box"><h2>&#9888; Report Generation Failed</h2><p>{str(exc)[:400]}</p></div>'


# ---------------------------------------------------------------------------
# Full newspaper webpage wrapper
# ---------------------------------------------------------------------------

def build_webpage(inner_html: str, today: datetime.date) -> str:
    date_str = today.strftime("%d %B %Y")
    dow = today.strftime("%A, %d %B %Y").upper()
    iso = today.isoformat()

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex,nofollow">
<title>CareEdge Credit Intelligence — {date_str}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=Source+Serif+4:ital,wght@0,400;0,600;1,400&family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    background: #e8e8e8;
    font-family: 'Inter', Arial, sans-serif;
    color: #1a1a1a;
    -webkit-text-size-adjust: 100%;
  }}

  /* ── PAGE LAYOUT ── */
  .page-wrap {{ max-width: 1000px; margin: 0 auto; background: #fff; box-shadow: 0 4px 24px rgba(0,0,0,.18); }}

  /* ── TOP BAR ── */
  .top-bar {{ background: #c00; height: 5px; }}

  /* ── MASTHEAD ── */
  .masthead {{ border-bottom: 3px solid #1a1a1a; padding: 14px 28px 10px; }}
  .masthead-meta {{ font-size: 10px; letter-spacing: 2px; text-transform: uppercase; color: #888; margin-bottom: 4px; }}
  .masthead-title {{ font-family: 'Playfair Display', Georgia, serif; font-size: clamp(28px, 5vw, 46px); font-weight: 900; line-height: 1; color: #1a1a1a; letter-spacing: -1px; }}
  .masthead-rule {{ border-top: 1px solid #1a1a1a; margin-top: 8px; padding-top: 5px; display: flex; justify-content: space-between; align-items: center; }}
  .masthead-tagline {{ font-family: 'Source Serif 4', Georgia, serif; font-size: 11px; font-style: italic; color: #555; }}
  .masthead-confidential {{ font-size: 9px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #c00; border: 1px solid #c00; padding: 2px 6px; }}

  /* ── SECTION NAV ── */
  .section-nav {{ background: #1a1a1a; border-bottom: 3px solid #c00; display: flex; }}
  .section-nav a {{ display: block; padding: 7px 14px; font-size: 9px; font-weight: 700; letter-spacing: 2px; text-transform: uppercase; color: #ccc; text-decoration: none; border-right: 1px solid #333; transition: color .15s; }}
  .section-nav a:first-child {{ color: #fff; }}
  .section-nav a:hover {{ color: #fff; }}

  /* ── MAIN CONTENT ── */
  .content {{ padding: 0 28px 28px; }}

  /* ── TICKER ── */
  .ticker {{ display: flex; align-items: center; background: #fff8f8; border-top: 2px solid #c00; border-bottom: 1px solid #e5e5e5; padding: 7px 0; margin: 0 -28px 16px; padding-left: 28px; padding-right: 28px; gap: 14px; overflow: hidden; }}
  .ticker-label {{ font-size: 9px; font-weight: 800; letter-spacing: 3px; text-transform: uppercase; color: #c00; white-space: nowrap; flex-shrink: 0; }}
  .ticker-text {{ font-size: 12px; font-weight: 600; color: #1a1a1a; line-height: 1.4; }}

  /* ── LEAD GRID ── */
  .lead-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0; border-bottom: 2px solid #1a1a1a; margin-bottom: 0; }}
  .lead-main {{ padding: 18px 18px 18px 0; border-right: 1px solid #ddd; }}
  .lead-side {{ display: flex; flex-direction: column; }}
  .lead-secondary {{ padding: 14px 0 14px 18px; flex: 1; }}
  .lead-secondary.bottom {{ border-top: 1px solid #ddd; }}

  /* ── ARTICLE ELEMENTS ── */
  .art-tag {{ font-size: 9px; font-weight: 800; letter-spacing: 2px; text-transform: uppercase; color: #c00; margin-bottom: 5px; }}
  .art-headline {{ font-family: 'Playfair Display', Georgia, serif; font-size: 20px; font-weight: 700; line-height: 1.25; color: #1a1a1a; margin-bottom: 10px; }}
  .art-headline-sm {{ font-family: 'Playfair Display', Georgia, serif; font-size: 15px; font-weight: 700; line-height: 1.25; color: #1a1a1a; margin-bottom: 7px; }}
  .art-body {{ font-family: 'Source Serif 4', Georgia, serif; font-size: 13px; line-height: 1.75; color: #333; margin-bottom: 10px; }}
  .art-body-sm {{ font-family: 'Source Serif 4', Georgia, serif; font-size: 12px; line-height: 1.65; color: #333; margin-bottom: 8px; }}
  .art-footer {{ font-size: 11px; margin-top: 8px; display: flex; align-items: center; gap: 8px; }}
  .read-more {{ color: #c00; font-weight: 700; text-decoration: none; }}
  .read-more:hover {{ text-decoration: underline; }}
  .source-tag {{ color: #888; font-size: 10px; }}

  /* ── CREDIT BOXES ── */
  .credit-box {{ border-left: 3px solid; padding: 8px 12px; margin-bottom: 10px; }}
  .credit-box.red {{ background: #fef2f2; border-color: #c00; }}
  .credit-box.amber {{ background: #fffbeb; border-color: #d97706; }}
  .credit-box.green {{ background: #f0fdf4; border-color: #16a34a; }}
  .credit-box.navy {{ background: #eff6ff; border-color: #1e40af; }}
  .credit-box.purple {{ background: #faf5ff; border-color: #7c3aed; }}
  .credit-label {{ font-size: 9px; font-weight: 800; letter-spacing: 1px; text-transform: uppercase; color: #c00; margin-bottom: 3px; }}
  .credit-text {{ font-size: 12px; color: #374151; line-height: 1.65; margin: 0; }}
  .credit-text-sm {{ font-size: 11px; color: #374151; line-height: 1.6; margin: 0; }}

  /* ── SECTION BLOCKS ── */
  .news-section {{ margin-top: 0; border-bottom: 1px solid #e5e5e5; padding-bottom: 4px; }}
  .section-header {{ padding: 8px 28px; font-size: 9px; font-weight: 800; letter-spacing: 3px; text-transform: uppercase; color: #fff; margin: 0 -28px; }}
  .section-header.s1 {{ background: #c00; }}
  .section-header.s2 {{ background: #b45309; }}
  .section-header.s3 {{ background: #1e3a8a; }}
  .section-header.s4 {{ background: #15803d; }}
  .section-header.s5 {{ background: #6d28d9; }}

  .article-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0; margin: 0 -28px; padding: 0 28px; }}
  .grid-card {{ padding: 12px 12px 12px 0; border-right: 1px solid #e5e5e5; border-bottom: 1px solid #e5e5e5; }}
  .grid-card:nth-child(even) {{ padding: 12px 0 12px 12px; border-right: none; }}
  .card-headline {{ font-family: 'Playfair Display', Georgia, serif; font-size: 13px; font-weight: 700; line-height: 1.3; color: #1a1a1a; margin-bottom: 5px; }}
  .card-headline a {{ color: #1a1a1a; text-decoration: none; }}
  .card-headline a:hover {{ color: #c00; }}
  .card-summary {{ font-size: 11px; color: #555; line-height: 1.6; margin-bottom: 4px; font-family: 'Source Serif 4', Georgia, serif; }}
  .card-angle {{ font-size: 10px; font-weight: 700; font-style: italic; color: #c00; }}
  .empty-section {{ padding: 12px 0; font-size: 12px; color: #aaa; font-style: italic; }}

  /* ── TOP 5 BRIEFING ── */
  .briefing-bar {{ margin: 0 -28px; border-top: 2px solid #1a1a1a; }}
  .briefing-header {{ background: #1a1a1a; padding: 9px 28px; font-size: 9px; font-weight: 800; letter-spacing: 3px; text-transform: uppercase; color: #fff; }}
  .briefing-grid {{ display: grid; grid-template-columns: repeat(5, 1fr); border-bottom: 1px solid #e5e5e5; }}
  .briefing-item {{ padding: 14px 12px; border-right: 1px solid #e5e5e5; }}
  .briefing-item:first-child {{ padding-left: 28px; }}
  .briefing-item:last-child {{ border-right: none; padding-right: 28px; }}
  .brief-num {{ display: block; font-family: 'Playfair Display', Georgia, serif; font-size: 32px; font-weight: 900; color: #c00; line-height: 1; margin-bottom: 4px; }}
  .brief-topic {{ font-size: 9px; font-weight: 800; letter-spacing: 1px; text-transform: uppercase; color: #666; margin-bottom: 5px; }}
  .brief-text {{ font-size: 11px; color: #1a1a1a; line-height: 1.6; }}

  /* ── FOOTER ── */
  .page-footer {{ background: #1a1a1a; padding: 16px 28px; text-align: center; font-size: 10px; color: #666; line-height: 2; }}
  .page-footer strong {{ color: #c00; }}
  .page-footer em {{ color: #555; }}

  /* ── ERROR BOX ── */
  .error-box {{ padding: 28px; background: #fff5f5; border: 2px solid #c00; margin: 20px 0; }}
  .error-box h2 {{ color: #c00; font-size: 16px; margin-bottom: 8px; }}

  /* ── RESPONSIVE ── */
  @media (max-width: 640px) {{
    .lead-grid, .article-grid, .briefing-grid {{ grid-template-columns: 1fr; }}
    .lead-main {{ border-right: none; border-bottom: 1px solid #ddd; padding: 14px 0; }}
    .lead-secondary {{ padding: 12px 0; }}
    .grid-card, .grid-card:nth-child(even) {{ padding: 10px 0; border-right: none; }}
    .briefing-grid {{ grid-template-columns: 1fr 1fr; }}
    .briefing-item:first-child, .briefing-item:last-child {{ padding-left: 12px; padding-right: 12px; }}
    .section-nav {{ flex-wrap: wrap; }}
  }}
</style>
</head>
<body>
<div class="page-wrap">

  <!-- TOP BAR -->
  <div class="top-bar"></div>

  <!-- MASTHEAD -->
  <header class="masthead">
    <p class="masthead-meta">{dow} &nbsp;&bull;&nbsp; Credit Strategy &amp; Surveillance Desk &nbsp;&bull;&nbsp; Internal Use Only</p>
    <h1 class="masthead-title">CareEdge Credit Intelligence</h1>
    <div class="masthead-rule">
      <span class="masthead-tagline">Daily Credit &amp; Markets Briefing &mdash; CareEdge Ratings</span>
      <span class="masthead-confidential">&#128274; Confidential</span>
    </div>
  </header>

  <!-- SECTION NAV -->
  <nav class="section-nav">
    <a href="#s1">&#9733; Watchlist</a>
    <a href="#s2">NBFC &amp; FI</a>
    <a href="#s3">Regulations</a>
    <a href="#s4">Markets</a>
    <a href="#s5">Macro</a>
  </nav>

  <!-- REPORT BODY -->
  <main class="content">
    {inner_html}
  </main>

  <!-- FOOTER -->
  <footer class="page-footer">
    <strong>CareEdge Ratings</strong> &nbsp;&mdash;&nbsp; Daily Credit Intelligence &nbsp;&mdash;&nbsp; {date_str}<br>
    Credit Strategy &amp; Surveillance Desk &nbsp;&bull;&nbsp; Jitendra.Meghrajani@careedge.in<br>
    <em>&#128274; Confidential &mdash; Internal Use Only. Not for external distribution.</em>
  </footer>

</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Publish webpage to docs/index.html and push to main
# ---------------------------------------------------------------------------

def publish_webpage(html: str, today: datetime.date) -> bool:
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    docs_dir = os.path.join(base, "docs")
    os.makedirs(docs_dir, exist_ok=True)
    index_path = os.path.join(docs_dir, "index.html")

    with open(index_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[publish] Wrote {len(html):,} chars to docs/index.html")

    try:
        date_str = today.strftime("%d %b %Y")
        subprocess.run(["git", "-C", base, "config", "user.email", "actions@github.com"], check=True)
        subprocess.run(["git", "-C", base, "config", "user.name", "GitHub Actions"], check=True)
        subprocess.run(["git", "-C", base, "add", "docs/index.html"], check=True)
        result = subprocess.run(
            ["git", "-C", base, "diff", "--cached", "--quiet"],
            capture_output=True
        )
        if result.returncode == 0:
            print("[publish] No changes to docs/index.html — skipping commit")
            return True
        subprocess.run(
            ["git", "-C", base, "commit", "-m", f"Daily Credit Intelligence Report — {date_str}"],
            check=True
        )
        subprocess.run(
            ["git", "-C", base, "push", "origin", "HEAD:main"],
            check=True
        )
        print(f"[publish] Pushed to main — live at {_PAGES_URL}")
        return True
    except subprocess.CalledProcessError as exc:
        print(f"[publish] Git push failed: {exc}")
        return False


# ---------------------------------------------------------------------------
# Email sender — compact notification with "view online" link
# ---------------------------------------------------------------------------

def send_email(subject: str, html_body: str, gmail_user: str, gmail_password: str) -> None:
    recipients = _get_recipients()
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_password)
        server.sendmail(gmail_user, recipients, msg.as_string())
        print(f"Email sent to {', '.join(recipients)}")


def build_email(today: datetime.date) -> str:
    date_str = today.strftime("%d %B %Y")
    dow = today.strftime("%A")
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:20px 0;background:#e8e8e8;font-family:Arial,sans-serif;">
<div style="max-width:560px;margin:0 auto;background:#fff;border-top:5px solid #c00;box-shadow:0 2px 8px rgba(0,0,0,.15);">
  <div style="padding:24px 28px 20px;">
    <p style="margin:0 0 4px;font-size:10px;letter-spacing:2px;text-transform:uppercase;color:#888;">{dow}, {date_str}</p>
    <p style="margin:0 0 16px;font-size:24px;font-weight:900;color:#1a1a1a;font-family:Georgia,serif;letter-spacing:-0.5px;">CareEdge Credit Intelligence</p>
    <p style="margin:0 0 20px;font-size:13px;color:#555;line-height:1.6;">Your daily credit &amp; markets briefing is ready. Open the full newspaper-style report in your browser:</p>
    <table cellpadding="0" cellspacing="0"><tr><td style="background:#c00;border-radius:3px;">
      <a href="{_PAGES_URL}" target="_blank" style="display:block;padding:12px 28px;font-size:13px;font-weight:700;color:#fff;text-decoration:none;letter-spacing:0.5px;">View Full Report &#8594;</a>
    </td></tr></table>
    <p style="margin:16px 0 0;font-size:10px;color:#aaa;">Or copy: {_PAGES_URL}</p>
  </div>
  <div style="background:#1a1a1a;padding:12px 28px;font-size:10px;color:#666;text-align:center;line-height:1.9;">
    <strong style="color:#c00;">CareEdge Ratings</strong> &nbsp;&mdash;&nbsp; Credit Strategy &amp; Surveillance Desk<br>
    <em style="color:#555;">Confidential &mdash; Internal Use Only</em>
  </div>
</div>
</body></html>"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    gmail_user = os.environ["GMAIL_USER"]
    gmail_password = os.environ["GMAIL_APP_PASSWORD"]
    anthropic_api_key = os.environ["ANTHROPIC_API_KEY"]
    newsapi_key = os.environ.get("NEWSAPI_KEY", "")

    today = datetime.date.today()
    subject = f"CareEdge Credit Intelligence — {today.strftime('%d %B %Y')}"

    print("Fetching news...")
    news_text = fetch_all_news(newsapi_key)
    print(f"Fetched {news_text.count(chr(10)) + 1} news items.")

    print("Calling Claude API to generate report...")
    inner_html = generate_report(news_text, today, anthropic_api_key)

    print("Building webpage...")
    webpage = build_webpage(inner_html, today)

    print("Publishing to GitHub Pages...")
    publish_webpage(webpage, today)

    print("Sending email notification...")
    email_html = build_email(today)
    send_email(subject, email_html, gmail_user, gmail_password)


if __name__ == "__main__":
    main()
