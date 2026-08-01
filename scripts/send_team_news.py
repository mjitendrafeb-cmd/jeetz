#!/usr/bin/env python3
"""
send_team_news.py — Per-person watchlist news + rule-based S1-S5 digest.

Runs WITHOUT the Anthropic API (zero credits). Driven by team.json
(managed at docs/team.html): one row per company with GH/Analyst/RH
names, emails, send flags, and S1-S5 section flags.

Each enabled person receives ONE email:
  S1 = news for the companies they are mapped to (only rows with S1 ticked)
  S2-S5 = rule-classified sector/regulation/bond/macro sections, included
          if ticked on any row where that person is enabled.
"""

import os
import re
import json
import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

from fetch_news import fetch_all_news

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEAM_PATH = os.path.join(_REPO_ROOT, "team.json")
_SEEN_PATH = os.path.join(_REPO_ROOT, "data", "team_seen.json")  # separate memory from
# the daily Claude report so the two systems never suppress each other's items.

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

SECTION_TITLES = {
    "S1": "Watchlist News",
    "S2": "S2 — NBFC / FI Sector",
    "S3": "S3 — RBI, SEBI & Regulations",
    "S4": "S4 — Bond & Money Markets",
    "S5": "S5 — Macro",
}

# Section routing mirrors the 7:30 report's prompt:
#   S1 — [WATCHLIST — Company] items only
#   S2 — NBFC, HFC, Banking, Broking, Fintech, MFI, rating agency actions
#   S3 — RBI, SEBI, NHB regulatory circulars/orders (+ ALL penalties)
#   S4 — Bonds, G-Sec, CP, Securitisation, FIMMDA, CCIL market items
#   S5 — Macro: GDP, CPI, IIP, forex, fiscal deficit, US Fed, global
_S4_RE = re.compile(
    r"\b(bond[s]?|ncd[s]?|debenture[s]?|yield[s]?|g-sec|gsec|gilt[s]?|"
    r"commercial paper|\bcp\b|securitisation|securitization|fimmda|ccil|"
    r"treasury bill[s]?|t-bill[s]?|masala bond|certificate[s]? of deposit|"
    r"repo auction|vrr|\bomo\b|state (development loan|government securities)|"
    r"money market|debt market|coupon rate|private placement)\b",
    re.IGNORECASE,
)
_S5_RE = re.compile(
    r"\b(gdp|inflation|cpi|wpi|iip|core sector|repo rate|monetary policy|\bmpc\b|"
    r"fiscal deficit|current account deficit|\bcad\b|forex reserves|foreign exchange reserves|"
    r"rupee|trade deficit|\bpmi\b|gst collection|us fed|federal reserve|fomc|"
    r"ecb|global growth|crude (oil )?price|industrial production|unemployment rate|"
    # Widened to close the gap with the 7:30 AI's S5 judgment — these are all
    # topics the AI routes to Macro but the old list missed.
    r"economic growth|growth (forecast|projection|estimate)|economic survey|"
    r"rate (cut|hike)|union budget|capex cycle|monsoon|el nino|"
    r"exports?|imports?|tariffs?|trade (war|deal|agreement)|"
    r"imf|world bank|\badb\b|\boecd\b|sovereign (rating|bond)|"
    r"dollar index|us treasur(y|ies)|brent|gold price|"
    r"consumer price|wholesale price|per capita income|employment (data|rate)|"
    r"bank of (japan|england)|\bboj\b|\bpboc\b)\b",
    re.IGNORECASE,
)
# Sources that only ever carry macro content — route straight to S5 even when
# the headline dodges every keyword (mirrors the 7:30 AI, which knows an
# RBI-DBIE / MOSPI release is macro from context, not keywords).
_S5_SOURCES = ("rbi-dbie", "macro-release", "mospi", "pib")
_S3_SOURCES = ("rbi", "sebi", "nhb", "rbi-enforcement")
# 7:30 rule: "Any RBI Imposes Monetary Penalty / SEBI Order / NHB Penalty or
# enforcement action ALWAYS goes to S3 — never S2 — regardless of entity."
_PENALTY_RE = re.compile(
    r"\b(monetary penalty|imposes? (a )?penalt|penalis|penaliz|"
    r"enforcement action|adjudication order|show cause notice|"
    r"debarr|cease and desist|sebi order|compounding order)\w*",
    re.IGNORECASE,
)

# Geography scope: this is an Indian credit desk (7:30 prompt: "Credit Rating
# Intelligence Agent at CareEdge Ratings"). Local financial news from other
# emerging markets leaks in through generic bond/market keywords — a Nigerian
# bond story reached S4. Drop those unless the item also concerns India.
# Major economies (US/UK/EU/China/Japan) are NOT listed: the 7:30 S5 explicitly
# admits "US Fed, global" macro.
_OUT_OF_SCOPE_GEO_RE = re.compile(
    r"\b(nigeria|nigerian|kenya|kenyan|ghana|uganda|tanzania|zimbabwe|zambia|"
    r"pakistan|bangladesh|sri lanka|nepal|myanmar|"
    r"philippine|vietnam|indonesia|malaysia|thailand|"
    r"brazil|argentin|colombia|mexico|peru|chile|"
    r"turkey|turkish|egypt|morocco|south africa|naira|shilling|"
    r"cedi|ringgit|baht|peso|rand)\w*",
    re.IGNORECASE,
)
_INDIA_RE = re.compile(
    r"\b(india|indian|bharat|rbi|sebi|irdai|nhb|nabard|sidbi|nse|bse|"
    r"rupee|crore|lakh|nbfc|hfc|mumbai|delhi|bengaluru|chennai|kolkata|"
    r"g-sec|gst|mpc|repo rate|dalal street|nifty|sensex)\w*",
    re.IGNORECASE,
)
# Country-code TLDs of sources that publish other markets' local news
# (e.g. streamlinefeed.co.ke). Not a blocklist of the outlet — a scope signal.
_FOREIGN_TLD_RE = re.compile(
    r"\.(ke|ng|gh|ug|tz|zw|pk|bd|lk|np|ph|vn|id|my|th|br|ar|mx|tr|eg|za)\b",
    re.IGNORECASE,
)


