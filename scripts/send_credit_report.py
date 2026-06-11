#!/usr/bin/env python3
"""
Daily Credit Intelligence Report — fully dynamic, AI-generated.
1. Fetches live news from RBI, SEBI, Google News, and NewsAPI.
2. Sends news to Claude API which generates the full credit analysis.
3. Wraps in HTML email template and sends via Gmail SMTP.

Reads env vars: GMAIL_USER, GMAIL_APP_PASSWORD, ANTHROPIC_API_KEY, NEWSAPI_KEY (optional).
"""

import os
import smtplib
import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import anthropic

from fetch_news import fetch_all_news


RECIPIENT = "Jitendra.Meghrajani@careedge.in"


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_prompt(news_text: str, day_str: str, date_str: str) -> str:
    return f"""You are a Senior Credit Strategist at CareEdge Ratings, India's leading credit rating agency.
Today is {day_str}, {date_str}.

Below are today's live news headlines from RBI, SEBI, and Indian financial news sources:

{news_text}

Generate a Daily Credit Intelligence Report covering these 10 sections. Use ONLY the news provided above — do not invent events not in the news. If a section has no relevant news, write a short "No significant developments today" note.

Sections to cover:
1. RBI Developments
2. SEBI Developments
3. Banking System Developments
4. NBFC Sector Developments
5. Housing Finance Developments
6. Broking & Fintech Developments
7. Bond Market Developments
8. Commercial Paper Market Developments
9. Securitisation Developments
10. Rating Actions Announced

For EACH news item provide:
- Rank it: CRITICAL / IMPORTANT / WATCHLIST
- What Happened (2-3 sentences, factual)
- Why It Matters (credit significance, 2-3 sentences)
- Credit Implications (3-5 bullet points)
- Impact on 6 dimensions: Liquidity, Capitalisation, Asset Quality, Profitability, Governance, Funding Access — each rated Positive/Negative/Neutral with one-line commentary

End with Top 10 Things a Rating Analyst Should Know Today — each point tagged to a section, one actionable paragraph each.

Return ONLY inner HTML using these exact CSS classes (no html/head/body tags):
- Section headers: <p class="section-label critical-label">...</p> or important-label or watchlist-label
- Items: <div class="item"><p class="item-title">...</p><p class="item-sector">SECTOR | <span class="badge badge-red">Critical</span></p>...
- Sub-headings: <p class="sub-heading">What Happened</p>
- Paragraphs: <p>...</p>
- Impact table: <table class="impact-table"><tr><th>Dimension</th><th>Impact</th><th>Commentary</th></tr><tr><td>Liquidity</td><td><span class="badge badge-red">Negative</span></td><td>explanation</td></tr>...</table>
- Sources: <div class="source-block">&#128279; Source: publication name and context</div>
- Top 10 section: <p class="section-label top10-label">&#127942; Top 10 Things to Know Today</p><div class="content"><div class="item"><div class="top10-item"><div class="top10-num">1</div><div class="top10-text"><strong>SECTION — Title</strong> paragraph</div></div>...</div></div>
- Badge colours: badge-red=Critical/Negative, badge-amber=Important/Mildly Negative, badge-blue=Watchlist/Neutral, badge-green=Positive/Improving

Wrap each section's items in: <div class="content">...</div>"""


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
<style>
  body {{
    font-family: 'Segoe UI', Arial, sans-serif;
    background: #f4f4f4;
    margin: 0; padding: 0;
    color: #1a1a2e;
  }}
  .wrapper {{
    max-width: 780px;
    margin: 24px auto;
    background: #ffffff;
    border-radius: 8px;
    overflow: hidden;
    box-shadow: 0 2px 12px rgba(0,0,0,0.10);
  }}
  .header {{
    background: #1a1a2e;
    color: #ffffff;
    padding: 28px 36px 20px 36px;
  }}
  .header h1 {{
    margin: 0 0 4px 0;
    font-size: 22px;
    letter-spacing: 1px;
    text-transform: uppercase;
  }}
  .header .date {{
    font-size: 13px;
    color: #a0aec0;
    margin: 0;
  }}
  .header .tagline {{
    font-size: 11px;
    color: #718096;
    margin-top: 8px;
    border-top: 1px solid #2d3748;
    padding-top: 10px;
  }}
  .section-label {{
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
    padding: 6px 36px;
    margin: 0;
  }}
  .critical-label  {{ background: #fff5f5; color: #c53030; border-left: 4px solid #c53030; }}
  .important-label {{ background: #fffbeb; color: #b7791f; border-left: 4px solid #d97706; }}
  .watchlist-label {{ background: #ebf8ff; color: #2b6cb0; border-left: 4px solid #3182ce; }}
  .analyst-label   {{ background: #f0fff4; color: #276749; border-left: 4px solid #38a169; }}
  .top10-label     {{ background: #faf5ff; color: #553c9a; border-left: 4px solid #6b46c1; }}
  .content {{ padding: 0 36px; }}
  .item {{
    border-bottom: 1px solid #edf2f7;
    padding: 20px 0;
  }}
  .item:last-child {{ border-bottom: none; }}
  .item-title {{
    font-size: 14px;
    font-weight: 700;
    color: #1a1a2e;
    margin: 0 0 4px 0;
  }}
  .item-sector {{
    font-size: 11px;
    color: #718096;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin: 0 0 10px 0;
  }}
  .item p {{
    font-size: 13px;
    line-height: 1.7;
    color: #4a5568;
    margin: 0 0 10px 0;
  }}
  .sub-heading {{
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    color: #2d3748;
    margin: 12px 0 4px 0;
  }}
  .impact-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
    margin: 10px 0;
  }}
  .impact-table th {{
    background: #f7fafc;
    color: #4a5568;
    font-weight: 600;
    text-align: left;
    padding: 6px 10px;
    border: 1px solid #e2e8f0;
  }}
  .impact-table td {{
    padding: 6px 10px;
    border: 1px solid #e2e8f0;
    vertical-align: top;
    color: #4a5568;
  }}
  .impact-table td:first-child {{
    font-weight: 600;
    color: #2d3748;
    white-space: nowrap;
    width: 130px;
  }}
  .badge {{
    display: inline-block;
    font-size: 10px;
    font-weight: 700;
    padding: 2px 7px;
    border-radius: 4px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-right: 4px;
  }}
  .badge-red    {{ background: #fff5f5; color: #c53030; border: 1px solid #feb2b2; }}
  .badge-amber  {{ background: #fffbeb; color: #b7791f; border: 1px solid #fbd38d; }}
  .badge-green  {{ background: #f0fff4; color: #276749; border: 1px solid #9ae6b4; }}
  .badge-blue   {{ background: #ebf8ff; color: #2b6cb0; border: 1px solid #bee3f8; }}
  .source-link {{
    font-size: 11px;
    color: #4299e1;
    text-decoration: none;
  }}
  .source-block {{
    font-size: 11px;
    color: #718096;
    margin-top: 8px;
    padding: 6px 10px;
    background: #f7fafc;
    border-radius: 4px;
    border-left: 3px solid #cbd5e0;
  }}
  .top10-item {{
    display: flex;
    padding: 10px 0;
    border-bottom: 1px solid #edf2f7;
    font-size: 13px;
    line-height: 1.6;
    color: #4a5568;
  }}
  .top10-num {{
    font-size: 18px;
    font-weight: 700;
    color: #6b46c1;
    min-width: 36px;
    padding-top: 1px;
  }}
  .top10-text strong {{
    color: #1a1a2e;
    display: block;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }}
  .alm-box {{
    background: #f7fafc;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 14px 16px;
    margin: 10px 0;
    font-size: 12px;
    color: #4a5568;
    line-height: 1.8;
  }}
  .alm-box code {{
    font-family: 'Courier New', monospace;
    background: #edf2f7;
    padding: 1px 5px;
    border-radius: 3px;
    font-size: 11px;
    color: #2d3748;
  }}
  .red-flag {{
    color: #c53030;
    font-weight: 600;
  }}
  .green-flag {{
    color: #276749;
    font-weight: 600;
  }}
  .footer {{
    background: #1a1a2e;
    color: #718096;
    font-size: 11px;
    padding: 18px 36px;
    text-align: center;
    line-height: 1.8;
  }}
  .footer a {{ color: #a0aec0; }}
  .divider {{
    height: 1px;
    background: #edf2f7;
    margin: 0;
  }}
</style>
</head>
<body>
<div class="wrapper">

  <!-- HEADER -->
  <div class="header">
    <h1>Daily Credit Intelligence</h1>
    <p class="date">{day_str}, {date_str} &nbsp;|&nbsp; CareEdge Ratings &nbsp;|&nbsp; Credit Strategy Desk</p>
    <p class="tagline">CONFIDENTIAL — INTERNAL USE ONLY &nbsp;|&nbsp; Not for external distribution &nbsp;|&nbsp; All rating decisions subject to formal committee process</p>
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
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = RECIPIENT
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_password)
        server.sendmail(gmail_user, RECIPIENT, msg.as_string())
        print(f"Report sent to {RECIPIENT}")


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
