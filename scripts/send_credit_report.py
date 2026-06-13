#!/usr/bin/env python3
"""
Daily Credit Intelligence Report — AI-generated, dual delivery.
1. Fetches live news from all configured sources.
2. Claude generates HTML for email body (top 5 stories + takeaways) and
   attachment (all 5 sections S1-S5, each item with news + credit implication).
3. Email: compact body + full-report HTML attachment.
4. GitHub Pages: static config/management console (not overwritten by report).
"""

import os
import json
import smtplib
import datetime
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

import anthropic

from fetch_news import fetch_all_news

_PAGES_URL = "https://mjitendrafeb-cmd.github.io/jeetz/"
_CONFIG_URL = "https://mjitendrafeb-cmd.github.io/jeetz/config.html"


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
# Prompt
# ---------------------------------------------------------------------------

def _build_prompt(news_text: str, day_str: str, date_str: str) -> str:
    return f"""You are a Credit Rating Intelligence Agent at CareEdge Ratings.
Today is {day_str}, {date_str}.

NEWS ITEMS below. Each is numbered. Tags: [WATCHLIST — Company], [TELEGRAM — @ch], source names.
URLs follow "| URL:" at end of each line.
ALL items are from the last 48 hours only.

{news_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INCLUDE only items affecting: Rating outlook · Liquidity · Funding · Asset quality · Capitalisation · Governance
SKIP: Product launches · CSR · Awards · Stock tips · Generic M&A · Generic business news
DEDUPLICATE: If two items cover the same story, use only the one with more detail.
WATCHLIST items ([WATCHLIST — Company]) are HIGHEST PRIORITY — always appear first in S1 and Part A.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT — raw HTML, ALL inline styles, NO class names, NO <style> blocks
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

════════════
PART A — TOP 5 LEAD STORIES  (goes in email body only, NOT in attachment)
════════════
Pick the 5 most credit-significant stories. Watchlist entities first.
Use this card for EACH of the 5 stories:

<table width="100%" cellpadding="0" cellspacing="0" style="border-bottom:1px solid #e5e5e5;margin-bottom:0;">
<tr valign="top">
  <td style="padding:14px 16px;">
    <p style="margin:0 0 3px 0;font-size:9px;font-weight:800;letter-spacing:2px;text-transform:uppercase;color:#cc0000;">SECTION · SOURCE</p>
    <p style="margin:0 0 8px 0;font-size:16px;font-weight:800;color:#1a1a1a;line-height:1.3;font-family:Georgia,serif;">HEADLINE</p>
    <table width="100%" cellpadding="0" cellspacing="0"><tr valign="top">
      <td width="50%" style="padding-right:12px;border-right:2px solid #e5e5e5;">
        <p style="margin:0 0 4px 0;font-size:9px;font-weight:800;text-transform:uppercase;letter-spacing:1px;color:#1e3a8a;">WHAT HAPPENED</p>
        <p style="margin:0;font-size:12px;color:#374151;line-height:1.7;">2-3 sentences. Facts only.</p>
      </td>
      <td width="50%" style="padding-left:12px;background:#fef9f9;">
        <p style="margin:0 0 4px 0;font-size:9px;font-weight:800;text-transform:uppercase;letter-spacing:1px;color:#cc0000;">CREDIT IMPLICATION</p>
        <p style="margin:0;font-size:12px;color:#374151;line-height:1.7;">2-3 sentences. Rating/liquidity/asset quality impact.</p>
      </td>
    </tr></table>
    <p style="margin:8px 0 0 0;font-size:11px;"><a href="ACTUAL_URL" target="_blank" style="color:#cc0000;font-weight:700;text-decoration:none;">Read full article &#8594;</a> &nbsp;<span style="font-size:10px;color:#999;">Source</span></p>
  </td>
</tr>
</table>

Omit the link row entirely if no URL available.

════════════
PART B — ALL 5 SECTIONS  (goes in attachment only, NOT in email body)
════════════
Show ALL 5 sections. Items must NOT repeat Part A stories.
Each item appears in EXACTLY ONE section.

Section routing:
  S1 — [WATCHLIST — Company] items ONLY
  S2 — NBFC, HFC, Banking, Broking, Fintech, MFI, rating agency actions
  S3 — RBI, SEBI, NHB regulatory circulars/orders
  S4 — Bonds, G-Sec, CP, Securitisation, FIMMDA, CCIL market items
  S5 — Macro: GDP, CPI, IIP, forex, fiscal deficit, US Fed, global

Section headers — copy EXACTLY (id attributes are required for nav anchors):
S1: <table id="s1" width="100%" cellpadding="0" cellspacing="0" style="margin-top:16px;"><tr><td style="background:#cc0000;padding:7px 16px;font-size:9px;font-weight:800;letter-spacing:3px;text-transform:uppercase;color:#fff;">&#9733; S1 — MY RATED ENTITIES &amp; WATCHLIST</td></tr></table>
S2: <table id="s2" width="100%" cellpadding="0" cellspacing="0" style="margin-top:16px;"><tr><td style="background:#b45309;padding:7px 16px;font-size:9px;font-weight:800;letter-spacing:3px;text-transform:uppercase;color:#fff;">S2 — NBFC, HFC, BROKING, FINTECH, FI SECTORS</td></tr></table>
S3: <table id="s3" width="100%" cellpadding="0" cellspacing="0" style="margin-top:16px;"><tr><td style="background:#1e3a8a;padding:7px 16px;font-size:9px;font-weight:800;letter-spacing:3px;text-transform:uppercase;color:#fff;">S3 — RBI, SEBI, NHB REGULATIONS</td></tr></table>
S4: <table id="s4" width="100%" cellpadding="0" cellspacing="0" style="margin-top:16px;"><tr><td style="background:#15803d;padding:7px 16px;font-size:9px;font-weight:800;letter-spacing:3px;text-transform:uppercase;color:#fff;">S4 — BOND &amp; MONEY MARKETS</td></tr></table>
S5: <table id="s5" width="100%" cellpadding="0" cellspacing="0" style="margin-top:16px;"><tr><td style="background:#6d28d9;padding:7px 16px;font-size:9px;font-weight:800;letter-spacing:3px;text-transform:uppercase;color:#fff;">S5 — MACROECONOMIC DEVELOPMENTS</td></tr></table>

After each section header, one card per article:
<table width="100%" cellpadding="0" cellspacing="0" style="border-bottom:1px solid #f0f0f0;">
<tr valign="top"><td style="padding:10px 16px;">
  <p style="margin:0 0 3px;font-size:9px;font-weight:700;text-transform:uppercase;color:#999;letter-spacing:1px;">SOURCE</p>
  <p style="margin:0 0 7px;font-size:14px;font-weight:800;color:#1a1a1a;font-family:Georgia,serif;line-height:1.3;">HEADLINE</p>
  <table width="100%" cellpadding="0" cellspacing="0"><tr valign="top">
    <td width="50%" style="padding-right:10px;border-right:2px solid #f0f0f0;">
      <p style="margin:0 0 3px;font-size:9px;font-weight:800;text-transform:uppercase;color:#1e3a8a;">WHAT HAPPENED</p>
      <p style="margin:0;font-size:11px;color:#374151;line-height:1.6;">1-2 sentences. Key facts.</p>
    </td>
    <td width="50%" style="padding-left:10px;background:#fef9f9;">
      <p style="margin:0 0 3px;font-size:9px;font-weight:800;text-transform:uppercase;color:#cc0000;">CREDIT IMPLICATION</p>
      <p style="margin:0;font-size:11px;color:#374151;line-height:1.6;">1-2 sentences. Rating/liquidity/asset quality angle.</p>
    </td>
  </tr></table>
  <p style="margin:5px 0 0;font-size:10px;"><a href="URL" target="_blank" style="color:#cc0000;font-weight:700;text-decoration:none;">Source &#8594;</a></p>
</td></tr>
</table>

Omit the link line if no URL. For empty section: <p style="padding:8px 16px;font-size:11px;color:#aaa;font-style:italic;margin:0;">No news in this category today.</p>

════════════
PART C — TOP 5 CREDIT TAKEAWAYS  (goes in email body only, NOT in attachment)
════════════
<table width="100%" cellpadding="0" cellspacing="0" style="margin-top:16px;background:#1a1a1a;">
<tr><td style="padding:8px 16px;font-size:9px;font-weight:800;letter-spacing:3px;text-transform:uppercase;color:#fff;">&#9679; TOP 5 CREDIT TAKEAWAYS FOR TODAY</td></tr>
</table>
<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e5e5e5;border-top:none;">
<tr valign="top">
  <td style="padding:10px 8px 10px 16px;font-size:30px;font-weight:900;color:#cc0000;line-height:1;font-family:Georgia,serif;width:48px;">01</td>
  <td style="padding:10px 16px 10px 4px;border-bottom:1px solid #f0f0f0;">
    <p style="margin:0 0 2px 0;font-size:9px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:#888;">SECTION / TOPIC</p>
    <p style="margin:0;font-size:12px;color:#1a1a1a;line-height:1.65;">One sharp, analyst-grade credit insight.</p>
  </td>
</tr>
<tr valign="top">
  <td style="padding:10px 8px 10px 16px;font-size:30px;font-weight:900;color:#cc0000;line-height:1;font-family:Georgia,serif;">02</td>
  <td style="padding:10px 16px 10px 4px;border-bottom:1px solid #f0f0f0;">
    <p style="margin:0 0 2px 0;font-size:9px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:#888;">SECTION / TOPIC</p>
    <p style="margin:0;font-size:12px;color:#1a1a1a;line-height:1.65;">One sharp credit insight.</p>
  </td>
</tr>
<tr valign="top">
  <td style="padding:10px 8px 10px 16px;font-size:30px;font-weight:900;color:#cc0000;line-height:1;font-family:Georgia,serif;">03</td>
  <td style="padding:10px 16px 10px 4px;border-bottom:1px solid #f0f0f0;">
    <p style="margin:0 0 2px 0;font-size:9px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:#888;">SECTION / TOPIC</p>
    <p style="margin:0;font-size:12px;color:#1a1a1a;line-height:1.65;">One sharp credit insight.</p>
  </td>
</tr>
<tr valign="top">
  <td style="padding:10px 8px 10px 16px;font-size:30px;font-weight:900;color:#cc0000;line-height:1;font-family:Georgia,serif;">04</td>
  <td style="padding:10px 16px 10px 4px;border-bottom:1px solid #f0f0f0;">
    <p style="margin:0 0 2px 0;font-size:9px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:#888;">SECTION / TOPIC</p>
    <p style="margin:0;font-size:12px;color:#1a1a1a;line-height:1.65;">One sharp credit insight.</p>
  </td>
</tr>
<tr valign="top">
  <td style="padding:10px 8px 10px 16px;font-size:30px;font-weight:900;color:#cc0000;line-height:1;font-family:Georgia,serif;">05</td>
  <td style="padding:10px 16px 10px 4px;">
    <p style="margin:0 0 2px 0;font-size:9px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:#888;">SECTION / TOPIC</p>
    <p style="margin:0;font-size:12px;color:#1a1a1a;line-height:1.65;">One sharp credit insight.</p>
  </td>
</tr>
</table>

OUTPUT RULES:
- Real URLs only from "| URL:" — never placeholder text. No <a> if no URL.
- ALL styles inline. No class names. No <style> blocks.
- No html/head/body wrappers.
- Output Parts A, B, C in order. Nothing else."""


