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

NEWS ITEMS (each has a tag like [WATCHLIST], [RBI], [NBFC], [Macro], [Bonds] etc. URLs follow "| URL:"):

{news_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YOUR OBJECTIVE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Focus ONLY on developments that affect:
Rating outlook · Liquidity · Funding access · Asset quality · Capitalisation · Governance · Earnings stability

IGNORE: Product launches · CSR · Awards · Marketing · Stock tips · Generic business news

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT STRUCTURE (follow exactly, every time)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CRITICAL PRIORITY RULE: Items tagged [WATCHLIST — CompanyName] must ALWAYS appear in Part W AND get priority placement in Part A highlights. Never skip or bury watchlist items.

PART W — WATCHLIST FOCUS (output this section FIRST, before Part A)
Pick ALL credit-relevant items tagged [WATCHLIST — CompanyName].
Show each as a full card. If zero watchlist items today, output: <p class="no-watchlist">No watchlist company news today.</p>

<table class="section-banner watchlist-banner" width="100%" cellpadding="0" cellspacing="0"><tr><td>
<span class="banner-icon">&#128204;</span> WATCHLIST &amp; RATED ENTITIES &mdash; {date_str}
</td></tr></table>

For each watchlist item:
<table class="news-card" width="100%" cellpadding="0" cellspacing="0">
  <tr><td class="card-company-tag">WATCHLIST &mdash; [CompanyName]</td></tr>
  <tr><td class="card-headline">[HEADLINE]</td></tr>
  <tr><td class="card-source">[Source Publication]</td></tr>
  <tr>
    <td>
      <table class="card-cols" width="100%" cellpadding="0" cellspacing="0"><tr>
        <td class="col-left" width="50%"><p class="col-label">&#128240; NEWS</p><p class="col-body">2-3 lines. What happened. Facts only.</p></td>
        <td class="col-divider" width="2px"></td>
        <td class="col-right" width="50%"><p class="col-label">&#9888; CREDIT IMPLICATION</p><p class="col-body">2-3 lines. Rating / liquidity / asset quality / funding impact.</p></td>
      </tr></table>
    </td>
  </tr>
  <tr><td class="card-readmore"><a href="URL" style="color:#1a56db;">Read more &#8599;</a> &nbsp;&#183;&nbsp; [Source]</td></tr>
</table>

PART A — TOP HIGHLIGHTS (10–15 most credit-important items from ALL sections; watchlist items that appear in Part W should also appear here for completeness if among top 10-15)
Order: watchlist items first, then most important others.

<table class="section-banner highlight-banner" width="100%" cellpadding="0" cellspacing="0"><tr><td>
&#11088; TOP HIGHLIGHTS &mdash; {date_str}
</td></tr></table>

For each highlight:
<table class="news-card" width="100%" cellpadding="0" cellspacing="0">
  <tr><td class="card-company-tag">[SECTION TAG] &mdash; [COMPANY / TOPIC]</td></tr>
  <tr><td class="card-headline">[HEADLINE]</td></tr>
  <tr><td class="card-source">[Source Publication]</td></tr>
  <tr>
    <td>
      <table class="card-cols" width="100%" cellpadding="0" cellspacing="0"><tr>
        <td class="col-left" width="50%"><p class="col-label">&#128240; NEWS</p><p class="col-body">2-3 lines. What happened. Facts only.</p></td>
        <td class="col-divider" width="2px"></td>
        <td class="col-right" width="50%"><p class="col-label">&#9888; CREDIT IMPLICATION</p><p class="col-body">2-3 lines. Rating / liquidity / asset quality / funding impact.</p></td>
      </tr></table>
    </td>
  </tr>
  <tr><td class="card-readmore"><a href="URL" style="color:#1a56db;">Read more &#8599;</a> &nbsp;&#183;&nbsp; [Source]</td></tr>
</table>
(Omit card-readmore row if no URL.)

PART B — ALL NEWS BY SECTION (compact link list for items NOT already shown above)
Output ALL 5 sections. Each section = compact clickable links.

Section routing:
  S1 — WATCHLIST: Only [WATCHLIST — CompanyName] tagged items NOT already in Part W
  S2 — NBFC/SECTORS: Items tagged NBFC, HFC, Banking, Broking, Fintech, MFI, Ratings
  S3 — REGULATIONS: Items tagged RBI, SEBI, NHB
  S4 — BOND MARKETS: Items tagged Bonds, CP, Securitisation, FIMMDA, CCIL
  S5 — MACRO: Items tagged Macro, or any GDP/CPI/IIP/forex/fiscal/Fed news

For each section:
<table class="section-banner [BANNER-CLASS]" width="100%" cellpadding="0" cellspacing="0"><tr><td>[SECTION TITLE]</td></tr></table>
<table class="link-list" width="100%" cellpadding="0" cellspacing="0">
  <tr><td class="link-row"><a href="URL" class="link-anchor">&#9656; Headline — Source</a></td></tr>
  ...
</table>

Banner classes: S1→watchlist-banner, S2→sector-banner, S3→reg-banner, S4→bond-banner, S5→macro-banner
Section titles (use exactly):
  &#128204; MY RATED ENTITIES &amp; WATCHLIST
  &#127970; NBFC, HFC, BROKING &amp; FINTECH SECTORS
  &#9878; RBI, SEBI &amp; NHB REGULATIONS
  &#128200; BOND &amp; MONEY MARKETS
  &#127758; MACROECONOMIC DEVELOPMENTS

For items with no URL: <tr><td class="link-row nolink">&#9656; Headline — Source</td></tr>
If section has zero remaining items: <tr><td class="link-row nolink" style="color:#9ca3af;font-style:italic;">No additional items today.</td></tr>

PART C — TOP 5 THINGS TO KNOW TODAY
<table class="section-banner top5-banner" width="100%" cellpadding="0" cellspacing="0"><tr><td>&#9733; TOP 5 THINGS TO KNOW TODAY</td></tr></table>
<table class="top5-list" width="100%" cellpadding="0" cellspacing="0">
  <tr>
    <td class="top5-num">1</td>
    <td class="top5-text"><strong>[Section / Company]</strong> — one-line credit insight.</td>
  </tr>
  ... (5 items total, watchlist items get priority)
</table>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Return ONLY inner HTML. No html/head/body tags. No markdown. No backticks."""


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
<table class="section-banner highlight-banner" width="100%" cellpadding="0" cellspacing="0"><tr><td>
&#9888; REPORT GENERATION FAILED
</td></tr></table>
<table class="news-card" width="100%" cellpadding="0" cellspacing="0">
  <tr><td class="card-headline">Automated Report Could Not Be Generated Today</td></tr>
  <tr><td class="card-body">The Claude API call failed. Check GitHub Actions logs for details.<br><br>Error: {str(exc)[:300]}</td></tr>
</table>
"""


# ---------------------------------------------------------------------------
# HTML wrapper — Newspaper broadsheet style, email-client safe
# ---------------------------------------------------------------------------

def build_html(inner_html: str, today: datetime.date) -> str:
    date_str = today.strftime("%d %B %Y")
    day_str = today.strftime("%A")
    day_upper = today.strftime("%A, %d %B %Y").upper()

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Daily Credit Intelligence — {date_str}</title>
<style>
/* Reset */
body, table, td, p, a, h1, h2, h3 {{ margin:0; padding:0; border:0; }}
body {{
  font-family: Georgia, 'Times New Roman', Times, serif;
  background: #f4f1eb;
  color: #1a1a1a;
  -webkit-text-size-adjust: 100%;
}}
img {{ border:0; display:block; }}

/* ── OUTER WRAPPER ── */
.outer {{
  background: #f4f1eb;
  padding: 20px 0 40px 0;
}}
.wrapper {{
  max-width: 680px;
  margin: 0 auto;
  background: #ffffff;
  border: 1px solid #c8b89a;
}}

/* ── MASTHEAD ── */
.masthead {{
  background: #ffffff;
  border-bottom: 4px double #1a1a1a;
  padding: 24px 32px 16px 32px;
  text-align: center;
}}
.masthead-kicker {{
  font-family: Arial, Helvetica, sans-serif;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 3px;
  text-transform: uppercase;
  color: #666666;
  border-top: 1px solid #1a1a1a;
  border-bottom: 1px solid #1a1a1a;
  padding: 4px 0;
  margin-bottom: 12px;
}}
.masthead-title {{
  font-family: Georgia, 'Times New Roman', Times, serif;
  font-size: 38px;
  font-weight: 700;
  color: #0a0a0a;
  letter-spacing: -1px;
  line-height: 1.1;
  margin-bottom: 6px;
}}
.masthead-sub {{
  font-family: Arial, Helvetica, sans-serif;
  font-size: 11px;
  color: #555555;
  letter-spacing: 0.5px;
  margin-bottom: 10px;
}}
.masthead-date-strip {{
  font-family: Arial, Helvetica, sans-serif;
  font-size: 10px;
  color: #333333;
  border-top: 2px solid #1a1a1a;
  border-bottom: 1px solid #1a1a1a;
  padding: 4px 0;
  margin-top: 10px;
  display: flex;
  justify-content: space-between;
}}
.masthead-date-strip td {{
  font-family: Arial, Helvetica, sans-serif;
  font-size: 10px;
  color: #333333;
  padding: 4px 8px;
}}
.masthead-confidential {{
  font-family: Arial, Helvetica, sans-serif;
  font-size: 9px;
  color: #888888;
  letter-spacing: 0.5px;
  margin-top: 6px;
}}

/* ── SECTION BANNERS ── */
.section-banner {{
  border-top: 3px solid #1a1a1a;
  border-bottom: 1px solid #1a1a1a;
  margin-bottom: 0;
}}
.section-banner td {{
  font-family: Arial, Helvetica, sans-serif;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 2.5px;
  text-transform: uppercase;
  padding: 7px 32px;
}}
.watchlist-banner  {{ background: #1a3a6b; }} .watchlist-banner td  {{ color: #ffffff; }}
.highlight-banner  {{ background: #1a1a1a; }} .highlight-banner td  {{ color: #ffffff; }}
.sector-banner     {{ background: #7c4700; }} .sector-banner td     {{ color: #ffffff; }}
.reg-banner        {{ background: #006633; }} .reg-banner td        {{ color: #ffffff; }}
.bond-banner       {{ background: #4a0072; }} .bond-banner td       {{ color: #ffffff; }}
.macro-banner      {{ background: #8b0000; }} .macro-banner td      {{ color: #ffffff; }}
.top5-banner       {{ background: #1a1a1a; border-top: 3px solid #c8a200; }} .top5-banner td {{ color: #c8a200; }}

/* ── NEWS CARD ── */
.news-card {{
  border-bottom: 1px solid #d4c5a9;
  margin: 0;
}}
.news-card td {{ padding: 0; }}
.card-company-tag {{
  font-family: Arial, Helvetica, sans-serif;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 2px;
  text-transform: uppercase;
  color: #1a3a6b;
  padding: 12px 32px 4px 32px !important;
}}
.card-headline {{
  font-family: Georgia, 'Times New Roman', Times, serif;
  font-size: 17px;
  font-weight: 700;
  color: #0a0a0a;
  line-height: 1.3;
  padding: 4px 32px 6px 32px !important;
}}
.card-source {{
  font-family: Arial, Helvetica, sans-serif;
  font-size: 9px;
  color: #888888;
  letter-spacing: 1px;
  text-transform: uppercase;
  padding: 0 32px 10px 32px !important;
  border-bottom: 1px solid #eee8d8;
}}
.card-cols {{ border-top: 0; }}
.card-cols td {{ vertical-align: top; }}
.col-left {{
  padding: 12px 16px 12px 32px !important;
  border-right: 1px solid #d4c5a9;
  background: #fdfcf8;
}}
.col-divider {{ background: #d4c5a9; width: 1px; }}
.col-right {{
  padding: 12px 32px 12px 16px !important;
  background: #f0f4ff;
}}
.col-label {{
  font-family: Arial, Helvetica, sans-serif;
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 2px;
  text-transform: uppercase;
  color: #666666;
  margin-bottom: 6px !important;
  padding-bottom: 4px !important;
  border-bottom: 1px solid #d4c5a9;
}}
.col-body {{
  font-family: Georgia, 'Times New Roman', Times, serif;
  font-size: 13px;
  line-height: 1.7;
  color: #2d2d2d;
  margin-top: 6px !important;
}}
.card-readmore {{
  font-family: Arial, Helvetica, sans-serif;
  font-size: 10px;
  color: #666666;
  padding: 8px 32px 12px 32px !important;
  border-top: 1px solid #eee8d8;
  background: #fdfcf8;
}}
.card-readmore a {{
  color: #1a3a6b;
  text-decoration: none;
  font-weight: 700;
}}
.card-body {{
  font-family: Georgia, 'Times New Roman', Times, serif;
  font-size: 13px;
  line-height: 1.7;
  color: #2d2d2d;
  padding: 16px 32px !important;
}}

/* ── COMPACT LINK LIST ── */
.link-list {{ border-bottom: 2px solid #d4c5a9; margin-bottom: 0; }}
.link-row {{
  font-family: Arial, Helvetica, sans-serif;
  font-size: 12px;
  line-height: 1.5;
  border-bottom: 1px solid #eee8d8;
  padding: 9px 32px !important;
  color: #1a1a1a;
}}
.link-anchor {{
  color: #1a3a6b;
  text-decoration: none;
  font-size: 12px;
  display: block;
}}
.link-anchor:hover {{ text-decoration: underline; }}
.nolink {{ color: #555555; }}

/* ── TOP 5 LIST ── */
.top5-list {{ border-bottom: 2px solid #1a1a1a; }}
.top5-num {{
  font-family: Georgia, 'Times New Roman', Times, serif;
  font-size: 28px;
  font-weight: 700;
  color: #c8a200;
  width: 48px;
  padding: 14px 8px 14px 32px !important;
  vertical-align: top;
  border-bottom: 1px solid #eee8d8;
  line-height: 1;
}}
.top5-text {{
  font-family: Georgia, 'Times New Roman', Times, serif;
  font-size: 13px;
  line-height: 1.7;
  color: #1a1a1a;
  padding: 14px 32px 14px 8px !important;
  border-bottom: 1px solid #eee8d8;
  vertical-align: top;
}}
.top5-text strong {{ color: #0a0a0a; font-weight: 700; }}

/* ── NO WATCHLIST ── */
.no-watchlist {{
  font-family: Arial, Helvetica, sans-serif;
  font-size: 11px;
  color: #888888;
  font-style: italic;
  padding: 14px 32px;
  border-bottom: 1px solid #eee8d8;
}}

/* ── FOOTER ── */
.footer-rule {{ background: #1a1a1a; height: 4px; }}
.footer {{
  background: #1a1a1a;
  padding: 20px 32px;
  text-align: center;
}}
.footer p {{
  font-family: Arial, Helvetica, sans-serif;
  font-size: 10px;
  color: #888888;
  line-height: 1.9;
  margin: 0;
}}
.footer a {{ color: #aaaaaa; text-decoration: none; }}

/* ── SPACER ── */
.spacer {{ height: 16px; background: #f4f1eb; }}
</style>
</head>
<body>
<div class="outer">
<div class="wrapper">

  <!-- MASTHEAD -->
  <div class="masthead">
    <div class="masthead-kicker">CareEdge Ratings &nbsp;&bull;&nbsp; Credit Strategy Desk</div>
    <div class="masthead-title">Daily Credit Intelligence</div>
    <div class="masthead-sub">India Credit &amp; Fixed Income Markets Monitor</div>
    <table class="masthead-date-strip" width="100%" cellpadding="0" cellspacing="0">
      <tr>
        <td align="left">{day_upper}</td>
        <td align="center">VOL. 1 &nbsp;|&nbsp; INTERNAL EDITION</td>
        <td align="right">CAREEDGE RATINGS</td>
      </tr>
    </table>
    <div class="masthead-confidential">CONFIDENTIAL — INTERNAL USE ONLY &nbsp;&bull;&nbsp; Not for external distribution &nbsp;&bull;&nbsp; All rating decisions subject to formal committee process</div>
  </div>

  {inner_html}

  <!-- FOOTER -->
  <div class="footer-rule"></div>
  <div class="footer">
    <p>
      Daily Credit Intelligence &nbsp;|&nbsp; {date_str} &nbsp;|&nbsp; CareEdge Ratings<br>
      Credit Strategy &amp; Surveillance Desk &nbsp;|&nbsp; Jitendra.Meghrajani@careedge.in<br>
      <br>
      <em>Confidential — Internal Use Only. Not for external distribution.<br>
      Auto-generated and delivered via GitHub Actions every weekday at 6:00 AM IST.</em>
    </p>
  </div>

</div><!-- /wrapper -->
</div><!-- /outer -->
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
