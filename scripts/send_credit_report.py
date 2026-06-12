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
WATCHLIST items (tagged [WATCHLIST — Company]) are HIGHEST PRIORITY — always appear first in every section.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT — NEWSPAPER STYLE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Output ONLY raw HTML. No markdown. No html/head/body tags. All styles must be inline.

═══════════════════════════════════════
PART A — TOP STORIES STRIP (breaking news ticker row)
═══════════════════════════════════════
Output exactly this structure — one row of 3 TOP story boxes side by side.
Pick the 3 single most important items (watchlist first).

<table width="100%" cellpadding="0" cellspacing="0" style="border-top:3px solid #c00;border-bottom:2px solid #e5e5e5;background:#fff8f8;margin-bottom:0;">
<tr><td style="padding:6px 16px;font-size:10px;font-weight:800;letter-spacing:3px;text-transform:uppercase;color:#c00;border-right:1px solid #e5e5e5;" width="100">&#9642; BREAKING</td>
<td style="padding:6px 14px;font-size:12px;font-weight:600;color:#1a1a1a;line-height:1.5;">SHORT 1-LINE SUMMARY OF TOP STORY 1</td></tr>
</table>

Then output the 3-column lead stories grid:
<table width="100%" cellpadding="0" cellspacing="0" style="border-bottom:2px solid #1a1a1a;margin-bottom:12px;">
<tr valign="top">

  <!-- LEAD STORY (wide, left) -->
  <td width="50%" style="padding:14px 12px 14px 16px;border-right:1px solid #ddd;">
    <p style="margin:0 0 4px 0;font-size:9px;font-weight:800;letter-spacing:2px;text-transform:uppercase;color:#c00;">WATCHLIST / SECTION TAG</p>
    <p style="margin:0 0 8px 0;font-size:17px;font-weight:900;color:#1a1a1a;line-height:1.3;font-family:Georgia,serif;">HEADLINE OF TOP STORY</p>
    <p style="margin:0 0 8px 0;font-size:12px;color:#444;line-height:1.7;">2-3 sentence factual summary of what happened.</p>
    <table width="100%" cellpadding="0" cellspacing="0" style="background:#fef2f2;border-left:3px solid #c00;margin-bottom:8px;">
    <tr><td style="padding:8px 10px;">
      <p style="margin:0 0 3px 0;font-size:9px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:#c00;">CREDIT IMPLICATION</p>
      <p style="margin:0;font-size:12px;color:#374151;line-height:1.6;">2-3 sentences on rating/liquidity/asset quality impact.</p>
    </td></tr>
    </table>
    <p style="margin:0;font-size:11px;"><a href="ACTUAL_URL" target="_blank" style="color:#c00;font-weight:700;text-decoration:none;">Read more &#8594;</a> &nbsp;<span style="color:#888;font-size:10px;">Source Name</span></p>
  </td>

  <!-- STORY 2 (top right) -->
  <td width="50%" style="padding:0;vertical-align:top;">
    <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td style="padding:14px 16px 10px 12px;border-bottom:1px solid #ddd;">
      <p style="margin:0 0 3px 0;font-size:9px;font-weight:800;letter-spacing:2px;text-transform:uppercase;color:#c00;">SECTION TAG</p>
      <p style="margin:0 0 6px 0;font-size:14px;font-weight:800;color:#1a1a1a;line-height:1.3;font-family:Georgia,serif;">HEADLINE STORY 2</p>
      <p style="margin:0 0 5px 0;font-size:12px;color:#444;line-height:1.6;">1-2 sentence summary.</p>
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#fff7ed;border-left:3px solid #f59e0b;margin-bottom:6px;">
      <tr><td style="padding:6px 10px;font-size:11px;color:#374151;line-height:1.6;">Credit implication in 1-2 sentences.</td></tr>
      </table>
      <p style="margin:0;font-size:11px;"><a href="ACTUAL_URL" target="_blank" style="color:#c00;font-weight:700;text-decoration:none;">Read more &#8594;</a> &nbsp;<span style="color:#888;font-size:10px;">Source Name</span></p>
    </td></tr>

    <!-- STORY 3 (bottom right) -->
    <tr><td style="padding:12px 16px 14px 12px;">
      <p style="margin:0 0 3px 0;font-size:9px;font-weight:800;letter-spacing:2px;text-transform:uppercase;color:#c00;">SECTION TAG</p>
      <p style="margin:0 0 6px 0;font-size:14px;font-weight:800;color:#1a1a1a;line-height:1.3;font-family:Georgia,serif;">HEADLINE STORY 3</p>
      <p style="margin:0 0 5px 0;font-size:12px;color:#444;line-height:1.6;">1-2 sentence summary.</p>
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#f0fdf4;border-left:3px solid #16a34a;margin-bottom:6px;">
      <tr><td style="padding:6px 10px;font-size:11px;color:#374151;line-height:1.6;">Credit implication in 1-2 sentences.</td></tr>
      </table>
      <p style="margin:0;font-size:11px;"><a href="ACTUAL_URL" target="_blank" style="color:#c00;font-weight:700;text-decoration:none;">Read more &#8594;</a> &nbsp;<span style="color:#888;font-size:10px;">Source Name</span></p>
    </td></tr>
    </table>
  </td>

