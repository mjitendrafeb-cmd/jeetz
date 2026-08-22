#!/usr/bin/env python3
"""
fetch_bse.py — BSE corporate announcements and quarterly financials for watchlist companies.
"""

import re
import datetime
import requests
import feedparser

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.bseindia.com/",
}


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "")
    return text.strip()


_BSE_HOME = "https://www.bseindia.com/"
_BSE_ANN_ENDPOINTS = (
    # Current API path, then the older one BSE still serves. Both are tried
    # because BSE rotates these without notice and a single hardcoded path
    # is why this source has been silently returning nothing.
    "https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w",
    "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w",
)


def _bse_session():
    """A session primed against bseindia.com.

    The API was returning "Expecting value: line 1 column 1" on every run —
    that is not a JSON bug, it is BSE serving an HTML bot-block page because
    the request arrived with no cookies and no browser context. Loading the
    homepage first banks the cookies the API gateway expects.
    """
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.bseindia.com/corporates/ann.html",
        "Origin": "https://www.bseindia.com",
        "X-Requested-With": "XMLHttpRequest",
    })
    try:
        sess.get(_BSE_HOME, timeout=12)
    except Exception as exc:
        print(f"[fetch_bse] homepage priming failed (continuing): {exc}")
    return sess


def _bse_rows(sess, url: str, params: dict):
    """Return the Table rows from one endpoint, or [] with a REASON logged.
    Distinguishing 'blocked', 'not JSON' and 'no rows' matters: the old code
    printed one generic parse error for all three."""
    try:
        r = sess.get(url, params=params, timeout=15)
    except Exception as exc:
        print(f"[fetch_bse] {url.rsplit('/', 1)[-1]}: request failed — {exc}")
        return []
    ctype = (r.headers.get("Content-Type") or "").lower()
    if r.status_code != 200:
        print(f"[fetch_bse] {url.rsplit('/', 1)[-1]}: HTTP {r.status_code}")
        return []
    if "json" not in ctype:
        head = (r.text or "")[:80].replace("\n", " ")
        print(f"[fetch_bse] {url.rsplit('/', 1)[-1]}: not JSON "
              f"(Content-Type={ctype or 'none'}) — likely a bot-block page: {head!r}")
        return []
    try:
        data = r.json()
        if isinstance(data, str):
            import json as _json
            data = _json.loads(data)
    except Exception as exc:
        print(f"[fetch_bse] {url.rsplit('/', 1)[-1]}: JSON decode failed — {exc}")
        return []
    rows = data.get("Table") if isinstance(data, dict) else None
    return rows or []


def _bse_date(row: dict) -> str:
    """BSE gives an ISO-ish timestamp; the pipeline wants '11 Aug'. Without
    this the item is undated, which makes it exempt from the recency filter
    and prints DATE UNCONFIRMED on the card."""
    for key in ("NEWS_DT", "DissemDT", "News_submission_dt", "ANNOUNCEMENT_DT"):
        raw = (row.get(key) or "").strip()
        if not raw:
            continue
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.datetime.strptime(raw[:26], fmt).strftime("%d %b")
            except Exception:
                continue
    return ""


