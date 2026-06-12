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

from fetch_news import fetch_all_news


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
# Prompt builder
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
WATCHLIST items (tagged [WATCHLIST — Company]) are HIGHEST PRIORITY — always appear first.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT — 3 PARTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PART A — TOP 12 HIGHLIGHTS (full analysis cards)
Order: Watchlist items first, then most important across sections.
Each card must use this EXACT HTML (all inline styles, no class names):

<table width="100%" cellpadding="0" cellspacing="0" style="border-bottom:2px solid #e8edf2;">
<tr><td style="padding:18px 24px 14px 24px;">
  <table width="100%" cellpadding="0" cellspacing="0"><tr>
    <td style="font-size:10px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#64748b;">SECTION · SOURCE</td>
    <td align="right" style="font-size:10px;color:#94a3b8;">Publication</td>
  </tr></table>
  <p style="margin:6px 0 12px 0;font-size:16px;font-weight:700;color:#0f172a;line-height:1.4;">COMPANY/TOPIC — HEADLINE</p>
  <table width="100%" cellpadding="0" cellspacing="0">
  <tr valign="top">
    <td width="49%" style="padding:10px 14px 10px 0;border-right:3px solid #e2e8f0;">
      <p style="margin:0 0 5px 0;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#2563eb;">&#128240; What Happened</p>
      <p style="margin:0;font-size:13px;color:#374151;line-height:1.7;">2-3 sentences. Facts only.</p>
    </td>
    <td width="2%"></td>
    <td width="49%" style="padding:10px 0 10px 14px;background:#f8fafc;">
      <p style="margin:0 0 5px 0;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#dc2626;">&#9888; Credit Implication</p>
      <p style="margin:0;font-size:13px;color:#374151;line-height:1.7;">2-3 sentences. Rating/liquidity/asset quality impact.</p>
    </td>
  </tr>
  </table>
  <p style="margin:10px 0 0 0;font-size:12px;"><a href="ACTUAL_URL_FROM_INPUT" target="_blank" style="color:#2563eb;text-decoration:none;font-weight:600;">&#128279; Read full article ↗</a></p>
</td></tr>
</table>
IMPORTANT: Use the actual URL from "| URL:" in the input. Omit the link if no URL was given.

PART B — ALL 5 SECTIONS (remaining items as compact links)
Include every item NOT already shown in Part A. Show ALL 5 sections, even if empty.

Section routing:
  S1 — Only [WATCHLIST — CompanyName] tagged items
  S2 — NBFC, HFC, Banking, Broking, Fintech, MFI, rating actions on companies
  S3 — RBI, SEBI, NHB regulatory items
  S4 — Bonds, CP, Securitisation, FIMMDA, CCIL market items
  S5 — Macro: GDP, CPI, IIP, forex, fiscal deficit, US Fed, global impact on India

Section header HTML (copy exactly):
S1: <div style="background:#fef2f2;border-left:4px solid #ef4444;padding:10px 24px;margin-top:8px;"><span style="font-size:10px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#b91c1c;">&#9733; Section 1 &mdash; My Rated Entities and Watchlist</span></div>
S2: <div style="background:#fffbeb;border-left:4px solid #f59e0b;padding:10px 24px;margin-top:8px;"><span style="font-size:10px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#92400e;">Section 2 &mdash; NBFC, HFC, Broking, Fintech, FI Sectors</span></div>
S3: <div style="background:#eff6ff;border-left:4px solid #3b82f6;padding:10px 24px;margin-top:8px;"><span style="font-size:10px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#1d4ed8;">Section 3 &mdash; RBI, SEBI, NHB Regulations</span></div>
S4: <div style="background:#f0fdf4;border-left:4px solid #22c55e;padding:10px 24px;margin-top:8px;"><span style="font-size:10px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#15803d;">Section 4 &mdash; Bond and Money Markets</span></div>
S5: <div style="background:#faf5ff;border-left:4px solid #8b5cf6;padding:10px 24px;margin-top:8px;"><span style="font-size:10px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#6d28d9;">Section 5 &mdash; Macroeconomic Developments</span></div>

