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


def fetch_bse_announcements(companies: list[str]) -> list[str]:
    """Fetch today's BSE corporate announcements filtered for watchlist companies."""
    if not companies:
        return []

    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)

    def fmt_date(d: datetime.date) -> str:
        return d.strftime("%Y%m%d")

    try:
        url = (
            f"https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w"
            f"?strScrip=&strSearch=P&strType=C"
            f"&strPrevDate={fmt_date(yesterday)}&strToDate={fmt_date(today)}"
            f"&subcategory=-1&strCat=-1"
        )
        r = requests.get(url, headers=_HEADERS, timeout=12)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, str):
            import json as _json
            data = _json.loads(data)
    except Exception as exc:
        print(f"[fetch_bse] API error: {exc}")
        return []

    # Build first-word lookup for fast matching
    first_words = {c.split()[0].lower(): c for c in companies}

    items = []
    for ann in data.get("Table", [])[:200]:
        name = _clean(ann.get("SLONGNAME", "") + " " + ann.get("SCRIP_CD", ""))
        subj = _clean(ann.get("NEWSSUB", ""))
        combined = (name + " " + subj).lower()

        matched_company = None
        for fw, company in first_words.items():
            if fw in combined:
                matched_company = company
                break

        if not matched_company:
            continue

        link = f"https://www.bseindia.com/corporates/ann.html"
        ann_link = ann.get("ATTACHMENTNAME", "")
        if ann_link:
            link = f"https://www.bseindia.com/{ann_link}"

        items.append(
            f"[BSE — {matched_company}] BSE: {subj[:200]} — Corporate announcement | URL:{link}"
        )
        if len(items) >= 20:
            break

    print(f"[fetch_bse] Announcements: {len(items)} matched watchlist companies")
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
