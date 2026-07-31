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

_S4_RE = re.compile(
    r"\b(bond[s]?|ncd[s]?|debenture|yield[s]?|g-sec|gsec|commercial paper|"
    r"securitisation|securitization|fimmda|ccil|treasury|masala bond|"
    r"certificate[s]? of deposit|repo auction|vrr|omo|state government securities)\b",
    re.IGNORECASE,
)
_S5_RE = re.compile(
    r"\b(gdp|inflation|cpi|wpi|iip|repo rate|monetary policy|mpc|fiscal deficit|"
    r"current account|forex reserves|rupee|trade deficit|pmi|gst collection)\b",
    re.IGNORECASE,
)
_S3_SOURCES = ("rbi", "sebi", "nhb", "rbi-enforcement")

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
    r"|\b52[- ]week (high|low)\b",
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


def _phrase(name: str) -> str:
    words = name.lower().split()
    return " ".join(words[:2]) if len(words) >= 2 else (words[0] if words else "")


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
    body = body.split(" | ")[0]
    source, _, rest = body.partition(": ")
    title, _, summary = rest.partition(" — ")
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
    if it["source"].lower().startswith(_S3_SOURCES) or "sebi" in it["source"].lower():
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
    text = (it["tags"] + " " + it["title"] + " " + it["summary"]).lower()
    tag = it.get("wl_company", "").lower()
    hits = []
    for r in rows:
        name = r["company"].strip()
        if not name:
            continue
        n = name.lower()
        if (tag and (tag == n or tag.startswith(n) or n.startswith(tag))) \
                or n in text or (_phrase(name) and _phrase(name) in text):
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
    href = it["url"] or "#"
    meta = " &middot; ".join(x for x in (it["source"], it["pub"]) if x)
    delta = _delta_badge(f'{it["title"]} {it["summary"]}')
    meta_html = f'{meta}{delta}' if (meta or delta) else ""
    return f"""<tr><td style="padding:10px 0;border-bottom:1px solid {_DIVIDER}">
<a href="{href}" style="font-family:Georgia,'Times New Roman',serif;font-size:15px;line-height:21px;color:{_NAVY};font-weight:bold;text-decoration:none">{it["title"]}</a>
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
<td style="font-family:Arial,Helvetica,sans-serif;color:{_CREAM};font-size:12px;letter-spacing:2px;text-transform:uppercase">Credit Intelligence</td>
<td align="right" style="font-family:Arial,Helvetica,sans-serif;color:{_NAVY_SOFT};font-size:12px">{date_str}</td>
</tr></table>
<div style="font-family:Georgia,'Times New Roman',serif;color:#FFFFFF;font-size:26px;line-height:32px;font-weight:bold;margin-top:14px">Watchlist Digest for {recipient_name}</div>
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
Credit Intelligence &mdash; internal research desk digest. Sources are aggregated from public RSS/news feeds; no AI analysis is applied to this mail.
</div>
</td></tr>

</table>
</td></tr></table>
</body></html>"""

def _send(to_addr: str, subject: str, html: str) -> None:
    user = os.environ["GMAIL_USER"]
    pw = os.environ["GMAIL_APP_PASSWORD"]
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Credit Intelligence <{user}>"
    msg["To"] = to_addr
    msg.attach(MIMEText(html, "html"))
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

    empty_row = ('<tr><td style="padding:14px 0;color:#B0AA9C;font-style:italic;'
                 'font-family:Arial,Helvetica,sans-serif;font-size:12px">'
                 '{msg}</td></tr>')

    for email, p in people.items():
        blocks, total, headlines = [], 0, []

        if "S1" in p["sections"]:
            s1_blocks = []
            shown: set[str] = set()  # one story = one card, even if it matches
            for comp in sorted(p["companies"]):  # several of this person's companies
                its = [it for it in items
                       if comp in it["companies"] and _key(it) not in shown]
                shown.update(_key(it) for it in its)
                if its:
                    total += len(its)
                    headlines.extend(it["title"] for it in its)
                    s1_blocks.append(_company_banner(comp, its) +
                                     "".join(_item_html(it) for it in its))
            body = "".join(s1_blocks) or empty_row.format(msg="No fresh news on your companies today.")
            blocks.append(_sec_banner(SECTION_TITLES["S1"], _RED) + body)

        for s in ("S2", "S3", "S4", "S5"):
            if s not in p["sections"]:
                continue
            its = by_section[s][:15]
            total += len(its)
            body = "".join(_item_html(it) for it in its) or empty_row.format(msg="No fresh items today.")
            blocks.append(_sec_banner(SECTION_TITLES[s], _NAVY) + body)

        if total == 0 and not team.get("send_empty_mail", False):
            print(f"[mail] skipping {email} — nothing new in their sections")
            continue

        preheader = (", ".join(headlines[:3])[:150] +
                     ("..." if len(", ".join(headlines[:3])) > 150 else "")) if headlines \
                    else f"Your watchlist digest for {now:%d %b %Y}."
        html = _shell(p["name"], date_str, len(p["companies"]), total, "".join(blocks), preheader)
        _send(email, f"Credit News — {now:%d %b %Y}", html)

    _save_seen(items)
    _mark_sent_today()
    print("Done.")


if __name__ == "__main__":
    main()