</tr>
</table>

═══════════════════════════════════════
PART B — SECTION PAGES (newspaper section layout)
═══════════════════════════════════════
For each of the 5 sections output a section block.
Include every item not already shown in Part A leads. Show all 5 sections even if empty.

Section routing:
  S1 — [WATCHLIST — CompanyName] tagged items ONLY
  S2 — NBFC, HFC, Banking, Broking, Fintech, MFI, rating actions
  S3 — RBI, SEBI, NHB regulatory items
  S4 — Bonds, CP, Securitisation, FIMMDA, CCIL market items
  S5 — Macro: GDP, CPI, IIP, forex, fiscal deficit, US Fed, global

Each section uses this structure:

SECTION HEADER (copy the exact color per section):
S1 header — red:    <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:14px;"><tr><td style="background:#c00;padding:7px 16px;"><span style="font-size:9px;font-weight:800;letter-spacing:3px;text-transform:uppercase;color:#fff;">&#9733; SECTION 1 &mdash; MY RATED ENTITIES &amp; WATCHLIST</span></td></tr></table>
S2 header — amber:  <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:14px;"><tr><td style="background:#b45309;padding:7px 16px;"><span style="font-size:9px;font-weight:800;letter-spacing:3px;text-transform:uppercase;color:#fff;">SECTION 2 &mdash; NBFC, HFC, BROKING, FINTECH, FI</span></td></tr></table>
S3 header — navy:   <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:14px;"><tr><td style="background:#1e3a8a;padding:7px 16px;"><span style="font-size:9px;font-weight:800;letter-spacing:3px;text-transform:uppercase;color:#fff;">SECTION 3 &mdash; RBI, SEBI, NHB REGULATIONS</span></td></tr></table>
S4 header — green:  <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:14px;"><tr><td style="background:#15803d;padding:7px 16px;"><span style="font-size:9px;font-weight:800;letter-spacing:3px;text-transform:uppercase;color:#fff;">SECTION 4 &mdash; BOND &amp; MONEY MARKETS</span></td></tr></table>
S5 header — purple: <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:14px;"><tr><td style="background:#6d28d9;padding:7px 16px;"><span style="font-size:9px;font-weight:800;letter-spacing:3px;text-transform:uppercase;color:#fff;">SECTION 5 &mdash; MACROECONOMIC DEVELOPMENTS</span></td></tr></table>