def fetch_bse_announcements(companies: list[str]) -> list[str]:
    """Today's BSE corporate announcements, filtered to watchlist companies.

    A company's own filing is the highest-signal S1 item there is — it is
    the disclosure the press then writes up. This source had been returning
    zero on every run for two separate reasons, both fixed here: the API
    call was being bot-blocked, and the name matching was too crude to be
    trusted even if it had worked.
    """
    if not companies:
        return []

    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    fmt = lambda d: d.strftime("%Y%m%d")

    # The good matcher lives in fetch_news. Imported lazily because
    # fetch_news imports THIS module lazily too — at call time both are
    # loaded, so there is no circular import.
    try:
        from fetch_news import _story_mentions_entity, _load_aliases
        alias_map = _load_aliases()
    except Exception:
        _story_mentions_entity, alias_map = None, {}

    sess = _bse_session()
    rows = []
    for url in _BSE_ANN_ENDPOINTS:
        rows = _bse_rows(sess, url, {
            "strCat": "-1", "strPrevDate": fmt(yesterday), "strScrip": "",
            "strSearch": "P", "strToDate": fmt(today), "strType": "C",
            "subcategory": "-1",
        })
        if rows:
            break

    if not rows:
        print("[fetch_bse] Announcements: 0 rows from every endpoint "
              "— source contributed nothing this run")
        return []

    items, seen = [], set()
    for ann in rows[:400]:
        subj = _clean(ann.get("NEWSSUB", "") or ann.get("HEADLINE", ""))
        name = _clean(ann.get("SLONGNAME", "") or ann.get("SNAME", ""))
        if not subj:
            continue
        blob = f"{name} {subj}"
        matched = None
        for company in companies:
            if _story_mentions_entity is None:
                # Degraded but still word-bounded, never a bare substring.
                core = company.split()[0].lower()
                if len(core) >= 4 and re.search(rf"\b{re.escape(core)}\b", blob.lower()):
                    matched = company
                    break
            elif _story_mentions_entity(company, alias_map.get(company.lower(), []), blob):
                matched = company
                break
        if not matched:
            continue
        key = (matched, subj[:80])
        if key in seen:
            continue
        seen.add(key)

        attach = ann.get("ATTACHMENTNAME", "")
        link = (f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{attach}"
                if attach else "https://www.bseindia.com/corporates/ann.html")
        pub = _bse_date(ann)
        date_part = f" | PUB:{pub}" if pub else ""
        # The company name goes in the TEXT, not just the tag. A filing
        # subject on its own ("Allotment of NCDs worth Rs 500 crore") names
        # nobody, so the mailer's own company matching would find nothing
        # and drop the item as untracked single-entity news.
        items.append(
            f"[BSE — {matched}] BSE Filing: {matched} — {subj[:200]}"
            f"{date_part} | URL:{link}"
        )
        if len(items) >= 25:
            break

    print(f"[fetch_bse] Announcements: {len(rows)} rows scanned, "
          f"{len(items)} matched watchlist companies")
    return items


def fetch_bse_financials(companies: list[str]) -> list[str]:
    """Monday-only: search Google News for recent quarterly results of watchlist companies."""
    if datetime.date.today().weekday() != 0:  # 0 = Monday
        return []
    if not companies:
        return []

    items = []
    seen: set[str] = set()

    for company in companies:
        if len(items) >= 20:
            break
        try:
            short = " ".join(company.split()[:2])
            query = f"{short} quarterly results financial results India"
            url = (
                f"https://news.google.com/rss/search"
                f"?q={requests.utils.quote(query)}&hl=en-IN&gl=IN&ceid=IN:en"
            )
            feed = feedparser.parse(url)
            cutoff = datetime.date.today() - datetime.timedelta(days=30)
            count = 0
            for entry in feed.entries:
                if count >= 2:
                    break
                title = _clean(entry.get("title", ""))
                if not title or title in seen:
                    continue
                # Check recency
                pub = entry.get("published_parsed")
                if pub:
                    pub_date = datetime.date(pub.tm_year, pub.tm_mon, pub.tm_mday)
                    if pub_date < cutoff:
                        continue
                seen.add(title)
                summary = _clean(entry.get("summary", ""))
                link = entry.get("link", "")
                source = "Google News"
                if " - " in title:
                    parts = title.rsplit(" - ", 1)
                    title = parts[0].strip()
                    source = parts[1].strip()
                items.append(
                    f"[FINANCIALS — {company}] {source}: {title} — {summary[:200]} | URL:{link}"
                )
                count += 1
        except Exception:
            pass

    print(f"[fetch_bse] Financials snapshot: {len(items)} items")
    return items
