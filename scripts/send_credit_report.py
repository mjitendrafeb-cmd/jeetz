#!/usr/bin/env python3
"""
Daily Credit Intelligence Report — fully dynamic, AI-generated.
1. Fetches live news from RBI, SEBI, Google News, and NewsAPI.
2. Sends news to Claude API which generates the full credit analysis.
3. Wraps in HTML email template and sends via Gmail SMTP.

Reads env vars: GMAIL_USER, GMAIL_APP_PASSWORD, ANTHROPIC_API_KEY, NEWSAPI_KEY (optional).
"""

import os
import json
import smtplib
import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import anthropic


def _load_config() -> dict:
    """Load config.json from repo root. Returns empty dict on failure."""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, "config.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

from fetch_news import fetch_all_news


_FALLBACK_RECIPIENT = "Jitendra.Meghrajani@careedge.in"


def _get_recipients() -> list[str]:
    cfg = _load_config()
    # Support both single recipient and list
    if cfg.get("recipients"):
        return cfg["recipients"]
    if cfg.get("recipient"):
        return [cfg["recipient"]]
    return [_FALLBACK_RECIPIENT]


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

_DEFAULT_SECTIONS = [
    "RBI Developments",
    "SEBI Developments",
    "Banking System Developments",
    "NBFC Sector Developments",
    "Housing Finance Developments",
    "Broking & Fintech Developments",
    "Bond Market Developments",
    "Commercial Paper Market Developments",
    "Securitisation Developments",
    "Rating Actions Announced",
]


def _build_prompt(news_text: str, day_str: str, date_str: str) -> str:
    return f"""You are a Credit Rating Intelligence Agent at CareEdge Ratings.
Today is {day_str}, {date_str}.

NEWS ITEMS (each may include a source URL after "| URL:"):

{news_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YOUR OBJECTIVE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
You are NOT summarising news. You are identifying developments that could affect:
1. Rating outlook  2. Liquidity  3. Funding access  4. Asset quality
5. Capitalisation  6. Governance  7. Earnings stability

PRIORITY ORDER (process in this sequence):
P1 — Rated entities and watchlist ([WATCHLIST — Company] items)
P2 — NBFC, HFC, Broking, Fintech, FI sector developments
P3 — RBI, SEBI, NHB regulations
P4 — Bond and money markets
P5 — Macroeconomic developments

IGNORE COMPLETELY (do not include):
Product launches · CSR activities · Marketing announcements · Awards ·
Generic business news · Stock recommendations · Market gossip

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Organise into these five sections. Only include a section if there is relevant news.

🔴 RATED ENTITIES   (P1 — watchlist companies)
🟠 SECTOR DEVELOPMENTS   (P2 — NBFC / HFC / Broking / Fintech / FI)
🟣 REGULATIONS   (P3 — RBI / SEBI / NHB)
🔵 BOND & FUNDING MARKETS   (P4)
⚫ MACRO   (P5)

For EACH item within a section:

[RANK] — Critical / Important / Watchlist

NEWS
2–3 lines. What happened. Facts only. No background, no history.

→ IMPLICATION
2–3 lines. Why it matters for credit — rating, liquidity, asset quality, funding, governance, or capitalisation. No generic statements.

[Source: Publication Name] <a href="URL" target="_blank" style="color:#4299e1;text-decoration:none;">↗</a>

(Only include the link if a URL was provided after "| URL:" in the news item. Never invent a URL.)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
END WITH
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📌 TOP 5 THINGS TO KNOW TODAY
Exactly 5 points. One line each. Most critical first. Reference the section (e.g. 🔴 / 🟠 / 🟣).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HTML RENDERING RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Return ONLY inner HTML (no html/head/body tags). Use these CSS classes:

Section header:
<p class="section-label critical-label">🔴 RATED ENTITIES</p>
(use critical-label for 🔴, important-label for 🟠, watchlist-label for 🟣, analyst-label for 🔵, top10-label for ⚫)

Each item:
<div class="content"><div class="item">
  <p class="item-sector"><span class="badge badge-red">Critical</span> &nbsp; COMPANY / SECTOR</p>
  <p class="item-title">HEADLINE</p>
  <p class="sub-heading">News</p>
  <p>2–3 line factual summary.</p>
  <p class="sub-heading">Implication</p>
  <p>2–3 line credit implication.</p>
  <div class="source-block">&#128279; Publication &nbsp;<a href="URL" target="_blank" style="color:#4299e1;text-decoration:none;">Read more ↗</a></div>
</div></div>

Badge classes: badge-red=Critical · badge-amber=Important · badge-blue=Watchlist

Top 5 section:
<p class="section-label top10-label">📌 Top 5 Things To Know Today</p>
<div class="content"><div class="item">
  <div class="top10-item"><div class="top10-num">1</div><div class="top10-text">🔴 <strong>Company/Topic</strong> — one-line insight.</div></div>
  ... (all 5)
</div></div>"""