After each section header, output article rows in 2-column newspaper column style:
<table width="100%" cellpadding="0" cellspacing="0">
<tr valign="top">
  <td width="50%" style="padding:10px 10px 10px 16px;border-right:1px solid #e5e5e5;border-bottom:1px solid #e5e5e5;">
    <p style="margin:0 0 3px 0;font-size:9px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#888;">SOURCE NAME</p>
    <p style="margin:0 0 5px 0;font-size:13px;font-weight:800;color:#1a1a1a;line-height:1.35;font-family:Georgia,serif;"><a href="URL" target="_blank" style="color:#1a1a1a;text-decoration:none;">HEADLINE</a></p>
    <p style="margin:0 0 5px 0;font-size:11px;color:#555;line-height:1.6;">1 sentence credit-focused summary.</p>
    <p style="margin:0;font-size:10px;color:#c00;font-weight:700;font-style:italic;">Credit angle in one phrase.</p>
  </td>
  <td width="50%" style="padding:10px 16px 10px 10px;border-bottom:1px solid #e5e5e5;">
    <!-- next article same structure, or empty td if odd number -->
  </td>
</tr>
</table>

Rules for section articles:
- Pair articles into 2-column rows. If odd number, leave right cell empty.
- Each article: source label, bold headline as link (if URL available), 1-line summary, credit angle tag.
- Empty section: <p style="padding:8px 16px;font-size:11px;color:#aaa;font-style:italic;margin:0;">No news in this category today.</p>

═══════════════════════════════════════
PART C — TOP 5 BRIEFING BAR
═══════════════════════════════════════
<table width="100%" cellpadding="0" cellspacing="0" style="margin-top:14px;background:#1a1a1a;">
<tr><td style="padding:8px 16px;"><span style="font-size:9px;font-weight:800;letter-spacing:3px;text-transform:uppercase;color:#fff;">&#9679; TODAY'S TOP 5 CREDIT BRIEFING</span></td></tr>
</table>
<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e5e5e5;border-top:none;">
<tr valign="top">
  <td width="20%" style="padding:12px 10px 12px 16px;border-right:1px solid #e5e5e5;border-bottom:1px solid #e5e5e5;">
    <p style="margin:0 0 2px 0;font-size:28px;font-weight:900;color:#c00;line-height:1;">01</p>
    <p style="margin:0 0 4px 0;font-size:9px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:#666;">S? / TOPIC</p>
    <p style="margin:0;font-size:11px;color:#1a1a1a;line-height:1.6;">One sharp credit insight sentence.</p>
  </td>
  <td width="20%" style="padding:12px 10px;border-right:1px solid #e5e5e5;border-bottom:1px solid #e5e5e5;">
    <p style="margin:0 0 2px 0;font-size:28px;font-weight:900;color:#c00;line-height:1;">02</p>
    <p style="margin:0 0 4px 0;font-size:9px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:#666;">S? / TOPIC</p>
    <p style="margin:0;font-size:11px;color:#1a1a1a;line-height:1.6;">One sharp credit insight sentence.</p>
  </td>
  <td width="20%" style="padding:12px 10px;border-right:1px solid #e5e5e5;border-bottom:1px solid #e5e5e5;">
    <p style="margin:0 0 2px 0;font-size:28px;font-weight:900;color:#c00;line-height:1;">03</p>
    <p style="margin:0 0 4px 0;font-size:9px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:#666;">S? / TOPIC</p>
    <p style="margin:0;font-size:11px;color:#1a1a1a;line-height:1.6;">One sharp credit insight sentence.</p>
  </td>
  <td width="20%" style="padding:12px 10px;border-right:1px solid #e5e5e5;border-bottom:1px solid #e5e5e5;">
    <p style="margin:0 0 2px 0;font-size:28px;font-weight:900;color:#c00;line-height:1;">04</p>
    <p style="margin:0 0 4px 0;font-size:9px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:#666;">S? / TOPIC</p>
    <p style="margin:0;font-size:11px;color:#1a1a1a;line-height:1.6;">One sharp credit insight sentence.</p>
  </td>
  <td width="20%" style="padding:12px 16px 12px 10px;border-bottom:1px solid #e5e5e5;">
    <p style="margin:0 0 2px 0;font-size:28px;font-weight:900;color:#c00;line-height:1;">05</p>
    <p style="margin:0 0 4px 0;font-size:9px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:#666;">S? / TOPIC</p>
    <p style="margin:0;font-size:11px;color:#1a1a1a;line-height:1.6;">One sharp credit insight sentence.</p>
  </td>
