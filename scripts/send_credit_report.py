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
    cfg = _load_config()
    sections = cfg.get("sections") or _DEFAULT_SECTIONS
    sections_text = "\n".join(f"{i+1}. {s}" for i, s in enumerate(sections))
    n = len(sections)

    return f"""You are a Senior Credit Strategist at CareEdge Ratings, India's leading credit rating agency.
Today is {day_str}, {date_str}.

Below are today's live news headlines from RBI, SEBI, Indian financial news sources, and company-specific watchlist news (marked [WATCHLIST — Company]):

{news_text}

Generate a complete Daily Credit Intelligence Report. Use ONLY the news provided above. If a section has no relevant news, write "No significant developments today."

PART 1 — MAIN REPORT (10 sections)
Cover these {n} sections:
{sections_text}

For EACH news item provide:
- Rank it: CRITICAL / IMPORTANT / WATCHLIST
- What Happened (2-3 sentences, factual)
- Credit Implications (3-5 bullet points)
- Source (publication name)

For any [WATCHLIST — CompanyName] headlines, make sure to include them under the relevant section with the company name highlighted.

PART 2 — ANALYST DEVELOPMENT
Pick ONE credit concept relevant to today's news. Write a 200-word educational note covering:
- What the concept is
- Why it matters today (link to a specific news item)
- 3 key things an analyst should check

PART 3 — TOP 10 THINGS A RATING ANALYST SHOULD KNOW TODAY
Write exactly 10 points. Each point must:
- Reference a specific news item from today
- Be tagged to a section (e.g. RBI / Banking / NBFC)
- Give one clear, actionable insight

Return ONLY inner HTML using these exact CSS classes (no html/head/body tags):

Section structure:
<p class="section-label critical-label">&#9888; Critical</p>
<div class="content">
  <div class="item">
    <p class="item-title">TITLE HERE</p>
    <p class="item-sector">SECTOR &nbsp;|&nbsp; <span class="badge badge-red">Critical</span></p>
    <p class="sub-heading">What Happened</p>
    <p>...</p>
    <p class="sub-heading">Credit Implications</p>
    <ul class="impl-list"><li>...</li><li>...</li></ul>
    <div class="source-block">&#128279; Source: publication name</div>
  </div>
</div>

For Important items use: important-label and badge-amber
For Watchlist items use: watchlist-label and badge-blue

Analyst Development section:
<p class="section-label analyst-label">&#128218; Analyst Development — [Topic]</p>
<div class="content"><div class="item">
  <p class="item-title">[Topic Title]</p>
  <p>Content here...</p>
</div></div>

Top 10 section:
<p class="section-label top10-label">&#127942; Top 10 Things to Know Today</p>
<div class="content"><div class="item">
  <div class="top10-item"><div class="top10-num">1</div><div class="top10-text"><strong>SECTION — Title</strong> Actionable insight paragraph.</div></div>
  <div class="top10-item"><div class="top10-num">2</div><div class="top10-text"><strong>SECTION — Title</strong> Actionable insight paragraph.</div></div>
  ... (all 10)
</div></div>

Badge colours: badge-red=Critical/Negative, badge-amber=Important, badge-blue=Watchlist/Neutral, badge-green=Positive"""


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

    # Trim news to max 10000 chars — enough for all sources including watchlist
    if len(news_text) > 10000:
        news_text = news_text[:10000] + "\n[...truncated for length]"

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
  /* ── TOP 10 ── */
  .top10-item {{
    display: flex;
    gap: 16px;
    padding: 14px 0;
    border-bottom: 1px solid #f1f5f9;
    align-items: flex-start;
  }}
  .top10-item:last-child {{ border-bottom: none; }}
  .top10-num {{
    font-size: 22px;
    font-weight: 700;
    color: #8b5cf6;
    min-width: 32px;
    line-height: 1.2;
    flex-shrink: 0;
  }}
  .top10-text {{
    font-size: 13.5px;
    line-height: 1.7;
    color: #475569;
  }}
  .top10-text strong {{
    color: #0f172a;
    display: block;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    margin-bottom: 4px;
  }}
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
