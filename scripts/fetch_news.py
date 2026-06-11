#!/usr/bin/env python3
"""
fetch_news.py — News fetching module for Daily Credit Intelligence Report.
Pulls headlines from RBI, SEBI, Google News, NewsAPI, and company watchlist.
"""

import os
import re
import json
import requests
import feedparser


def load_config() -> dict:
    """Load config.json from repo root. Returns empty dict on failure."""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, "config.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def load_watchlist() -> list[str]:
    """Read watchlist.txt from repo root and return list of company names."""
    # Look for watchlist.txt relative to this script's location
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, "watchlist.txt")
    if not os.path.exists(path):
        return []
    companies = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                companies.append(line)
    return companies


def fetch_company_news() -> list[str]:
    """
    Fetch Google News RSS for each company in watchlist.txt.
    Returns up to 2 headlines per company, max 50 items total.
    """
    companies = load_watchlist()
    if not companies:
        return []

    items = []
    seen_titles: set[str] = set()

    for company in companies:
        if len(items) >= 50:
            break
        try:
            query = f'"{company}" India credit loan rating NPA'
            url = (
                f"https://news.google.com/rss/search"
                f"?q={requests.utils.quote(query)}&hl=en-IN&gl=IN&ceid=IN:en"
            )
            feed = feedparser.parse(url)
            count = 0
            for entry in feed.entries:
                if count >= 2:
                    break
                title = _clean(entry.get("title", "")).strip()
                if not title or title in seen_titles:
                    continue
                seen_titles.add(title)
                source = "Google News"
                if " - " in title:
                    parts = title.rsplit(" - ", 1)
                    title = parts[0].strip()
                    source = parts[1].strip()
                summary = _clean(entry.get("summary", entry.get("description", ""))).strip()
                items.append(f"[WATCHLIST — {company}] {source}: {title} — {summary[:200]}")
                count += 1
        except Exception as exc:
            print(f"[fetch_news] Company news error for '{company}': {exc}")

    return items


def _clean(text: str) -> str:
    """Strip HTML tags and normalise whitespace."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    return " ".join(text.split())


def fetch_rbi_news() -> list[str]:
    """Parse RBI RSS and return up to 10 formatted headline strings."""
    try:
        feed = feedparser.parse("https://www.rbi.org.in/scripts/rss.aspx")
        items = []
        for entry in feed.entries[:10]:
            title = _clean(entry.get("title", "")).strip()
            summary = _clean(entry.get("summary", entry.get("description", ""))).strip()
            if title:
                items.append(f"RBI: {title} — {summary[:300]}")
        return items
    except Exception as exc:
        print(f"[fetch_news] RBI RSS error: {exc}")
        return []


def fetch_sebi_news() -> list[str]:
    """Parse SEBI RSS and return up to 10 formatted headline strings."""
    try:
        feed = feedparser.parse("https://www.sebi.gov.in/sebirss.xml")
        items = []
        for entry in feed.entries[:10]:
            title = _clean(entry.get("title", "")).strip()
            summary = _clean(entry.get("summary", entry.get("description", ""))).strip()
            if title:
                items.append(f"SEBI: {title} — {summary[:300]}")
        return items
    except Exception as exc:
        print(f"[fetch_news] SEBI RSS error: {exc}")
        return []


def fetch_google_news() -> list[str]:
    """Fetch Google News RSS for 5 credit-related queries and return formatted strings."""
    queries = [
        "RBI India banking credit",
        "SEBI bond market India",
        "NBFC India stress NPA",
        "Indian banking sector",
        "credit rating India CRISIL ICRA CareEdge",
    ]
    items = []
    seen_titles: set[str] = set()

    for query in queries:
        try:
            url = (
                f"https://news.google.com/rss/search"
                f"?q={requests.utils.quote(query)}&hl=en-IN&gl=IN&ceid=IN:en"
            )
            feed = feedparser.parse(url)
            count = 0
            for entry in feed.entries:
                if count >= 3:
                    break
                title = _clean(entry.get("title", "")).strip()
                if not title or title in seen_titles:
                    continue
                seen_titles.add(title)
                # Google News puts source in title as " - Source Name"
                source = "Google News"
                if " - " in title:
                    parts = title.rsplit(" - ", 1)
                    title = parts[0].strip()
                    source = parts[1].strip()
                summary = _clean(entry.get("summary", entry.get("description", ""))).strip()
                items.append(f"{source}: {title} — {summary[:300]}")
                count += 1
        except Exception as exc:
            print(f"[fetch_news] Google News error for '{query}': {exc}")

    return items


def fetch_newsapi_news(api_key: str) -> list[str]:
    """Fetch from NewsAPI and return formatted headline strings. Returns [] if no key."""
    if not api_key:
        return []
    try:
        resp = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": "RBI OR SEBI OR NBFC OR 'credit rating' India",
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": 20,
                "domains": (
                    "economictimes.indiatimes.com,livemint.com,"
                    "business-standard.com,reuters.com"
                ),
            },
            headers={"X-Api-Key": api_key},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        items = []
        for article in data.get("articles", []):
            source = article.get("source", {}).get("name", "NewsAPI")
            title = _clean(article.get("title", "")).strip()
            description = _clean(article.get("description", "")).strip()
            if title:
                items.append(f"{source}: {title} — {description[:300]}")
        return items
    except Exception as exc:
        print(f"[fetch_news] NewsAPI error: {exc}")
        return []


def fetch_all_news(newsapi_key: str = "") -> str:
    """
    Fetch news from all sources, respecting config.json source toggles.
    Deduplicates by title and returns a numbered formatted string (max 40 items).
    """
    cfg = load_config()
    sources = cfg.get("sources", {})

    def src_on(key: str) -> bool:
        # Default to True if key is absent (backwards-compatible)
        return sources.get(key, True)

    all_items: list[str] = []
    if src_on("rbi_rss"):
        all_items.extend(fetch_rbi_news())
    if src_on("sebi_rss"):
        all_items.extend(fetch_sebi_news())
    if src_on("google_news"):
        all_items.extend(fetch_google_news())
    if src_on("newsapi"):
        all_items.extend(fetch_newsapi_news(newsapi_key))
    if src_on("company_watchlist"):
        all_items.extend(fetch_company_news())

    # Deduplicate by normalised title (first segment before " — ")
    seen: set[str] = set()
    unique: list[str] = []
    for item in all_items:
        key = item.split(" — ")[0].lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(item)
        if len(unique) >= 40:
            break

    if not unique:
        return "No news items were fetched today. Please check network connectivity and RSS feed availability."

    lines = [f"{i + 1}. {item}" for i, item in enumerate(unique)]
    return "\n".join(lines)