# ---------------------------------------------------------------------------
# Claude API call
# ---------------------------------------------------------------------------

def generate_report(news_text: str, today: datetime.date, api_key: str) -> str:
    """
    Call Claude API with the news text and return inner HTML for the report body.
    Returns a fallback HTML fragment on failure.
    """
    day_str = today.strftime("%A")
    date_str = today.strftime("%d %B %Y")

    # Trim news — larger limit now that we fetch more targeted items
    if len(news_text) > 18000:
        news_text = news_text[:18000] + "\n[...truncated for length]"

    prompt = _build_prompt(news_text, day_str, date_str)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=8000,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text
    except Exception as exc:
        print(f"[generate_report] Claude API error: {exc}")
        return f"""
<p class="section-label critical-label">&#9888; Report Generation Failed</p>
<div class="content">
  <div class="item">
    <p class="item-title">Automated Report Could Not Be Generated Today</p>
    <p class="item-sector">SYSTEM &nbsp;|&nbsp; <span class="badge badge-red">Error</span></p>
    <p>The Claude API call failed during report generation. Please check GitHub Actions logs for details.</p>
    <p>Error details: {str(exc)[:500]}</p>
    <p>News was fetched successfully. You may review the raw news below or re-trigger the workflow manually.</p>
    <div class="source-block">&#128279; Check: GitHub Actions → Daily Credit Intelligence Report → Latest run → Logs</div>
  </div>
</div>
"""


# ---------------------------------------------------------------------------
# HTML wrapper
# ---------------------------------------------------------------------------