def _is_out_of_scope(it: dict) -> bool:
    """True when the story is another market's local news with no India angle."""
    body = f'{it["title"]} {it["summary"]}'
    if _INDIA_RE.search(body) or _INDIA_RE.search(it["source"]):
        return False
    return bool(_OUT_OF_SCOPE_GEO_RE.search(body)
                or _FOREIGN_TLD_RE.search(it["source"]))

# Mechanical version of the 7:30 report's AI SKIP rules (stock tips, target
# price calls, awards, CSR, consumer product launches). Same intent, no AI.
_TEAM_JUNK_RE = re.compile(
    r"\b(buy|sell|hold|accumulate|reduce|add|neutral|not rated)\b[^.|]{0,70}\btarget\b"
    r"|\bfor the target\b"
    r"|\btarget (price|rs\.?)\b"
    r"|\b(rated|maintains?|reiterates?|upgrades? to|downgrades? to) (strong )?(buy|sell|hold|accumulate|reduce|neutral|overweight|underweight)\b"
    r"|\bstock (pick|tip|recommendation)s?\b"
    r"|\bbrokerage[s]? (say|view|pick)"
    r"|\b(wins?|receives?|bags?|conferred) .{0,40}award\b|\bfelicitat"
    r"|\bcsr (initiative|activity|spend)"
    r"|\blaunch(es|ed)? .{0,30}\b(app|campaign|scheme|platform|card|savings account)\b"
    # Technical-analysis / chart noise (MarketsMojo, TradingView and similar).
    # Never credit-relevant, and it dominates Google's top slots for small caps.
    r"|\b(golden|death) cross\b"
    r"|\btechnical(s\b|\s+(signal|momentum|improvement|indicator|analysis|chart|outlook|strength|weakness))"
    r"|\b(moving average|rsi|macd|bollinger|candlestick|support and resistance)\b"
    # Stock-recommendation grade changes (NOT credit rating grades — those use
    # AAA/AA/BBB etc, which deliberately do not appear in this word list).
    r"|\b(upgraded|downgraded|upgrade[sd]?|downgrade[sd]?) to (strong )?(buy|sell|hold|accumulate|reduce|neutral|outperform|underperform)\b"
    r"|\brevenue breakdown\b"
    r"|\b52[- ]week (high|low)\b"
    r"|\bsubscribe\b.{0,60}\bipo\b|\bipo\b.{0,60}\bsubscribe\b"
    r"|\b(gmp|grey market premium)\b"
    # Mutual-fund scheme/NAV pages — matched S4 on 'gilt' but carry no news
    # ("Kotak Gilt Investment Regular-IDCW Quarterly - NAV, Reviews...").
    r"|\bnav\b.{0,40}\b(review|asset allocation|scheme|portfolio)\b"
    r"|\b(idcw|direct plan|regular plan)\b"
    r"|\basset allocation\b.{0,30}\breview"
    r"|\bfund (performance|returns?) (review|analysis)\b",
    re.IGNORECASE,
)


def _is_team_junk(it: dict) -> bool:
    return bool(_TEAM_JUNK_RE.search(f'{it["title"]} {it["summary"]}'))

ROLES = (("gh_name", "gh_email", "send_gh"),
         ("analyst_name", "analyst_email", "send_analyst"),
         ("rh_name", "rh_email", "send_rh"))


def _load_team() -> dict:
    with open(_TEAM_PATH, encoding="utf-8") as f:
        return json.load(f)


_FILLER = {"of", "and", "the", "&", "for"}


def _phrase(name: str) -> str:
    """Contiguous prefix of the company name covering TWO significant words.
    'Bank of Baroda' -> 'bank of baroda' (a bare 'bank of' matched every
    bank headline — the BoB/BoI/BoM rows all 'matched' the same items).
    'Small Industries Development Bank' -> 'small industries'.
    'D. S. Integrated FinSec' -> 'd. s. integrated finsec' (initials are
    not significant on their own)."""
    words = name.lower().split()
    if not words:
        return ""
    sig = 0
    for i, w in enumerate(words):
        if len(w.strip(".")) >= 3 and w not in _FILLER:
            sig += 1
        if sig == 2:
            return " ".join(words[:i + 1])
    return " ".join(words)


_SUFFIXES = {"private", "limited", "ltd", "pvt", "co", "company", "(india)", "india"}
# Words too common in BFSI headlines to identify a company on their own —
# 'small' alone must not attach an Equitas Small Finance story to SIDBI.
_COMMON = {"small", "national", "india", "indian", "bank", "finance", "financial",
           "capital", "home", "housing", "credit", "micro", "asset", "industries",
           "development", "investment", "securities", "insurance", "mutual", "fund"}


