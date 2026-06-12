#!/usr/bin/env python3
"""
Daily Credit Intelligence Report — fully dynamic, AI-generated.
1. Fetches live news from RBI, SEBI, Google News, NewsAPI, Telegram, Web.
2. Sends news to Claude API which generates the full credit analysis.
3. Wraps in newspaper-style HTML email and sends via Gmail SMTP.

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
# Prompt builder — Claude outputs inline-style HTML body for email
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
WATCHLIST items (tagged [WATCHLIST — Company]) are HIGHEST PRIORITY — always first.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT — NEWSPAPER-STYLE EMAIL HTML
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Output ONLY raw HTML. No markdown. No html/head/body tags.
ALL styles must be inline (no class names, no <style> tags — email clients strip them).

════════════════════════
PART A — BREAKING TICKER + LEAD GRID
════════════════════════

Breaking ticker (top headline, 1 line):
<table width="100%" cellpadding="0" cellspacing="0" style="border-top:3px solid #cc0000;border-bottom:1px solid #e5e5e5;background:#fff8f8;margin-bottom:0;">
<tr>
  <td width="90" style="padding:7px 12px 7px 16px;font-size:9px;font-weight:800;letter-spacing:3px;text-transform:uppercase;color:#cc0000;border-right:1px solid #e5e5e5;white-space:nowrap;">&#9642; BREAKING</td>
  <td style="padding:7px 14px;font-size:12px;font-weight:600;color:#1a1a1a;line-height:1.4;">SINGLE LINE SUMMARY OF TOP STORY</td>
</tr>
</table>

Lead stories grid (watchlist story gets the wide left column):
<table width="100%" cellpadding="0" cellspacing="0" style="border-bottom:2px solid #1a1a1a;margin-bottom:0;">
<tr valign="top">

  <!-- LEAD STORY left (wide) -->
  <td width="52%" style="padding:16px 14px 16px 16px;border-right:1px solid #ddd;">
    <p style="margin:0 0 4px 0;font-size:9px;font-weight:800;letter-spacing:2px;text-transform:uppercase;color:#cc0000;">WATCHLIST · COMPANY or SECTION</p>
    <p style="margin:0 0 8px 0;font-size:18px;font-weight:900;color:#1a1a1a;line-height:1.25;font-family:Georgia,serif;">Full headline of the lead story</p>
    <p style="margin:0 0 10px 0;font-size:12px;color:#444;line-height:1.75;font-family:Georgia,serif;">2-3 sentence factual summary.</p>
    <table width="100%" cellpadding="0" cellspacing="0" style="background:#fef2f2;border-left:3px solid #cc0000;margin-bottom:10px;">
    <tr><td style="padding:8px 12px;">
      <p style="margin:0 0 3px 0;font-size:9px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:#cc0000;">&#9888; CREDIT IMPLICATION</p>
      <p style="margin:0;font-size:12px;color:#374151;line-height:1.65;">2-3 sentences on rating/liquidity/asset quality impact.</p>
    </td></tr>
    </table>
    <p style="margin:0;font-size:11px;"><a href="ACTUAL_URL" target="_blank" style="color:#cc0000;font-weight:700;text-decoration:none;">Read full story &#8594;</a> &nbsp;<span style="color:#999;font-size:10px;">Source Name</span></p>
  </td>

  <!-- Right column: story 2 top, story 3 bottom -->
  <td width="48%" style="padding:0;vertical-align:top;">
    <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td style="padding:12px 16px 10px 14px;border-bottom:1px solid #ddd;">
      <p style="margin:0 0 3px 0;font-size:9px;font-weight:800;letter-spacing:2px;text-transform:uppercase;color:#cc0000;">SECTION TAG</p>
      <p style="margin:0 0 6px 0;font-size:14px;font-weight:800;color:#1a1a1a;line-height:1.3;font-family:Georgia,serif;">Headline story 2</p>
      <p style="margin:0 0 7px 0;font-size:12px;color:#444;line-height:1.65;">1-2 sentence summary.</p>
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#fffbeb;border-left:3px solid #d97706;margin-bottom:7px;">
      <tr><td style="padding:6px 10px;font-size:11px;color:#374151;line-height:1.6;">Credit implication in 1-2 sentences.</td></tr>
      </table>
      <p style="margin:0;font-size:11px;"><a href="ACTUAL_URL" target="_blank" style="color:#cc0000;font-weight:700;text-decoration:none;">Read more &#8594;</a> &nbsp;<span style="color:#999;font-size:10px;">Source</span></p>
    </td></tr>
    <tr><td style="padding:12px 16px 14px 14px;">
      <p style="margin:0 0 3px 0;font-size:9px;font-weight:800;letter-spacing:2px;text-transform:uppercase;color:#cc0000;">SECTION TAG</p>
      <p style="margin:0 0 6px 0;font-size:14px;font-weight:800;color:#1a1a1a;line-height:1.3;font-family:Georgia,serif;">Headline story 3</p>
      <p style="margin:0 0 7px 0;font-size:12px;color:#444;line-height:1.65;">1-2 sentence summary.</p>
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#f0fdf4;border-left:3px solid #16a34a;margin-bottom:7px;">
      <tr><td style="padding:6px 10px;font-size:11px;color:#374151;line-height:1.6;">Credit implication in 1-2 sentences.</td></tr>
      </table>
      <p style="margin:0;font-size:11px;"><a href="ACTUAL_URL" target="_blank" style="color:#cc0000;font-weight:700;text-decoration:none;">Read more &#8594;</a> &nbsp;<span style="color:#999;font-size:10px;">Source</span></p>
    </td></tr>
    </table>
  </td>

</tr>
</table>

════════════════════════
PART B — 5 SECTION PAGES
════════════════════════
For each of the 5 sections output a block. Include ALL items NOT in Part A leads. Show all 5 sections.

Section routing:
  S1 — [WATCHLIST — CompanyName] items ONLY
  S2 — NBFC, HFC, Banking, Broking, Fintech, MFI, rating actions
  S3 — RBI, SEBI, NHB regulatory items
  S4 — Bonds, CP, Securitisation, FIMMDA, CCIL market items
  S5 — Macro: GDP, CPI, IIP, forex, fiscal deficit, US Fed, global

Section header (use exact bg colour per section):
S1: <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:12px;"><tr><td style="background:#cc0000;padding:7px 16px;font-size:9px;font-weight:800;letter-spacing:3px;text-transform:uppercase;color:#fff;">&#9733; SECTION 1 &mdash; MY RATED ENTITIES &amp; WATCHLIST</td></tr></table>
S2: <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:12px;"><tr><td style="background:#b45309;padding:7px 16px;font-size:9px;font-weight:800;letter-spacing:3px;text-transform:uppercase;color:#fff;">SECTION 2 &mdash; NBFC, HFC, BROKING, FINTECH, FI</td></tr></table>
S3: <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:12px;"><tr><td style="background:#1e3a8a;padding:7px 16px;font-size:9px;font-weight:800;letter-spacing:3px;text-transform:uppercase;color:#fff;">SECTION 3 &mdash; RBI, SEBI, NHB REGULATIONS</td></tr></table>
S4: <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:12px;"><tr><td style="background:#15803d;padding:7px 16px;font-size:9px;font-weight:800;letter-spacing:3px;text-transform:uppercase;color:#fff;">SECTION 4 &mdash; BOND &amp; MONEY MARKETS</td></tr></table>
S5: <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:12px;"><tr><td style="background:#6d28d9;padding:7px 16px;font-size:9px;font-weight:800;letter-spacing:3px;text-transform:uppercase;color:#fff;">SECTION 5 &mdash; MACROECONOMIC DEVELOPMENTS</td></tr></table>

After each header, list every article as a compact row (one per line, no column splitting):
<table width="100%" cellpadding="0" cellspacing="0">
<tr><td style="padding:8px 16px;border-bottom:1px solid #f0f0f0;">
  <span style="font-size:9px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#999;">SOURCE</span>
  &nbsp;&nbsp;<a href="URL" target="_blank" style="font-size:13px;font-weight:700;color:#1a1a1a;text-decoration:none;font-family:Georgia,serif;">HEADLINE</a>
  &nbsp;&mdash;&nbsp;<span style="font-size:11px;color:#cc0000;font-style:italic;">Credit angle in one phrase.</span>
</td></tr>
<!-- repeat one <tr> per article -->
</table>

Empty section: <p style="padding:8px 16px;font-size:11px;color:#aaa;font-style:italic;margin:0;">No news in this category today.</p>

════════════════════════
PART C — TOP 5 BRIEFING BAR
════════════════════════
<table width="100%" cellpadding="0" cellspacing="0" style="margin-top:12px;background:#1a1a1a;">
<tr><td style="padding:8px 16px;font-size:9px;font-weight:800;letter-spacing:3px;text-transform:uppercase;color:#fff;">&#9679; TODAY'S TOP 5 CREDIT BRIEFING</td></tr>
</table>
<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e5e5e5;border-top:none;">
<tr valign="top">
  <td style="padding:10px 8px 10px 16px;font-size:28px;font-weight:900;color:#cc0000;line-height:1;font-family:Georgia,serif;width:44px;">01</td>
  <td style="padding:10px 16px 10px 0;border-bottom:1px solid #f0f0f0;">
    <p style="margin:0 0 2px 0;font-size:9px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:#777;">S1 / TOPIC</p>
    <p style="margin:0;font-size:12px;color:#1a1a1a;line-height:1.6;">One sharp credit insight.</p>
  </td>
</tr>
<tr valign="top">
  <td style="padding:10px 8px 10px 16px;font-size:28px;font-weight:900;color:#cc0000;line-height:1;font-family:Georgia,serif;">02</td>
  <td style="padding:10px 16px 10px 0;border-bottom:1px solid #f0f0f0;">
    <p style="margin:0 0 2px 0;font-size:9px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:#777;">S2 / TOPIC</p>
    <p style="margin:0;font-size:12px;color:#1a1a1a;line-height:1.6;">One sharp credit insight.</p>
  </td>
</tr>
<tr valign="top">
  <td style="padding:10px 8px 10px 16px;font-size:28px;font-weight:900;color:#cc0000;line-height:1;font-family:Georgia,serif;">03</td>
  <td style="padding:10px 16px 10px 0;border-bottom:1px solid #f0f0f0;">
    <p style="margin:0 0 2px 0;font-size:9px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:#777;">S3 / TOPIC</p>
    <p style="margin:0;font-size:12px;color:#1a1a1a;line-height:1.6;">One sharp credit insight.</p>
  </td>
</tr>
<tr valign="top">
  <td style="padding:10px 8px 10px 16px;font-size:28px;font-weight:900;color:#cc0000;line-height:1;font-family:Georgia,serif;">04</td>
  <td style="padding:10px 16px 10px 0;border-bottom:1px solid #f0f0f0;">
    <p style="margin:0 0 2px 0;font-size:9px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:#777;">S4 / TOPIC</p>
    <p style="margin:0;font-size:12px;color:#1a1a1a;line-height:1.6;">One sharp credit insight.</p>
  </td>
</tr>
<tr valign="top">
  <td style="padding:10px 8px 10px 16px;font-size:28px;font-weight:900;color:#cc0000;line-height:1;font-family:Georgia,serif;">05</td>
  <td style="padding:10px 16px 10px 0;">
    <p style="margin:0 0 2px 0;font-size:9px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:#777;">S5 / TOPIC</p>
    <p style="margin:0;font-size:12px;color:#1a1a1a;line-height:1.6;">One sharp credit insight.</p>
  </td>
</tr>
</table>

CRITICAL RULES:
- Use ACTUAL URLs from "| URL:" in input. Omit <a> entirely if no URL given.
- ALL styles inline. No class names. No <style> blocks.
- Do NOT output html/head/body tags, masthead, or any outer wrapper.
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
            max_tokens=16000,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text
    except Exception as exc:
        print(f"[generate_report] Claude API error: {exc}")
        return f"""