Links after each header:
<div style="padding:4px 24px 8px 24px;"><a href="URL" target="_blank" style="display:block;font-size:13px;color:#1d4ed8;text-decoration:none;padding:7px 0;border-bottom:1px solid #f1f5f9;line-height:1.5;">Headline — Source</a></div>
No URL: <div style="padding:4px 24px 8px 24px;"><span style="display:block;font-size:13px;color:#475569;padding:7px 0;border-bottom:1px solid #f1f5f9;">Headline — Source</span></div>
Empty: <div style="padding:8px 24px;font-size:12px;color:#94a3b8;font-style:italic;">No news today.</div>

PART C — TOP 5 TAKEAWAYS
<div style="background:#0f172a;padding:10px 24px;margin-top:8px;"><span style="font-size:10px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#f1f5f9;">&#128204; Top 5 Things To Know Today</span></div>
<div style="padding:4px 24px 16px 24px;">
<table width="100%" cellpadding="0" cellspacing="0">
<tr valign="top"><td width="36" style="font-size:26px;font-weight:800;color:#8b5cf6;padding:10px 8px 10px 0;">1</td><td style="font-size:13px;color:#374151;line-height:1.65;padding:10px 0;border-bottom:1px solid #f1f5f9;"><strong style="color:#0f172a;">S? / Topic</strong> — one sharp credit insight.</td></tr>
<tr valign="top"><td style="font-size:26px;font-weight:800;color:#8b5cf6;padding:10px 8px 10px 0;">2</td><td style="font-size:13px;color:#374151;line-height:1.65;padding:10px 0;border-bottom:1px solid #f1f5f9;"><strong style="color:#0f172a;">S? / Topic</strong> — one sharp credit insight.</td></tr>
<tr valign="top"><td style="font-size:26px;font-weight:800;color:#8b5cf6;padding:10px 8px 10px 0;">3</td><td style="font-size:13px;color:#374151;line-height:1.65;padding:10px 0;border-bottom:1px solid #f1f5f9;"><strong style="color:#0f172a;">S? / Topic</strong> — one sharp credit insight.</td></tr>
<tr valign="top"><td style="font-size:26px;font-weight:800;color:#8b5cf6;padding:10px 8px 10px 0;">4</td><td style="font-size:13px;color:#374151;line-height:1.65;padding:10px 0;border-bottom:1px solid #f1f5f9;"><strong style="color:#0f172a;">S? / Topic</strong> — one sharp credit insight.</td></tr>
<tr valign="top"><td style="font-size:26px;font-weight:800;color:#8b5cf6;padding:10px 8px 10px 0;">5</td><td style="font-size:13px;color:#374151;line-height:1.65;padding:10px 0;"><strong style="color:#0f172a;">S? / Topic</strong> — one sharp credit insight.</td></tr>
</table>
</div>

Return ONLY the HTML for Parts A, B, C. No masthead. No html/head/body tags. No markdown."""


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
        return f"""
<div style="padding:24px;font-family:Arial,sans-serif;color:#374151;">
  <p style="font-size:16px;font-weight:700;color:#dc2626;">&#9888; Report Generation Failed</p>
  <p>The Claude API call failed. Please check GitHub Actions logs.</p>
  <p style="font-size:12px;color:#6b7280;">Error: {str(exc)[:500]}</p>
</div>
"""


# ---------------------------------------------------------------------------
# HTML wrapper — minimal shell, all design is inline in Claude's output
# ---------------------------------------------------------------------------

def build_html(inner_html: str, today: datetime.date) -> str:
    date_str = today.strftime("%d %B %Y")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="light">
</head>
<body style="margin:0;padding:16px 0;background:#dde3ea;font-family:Arial,Helvetica,sans-serif;-webkit-text-size-adjust:100%;">
<div style="max-width:660px;margin:0 auto;background:#ffffff;border:1px solid #cbd5e1;border-radius:4px;overflow:hidden;">

{inner_html}

<table width="100%" cellpadding="0" cellspacing="0" style="background:#0f172a;margin-top:8px;">
<tr><td style="padding:16px 24px;text-align:center;font-size:11px;color:#64748b;line-height:1.9;">
  Daily Credit Intelligence &nbsp;&middot;&nbsp; {date_str} &nbsp;&middot;&nbsp; CareEdge Ratings<br>
  Credit Strategy &amp; Surveillance Desk &nbsp;&middot;&nbsp; Jitendra.Meghrajani@careedge.in<br>
  <span style="color:#475569;font-style:italic;">Confidential &mdash; Internal Use Only. Not for external distribution.</span>
</td></tr>
</table>

</div>
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
