#!/usr/bin/env python3
"""
Daily Credit Intelligence Report — AI-generated, dual delivery.
- Email: short masthead + top 5 credit takeaways + attachment notice
- Attachment: full S1-S5 sections, each item with news + credit implication
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
PART A — TOP 5 LEAD STORIES  (used only for deciding Part B ordering; NOT output separately)
════════════
Identify the 5 most credit-significant stories mentally. Watchlist entities first.
DO NOT output Part A as HTML. Use it only to ensure those 5 stories appear at the TOP of their respective sections in Part B.

════════════
PART B — ALL 5 SECTIONS  (goes in attachment)
════════════
Show ALL 5 sections. Each item in EXACTLY ONE section. Top stories for each section come first.

Section routing:
  S1 — [WATCHLIST — Company] items ONLY
  S2 — NBFC, HFC, Banking, Broking, Fintech, MFI, rating agency actions
  S3 — RBI, SEBI, NHB regulatory circulars/orders
  S4 — Bonds, G-Sec, CP, Securitisation, FIMMDA, CCIL market items
  S5 — Macro: GDP, CPI, IIP, forex, fiscal deficit, US Fed, global

Section headers (copy EXACTLY including id attributes):
S1: <table id="s1" width="100%" cellpadding="0" cellspacing="0" style="margin-top:16px;"><tr><td style="background:#cc0000;padding:7px 16px;font-size:9px;font-weight:800;letter-spacing:3px;text-transform:uppercase;color:#fff;">&#9733; S1 — MY RATED ENTITIES &amp; WATCHLIST</td></tr></table>
S2: <table id="s2" width="100%" cellpadding="0" cellspacing="0" style="margin-top:16px;"><tr><td style="background:#b45309;padding:7px 16px;font-size:9px;font-weight:800;letter-spacing:3px;text-transform:uppercase;color:#fff;">S2 — NBFC, HFC, BROKING, FINTECH, FI SECTORS</td></tr></table>
S3: <table id="s3" width="100%" cellpadding="0" cellspacing="0" style="margin-top:16px;"><tr><td style="background:#1e3a8a;padding:7px 16px;font-size:9px;font-weight:800;letter-spacing:3px;text-transform:uppercase;color:#fff;">S3 — RBI, SEBI, NHB REGULATIONS</td></tr></table>
S4: <table id="s4" width="100%" cellpadding="0" cellspacing="0" style="margin-top:16px;"><tr><td style="background:#15803d;padding:7px 16px;font-size:9px;font-weight:800;letter-spacing:3px;text-transform:uppercase;color:#fff;">S4 — BOND &amp; MONEY MARKETS</td></tr></table>
S5: <table id="s5" width="100%" cellpadding="0" cellspacing="0" style="margin-top:16px;"><tr><td style="background:#6d28d9;padding:7px 16px;font-size:9px;font-weight:800;letter-spacing:3px;text-transform:uppercase;color:#fff;">S5 — MACROECONOMIC DEVELOPMENTS</td></tr></table>

After each header, one card per article:
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
PART C — TOP 5 CREDIT TAKEAWAYS  (goes in email body)
════════════
<table width="100%" cellpadding="0" cellspacing="0" style="background:#1a1a1a;">
<tr><td style="padding:8px 16px;font-size:9px;font-weight:800;letter-spacing:3px;text-transform:uppercase;color:#fff;">&#9679; TOP 5 CREDIT TAKEAWAYS — {date_str}</td></tr>
</table>
<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e5e5e5;border-top:none;">
<tr valign="top">
  <td style="padding:10px 8px 10px 16px;font-size:28px;font-weight:900;color:#cc0000;line-height:1;font-family:Georgia,serif;width:44px;">01</td>
  <td style="padding:10px 16px 10px 4px;border-bottom:1px solid #f0f0f0;">
    <p style="margin:0 0 2px;font-size:9px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:#888;">SECTION / TOPIC</p>
    <p style="margin:0;font-size:12px;color:#1a1a1a;line-height:1.6;">One sharp analyst-grade credit insight.</p>
  </td>
</tr>
<tr valign="top">
  <td style="padding:10px 8px 10px 16px;font-size:28px;font-weight:900;color:#cc0000;line-height:1;font-family:Georgia,serif;">02</td>
  <td style="padding:10px 16px 10px 4px;border-bottom:1px solid #f0f0f0;">
    <p style="margin:0 0 2px;font-size:9px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:#888;">SECTION / TOPIC</p>
    <p style="margin:0;font-size:12px;color:#1a1a1a;line-height:1.6;">One sharp credit insight.</p>
  </td>
</tr>
<tr valign="top">
  <td style="padding:10px 8px 10px 16px;font-size:28px;font-weight:900;color:#cc0000;line-height:1;font-family:Georgia,serif;">03</td>
  <td style="padding:10px 16px 10px 4px;border-bottom:1px solid #f0f0f0;">
    <p style="margin:0 0 2px;font-size:9px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:#888;">SECTION / TOPIC</p>
    <p style="margin:0;font-size:12px;color:#1a1a1a;line-height:1.6;">One sharp credit insight.</p>
  </td>
</tr>
<tr valign="top">
  <td style="padding:10px 8px 10px 16px;font-size:28px;font-weight:900;color:#cc0000;line-height:1;font-family:Georgia,serif;">04</td>
  <td style="padding:10px 16px 10px 4px;border-bottom:1px solid #f0f0f0;">
    <p style="margin:0 0 2px;font-size:9px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:#888;">SECTION / TOPIC</p>
    <p style="margin:0;font-size:12px;color:#1a1a1a;line-height:1.6;">One sharp credit insight.</p>
  </td>
</tr>
<tr valign="top">
  <td style="padding:10px 8px 10px 16px;font-size:28px;font-weight:900;color:#cc0000;line-height:1;font-family:Georgia,serif;">05</td>
  <td style="padding:10px 16px 10px 4px;">
    <p style="margin:0 0 2px;font-size:9px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:#888;">SECTION / TOPIC</p>
    <p style="margin:0;font-size:12px;color:#1a1a1a;line-height:1.6;">One sharp credit insight.</p>
  </td>
</tr>
</table>

OUTPUT RULES:
- Real URLs only from "| URL:" — never placeholder text. No <a> if no URL.
- ALL styles inline. No class names. No <style> blocks.
- No html/head/body wrappers.
- Output Part B then Part C in order. Nothing else."""


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
        return f"""<table width="100%" cellpadding="0" cellspacing="0" style="background:#1a1a1a;">
<tr><td style="padding:8px 16px;font-size:9px;font-weight:800;letter-spacing:3px;text-transform:uppercase;color:#fff;">&#9679; TOP 5 CREDIT TAKEAWAYS</td></tr></table>
<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e5e5e5;border-top:none;">
<tr><td style="padding:16px;font-size:13px;color:#cc0000;">Report generation failed: {str(exc)[:200]}</td></tr>
</table>"""