def _sig_words(name: str) -> list[str]:
    """First two significant words of a company name (len>=3, no fillers,
    no corporate suffixes) — used to sanity-check tag attribution."""
    out = []
    for w in name.lower().split():
        w2 = w.strip(".,()")
        if len(w2) >= 3 and w2 not in _FILLER and w2 not in _SUFFIXES:
            out.append(w2)
        if len(out) == 2:
            break
    return out


def _acronym(name: str) -> str:
    """SIDBI-style initialism from the name's non-filler words — real
    headlines say 'SIDBI', not 'Small Industries Development Bank'."""
    letters = [w[0] for w in name.lower().split()
               if w.strip(".,()") and w not in _FILLER and not w.startswith("(")]
    a = "".join(letters)
    return a if len(a) >= 4 else ""


def _mentions_company(body: str, name: str) -> bool:
    """Does the story text actually refer to this company? True when it
    contains the acronym (sidbi), any DISTINCTIVE name word (indostar,
    baroda, equitas), or at least TWO common words ('small' + 'industries').
    A single common word like 'small' is not enough — that attached
    Equitas Small Finance stories to SIDBI."""
    acro = _acronym(name)
    if acro and re.search(r"\b" + re.escape(acro) + r"\b", body):
        return True
    words = _sig_words(name)
    matched = [w for w in words if w in body]
    if any(w not in _COMMON for w in matched):
        return True
    return len(matched) >= 2


_URL_IN_TEXT_RE = re.compile(r"https?://\S+")
_MD_RE = re.compile(r"[*_`]{1,3}")
# A headline that is only a date ("Jul 29 2026", "29 July 2026") carries no
# information — Telegram posts often open with a date line.
_DATE_ONLY_RE = re.compile(
    r"^\W*(?:\d{1,2}[\s./-]+\w{3,9}[\s./-]+\d{2,4}"
    r"|\w{3,9}[\s./-]+\d{1,2},?[\s./-]+\d{2,4}"
    r"|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\W*$",
    re.IGNORECASE,
)


def _tidy_text(s: str) -> str:
    """Strip inline URLs and markdown, collapse whitespace."""
    s = _URL_IN_TEXT_RE.sub(" ", s)
    s = _MD_RE.sub("", s)
    return " ".join(s.split()).strip(" -–—:|·")


def _first_sentence(s: str, limit: int = 130) -> str:
    """Leading sentence/clause of a blob, capped for a headline."""
    s = s.strip()
    for sep in (". ", " | ", "? ", "! "):
        idx = s.find(sep)
        if 25 <= idx <= limit:
            return s[:idx].strip()
    return s[:limit].rstrip() + ("…" if len(s) > limit else "")


# Boilerplate that trails Telegram forwards of news articles.
_TG_TAIL_RE = re.compile(
    r"\s*(\d+\s*min read|last updated|read more|click here|share this|"
    r"subscribe|join (our )?channel|via @\S+|source\s*:.*)\s*$",
    re.IGNORECASE,
)
_TG_LEAD_DATE_RE = re.compile(
    r"^\W*(?:\d{1,2}[\s./-]+\w{3,9}[\s./-]+\d{2,4}"
    r"|\w{3,9}[\s./-]+\d{1,2},?[\s./-]+\d{2,4})\W*",
    re.IGNORECASE,
)


def _telegram_headline(body: str) -> str:
    """Pull a real headline out of a raw Telegram message.

    Channels mark the headline with *bold* markdown, and otherwise put it
    before the article URL. Without this, _parse_item's ':'/'—' splits gave
    a bare date ('Jul 29 2026') or a wall of rate-table numbers."""
    bold = re.search(r"\*\*?([^*]{20,200})\*\*?", body)
    if bold:
        head = bold.group(1)
    else:
        u = _URL_IN_TEXT_RE.search(body)
        head = body[:u.start()] if (u and u.start() > 20) else body
    head = _tidy_text(head)
    head = _TG_LEAD_DATE_RE.sub("", head)          # drop leading date line
    for _ in range(3):                              # drop trailing boilerplate
        new_head = _TG_TAIL_RE.sub("", head).strip(" -–—:|·,")
        if new_head == head:
            break
        head = new_head
    return _first_sentence(head) if head else ""


