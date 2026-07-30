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
# HTML rendering (plain, no AI)
# ---------------------------------------------------------------------------

def _item_html(it: dict) -> str:
    link = (f'<a href="{it["url"]}" style="color:#1e3a8a;text-decoration:none">'
            if it["url"] else "<span>")
    close = "</a>" if it["url"] else "</span>"
    meta = " \u00b7 ".join(x for x in (it["source"], it["pub"]) if x)
    meta_html = (f' <span style="font-size:10px;color:#999;white-space:nowrap">'
                 f'&mdash; {meta}</span>' if meta else "")
    # Skip the summary when it just restates the headline (common on Google items)
    summ = ""
    s, t = it["summary"].strip(), it["title"].strip()
    if s and not s.lower().startswith(t[:40].lower()) and t[:40].lower() not in s.lower():
        summ = f'<div style="font-size:11px;color:#555;margin-top:1px">{s}</div>'
    return (f'<div style="padding:4px 0 5px;border-bottom:1px solid #f2f2f2">'
            f'{link}<strong style="font-size:13px">{it["title"]}</strong>{close}'
            f'{meta_html}{summ}</div>')


def _sec_banner(title: str, color: str = "#cc0000") -> str:
    """Section header — solid dark bar with a colored accent edge."""
    return (f'<div style="margin-top:18px;background:#1a1a1a;color:#fff;font-size:11px;'
            f'font-weight:bold;letter-spacing:2px;text-transform:uppercase;'
            f'padding:6px 10px;border-left:4px solid {color}">{title}</div>')


def _company_banner(name: str) -> str:
    """Company sub-header — small red label with a dotted underline (visually
    distinct from the dark section bar)."""
    return (f'<div style="margin-top:10px;font-size:10px;font-weight:bold;'
            f'letter-spacing:1px;text-transform:uppercase;color:#cc0000;'
            f'border-bottom:1px dotted #cc9999;padding-bottom:2px">{name}</div>')


def _shell(title: str, inner: str, date_str: str) -> str:
    manage = "https://mjitendrafeb-cmd.github.io/jeetz/team.html"
    return f"""<html><body style="margin:0;background:#f0ece4;font-family:Georgia,serif">
<div style="max-width:640px;margin:0 auto;background:#fdfaf5;padding:0 0 20px">
<div style="background:#1a1a1a;color:#fff;padding:16px 24px;border-bottom:4px solid #cc0000">
  <div style="font-size:10px;letter-spacing:2px;color:#bbb;text-transform:uppercase">{date_str}</div>
  <div style="font-size:22px;font-weight:bold">{title}</div>
</div>
<div style="padding:8px 24px">{inner}</div>
<div style="padding:14px 24px;border-top:1px solid #ddd;font-size:10px;color:#999">
  Auto-generated · <a href="{manage}" style="color:#999">Manage companies &amp; recipients</a>
</div></div></body></html>"""


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
    news_text, _summary = fetch_all_news(os.environ.get("NEWSAPI_KEY", ""), apply_seen=False)
    items = [_parse_item(ln) for ln in news_text.splitlines() if ln.strip()]

    seen = _load_seen()
    items = [it for it in items if _key(it) not in seen]
    print(f"{len(items)} items after team-mail dedup")

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

    for email, p in people.items():
        blocks, total = [], 0

        if "S1" in p["sections"]:
            s1_blocks = []
            for comp in sorted(p["companies"]):
                its = [it for it in items if comp in it["companies"]]
                if its:
                    total += len(its)
                    s1_blocks.append(_company_banner(comp) +
                                     "".join(_item_html(it) for it in its))
            body = "".join(s1_blocks) or \
                '<div style="padding:8px 0;color:#aaa;font-style:italic;font-size:12px">No fresh news on your companies today.</div>'
            blocks.append(_sec_banner(SECTION_TITLES["S1"], "#cc0000") + body)

        for s in ("S2", "S3", "S4", "S5"):
            if s not in p["sections"]:
                continue
            its = by_section[s][:15]
            total += len(its)
            body = "".join(_item_html(it) for it in its) or \
                '<div style="padding:8px 0;color:#aaa;font-style:italic;font-size:12px">No fresh items today.</div>'
            blocks.append(_sec_banner(SECTION_TITLES[s], "#1e3a8a") + body)

        if total == 0 and not team.get("send_empty_mail", False):
            print(f"[mail] skipping {email} — nothing new in their sections")
            continue
        html = _shell(f"Credit News — {p['name']}", "".join(blocks), date_str)
        _send(email, f"Credit News — {now:%d %b %Y}", html)

    _save_seen(items)
    _mark_sent_today()
    print("Done.")


if __name__ == "__main__":
    main()
