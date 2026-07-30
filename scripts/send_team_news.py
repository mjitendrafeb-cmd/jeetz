#!/usr/bin/env python3
"""
send_team_news.py — Portfolio-routed watchlist news + rule-based S1-S5 digest.

Runs WITHOUT the Anthropic API (zero credits needed):
  1. Fetches news via the existing free pipeline (Google News, NSE/BSE RSS,
     RBI/SEBI RSS, scrapes, Telegram).
  2. Entity routing: each entity's news goes to its GH / Analyst / RH —
     only to people whose "enabled" flag is ticked in team.json.
  3. Section digest: classifies items into S1-S5 by rules and emails each
     enabled section-recipient only the sections ticked for them.

All routing is managed at docs/team.html (GitHub Pages console).
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
_SEEN_PATH = os.path.join(_REPO_ROOT, "data", "team_seen.json")  # separate from the
# daily Claude report's memory so the two systems never suppress each other.

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

SECTION_TITLES = {
    "S1": "S1 — Watchlist Entities",
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


def _load_team() -> dict:
    with open(_TEAM_PATH, encoding="utf-8") as f:
        return json.load(f)


def _phrase(name: str) -> str:
    words = name.lower().split()
    return " ".join(words[:2]) if len(words) >= 2 else (words[0] if words else "")


def _parse_item(raw: str) -> dict:
    """Split 'N. [TAGS] source: title — summary | PUB:x | URL:y' into fields."""
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
    return {
        "raw": item,
        "tags": " ".join(tags),
        "source": source.strip(),
        "title": (title or rest).strip(),
        "summary": summary.strip()[:220],
        "url": url,
        "pub": pub,
    }


def _classify(it: dict, entity_phrases: list[str]) -> str:
    text = (it["tags"] + " " + it["source"] + " " + it["title"] + " " + it["summary"]).lower()
    if "watchlist" in it["tags"].lower() or any(p and p in text for p in entity_phrases):
        return "S1"
    if it["source"].lower().startswith(_S3_SOURCES) or "sebi" in it["source"].lower():
        return "S3"
    if _S4_RE.search(text):
        return "S4"
    if _S5_RE.search(text):
        return "S5"
    return "S2"


def _match_entities(it: dict, entities: list[dict]) -> list[str]:
    text = (it["tags"] + " " + it["title"] + " " + it["summary"]).lower()
    hits = []
    for e in entities:
        name = e["name"].strip()
        if not name:
            continue
        if name.lower() in text or (_phrase(name) and _phrase(name) in text):
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
# HTML rendering (plain, inline styles, no AI)
# ---------------------------------------------------------------------------

def _item_html(it: dict) -> str:
    link = (f'<a href="{it["url"]}" style="color:#1e3a8a;text-decoration:none">'
            if it["url"] else "<span>")
    close = "</a>" if it["url"] else "</span>"
    meta = " · ".join(x for x in (it["source"], it["pub"]) if x)
    summ = (f'<div style="font-size:12px;color:#444;margin-top:2px">{it["summary"]}</div>'
            if it["summary"] else "")
    return (f'<div style="padding:9px 0;border-bottom:1px solid #eee">'
            f'{link}<strong style="font-size:13px">{it["title"]}</strong>{close}'
            f'<div style="font-size:10px;color:#999;margin-top:2px;text-transform:uppercase;'
            f'letter-spacing:1px">{meta}</div>{summ}</div>')


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
  Auto-generated · <a href="{manage}" style="color:#999">Manage entities &amp; recipients</a>
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

def main() -> None:
    team = _load_team()
    entities = team.get("entities", [])
    now = datetime.datetime.now(IST)
    date_str = now.strftime("%A, %d %B %Y")

    print("Fetching news (free sources, no AI)...")
    news_text, summary = fetch_all_news(os.environ.get("NEWSAPI_KEY", ""))
    raw_items = [ln for ln in news_text.splitlines() if ln.strip()]
    items = [_parse_item(r) for r in raw_items]

    seen = _load_seen()
    items = [it for it in items if _key(it) not in seen]
    print(f"{len(items)} items after team-mail dedup")

    phrases = [_phrase(e["name"]) for e in entities if e["name"].strip()]
    for it in items:
        it["section"] = _classify(it, phrases)
        it["entities"] = _match_entities(it, entities)

    # ---- 1) Entity-routed mails (GH / Analyst / RH, enabled only) ----------
    per_person: dict[str, dict] = {}
    for e in entities:
        ent_items = [it for it in items if e["name"] in it["entities"]]
        if not ent_items:
            continue
        for role in ("gh", "analyst", "rh"):
            p = e.get(role, {})
            if p.get("enabled") and p.get("email", "").strip():
                rec = per_person.setdefault(
                    p["email"].strip(),
                    {"name": p.get("name", "") or p["email"].split("@")[0], "ents": {}},
                )
                rec["ents"][e["name"]] = ent_items

    for email, rec in per_person.items():
        blocks = []
        for ent, its in rec["ents"].items():
            blocks.append(
                f'<div style="margin-top:16px;font-size:11px;font-weight:bold;'
                f'letter-spacing:2px;text-transform:uppercase;color:#cc0000;'
                f'border-bottom:2px solid #cc0000;padding-bottom:4px">{ent}</div>'
                + "".join(_item_html(it) for it in its)
            )
        html = _shell(f"Portfolio News — {rec['name']}", "".join(blocks), date_str)
        _send(email, f"Portfolio News — {now:%d %b %Y}", html)

    if not per_person:
        print("[route] no entity news matched any enabled person today")

    # ---- 2) Section digest mails (S1-S5, rule-based) -----------------------
    by_section: dict[str, list[dict]] = {s: [] for s in SECTION_TITLES}
    for it in items:
        by_section[it["section"]].append(it)
    print("Section counts:", {s: len(v) for s, v in by_section.items()})

    for p in team.get("section_recipients", []):
        if not (p.get("enabled") and p.get("email", "").strip()):
            continue
        wanted = [s for s in ("S1", "S2", "S3", "S4", "S5") if s in p.get("sections", [])]
        blocks, total = [], 0
        for s in wanted:
            its = by_section[s][:15]
            total += len(its)
            body = "".join(_item_html(it) for it in its) or \
                '<div style="padding:8px 0;color:#aaa;font-style:italic;font-size:12px">No fresh items today.</div>'
            blocks.append(
                f'<div style="margin-top:16px;font-size:11px;font-weight:bold;'
                f'letter-spacing:2px;text-transform:uppercase;color:#1e3a8a;'
                f'border-bottom:2px solid #1e3a8a;padding-bottom:4px">{SECTION_TITLES[s]}</div>' + body
            )
        if total == 0 and not team.get("send_empty_mail", False):
            print(f"[digest] skipping {p['email']} — no items in their sections")
            continue
        html = _shell("Credit News Digest", "".join(blocks), date_str)
        _send(p["email"].strip(), f"Credit News Digest — {now:%d %b %Y}", html)

    _save_seen(items)
    print("Done.")


if __name__ == "__main__":
    main()