<table width="100%" cellpadding="0" cellspacing="0">
<tr><td style="padding:24px;background:#fff5f5;border:2px solid #cc0000;">
  <p style="margin:0 0 8px 0;font-size:15px;font-weight:700;color:#cc0000;">&#9888; Report Generation Failed</p>
  <p style="margin:0;font-size:13px;color:#374151;">Claude API call failed. Check GitHub Actions logs.</p>
  <p style="margin:8px 0 0 0;font-size:11px;color:#888;">Error: {str(exc)[:400]}</p>
</td></tr>
</table>"""


# ---------------------------------------------------------------------------
# HTML email wrapper — newspaper masthead + inner content
# ---------------------------------------------------------------------------

def build_html(inner_html: str, today: datetime.date) -> str:
    date_str = today.strftime("%d %B %Y")
    dow = today.strftime("%A, %d %B %Y").upper()

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="light">
</head>
<body style="margin:0;padding:14px 0;background:#d0d0d0;font-family:Arial,Helvetica,sans-serif;-webkit-text-size-adjust:100%;">
<div style="max-width:680px;margin:0 auto;background:#ffffff;box-shadow:0 2px 10px rgba(0,0,0,0.2);">

<!-- RED ACCENT BAR -->
<table width="100%" cellpadding="0" cellspacing="0"><tr><td style="background:#cc0000;height:5px;font-size:0;line-height:0;">&nbsp;</td></tr></table>

<!-- MASTHEAD -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-bottom:3px solid #1a1a1a;">
<tr><td style="padding:12px 20px 8px 20px;">
  <p style="margin:0 0 3px 0;font-size:9px;letter-spacing:2px;text-transform:uppercase;color:#999;">{dow} &nbsp;&bull;&nbsp; INTERNAL USE ONLY &nbsp;&bull;&nbsp; CAREEDGE RATINGS</p>
  <p style="margin:0;font-size:34px;font-weight:900;color:#1a1a1a;letter-spacing:-1px;line-height:1;font-family:Georgia,'Times New Roman',serif;">CareEdge Credit Intelligence</p>
  <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:7px;border-top:1px solid #1a1a1a;">
  <tr>
    <td style="padding-top:5px;font-size:10px;font-style:italic;color:#555;font-family:Georgia,serif;">Daily Credit &amp; Markets Briefing &mdash; Credit Strategy &amp; Surveillance Desk</td>
    <td align="right" style="padding-top:5px;font-size:9px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#cc0000;white-space:nowrap;">&#128274; CONFIDENTIAL</td>
  </tr>
  </table>
</td></tr>
</table>

<!-- SECTION NAV BAR -->
<table width="100%" cellpadding="0" cellspacing="0" style="background:#1a1a1a;border-bottom:3px solid #cc0000;">
<tr>
  <td style="padding:7px 10px 7px 20px;font-size:9px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#ffffff;border-right:1px solid #333;">&#9733; WATCHLIST</td>
  <td style="padding:7px 10px;font-size:9px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#bbbbbb;border-right:1px solid #333;">NBFC &amp; FI</td>
  <td style="padding:7px 10px;font-size:9px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#bbbbbb;border-right:1px solid #333;">REGULATIONS</td>
  <td style="padding:7px 10px;font-size:9px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#bbbbbb;border-right:1px solid #333;">MARKETS</td>
  <td style="padding:7px 10px;font-size:9px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#bbbbbb;">MACRO</td>
</tr>
</table>

<!-- REPORT BODY -->
{inner_html}

<!-- FOOTER -->
<table width="100%" cellpadding="0" cellspacing="0" style="margin-top:14px;background:#1a1a1a;">
<tr><td style="padding:14px 20px;text-align:center;font-size:10px;color:#777;line-height:2;">
  <span style="color:#cc0000;font-weight:700;">CareEdge Ratings</span> &nbsp;&mdash;&nbsp; Daily Credit Intelligence &nbsp;&mdash;&nbsp; {date_str}<br>
  Credit Strategy &amp; Surveillance Desk &nbsp;&bull;&nbsp; Jitendra.Meghrajani@careedge.in<br>
  <span style="font-style:italic;color:#555;">&#128274; Confidential &mdash; Internal Use Only. Not for external distribution.</span>
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
    subject = f"CareEdge Credit Intelligence — {today.strftime('%d %B %Y')}"

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
