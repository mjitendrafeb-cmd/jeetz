#!/usr/bin/env python3
"""
fetch_bse.py — BSE announcements and financials for watchlist companies.
"""

import datetime
import time
import requests
import feedparser


_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.bseindia.com/",
}


def fetch_bse_announcements(companies: list[str]) -> list[str]:
    """Fetch BSE corporate announcements for watchlist companies."""
    if not companies:
        return []
    try:
        today = datetime.date.today()
        yesterday = today - datetime.timedelta(days=1)
        today_str = today.strftime("%d%m%Y")
        yesterday_str = yesterday.strftime("%d%m%Y")

        url = (
            f"https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w"
            f"?strScrip=&strSearch=P&strType=C"
            f"&strPrevDate={yesterday_str}&strToDate={today_str}"
            f"&subcategory=-1&strCat=-1"
        )
        r = requests.get(url, headers=_HEADERS, timeout=10)
        r.raise_for_status()
        data = r.json()

        # Prepare first words of company names for matching
        company_first_words = {
            company: company.lower().split()[0]
            for company in companies
        }

        items = []
        announcements = data if isinstance(data, list) else data.get("Table", [])
        for ann in announcements:
            if len(items) >= 20:
                break
            long_name = (ann.get("SLONGNAME") or "").lower()
            news_sub = (ann.get("NEWSSUB") or "").lower()
            combined = long_name + " " + news_sub

            matched_company = None
            for company, first_word in company_first_words.items():
                if first_word in combined:
                    matched_company = company
                    break

            if matched_company:
                news_sub_display = ann.get("NEWSSUB", "Corporate Announcement")
                items.append(
                    f"[BSE — {matched_company}] BSE: {news_sub_display} — "
                    f"Corporate announcement | URL:https://www.bseindia.com/corporates/ann.html"
                )

        return items
    except Exception as exc:
        print(f"[fetch_bse] BSE announcements error: {exc}")
        return []


def fetch_bse_financials(companies: list[str]) -> list[str]:
    """Fetch quarterly results news for watchlist companies. Only runs on Mondays."""
    if datetime.date.today().weekday() != 0:  # 0 = Monday
        return []
    if not companies:
        return []

    cutoff = datetime.date.today() - datetime.timedelta(days=30)
    items = []

    for company in companies:
        if len(items) >= 20:
            break
        try:
            short_name = " ".join(company.split()[:2])
            query = f"{short_name} quarterly results"
            url = (
                f"https://news.google.com/rss/search"
                f"?q={requests.utils.quote(query)}&hl=en-IN&gl=IN&ceid=IN:en"
            )
            feed = feedparser.parse(url)
            count = 0
            for entry in feed.entries:
                if count >= 2:
                    break
                # Check if within last 30 days
                pub = entry.get("published_parsed")
                if pub:
                    import calendar
                    pub_date = datetime.date(*pub[:3])
                    if pub_date < cutoff:
                        continue
                title = entry.get("title", "").strip()
                if not title:
                    continue
                # Strip publication name suffix
                if " - " in title:
                    parts = title.rsplit(" - ", 1)
                    title = parts[0].strip()
                summary = entry.get("summary", entry.get("description", "")).strip()
                link = entry.get("link", "")
                items.append(
                    f"[FINANCIALS — {company}] Source: {title} — {summary[:200]} | URL:{link}"
                )
                count += 1
            time.sleep(0.3)
        except Exception as exc:
            print(f"[fetch_bse] Financials error for '{company}': {exc}")

    return items
