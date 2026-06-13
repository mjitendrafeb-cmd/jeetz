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
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SEEN_PATH = os.path.join(_REPO_ROOT, "data", "seen_headlines.json")


def _load_seen_headlines() -> set[str]:
    try:
        with open(_SEEN_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return set(data.get("keys", []))
    except Exception:
        return set()


def _save_seen_headlines(news_text: str) -> None:
    """Persist normalised keys from today's feed so tomorrow can skip them."""
    import re as _re
    keys = []
    for line in news_text.splitlines():
        # Strip numbering and tag prefix, take first 120 chars as key
        line = _re.sub(r"^\d+\.\s*", "", line)
        line = _re.sub(r"^\[[^\]]+\]\s*", "", line)
        key = line.lower().strip()[:120]
        if key:
            keys.append(key)
    os.makedirs(os.path.dirname(_SEEN_PATH), exist_ok=True)
    with open(_SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump({"date": str(datetime.date.today()), "keys": keys}, f, indent=2)
    # Commit and push so the file persists across workflow runs
    try:
        import subprocess
        token = os.environ.get("GITHUB_TOKEN", "")
        if token:
            subprocess.run(
                ["git", "remote", "set-url", "origin",
                 f"https://x-access-token:{token}@github.com/mjitendrafeb-cmd/jeetz.git"],
                cwd=_REPO_ROOT, check=True, capture_output=True
            )
        subprocess.run(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"],
                       cwd=_REPO_ROOT, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "github-actions[bot]"],
                       cwd=_REPO_ROOT, check=True, capture_output=True)
        subprocess.run(["git", "add", _SEEN_PATH], cwd=_REPO_ROOT, check=True, capture_output=True)
        result = subprocess.run(
            ["git", "commit", "-m", f"chore: update seen headlines {datetime.date.today()}"],
            cwd=_REPO_ROOT, capture_output=True
        )
        if result.returncode == 0:
            subprocess.run(["git", "push", "origin", "HEAD:main"],
                           cwd=_REPO_ROOT, check=True, capture_output=True)
            print(f"[seen_headlines] Saved {len(keys)} keys and pushed to repo")
        else:
            print("[seen_headlines] Nothing to commit (no change)")
    except Exception as exc:
        print(f"[seen_headlines] Push failed (non-fatal): {exc}")


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
DEDUPLICATE: If two items cover the same story (even if from different sections), keep only ONE card in the most relevant section. Below that card's source link, add a single line: <span style="font-size:10px;color:#999;">Also reported by: Source2, Source3</span>
MONETARY PENALTIES: Any "RBI Imposes Monetary Penalty", "SEBI Order", "NHB Penalty" or enforcement action ALWAYS goes to S3 — never S2 — regardless of which entity was penalised. Format: 1-sentence "What Happened" (amount + entity + reason), NO credit implication section, just the link.
WATCHLIST items ([WATCHLIST — Company]) are HIGHEST PRIORITY — always appear first in S1.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT — raw HTML, ALL inline styles, NO class names, NO <style> blocks
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

════════════
PART A — TOP 5 LEAD STORIES  (used only for deciding Part B ordering; NOT output separately)
════════════
Identify the 5 most credit-significant stories mentally. Watchlist entities first.
DO NOT output Part A as HTML. Use it only to ensure those 5 stories appear at the TOP of their respective sections in Part B.

════════════
PART B — ALL 5 SECTIONS  (goes in attachment, newspaper column layout)
════════════
Show ALL 5 sections. Each item in EXACTLY ONE section. Most credit-significant story per section comes FIRST.

Section routing:
  S1 — [WATCHLIST — Company] items ONLY
  S2 — NBFC, HFC, Banking, Broking, Fintech, MFI, rating agency actions
  S3 — RBI, SEBI, NHB regulatory circulars/orders
  S4 — Bonds, G-Sec, CP, Securitisation, FIMMDA, CCIL market items
  S5 — Macro: GDP, CPI, IIP, forex, fiscal deficit, US Fed, global

Each section = one section-banner div + article divs. Use EXACTLY this structure:

SECTION BANNER (copy exactly, note id and data-section):
S1: <div id="s1" data-section="banner" style="margin:20px 0 0;padding:6px 0;border-top:3px solid #cc0000;border-bottom:1px solid #cc0000;font-size:9px;font-weight:800;letter-spacing:3px;text-transform:uppercase;color:#cc0000;">&#9733; S1 &mdash; MY RATED ENTITIES &amp; WATCHLIST</div>
S2: <div id="s2" data-section="banner" style="margin:20px 0 0;padding:6px 0;border-top:3px solid #b45309;border-bottom:1px solid #b45309;font-size:9px;font-weight:800;letter-spacing:3px;text-transform:uppercase;color:#b45309;">S2 &mdash; NBFC, HFC, BROKING, FINTECH, FI SECTORS</div>
S3: <div id="s3" data-section="banner" style="margin:20px 0 0;padding:6px 0;border-top:3px solid #1e3a8a;border-bottom:1px solid #1e3a8a;font-size:9px;font-weight:800;letter-spacing:3px;text-transform:uppercase;color:#1e3a8a;">S3 &mdash; RBI, SEBI, NHB REGULATIONS</div>
S4: <div id="s4" data-section="banner" style="margin:20px 0 0;padding:6px 0;border-top:3px solid #15803d;border-bottom:1px solid #15803d;font-size:9px;font-weight:800;letter-spacing:3px;text-transform:uppercase;color:#15803d;">S4 &mdash; BOND &amp; MONEY MARKETS</div>
S5: <div id="s5" data-section="banner" style="margin:20px 0 0;padding:6px 0;border-top:3px solid #6d28d9;border-bottom:1px solid #6d28d9;font-size:9px;font-weight:800;letter-spacing:3px;text-transform:uppercase;color:#6d28d9;">S5 &mdash; MACROECONOMIC DEVELOPMENTS</div>

ARTICLE (use for EVERY article — newspaper column style):
<div style="break-inside:avoid;padding:12px 0;border-bottom:1px solid #ddd;">
  <p style="margin:0 0 3px;font-size:8px;font-weight:800;text-transform:uppercase;letter-spacing:1.5px;color:#999;">SOURCE &bull; DATE</p>
  <p style="margin:0 0 6px;font-size:14px;font-weight:700;font-family:Georgia,serif;line-height:1.25;color:#111;">HEADLINE</p>
  <p style="margin:0 0 5px;font-size:10.5px;color:#333;line-height:1.65;">What happened in 2-3 tight sentences. Facts only.</p>
  <p style="margin:0 0 6px;font-size:10px;color:#444;line-height:1.6;border-left:3px solid #cc0000;padding-left:7px;font-style:italic;">Credit implication: 1-2 sentences on rating/liquidity/asset quality/governance impact.</p>
  <a href="ACTUAL_URL" target="_blank" style="font-size:9px;color:#888;text-decoration:none;font-weight:600;">Read more &#8594;</a>
</div>

For FIRST article in S1 only (lead story), use this wider hero format:
<div style="break-inside:avoid;padding:12px 0 14px;border-bottom:2px solid #cc0000;margin-bottom:4px;">
  <p style="margin:0 0 3px;font-size:8px;font-weight:800;text-transform:uppercase;letter-spacing:1.5px;color:#cc0000;">&#9733; WATCHLIST &bull; SOURCE</p>
  <p style="margin:0 0 8px;font-size:18px;font-weight:800;font-family:Georgia,serif;line-height:1.2;color:#111;">HEADLINE — BIGGER AND BOLDER</p>
  <p style="margin:0 0 6px;font-size:11px;color:#222;line-height:1.7;">What happened in 2-3 sentences. Facts only.</p>
  <p style="margin:0 0 6px;font-size:10.5px;color:#333;line-height:1.65;border-left:3px solid #cc0000;padding-left:8px;font-style:italic;">Credit implication: impact on rating outlook / liquidity / asset quality.</p>
  <a href="ACTUAL_URL" target="_blank" style="font-size:9px;color:#cc0000;text-decoration:none;font-weight:700;">Read full story &#8594;</a>
</div>

Omit the link if no URL. For empty section: <p style="padding:10px 0;font-size:10px;color:#aaa;font-style:italic;">No news in this category today.</p>

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

    if len(news_text) > 32000:
        news_text = news_text[:32000] + "\n[...truncated]"

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
    # Part C starts at the black takeaways header (background:#1a1a1a table)
    c_match = re.search(
        r'<table[^>]*style="[^"]*background\s*:\s*#1a1a1a[^"]*"',
        full_html
    )
    # Part B starts at first section banner (data-section="banner" div or id="s1")
    b_match = re.search(r'<div[^>]+data-section=["\']banner["\']|<div[^>]+id=["\']s1["\']', full_html)

    if b_match and c_match and c_match.start() > b_match.start():
        part_b = full_html[b_match.start():c_match.start()].strip()
        part_c = full_html[c_match.start():].strip()
        return part_b, part_c
    if c_match:
        return full_html[:c_match.start()].strip(), full_html[c_match.start():].strip()
    if b_match:
        return full_html[b_match.start():].strip(), ""
    return full_html, ""


# ---------------------------------------------------------------------------
# Attachment — S1-S5 with clickable nav
# ---------------------------------------------------------------------------

def build_attachment(part_b_html: str, today: datetime.date) -> str:
    date_str = today.strftime("%d %B %Y")
    dow_full = today.strftime("%A, %d %B %Y").upper()
    edition = f"Vol. {today.year} · Internal Use Only"

    sections = [
        ("s1", "★ My Rated Entities &amp; Watchlist", "1"),
        ("s2", "NBFC, HFC, Broking, Fintech &amp; FI", "2"),
        ("s3", "RBI, SEBI, NHB Regulations", "3"),
        ("s4", "Bond &amp; Money Markets", "4"),
        ("s5", "Macroeconomic Developments", "5"),
    ]

    pages_html = ""
    for sid, title, pnum in sections:
        if sid == "s1":
            # Front page — full masthead
            pages_html += f"""
<div class="news-page front-page" id="pg1">
  <div class="mast-top">
    <div class="mast-left">{dow_full}<br>{edition}</div>
    <div class="mast-right">Credit &amp; Markets Intelligence</div>
  </div>
  <div class="mast-center">
    <div class="mast-name">Credit Intelligence News</div>
    <hr class="mast-rule">
  </div>
  <div class="mast-sub">
    <span>S1 Watchlist &middot; S2 NBFC/FI &middot; S3 Regs &middot; S4 Markets &middot; S5 Macro</span>
    <span class="red">&#128274; CONFIDENTIAL</span>
  </div>
  <nav class="navbar">
    <a href="#pg1">&#9733; Watchlist</a>
    <a href="#pg2">NBFC &amp; FI</a>
    <a href="#pg3">Regulations</a>
    <a href="#pg4">Markets</a>
    <a href="#pg5">Macro</a>
  </nav>
  <div class="columns" id="{sid}-col"></div>
  <div class="page-foot">
    <span>Credit Intelligence News &mdash; {date_str}</span>
    <span>Page 1 of 5</span>
    <span>&#128274; Confidential</span>
  </div>
</div>"""
        else:
            pages_html += f"""
<div class="news-page" id="pg{pnum}">
  <div class="page-header">
    <div class="ph-meta">{date_str} &bull; Internal Use Only</div>
    <div class="ph-title">{title}</div>
    <div class="ph-num">{pnum}</div>
  </div>
  <div class="columns" id="{sid}-col"></div>
  <div class="page-foot">
    <span>Credit Intelligence News &mdash; {date_str}</span>
    <span>Page {pnum} of 5</span>
    <span>&#128274; Confidential</span>
  </div>
</div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Credit Intelligence News — {date_str}</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,700;0,900;1,700&family=PT+Serif:ital,wght@0,400;0,700;1,400&display=swap" rel="stylesheet">
<style>
  @page {{ size: A4; margin: 1.2cm 1.4cm; }}
  @page :first {{ margin-top: 0.5cm; }}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#f0ece4;font-family:'PT Serif',Georgia,serif;color:#111;font-size:11px}}
  .newspaper{{max-width:960px;margin:20px auto}}

  /* ── PAGE UNITS ── */
  .news-page{{background:#fdfaf5;box-shadow:0 2px 24px rgba(0,0,0,.18);margin-bottom:28px;padding-bottom:20px;break-before:page;page-break-before:always}}
  .front-page{{break-before:auto;page-break-before:auto}}

  /* ── MASTHEAD (front page only) ── */
  .mast-top{{display:flex;justify-content:space-between;align-items:flex-end;padding:14px 28px 6px;border-bottom:1px solid #aaa}}
  .mast-left{{font-size:8.5px;letter-spacing:1.5px;text-transform:uppercase;color:#555;line-height:1.8}}
  .mast-right{{font-size:8.5px;text-align:right;color:#555;line-height:1.8}}
  .mast-center{{text-align:center;padding:4px 28px 0}}
  .mast-name{{font-family:'Playfair Display',Georgia,serif;font-size:58px;font-weight:900;line-height:1;letter-spacing:-2px;color:#111}}
  .mast-rule{{border:none;border-top:3px double #111;margin:6px 0 0}}
  .mast-sub{{display:flex;justify-content:space-between;align-items:center;padding:5px 28px;border-bottom:3px solid #111;font-size:8.5px;letter-spacing:1px;text-transform:uppercase;color:#555}}
  .mast-sub .red{{color:#cc0000;font-weight:700;border:1px solid #cc0000;padding:1px 6px}}

  /* ── NAV BAR ── */
  .navbar{{display:flex;border-bottom:2px solid #cc0000;background:#111}}
  .navbar a{{flex:1;text-align:center;padding:7px 4px;font-size:8px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#ccc;text-decoration:none;border-right:1px solid #333}}
  .navbar a:first-child{{color:#fff}}
  .navbar a:last-child{{border-right:none}}

  /* ── INNER PAGE HEADER ── */
  .page-header{{display:flex;justify-content:space-between;align-items:center;padding:8px 28px;border-bottom:3px solid #111;border-top:4px solid #cc0000}}
  .page-header .ph-meta{{font-size:8px;letter-spacing:1px;text-transform:uppercase;color:#777}}
  .page-header .ph-title{{font-family:'Playfair Display',Georgia,serif;font-size:14px;font-weight:700;color:#111}}
  .page-header .ph-num{{font-size:26px;font-weight:900;font-family:'Playfair Display',Georgia,serif;color:#cc0000;line-height:1}}

  /* ── COLUMNS ── */
  .columns{{padding:0 28px 8px;column-count:3;column-gap:0;column-rule:1px solid #ccc;min-height:80px}}

  /* Section banners span all columns */
  [data-section="banner"]{{column-span:all;margin:20px -28px 0;padding:5px 28px;border-top:3px solid;border-bottom:1px solid}}

  /* ── PAGE FOOTER ── */
  .page-foot{{display:flex;justify-content:space-between;border-top:1px solid #bbb;margin:8px 28px 0;padding-top:6px;font-size:8px;color:#888;letter-spacing:1px;text-transform:uppercase}}

  @media print {{
    body{{background:#fff}}
    .news-page{{box-shadow:none;margin-bottom:0}}
  }}
</style>
</head>
<body>
<div class="newspaper">
{pages_html}
</div>

<!-- Hidden staging area for Claude's HTML, distributed by JS below -->
<div id="raw-content" style="display:none">{part_b_html}</div>

<script>
(function(){{
  var raw = document.getElementById('raw-content');
  var sids = ['s1','s2','s3','s4','s5'];
  var buckets = {{}};
  sids.forEach(function(s){{ buckets[s] = []; }});
  var current = null;
  Array.from(raw.childNodes).forEach(function(node){{
    if(node.nodeType === 1){{
      var id = node.id || '';
      if(sids.indexOf(id) !== -1){{ current = id; return; }}
    }}
    if(current) buckets[current].push(node.cloneNode(true));
  }});
  sids.forEach(function(sid){{
    var col = document.getElementById(sid + '-col');
    if(!col) return;
    if(buckets[sid].length === 0){{
      col.innerHTML = '<p style="padding:20px 0;font-size:11px;color:#aaa;font-style:italic;">No news in this category today.</p>';
    }} else {{
      buckets[sid].forEach(function(n){{ col.appendChild(n); }});
    }}
  }});
}})();
</script>
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
  <p style="margin:0 0 3px;font-size:9px;letter-spacing:2px;text-transform:uppercase;color:#999;">{dow} &bull; INTERNAL USE ONLY</p>
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
  <span style="color:#cc0000;font-weight:700;">Credit Intelligence News</span> &mdash; {date_str}<br>
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

    print("Saving seen headlines for tomorrow's dedup...")
    _save_seen_headlines(news_text)

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