# ---------------------------------------------------------------------------
# Claude API call
# ---------------------------------------------------------------------------

def generate_report(news_text: str, today: datetime.date, api_key: str) -> str:
    day_str = today.strftime("%A")
    date_str = today.strftime("%d %B %Y")

    if len(news_text) > 28000:
        news_text = news_text[:28000] + "\n[...truncated]"

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
        return f"""<table width="100%" cellpadding="0" cellspacing="0">
<tr><td style="padding:24px;background:#fff5f5;border:2px solid #cc0000;">
  <p style="margin:0 0 8px;font-size:15px;font-weight:700;color:#cc0000;">&#9888; Report Generation Failed</p>
  <p style="margin:0;font-size:13px;color:#374151;">Error: {str(exc)[:300]}</p>
</td></tr></table>"""


# ---------------------------------------------------------------------------
# Split Claude output into Part A, Part B, Part C
# ---------------------------------------------------------------------------

def split_parts(full_html: str) -> tuple[str, str, str]:
    """Return (part_a, part_b, part_c)."""
    b_match = re.search(
        r'<table[^>]*id=["\']s1["\'][^>]*>|'
        r'<table[^>]*style="[^"]*margin-top:16px[^"]*"[^>]*>\s*<tr>\s*<td[^>]*style="[^"]*background:#cc0000[^"]*"',
        full_html
    )
    c_match = re.search(
        r'<table[^>]*style="[^"]*background:#1a1a1a[^"]*"',
        full_html
    )

    if b_match and c_match and c_match.start() > b_match.start():
        part_a = full_html[:b_match.start()].strip()
        part_b = full_html[b_match.start():c_match.start()].strip()
        part_c = full_html[c_match.start():].strip()
        return part_a, part_b, part_c
    elif b_match:
        part_a = full_html[:b_match.start()].strip()
        part_b = full_html[b_match.start():].strip()
        return part_a, part_b, ""
    return full_html, "", ""