def build_html(inner_html: str, today: datetime.date) -> str:
    date_str = today.strftime("%d %B %Y")
    day_str = today.strftime("%A")

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  body {{
    font-family: 'Inter', 'Segoe UI', Arial, sans-serif;
    background: #eef2f7;
    margin: 0; padding: 20px 0;
    color: #1e293b;
  }}
  .wrapper {{
    max-width: 700px;
    margin: 0 auto;
    background: #ffffff;
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 4px 24px rgba(0,0,0,0.10);
  }}
  /* ── HEADER ── */
  .header {{
    background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 100%);
    color: #ffffff;
    padding: 32px 40px 24px;
  }}
  .header-top {{
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 12px;
  }}
  .header h1 {{
    margin: 0 0 6px 0;
    font-size: 20px;
    font-weight: 700;
    letter-spacing: 0.5px;
    text-transform: uppercase;
  }}
  .header .date {{
    font-size: 13px;
    color: #94a3b8;
    margin: 0;
    font-weight: 400;
  }}
  .header-badge {{
    background: rgba(255,255,255,0.1);
    color: #cbd5e1;
    font-size: 10px;
    font-weight: 600;
    padding: 4px 10px;
    border-radius: 20px;
    white-space: nowrap;
    letter-spacing: 0.5px;
  }}
  .header .tagline {{
    font-size: 10px;
    color: #475569;
    margin-top: 16px;
    padding-top: 12px;
    border-top: 1px solid rgba(255,255,255,0.08);
    letter-spacing: 0.3px;
  }}
  /* ── SECTION LABELS ── */
  .section-label {{
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
    padding: 10px 40px;
    margin: 0;
    display: flex;
    align-items: center;
    gap: 8px;
  }}
  .critical-label  {{ background: #fef2f2; color: #b91c1c; border-left: 3px solid #ef4444; }}
  .important-label {{ background: #fffbeb; color: #92400e; border-left: 3px solid #f59e0b; }}
  .watchlist-label {{ background: #eff6ff; color: #1d4ed8; border-left: 3px solid #3b82f6; }}
  .analyst-label   {{ background: #f0fdf4; color: #15803d; border-left: 3px solid #22c55e; }}
  .top10-label     {{ background: #faf5ff; color: #6d28d9; border-left: 3px solid #8b5cf6; }}
  /* ── CONTENT AREA ── */
  .content {{ padding: 0 40px; }}
  .item {{
    padding: 22px 0;
    border-bottom: 1px solid #f1f5f9;
  }}
  .item:last-child {{ border-bottom: none; }}
  .item-title {{
    font-size: 15px;
    font-weight: 700;
    color: #0f172a;
    margin: 0 0 6px 0;
    line-height: 1.4;
  }}
  .item-sector {{
    font-size: 11px;
    color: #94a3b8;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    margin: 0 0 14px 0;
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }}
  .item p {{
    font-size: 13.5px;
    line-height: 1.75;
    color: #475569;
    margin: 0 0 12px 0;
  }}
  .sub-heading {{
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: #64748b;
    margin: 16px 0 6px 0;
    padding-bottom: 4px;
    border-bottom: 1px solid #f1f5f9;
  }}
  .impl-list {{
    margin: 6px 0 12px 0;
    padding-left: 18px;
    color: #475569;
    font-size: 13.5px;
    line-height: 1.8;
  }}
  .impl-list li {{ margin-bottom: 4px; }}
  /* ── BADGES ── */
  .badge {{
    display: inline-flex;
    align-items: center;
    font-size: 10px;
    font-weight: 600;
    padding: 3px 8px;
    border-radius: 20px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }}
  .badge-red   {{ background: #fee2e2; color: #b91c1c; }}
  .badge-amber {{ background: #fef3c7; color: #92400e; }}
  .badge-green {{ background: #dcfce7; color: #15803d; }}
  .badge-blue  {{ background: #dbeafe; color: #1d4ed8; }}
  /* ── SOURCE BLOCK ── */
  .source-block {{
    font-size: 11px;
    color: #94a3b8;
    margin-top: 12px;
    padding: 8px 12px;
    background: #f8fafc;
    border-radius: 6px;
    border-left: 3px solid #e2e8f0;
  }}
  /* ── TOP 5 / TOP 10 ── */
  .top10-item {{
    display: flex;
    gap: 14px;
    padding: 12px 0;
    border-bottom: 1px solid #f1f5f9;
    align-items: flex-start;
  }}
  .top10-item:last-child {{ border-bottom: none; }}
  .top10-num {{
    font-size: 20px;
    font-weight: 800;
    color: #8b5cf6;
    min-width: 28px;
    line-height: 1.2;
    flex-shrink: 0;
  }}
  .top10-text {{
    font-size: 13.5px;
    line-height: 1.7;
    color: #475569;
  }}
  .top10-text strong {{ color: #0f172a; }}
  /* ── FOOTER ── */
  .footer {{
    background: #0f172a;
    color: #475569;
    font-size: 11px;
    padding: 20px 40px;
    text-align: center;
    line-height: 2;
  }}
  .footer a {{ color: #64748b; text-decoration: none; }}
</style>
</head>
<body>
<div class="wrapper">

  <!-- HEADER -->
  <div class="header">
    <div class="header-top">
      <div>
        <h1>Daily Credit Intelligence</h1>
        <p class="date">{day_str}, {date_str} &nbsp;·&nbsp; CareEdge Ratings</p>
      </div>
      <span class="header-badge">Credit Strategy Desk</span>
    </div>
    <p class="tagline">CONFIDENTIAL — INTERNAL USE ONLY &nbsp;·&nbsp; Not for external distribution &nbsp;·&nbsp; All rating decisions subject to formal committee process</p>
  </div>

  {inner_html}

  <!-- FOOTER -->
  <div class="footer">
    Daily Credit Intelligence &nbsp;|&nbsp; {date_str} &nbsp;|&nbsp; CareEdge Ratings<br>
    Credit Strategy &amp; Surveillance Desk &nbsp;|&nbsp; Jitendra.Meghrajani@careedge.in<br>
    <br>
    <em>Confidential — Internal Use Only. Not for external distribution.<br>
    This report is auto-generated and delivered via GitHub Actions every weekday at 6:00 AM IST.</em>
  </div>

</div><!-- /wrapper -->
</body>
</html>"""


# ---------------------------------------------------------------------------
# Email sender
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
        print(f"Report sent to {', '.join(recipients)}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    gmail_user = os.environ["GMAIL_USER"]
    gmail_password = os.environ["GMAIL_APP_PASSWORD"]
    anthropic_api_key = os.environ["ANTHROPIC_API_KEY"]
    newsapi_key = os.environ.get("NEWSAPI_KEY", "")

    today = datetime.date.today()
    subject = f"Daily Credit Intelligence — {today.strftime('%d %B %Y')}"

    print("Fetching news...")
    news_text = fetch_all_news(newsapi_key)
    print(f"Fetched {news_text.count(chr(10)) + 1} news items.")

    print("Calling Claude API to generate report...")
    inner_html = generate_report(news_text, today, anthropic_api_key)

    print("Building HTML email...")
    html_body = build_html(inner_html, today)

    print("Sending email...")
    send_email(subject, html_body, gmail_user, gmail_password)


if __name__ == "__main__":
    main()