def _parse_item(raw: str) -> dict:
    item = re.sub(r"^\d+\.\s*", "", raw)
    tags = re.findall(r"^\[([^\]]+)\]\s*", item)
    body = re.sub(r"^(\[[^\]]+\]\s*)+", "", item)
    url = ""
    m = re.search(r"\|\s*URL:(\S+)", body)
    if m:
        url = m.group(1)
    pub = ""
    m = re.search(r"\|\s*PUB:([^|]+)", body)
    if m:
        pub = m.group(1).strip()
    tag_str = " ".join(tags)
    if "TELEGRAM" in tag_str.upper():
        # Telegram arrives as a raw 500-char message dump with no
        # "source: title — summary" structure, so the ':' / '—' splits below
        # produced garbage headlines (a bare date, or a wall of text with the
        # URL printed inline). Rebuild a clean headline + link instead.
        ch = re.search(r"TELEGRAM[^@]*(@\S+)", tag_str)
        source = ch.group(1) if ch else "Telegram"
        if not url:
            u = _URL_IN_TEXT_RE.search(body)
            if u:
                url = u.group(0).rstrip(").,;")
        title = _telegram_headline(body)
        clean = _tidy_text(body)
        rest = clean[len(title):] if clean.startswith(title) else clean
        summary = _TG_TAIL_RE.sub("", rest).strip(" -–—:|·,")[:180]
        if not title:
            title, summary = _first_sentence(clean), ""
    else:
        body = body.split(" | ")[0]
        source, _, rest = body.partition(": ")
        title, _, summary = rest.partition(" — ")
        title, summary = _tidy_text(title), _tidy_text(summary)
        # A date-only or stub headline is useless — promote from the summary.
        if summary and (_DATE_ONLY_RE.match(title) or len(title) < 15):
            title = _first_sentence(summary)
            summary = ""
        if len(title) > 150:
            title = _first_sentence(title, 150)
    wl_company = ""
    for t in tags:
        m2 = re.match(r"WATCHLIST\s*[—-]\s*(.+)", t)
        if m2:
            wl_company = m2.group(1).strip()
    return {
        "tags": " ".join(tags),
        "wl_company": wl_company,
        "source": source.strip(),
        "title": (title or rest).strip(),
        "summary": summary.strip()[:220],
        "url": url,
        "pub": pub,
    }


def _classify(it: dict, company_phrases: list[str]) -> str:
    text = (it["tags"] + " " + it["source"] + " " + it["title"] + " " + it["summary"]).lower()
    if "watchlist" in it["tags"].lower() or any(p and p in text for p in company_phrases):
        return "S1"
    # 7:30 rule: penalties/enforcement ALWAYS S3, never S2, whoever the entity.
    if _PENALTY_RE.search(text):
        return "S3"
    src = it["source"].lower()
    # Macro-only sources go to S5 before the generic "rbi*" S3 rule can grab
    # them (RBI-DBIE is macro data, not regulation).
    if src.startswith(_S5_SOURCES):
        return "S5"
    if src.startswith(_S3_SOURCES) or "sebi" in src:
        return "S3"
    if _S4_RE.search(text):
        return "S4"
    if _S5_RE.search(text):
        return "S5"
    return "S2"


def _match_companies(it: dict, rows: list[dict]) -> list[str]:
    """Tag from the fetcher is authoritative (the item came from that
    company's own query); text phrase match is only a fallback. Re-matching
    by text alone silently dropped tagged items whose headline did not
    repeat the company name."""
    body = (it["title"] + " " + it["summary"]).lower()
    tag = it.get("wl_company", "").lower()
    hits = []
    for r in rows:
        name = r["company"].strip()
        if not name:
            continue
        n = name.lower()
        tag_match = tag and (tag == n or tag.startswith(n) or n.startswith(tag))
        if tag_match:
            # Sanity: the story must actually mention the company. Google's
            # per-company query sometimes returns unrelated stories (e.g. a
            # Patanjali deal from 'D. S. Integrated's query because 'd.' is
            # a substring of every 'Ltd.').
            if _sig_words(name) and not _mentions_company(body, name):
                print(f"[WARN] tag '{name[:40]}' but story never mentions it: "
                      f"'{it['title'][:60]}' — dropped from this company")
                tag_match = False
        if tag_match or n in body or (_phrase(name) and _phrase(name) in body):
            hits.append(name)
    return hits


# ---------------------------------------------------------------------------
# Dedup memory (30-day, independent of the Claude report's memory)
# ---------------------------------------------------------------------------

def _key(it: dict) -> str:
    return f"{it['source']}: {it['title']}".lower().strip()[:120]


def _load_seen() -> set[str]:
    try:
        with open(_SEEN_PATH, encoding="utf-8") as f:
            data = json.load(f)
        today = str(datetime.date.today())
        keys: set[str] = set()
        for d, ks in data.get("days", {}).items():
            if d < today:
                keys.update(ks)
        return keys
    except Exception:
        return set()