# ---------------------------------------------------------------------------
# Attachment — S1-S5 sections with clickable nav
# ---------------------------------------------------------------------------

def build_attachment(part_b_html: str, today: datetime.date) -> str:
    date_str = today.strftime("%d %B %Y")
    dow = today.strftime("%A, %d %B %Y").upper()

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Credit Intelligence News — {date_str}</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#ddd;font-family:'Inter',Arial,sans-serif;color:#1a1a1a}}
.wrap{{max-width:780px;margin:0 auto;background:#fff;box-shadow:0 4px 20px rgba(0,0,0,.2)}}
.bar{{background:#cc0000;height:5px}}
.mast{{padding:16px 24px 10px;border-bottom:3px solid #1a1a1a}}
.mast-meta{{font-size:9px;letter-spacing:2px;text-transform:uppercase;color:#999;margin-bottom:4px}}
.mast-title{{font-family:'Playfair Display',Georgia,serif;font-size:38px;font-weight:900;line-height:1;letter-spacing:-1px}}
.mast-sub{{display:flex;justify-content:space-between;align-items:center;border-top:1px solid #1a1a1a;margin-top:8px;padding-top:6px}}
nav{{background:#1a1a1a;border-bottom:3px solid #cc0000;display:flex;flex-wrap:wrap}}
nav a{{padding:8px 16px;font-size:9px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#ccc;border-right:1px solid #333;text-decoration:none}}
nav a:first-child{{color:#fff}}
nav a:hover{{color:#fff;background:#333}}
.body{{padding:0 24px 32px}}
footer{{background:#1a1a1a;padding:14px 24px;text-align:center;font-size:10px;color:#666;line-height:2}}
footer strong{{color:#cc0000}}
@media(max-width:600px){{.mast-title{{font-size:26px}}.body{{padding:0 14px 24px}}}}
</style>
</head>
<body>
<div class="wrap">
<div class="bar"></div>
<header class="mast">
  <p class="mast-meta">{dow} &bull; Credit Strategy &amp; Surveillance Desk &bull; CareEdge Ratings</p>
  <h1 class="mast-title">Credit Intelligence News</h1>
  <div class="mast-sub">
    <span style="font-size:10px;font-style:italic;color:#555">Full Report — All 5 Sections</span>
    <span style="font-size:9px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#cc0000;border:1px solid #cc0000;padding:2px 7px">&#128274; Confidential</span>
  </div>
</header>
<nav>
  <a href="#s1">&#9733; Watchlist</a>
  <a href="#s2">NBFC &amp; FI</a>
  <a href="#s3">Regulations</a>
  <a href="#s4">Markets</a>
  <a href="#s5">Macro</a>
</nav>
<main class="body">
{part_b_html}
</main>
<footer>
  <strong>Credit Intelligence News</strong> &mdash; CareEdge Ratings &mdash; {date_str}<br>
  Credit Strategy &amp; Surveillance Desk &bull; Jitendra.Meghrajani@careedge.in<br>
  <em>&#128274; Confidential &mdash; Internal Use Only. Not for external distribution.</em>
</footer>
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Email body — top 5 lead stories + top 5 takeaways
# ---------------------------------------------------------------------------

def build_email(part_a_html: str, part_c_html: str, today: datetime.date) -> str:
    date_str = today.strftime("%d %B %Y")
    dow = today.strftime("%A, %d %B %Y").upper()

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:12px 0;background:#d4d4d4;font-family:Arial,Helvetica,sans-serif;">
<div style="max-width:660px;margin:0 auto;background:#fff;box-shadow:0 2px 10px rgba(0,0,0,.18);">

<!-- RED BAR -->
<table width="100%" cellpadding="0" cellspacing="0"><tr><td style="background:#cc0000;height:5px;font-size:0;">&nbsp;</td></tr></table>

<!-- MASTHEAD -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-bottom:3px solid #1a1a1a;">
<tr><td style="padding:12px 20px 8px;">
  <p style="margin:0 0 3px;font-size:9px;letter-spacing:2px;text-transform:uppercase;color:#999;">{dow} &bull; CAREEDGE RATINGS &bull; INTERNAL USE ONLY</p>
  <p style="margin:0;font-size:30px;font-weight:900;color:#1a1a1a;letter-spacing:-1px;line-height:1;font-family:Georgia,serif;">Credit Intelligence News</p>
  <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:7px;border-top:1px solid #1a1a1a;">
  <tr>
    <td style="padding-top:5px;font-size:10px;font-style:italic;color:#555;font-family:Georgia,serif;">Daily Credit &amp; Markets Briefing &mdash; Credit Strategy &amp; Surveillance Desk</td>
    <td align="right" style="padding-top:5px;font-size:9px;font-weight:700;text-transform:uppercase;color:#cc0000;white-space:nowrap;">&#128274; CONFIDENTIAL</td>
  </tr>
  </table>
</td></tr>
</table>

<!-- NAV BAR -->
<table width="100%" cellpadding="0" cellspacing="0" style="background:#1a1a1a;border-bottom:3px solid #cc0000;">
<tr>
  <td style="padding:6px 10px 6px 20px;font-size:9px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#fff;border-right:1px solid #333;">&#9733; WATCHLIST</td>
  <td style="padding:6px 10px;font-size:9px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#bbb;border-right:1px solid #333;">NBFC &amp; FI</td>
  <td style="padding:6px 10px;font-size:9px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#bbb;border-right:1px solid #333;">REGULATIONS</td>
  <td style="padding:6px 10px;font-size:9px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#bbb;border-right:1px solid #333;">MARKETS</td>
  <td style="padding:6px 10px;font-size:9px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#bbb;">MACRO</td>
</tr>
</table>

<!-- TOP 5 STORIES HEADER -->
<table width="100%" cellpadding="0" cellspacing="0" style="background:#fff8f8;border-bottom:1px solid #e5e5e5;">
<tr><td style="padding:8px 20px;font-size:9px;font-weight:800;letter-spacing:3px;text-transform:uppercase;color:#cc0000;">&#9642; TOP 5 LEAD STORIES TODAY</td></tr>
</table>

{part_a_html}

<!-- TAKEAWAYS -->
{part_c_html}

<!-- ATTACHMENT NOTICE -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-top:2px solid #e5e5e5;">
<tr><td style="padding:16px 20px;text-align:center;background:#f9f9f9;">
  <p style="margin:0 0 4px;font-size:13px;font-weight:700;color:#1a1a1a;">&#128206; Full Report Attached</p>
  <p style="margin:0 0 10px;font-size:11px;color:#666;line-height:1.6;">All 5 sections (S1 Watchlist · S2 NBFC/FI · S3 Regulations · S4 Markets · S5 Macro)<br>with detailed news &amp; credit implications are in the attached HTML file.</p>
  <p style="margin:0;font-size:10px;color:#aaa;">Open attachment in Chrome or Safari for the full newspaper-style report.</p>
</td></tr>
</table>

<!-- FOOTER -->
<table width="100%" cellpadding="0" cellspacing="0" style="background:#1a1a1a;">
<tr><td style="padding:10px 20px;text-align:center;font-size:10px;color:#666;line-height:2;">
  <span style="color:#cc0000;font-weight:700;">CareEdge Ratings</span> &mdash; Credit Intelligence News &mdash; {date_str}<br>
  <span style="font-style:italic;color:#555;">&#128274; Confidential &mdash; Internal Use Only. Not for external distribution.</span>
</td></tr>
</table>

</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Email sender
# ---------------------------------------------------------------------------

def send_email(subject: str, html_body: str, gmail_user: str, gmail_password: str,
               attachment_html: str = "", attachment_name: str = "") -> None:
    recipients = _get_recipients()
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = ", ".join(recipients)

    body_part = MIMEMultipart("alternative")
    body_part.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(body_part)

    if attachment_html and attachment_name:
        att = MIMEBase("text", "html", charset="utf-8")
        att.set_payload(attachment_html.encode("utf-8"))
        encoders.encode_base64(att)
        att.add_header("Content-Disposition", "attachment", filename=attachment_name)
        msg.attach(att)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_password)
        server.sendmail(gmail_user, recipients, msg.as_string())
        print(f"Email sent to {', '.join(recipients)}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    gmail_user = os.environ["GMAIL_USER"]
    gmail_password = os.environ["GMAIL_APP_PASSWORD"]
    anthropic_api_key = os.environ["ANTHROPIC_API_KEY"]
    newsapi_key = os.environ.get("NEWSAPI_KEY", "")

    today = datetime.date.today()
    subject = f"Credit Intelligence News — {today.strftime('%d %B %Y')}"

    print("Fetching news...")
    news_text = fetch_all_news(newsapi_key)
    item_count = news_text.count("\n") + 1
    print(f"Fetched {item_count} news items.")

    print("Calling Claude API...")
    full_html = generate_report(news_text, today, anthropic_api_key)

    print("Splitting parts...")
    part_a, part_b, part_c = split_parts(full_html)
    print(f"Part A: {len(part_a)} chars | Part B: {len(part_b)} chars | Part C: {len(part_c)} chars")

    print("Building email body...")
    email_html = build_email(part_a, part_c, today)

    print("Building attachment...")
    attachment_html = build_attachment(part_b, today)
    attachment_name = f"Credit_Intelligence_{today.strftime('%d%b%Y')}.html"

    print("Sending email with attachment...")
    send_email(subject, email_html, gmail_user, gmail_password,
               attachment_html=attachment_html, attachment_name=attachment_name)


if __name__ == "__main__":
    main()