# ---------------------------------------------------------------------------
# Split output: Part B (sections) and Part C (takeaways)
# ---------------------------------------------------------------------------

def split_parts(full_html: str) -> tuple[str, str]:
    """Return (part_b, part_c). part_b = S1-S5 sections, part_c = takeaways."""
    # Part C starts at the black takeaways header
    c_match = re.search(
        r'<table[^>]*style="[^"]*background:#1a1a1a[^"]*"',
        full_html
    )
    if c_match:
        part_b = full_html[:c_match.start()].strip()
        part_c = full_html[c_match.start():].strip()
        return part_b, part_c
    return full_html, ""


# ---------------------------------------------------------------------------
# Attachment — S1-S5 with clickable nav
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
.mast{{padding:14px 24px 10px;border-bottom:3px solid #1a1a1a}}
.mast-meta{{font-size:9px;letter-spacing:2px;text-transform:uppercase;color:#999;margin-bottom:4px}}
.mast-title{{font-family:'Playfair Display',Georgia,serif;font-size:36px;font-weight:900;line-height:1;letter-spacing:-1px}}
.mast-sub{{display:flex;justify-content:space-between;align-items:center;border-top:1px solid #1a1a1a;margin-top:7px;padding-top:5px}}
nav{{background:#1a1a1a;border-bottom:3px solid #cc0000;display:flex;flex-wrap:wrap}}
nav a{{padding:8px 16px;font-size:9px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#ccc;border-right:1px solid #333;text-decoration:none}}
nav a:first-child{{color:#fff}}
nav a:hover{{color:#fff;background:#333}}
.body{{padding:0 24px 32px}}
footer{{background:#1a1a1a;padding:12px 24px;text-align:center;font-size:10px;color:#666;line-height:2}}
footer strong{{color:#cc0000}}
@media(max-width:600px){{.mast-title{{font-size:26px}}.body{{padding:0 14px 24px}}}}
</style>
</head>
<body>
<div class="wrap">
<div class="bar"></div>
<header class="mast">
  <p class="mast-meta">{dow} &bull; CareEdge Ratings</p>
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
  <em>&#128274; Confidential — Internal Use Only. Not for external distribution.</em>
</footer>
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Email body — short: masthead + top 5 takeaways + attachment notice
# ---------------------------------------------------------------------------

def build_email(part_c_html: str, today: datetime.date) -> str:
    date_str = today.strftime("%d %B %Y")
    dow = today.strftime("%A, %d %B %Y").upper()

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:12px 0;background:#d4d4d4;font-family:Arial,Helvetica,sans-serif;">
<div style="max-width:620px;margin:0 auto;background:#fff;box-shadow:0 2px 10px rgba(0,0,0,.18);">

<table width="100%" cellpadding="0" cellspacing="0"><tr><td style="background:#cc0000;height:5px;font-size:0;">&nbsp;</td></tr></table>

<table width="100%" cellpadding="0" cellspacing="0" style="border-bottom:2px solid #1a1a1a;">
<tr><td style="padding:12px 20px 10px;">
  <p style="margin:0 0 3px;font-size:9px;letter-spacing:2px;text-transform:uppercase;color:#999;">{dow} &bull; CAREEDGE RATINGS</p>
  <p style="margin:0;font-size:28px;font-weight:900;color:#1a1a1a;letter-spacing:-1px;line-height:1;font-family:Georgia,serif;">Credit Intelligence News</p>
</td></tr>
</table>

{part_c_html}

<table width="100%" cellpadding="0" cellspacing="0" style="border-top:2px solid #e5e5e5;">
<tr><td style="padding:14px 20px;text-align:center;background:#f9f9f9;">
  <p style="margin:0 0 3px;font-size:12px;font-weight:700;color:#1a1a1a;">&#128206; Full Report Attached</p>
  <p style="margin:0;font-size:11px;color:#888;">S1 Watchlist · S2 NBFC/FI · S3 Regulations · S4 Markets · S5 Macro — open in Chrome/Safari</p>
</td></tr>
</table>

<table width="100%" cellpadding="0" cellspacing="0" style="background:#1a1a1a;">
<tr><td style="padding:8px 20px;text-align:center;font-size:10px;color:#555;">
  <span style="color:#cc0000;font-weight:700;">CareEdge Ratings</span> &mdash; {date_str} &mdash;
  <em>&#128274; Confidential — Internal Use Only</em>
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
    part_b, part_c = split_parts(full_html)
    print(f"Part B (sections): {len(part_b)} chars | Part C (takeaways): {len(part_c)} chars")

    print("Building email...")
    email_html = build_email(part_c, today)

    print("Building attachment...")
    attachment_html = build_attachment(part_b, today)
    attachment_name = f"Credit_Intelligence_{today.strftime('%d%b%Y')}.html"

    print("Sending email...")
    send_email(subject, email_html, gmail_user, gmail_password,
               attachment_html=attachment_html, attachment_name=attachment_name)


if __name__ == "__main__":
    main()