</tr>
</table>

CRITICAL RULES:
- Use ACTUAL URLs from "| URL:" in input — never placeholder text. Omit link tag entirely if no URL.
- All styles must be inline. Zero class names. Zero external CSS.
- Do NOT output html/head/body tags, masthead, or any wrapper.
- Output Parts A, B, C in order, nothing else."""


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
    day_str = today.strftime("%A")
    dow = today.strftime("%A, %d %B %Y").upper()

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="light">
</head>
<body style="margin:0;padding:12px 0;background:#c8c8c8;font-family:Arial,Helvetica,sans-serif;-webkit-text-size-adjust:100%;">
<div style="max-width:680px;margin:0 auto;background:#ffffff;box-shadow:0 2px 8px rgba(0,0,0,0.18);">

<!-- TOP ACCENT BAR -->
<table width="100%" cellpadding="0" cellspacing="0">
<tr>
  <td style="background:#c00;height:4px;"></td>
</tr>
</table>

<!-- MASTHEAD -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-bottom:3px solid #1a1a1a;">
<tr>
  <td style="padding:10px 16px 4px 16px;">
    <!-- date line -->
    <p style="margin:0 0 2px 0;font-size:9px;letter-spacing:2px;text-transform:uppercase;color:#888;">{dow} &nbsp;&bull;&nbsp; VOL. 1 &nbsp;&bull;&nbsp; INTERNAL USE ONLY</p>
    <!-- publication name -->
    <p style="margin:0;font-size:30px;font-weight:900;color:#1a1a1a;letter-spacing:-1px;line-height:1;font-family:Georgia,'Times New Roman',serif;">CareEdge Credit Intelligence</p>
    <!-- tagline rule -->
    <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:6px;">
    <tr>
      <td style="border-top:1px solid #1a1a1a;padding-top:4px;">
        <p style="margin:0;font-size:10px;color:#555;font-style:italic;font-family:Georgia,serif;">Daily Credit &amp; Markets Briefing &mdash; Credit Strategy &amp; Surveillance Desk</p>
      </td>
    </tr>
    </table>
  </td>
</tr>
</table>

<!-- SECTION NAV BAR -->
<table width="100%" cellpadding="0" cellspacing="0" style="background:#1a1a1a;border-bottom:2px solid #c00;">
<tr>
  <td style="padding:0;">
    <table cellpadding="0" cellspacing="0">
    <tr>
      <td style="padding:6px 12px 6px 16px;font-size:9px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#fff;border-right:1px solid #444;">WATCHLIST</td>
      <td style="padding:6px 12px;font-size:9px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#ccc;border-right:1px solid #444;">NBFC &amp; FI</td>
      <td style="padding:6px 12px;font-size:9px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#ccc;border-right:1px solid #444;">REGULATIONS</td>
      <td style="padding:6px 12px;font-size:9px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#ccc;border-right:1px solid #444;">MARKETS</td>
      <td style="padding:6px 12px;font-size:9px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#ccc;">MACRO</td>
    </tr>
    </table>
  </td>
</tr>
</table>

<!-- REPORT BODY (Claude-generated) -->
{inner_html}

<!-- FOOTER -->
<table width="100%" cellpadding="0" cellspacing="0" style="margin-top:16px;border-top:3px solid #1a1a1a;background:#1a1a1a;">
<tr><td style="padding:14px 16px;text-align:center;font-size:10px;color:#999;line-height:1.9;">
  <span style="color:#c00;font-weight:700;">CareEdge Ratings</span> &nbsp;&mdash;&nbsp; Daily Credit Intelligence &nbsp;&mdash;&nbsp; {date_str}<br>
  Credit Strategy &amp; Surveillance Desk &nbsp;&bull;&nbsp; Jitendra.Meghrajani@careedge.in<br>
  <span style="font-style:italic;color:#666;">&#128274; Confidential &mdash; Internal Use Only. Not for external distribution.</span>
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