def _save_seen(items: list[dict]) -> None:
    os.makedirs(os.path.dirname(_SEEN_PATH), exist_ok=True)
    try:
        with open(_SEEN_PATH, encoding="utf-8") as f:
            days = json.load(f).get("days", {})
    except Exception:
        days = {}
    days[str(datetime.date.today())] = [_key(it) for it in items]
    cutoff = str(datetime.date.today() - datetime.timedelta(days=30))
    days = {d: v for d, v in days.items() if d >= cutoff}
    with open(_SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump({"days": days}, f, indent=2)
    _git_push(_SEEN_PATH)


def _git_push(path: str) -> None:
    try:
        import subprocess
        token = os.environ.get("GITHUB_TOKEN", "")
        if token:
            subprocess.run(["git", "remote", "set-url", "origin",
                            f"https://x-access-token:{token}@github.com/mjitendrafeb-cmd/jeetz.git"],
                           cwd=_REPO_ROOT, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"],
                       cwd=_REPO_ROOT, capture_output=True)
        subprocess.run(["git", "config", "user.name", "github-actions[bot]"],
                       cwd=_REPO_ROOT, capture_output=True)
        subprocess.run(["git", "add", path], cwd=_REPO_ROOT, capture_output=True)
        r = subprocess.run(["git", "commit", "-m", "chore: update team news memory"],
                           cwd=_REPO_ROOT, capture_output=True)
        if r.returncode == 0:
            subprocess.run(["git", "pull", "--rebase", "origin", "main"], cwd=_REPO_ROOT, capture_output=True)
            subprocess.run(["git", "push", "origin", "HEAD:main"], cwd=_REPO_ROOT, capture_output=True)
    except Exception as exc:
        print(f"[git] non-fatal: {exc}")


# ---------------------------------------------------------------------------
# HTML rendering (plain, no AI) -- table-based layout for email-client
# compatibility (Outlook/Gmail), cream/navy palette.
# ---------------------------------------------------------------------------

_NAVY = "#132A46"
_NAVY_SOFT = "#9AA9BC"
_CREAM = "#EDEAE3"
_RED = "#A32638"
_GREEN = "#2E6B4F"
_GREY = "#8A8578"
_DIVIDER = "#ECE8E0"
_MANAGE_URL = "https://mjitendrafeb-cmd.github.io/jeetz/team.html"

# Matches "up ~34%", "profit up 36%", "falls 12.5%", "-74.4%", "surges 8%"
_DELTA_RE = re.compile(
    r"\b(up|rise[sd]?|surge[sd]?|jump[sd]?|grow[sn]?|gain[sed]*|higher)\b[^%\d]{0,25}(\d+\.?\d*)\s*%"
    r"|(\d+\.?\d*)\s*%[^%]{0,15}\b(up|rise[sd]?|surge[sd]?|jump[sd]?|grow[sn]?|gain[sed]*|higher)\b"
    r"|\b(down|falls?|fell|declin\w*|drop[sped]*|slid\w*|contract\w*|lower)\b[^%\d]{0,25}(\d+\.?\d*)\s*%"
    r"|(\d+\.?\d*)\s*%[^%]{0,15}\b(down|falls?|fell|declin\w*|drop[sped]*|slid\w*|contract\w*|lower)\b",
    re.IGNORECASE,
)
_NEG_WORDS = ("down", "fall", "fell", "declin", "drop", "slid", "contract", "lower")


def _delta_badge(text: str) -> str:
    """Extract an 'up 36%' / 'down 74.4%' pattern and render a coloured
    up/down arrow badge, or '' if the item carries no percentage move."""
    m = _DELTA_RE.search(text)
    if not m:
        return ""
    groups = [g for g in m.groups() if g]
    pct = next((g for g in groups if re.match(r"^\d+\.?\d*$", g)), None)
    if not pct:
        return ""
    negative = any(w in m.group(0).lower() for w in _NEG_WORDS)
    color = _RED if negative else _GREEN
    arrow = "&#9660;" if negative else "&#9650;"
    sign = "-" if negative else "+"
    return (f' &middot; <span style="color:{color};font-weight:bold">'
            f'{arrow} {sign}{pct}%</span>')


def _item_polarity(it: dict) -> str:
    text = f'{it["title"]} {it["summary"]}'
    m = _DELTA_RE.search(text)
    if not m:
        return "neutral"
    return "negative" if any(w in m.group(0).lower() for w in _NEG_WORDS) else "positive"


def _item_html(it: dict) -> str:
    meta = " &middot; ".join(x for x in (it["source"], it["pub"]) if x)
    delta = _delta_badge(f'{it["title"]} {it["summary"]}')
    meta_html = f'{meta}{delta}' if (meta or delta) else ""
    style = (f"font-family:Georgia,'Times New Roman',serif;font-size:15px;"
             f"line-height:21px;color:{_NAVY};font-weight:bold;text-decoration:none")
    # 7:30 LINKS rule: if an item has no URL, render it without any link —
    # never emit href="#" (that produced dead headlines in S5).
    headline = (f'<a href="{it["url"]}" style="{style}">{it["title"]}</a>'
                if it["url"] else f'<span style="{style}">{it["title"]}</span>')
    return f"""<tr><td style="padding:10px 0;border-bottom:1px solid {_DIVIDER}">
{headline}
<div style="font-family:Arial,Helvetica,sans-serif;font-size:11px;color:{_GREY};margin-top:3px">{meta_html}</div>
</td></tr>"""


def _sec_banner(title: str, color: str = _RED) -> str:
    """Section header -- full-width dark bar with a coloured accent edge."""
    return f"""<tr><td style="padding:22px 0 0 0">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
<td style="background:{_NAVY};color:#fff;font-family:Arial,Helvetica,sans-serif;font-size:11px;font-weight:bold;letter-spacing:2px;text-transform:uppercase;padding:7px 12px;border-left:4px solid {color}">{title}</td>
</tr></table></td></tr>"""


def _company_banner(name: str, items: list = None) -> str:
    """Company sub-header -- small caps label with a coloured left border.
    Green only when every dated move for this company is a positive
    percentage move; red (brand default) otherwise."""
    polarities = [_item_polarity(it) for it in (items or [])]
    color = _GREEN if polarities and all(p == "positive" for p in polarities) and \
        any(p != "neutral" for p in polarities) else _RED
    return f"""<tr><td style="padding:18px 0 0 0">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
<td style="border-left:3px solid {color};padding-left:12px;font-family:Arial,Helvetica,sans-serif;font-size:11px;letter-spacing:1.2px;text-transform:uppercase;color:{color};font-weight:bold">{name}</td>
</tr></table></td></tr>"""


def _shell(recipient_name: str, date_str: str, company_count: int, story_count: int,
           inner_rows: str, preheader: str) -> str:
    plural_c = "y" if company_count == 1 else "ies"
    if story_count:
        subtitle = (f"{company_count} compan{plural_c} &nbsp;&middot;&nbsp; "
                    f"{story_count} stor{'y' if story_count == 1 else 'ies'} today")
    else:
        subtitle = f"{company_count} compan{plural_c} &nbsp;&middot;&nbsp; no new stories today"
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark"><meta name="supported-color-schemes" content="light dark">
<style>
  body {{ margin:0; padding:0; background-color:{_CREAM}; }}
  table {{ border-collapse:collapse; }}
  a {{ text-decoration:none; }}
  @media (max-width:620px) {{
    .container {{ width:100% !important; }}
    .stack-pad {{ padding-left:20px !important; padding-right:20px !important; }}
  }}
</style></head>
<body style="margin:0;padding:0;background-color:{_CREAM};font-family:Georgia,'Times New Roman',serif">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;font-size:1px;line-height:1px;color:{_CREAM}">{preheader}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
<td align="center" style="padding:32px 16px">
<table role="presentation" class="container" width="600" cellpadding="0" cellspacing="0" border="0" style="width:600px;max-width:600px;background-color:#FFFFFF">

<tr><td style="background-color:{_NAVY};padding:28px 32px" class="stack-pad">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
<td style="font-family:Arial,Helvetica,sans-serif;color:{_CREAM};font-size:12px;letter-spacing:2px;text-transform:uppercase">Daily News</td>
<td align="right" style="font-family:Arial,Helvetica,sans-serif;color:{_NAVY_SOFT};font-size:12px">{date_str}</td>
</tr></table>
<div style="font-family:Georgia,'Times New Roman',serif;color:#FFFFFF;font-size:26px;line-height:32px;font-weight:bold;margin-top:14px">CareEdge Daily News</div>
<div style="font-family:Arial,Helvetica,sans-serif;color:{_CREAM};font-size:14px;margin-top:4px">For {recipient_name}</div>
<div style="font-family:Arial,Helvetica,sans-serif;color:{_NAVY_SOFT};font-size:13px;margin-top:6px">{subtitle}</div>
</td></tr>

<tr><td style="padding:28px 32px 8px 32px" class="stack-pad">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
{inner_rows}
</table>
</td></tr>

<tr><td align="center" style="padding:28px 32px 8px 32px" class="stack-pad">
<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
<td bgcolor="{_NAVY}" style="border-radius:4px">
<a href="{_MANAGE_URL}" style="display:block;padding:12px 28px;font-family:Arial,Helvetica,sans-serif;font-size:13px;color:#FFFFFF;font-weight:bold;letter-spacing:0.5px">Manage Watchlist &amp; Recipients</a>
</td></tr></table>
</td></tr>

<tr><td style="padding:24px 32px 32px 32px;border-top:1px solid {_DIVIDER}" class="stack-pad">
<div style="font-family:Arial,Helvetica,sans-serif;font-size:12px;color:{_GREY};line-height:18px">
Auto-generated for your watchlist &middot; <a href="{_MANAGE_URL}" style="color:{_NAVY};text-decoration:underline">Manage companies &amp; recipients</a>
</div>
<div style="font-family:Arial,Helvetica,sans-serif;font-size:11px;color:#B0AA9C;line-height:16px;margin-top:14px">
CareEdge Daily News &mdash; internal digest. Sources are aggregated from public RSS/news feeds; no AI analysis is applied to this mail.
</div>
</td></tr>

</table>
</td></tr></table>
</body></html>"""

# ---------------------------------------------------------------------------
# Newspaper-format rendering — mirrors the 7:30 report's layout exactly by
# reusing send_credit_report's build_attachment/build_email (lazily imported
# to avoid a circular import), with per-person S1 and section subscriptions.
# No AI: cards carry headline+summary; the AI's credit-implication sentence
# and cross-source dedup are the only pieces that need API credits.
# ---------------------------------------------------------------------------

_NP_SECTIONS = [
    ("s1", "sb1", "S1", "&#9733; S1 &mdash; MY RATED ENTITIES &amp; WATCHLIST"),
    ("s2", "sb2", "S2", "S2 &mdash; NBFC, HFC, BROKING, FINTECH, FI SECTORS"),
    ("s3", "sb3", "S3", "S3 &mdash; RBI, SEBI, NHB REGULATIONS"),
    ("s4", "sb4", "S4", "S4 &mdash; BOND &amp; MONEY MARKETS"),
    ("s5", "sb5", "S5", "S5 &mdash; MACROECONOMIC DEVELOPMENTS"),
]

_RATING_ACTION_RE = re.compile(
    r"\b(upgrad\w*|downgrad\w*|rating watch|outlook (revised|negative|positive)|"
    r"revises? outlook|defaults?\b|delays? (in )?(payment|repayment)|withdraws? rating)",
    re.IGNORECASE,
)


def _story_score(it: dict) -> int:
    """Rank stories for the Top-5 table the way the AI ranks its takeaways:
    watchlist first, then penalties/rating actions, then regulatory."""
    text = it["title"] + " " + it["summary"]
    s = 0
    if it.get("companies"):
        s += 4
    if _PENALTY_RE.search(text):
        s += 3
    if _RATING_ACTION_RE.search(text):
        s += 3
    if it.get("section") == "S3":
        s += 2
    if it.get("section") in ("S4", "S5"):
        s += 1
    if "[T1]" in it.get("tags", ""):
        s += 1
    return s


def _np_card(it: dict, hero: bool = False, company: str = "") -> str:
    cls = "art hero" if hero else "art"
    bits = [b for b in (company.upper() if company else "", it["source"], it.get("pub", "")) if b]
    link = (f'<a class="rm" href="{it["url"]}" target="_blank">Read more &#8594;</a>'
            if it["url"] else "")
    return (f'<div class="{cls}"><p class="src">{" &bull; ".join(bits)}</p>'
            f'<p class="hl">{it["title"]}</p>'
            f'<p class="wh">{it["summary"] or "No summary available."}</p>{link}</div>')


def _np_brief(it: dict) -> str:
    link = f'<a href="{it["url"]}" target="_blank">&#8594;</a>' if it["url"] else ""
    return f'<p class="ib">&#8226; {it["title"]} ({it["source"]}) {link}</p>'


def _np_partb(p: dict, items: list[dict], by_section: dict) -> tuple[str, int, list[dict]]:
    """Per-person Part B in the 7:30 class markup. Returns (html, story_count,
    the stories shown — used to pick the Top 5)."""
    parts: list[str] = []
    chosen: list[dict] = []
    total = 0
    for sid, sbcls, skey, title in _NP_SECTIONS:
        parts.append(f'<div id="{sid}" data-section="banner" class="sb {sbcls}">{title}</div>')
        if skey not in p["sections"]:
            parts.append('<p class="empty">Not subscribed &mdash; enable this section in the console.</p>')
            continue
        if skey == "S1":
            sec: list[tuple[str, dict]] = []
            shown: set[str] = set()
            for comp in sorted(p["companies"]):
                for it in items:
                    if comp in it["companies"] and _key(it) not in shown:
                        shown.add(_key(it))
                        sec.append((comp, it))
            if not sec:
                parts.append('<p class="empty">No news in this category today.</p>')
                continue
            total += len(sec)
            chosen.extend(it for _, it in sec)
            # 7:30 rule: every watchlist item is a full article — no cap.
            for i, (comp, it) in enumerate(sec):
                parts.append(_np_card(it, hero=(i == 0), company=comp))
        else:
            sec_items = by_section[skey][:20]
            if not sec_items:
                parts.append('<p class="empty">No news in this category today.</p>')
                continue
            total += len(sec_items)
            chosen.extend(sec_items)
            cards, brief = sec_items[:6], sec_items[6:]
            parts.extend(_np_card(it) for it in cards)
            if brief:
                parts.append('<p class="ibh">In brief</p>')
                parts.extend(_np_brief(it) for it in brief)
    return "\n".join(parts), total, chosen


def _np_partc(top5: list[dict], date_str: str) -> str:
    """Top-5 table in the exact Part C markup the 7:30 email body uses."""
    rows = ""
    for i, it in enumerate(top5):
        border = "border-bottom:1px solid #f0f0f0;" if i < len(top5) - 1 else ""
        label = SECTION_TITLES.get(it.get("section", "S2"), "News").upper()
        rows += (
            f'<tr valign="top">'
            f'<td style="padding:10px 8px 10px 16px;font-size:28px;font-weight:900;'
            f'color:#cc0000;line-height:1;font-family:Georgia,serif;width:44px;">0{i + 1}</td>'
            f'<td style="padding:10px 16px 10px 4px;{border}">'
            f'<p style="margin:0 0 2px;font-size:9px;font-weight:800;letter-spacing:1px;'
            f'text-transform:uppercase;color:#888;">{label} &bull; {it["source"]}</p>'
            f'<p style="margin:0;font-size:12px;color:#1a1a1a;line-height:1.6;">{it["title"]}</p>'
            f'</td></tr>'
        )
    if not rows:
        rows = ('<tr><td style="padding:10px 16px;color:#1a1a1a;font-size:12px;">'
                'No fresh items in your sections today.</td></tr>')
    return (
        f'<table id="takeaways" width="100%" cellpadding="0" cellspacing="0" style="background:#1a1a1a;">'
        f'<tr><td style="padding:8px 16px;font-size:9px;font-weight:800;letter-spacing:3px;'
        f'text-transform:uppercase;color:#fff;">&#9679; TOP 5 HEADLINES &mdash; {date_str}</td></tr>'
        f'</table>'
        f'<table width="100%" cellpadding="0" cellspacing="0" '
        f'style="border:1px solid #e5e5e5;border-top:none;">{rows}</table>'
    )


def _np_rebrand(html: str) -> str:
    """The 7:30 templates carry the 'Credit Intelligence News' masthead and
    repo-edit links; this mail is branded CareEdge Daily News and managed
    from the team console."""
    html = html.replace("Credit Intelligence News", "CareEdge Daily News")
    for stale in (
        "https://github.com/mjitendrafeb-cmd/jeetz/edit/main/config.json",
        "https://github.com/mjitendrafeb-cmd/jeetz/edit/main/watchlist.txt",
    ):
        html = html.replace(stale, _MANAGE_URL)
    html = html.replace(
        "https://github.com/mjitendrafeb-cmd/jeetz/actions/workflows/daily_credit_report.yml",
        "https://github.com/mjitendrafeb-cmd/jeetz/actions/workflows/team_news.yml",
    )
    return html


def _send(to_addr: str, subject: str, html: str,
          attachment_html: str = "", attachment_name: str = "") -> None:
    user = os.environ["GMAIL_USER"]
    pw = os.environ["GMAIL_APP_PASSWORD"]
    if attachment_html:
        msg = MIMEMultipart("mixed")
        body = MIMEMultipart("alternative")
        body.attach(MIMEText(html, "html"))
        msg.attach(body)
        part = MIMEBase("text", "html")
        part.set_payload(attachment_html.encode("utf-8"))
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{attachment_name}"')
        msg.attach(part)
    else:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(html, "html"))
    msg["Subject"] = subject
    msg["From"] = f"CareEdge Daily News <{user}>"
    msg["To"] = to_addr
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(user, pw)
        s.sendmail(user, [to_addr], msg.as_string())
    print(f"[mail] sent '{subject}' -> {to_addr}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _mark_sent_today() -> None:
    path = os.path.join(_REPO_ROOT, "data", "team_last_sent.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    today = datetime.datetime.now(IST).date().isoformat()
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"date": today}, f)
    _git_push(path)


def main() -> None:
    team = _load_team()
    rows = [r for r in team.get("rows", []) if r.get("company", "").strip()]
    now = datetime.datetime.now(IST)
    date_str = now.strftime("%A, %d %B %Y")

    print("Fetching news (free sources, no AI)...")
    # apply_seen=False: do NOT inherit the daily Claude report's memory —
    # otherwise items that report published are hidden from team mails
    # forever even though the team mail never delivered them. The team
    # mailer relies solely on its own team_seen.json.
    # per_company_cap=5: wider net than the 7:30 report's default of 3, because
    # this mail has its own mechanical junk filter (_is_team_junk) to strip the
    # technical-chart noise that Google often ranks above the real story.
    news_text, _summary = fetch_all_news(os.environ.get("NEWSAPI_KEY", ""),
                                         apply_seen=False, per_company_cap=5)
    items = [_parse_item(ln) for ln in news_text.splitlines() if ln.strip()]

    seen = _load_seen()
    items = [it for it in items if _key(it) not in seen]
    print(f"{len(items)} items after team-mail dedup")

    pre_junk = len(items)
    dropped = [it for it in items if _is_team_junk(it)]
    items = [it for it in items if not _is_team_junk(it)]
    for it in dropped[:10]:
        print(f"[junk] dropped: {it['title'][:80]}")
    print(f"{len(items)} items after junk filter (dropped {pre_junk - len(items)})")

    pre_geo = len(items)
    off = [it for it in items if _is_out_of_scope(it)]
    items = [it for it in items if not _is_out_of_scope(it)]
    for it in off[:10]:
        print(f"[scope] dropped (not India): {it['title'][:75]}")
    print(f"{len(items)} items after geography filter (dropped {pre_geo - len(items)})")

    phrases = [_phrase(r["company"]) for r in rows]
    for it in items:
        it["section"] = _classify(it, phrases)
        it["companies"] = _match_companies(it, rows)

    comp_counts: dict[str, int] = {}
    for it in items:
        for c in it["companies"]:
            comp_counts[c] = comp_counts.get(c, 0) + 1
        if it.get("wl_company") and not it["companies"]:
            print(f"[WARN] watchlist-tagged item matched no row: "
                  f"tag='{it['wl_company']}' title='{it['title'][:70]}'")
    print("Per-company matches:", comp_counts or "none")

    by_section: dict[str, list[dict]] = {s: [] for s in SECTION_TITLES}
    for it in items:
        by_section[it["section"]].append(it)
    print("Section counts:", {s: len(v) for s, v in by_section.items()})

    # Build per-person profile: email -> {name, companies(for S1), sections}
    people: dict[str, dict] = {}
    for r in rows:
        secs = r.get("sections", [])
        for name_f, email_f, send_f in ROLES:
            if not r.get(send_f):
                continue
            email = r.get(email_f, "").strip()
            if not email:
                continue
            p = people.setdefault(email, {
                "name": r.get(name_f, "").strip() or email.split("@")[0],
                "companies": set(), "sections": set(),
            })
            p["sections"].update(secs)
            if "S1" in secs:
                p["companies"].add(r["company"])

    if not people:
        print("[route] nobody is enabled in team.json — no mails to send")
        _save_seen(items)
        return

    # Lazy import: send_credit_report imports helpers from this module at its
    # top level, so importing it here (after this module is fully loaded) is
    # safe, while a module-level import would be circular.
    import send_credit_report as _scr

    today = now.date()
    for email, p in people.items():
        part_b, total, person_items = _np_partb(p, items, by_section)

        if total == 0 and not team.get("send_empty_mail", False):
            print(f"[mail] skipping {email} — nothing new in their sections")
            continue

        top5 = sorted(person_items, key=_story_score, reverse=True)[:5]
        part_c = _np_partc(top5, now.strftime("%d %B %Y"))
        body = _np_rebrand(_scr.build_email(part_c, today, _summary))
        attachment = _np_rebrand(_scr.build_attachment(part_b, today))
        _send(email, f"CareEdge Daily News — {now:%d %b %Y}", body,
              attachment_html=attachment,
              attachment_name=f"CareEdge_Daily_News_{today:%Y%m%d}.html")

    _save_seen(items)
    _mark_sent_today()
    print("Done.")


if __name__ == "__main__":
    main()
