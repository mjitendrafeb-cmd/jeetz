#!/usr/bin/env python3
"""
fetch_news.py — News fetching module for Daily Credit Intelligence Report.
Pulls headlines from RBI, SEBI, Google News, NewsAPI, and company watchlist.
Each item includes a URL where available so Claude can render clickable links.
"""

import os
import re
import json
import requests
import feedparser

from fetch_telegram import fetch_telegram_channels
from fetch_web import fetch_all_web


def load_config() -> dict:
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, "config.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def load_watchlist() -> list[str]:
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


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return " ".join(text.split())


def _fmt(source: str, title: str, summary: str, url: str = "") -> str:
    link = f" | URL:{url}" if url else ""
    return f"{source}: {title} — {summary[:250]}{link}"


def fetch_rbi_news() -> list[str]:
    from bs4 import BeautifulSoup
    items = []

    # Try RSS first
    try:
        feed = feedparser.parse("https://www.rbi.org.in/scripts/rss.aspx")
        for entry in feed.entries[:10]:
            title = _clean(entry.get("title", "")).strip()
            summary = _clean(entry.get("summary", entry.get("description", ""))).strip()
            url = entry.get("link", "")
            if title:
                items.append(_fmt("RBI", title, summary, url))
    except Exception as exc:
        print(f"[fetch_news] RBI RSS error: {exc}")

    # Fallback: scrape RBI press release page
    if not items:
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
            r = requests.get("https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx",
                             headers=headers, timeout=15)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                for a in soup.find_all("a", href=True)[:20]:
                    text = _clean(a.get_text()).strip()
                    href = a["href"]
                    if len(text) > 20:
                        full_url = href if href.startswith("http") else "https://www.rbi.org.in" + href
                        items.append(_fmt("RBI", text, "", full_url))
                        if len(items) >= 10:
                            break
        except Exception as exc:
            print(f"[fetch_news] RBI press release scrape error: {exc}")

    # Final fallback: Google News
    if not items:
        try:
            gn_url = "https://news.google.com/rss/search?q=RBI+India+monetary+policy+regulation&hl=en-IN&gl=IN&ceid=IN:en"
            feed = feedparser.parse(gn_url)
            for entry in feed.entries[:5]:
                title = _clean(entry.get("title", "")).strip()
                summary = _clean(entry.get("summary", "")).strip()
                url = entry.get("link", "")
                if title:
                    items.append(_fmt("RBI", title, summary, url))
        except Exception as exc:
            print(f"[fetch_news] RBI Google News fallback error: {exc}")

    return items


def fetch_sebi_news() -> list[str]:
    try:
        feed = feedparser.parse("https://www.sebi.gov.in/sebirss.xml")
        items = []
        for entry in feed.entries[:10]:
            title = _clean(entry.get("title", "")).strip()
            summary = _clean(entry.get("summary", entry.get("description", ""))).strip()
            url = entry.get("link", "")
            if title:
                items.append(_fmt("SEBI", title, summary, url))
        return items
    except Exception as exc:
        print(f"[fetch_news] SEBI RSS error: {exc}")
        return []


# Targeted queries covering all 10 report sections
_GOOGLE_QUERIES = [
    # RBI / Regulatory
    ("RBI", "RBI India monetary policy repo rate liquidity"),
    ("RBI", "RBI circular regulation banking India"),
    # SEBI
    ("SEBI", "SEBI India capital market regulation bond"),
    # Banking
    ("Banking", "Indian bank NPA stressed assets credit"),
    ("Banking", "SBI HDFC ICICI Axis bank results earnings"),
    # NBFC
    ("NBFC", "NBFC India loan disbursement stress liquidity"),
    ("NBFC", "microfinance MFI India NPA collections"),
    # Housing Finance
    ("HFC", "housing finance India HFC mortgage home loan"),
    ("HFC", "LIC Housing HDFC housing affordable housing"),
    # Broking & Fintech
    ("Broking", "India broking fintech SEBI regulation stock broker"),
    # Bond Market
    ("Bonds", "India bond market yield G-sec government securities"),
    ("Bonds", "India corporate bond credit spread debenture"),
    # Commercial Paper
    ("CP", "commercial paper India money market CP issuance"),
    # Securitisation
    ("Securitisation", "India securitisation ABS RMBS PTC pool"),
    # Rating Actions
    ("Ratings", "credit rating upgrade downgrade India CRISIL ICRA CareEdge India Ratings"),
    ("Ratings", "rating watch negative outlook India bond issuer"),
]


def fetch_google_news() -> list[str]:
    items = []
    seen_titles: set[str] = set()

    for (tag, query) in _GOOGLE_QUERIES:
        try:
            url = (
                f"https://news.google.com/rss/search"
                f"?q={requests.utils.quote(query)}&hl=en-IN&gl=IN&ceid=IN:en"
            )
            feed = feedparser.parse(url)
            count = 0
            for entry in feed.entries:
                if count >= 2:
                    break
                raw_title = _clean(entry.get("title", "")).strip()
                if not raw_title or raw_title in seen_titles:
                    continue
                seen_titles.add(raw_title)
                source = tag
                title = raw_title
                if " - " in raw_title:
                    parts = raw_title.rsplit(" - ", 1)
                    title = parts[0].strip()
                    source = parts[1].strip()
                summary = _clean(entry.get("summary", entry.get("description", ""))).strip()
                link = entry.get("link", "")
                items.append(_fmt(source, title, summary, link))
                count += 1
        except Exception as exc:
            print(f"[fetch_news] Google News error for '{query}': {exc}")

    return items


def fetch_newsapi_news(api_key: str) -> list[str]:
    if not api_key:
        return []
    try:
        resp = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": (
                    "RBI OR SEBI OR NBFC OR HFC OR securitisation OR "
                    "'commercial paper' OR 'credit rating' OR 'bond market' India"
                ),
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": 30,
                "domains": (
                    "economictimes.indiatimes.com,livemint.com,"
                    "business-standard.com,reuters.com,financialexpress.com"
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
            url = article.get("url", "")
            if title:
                items.append(_fmt(source, title, description, url))
        return items
    except Exception as exc:
        print(f"[fetch_news] NewsAPI error: {exc}")
        return []


def fetch_company_news() -> list[str]:
    companies = load_watchlist()
    if not companies:
        return []

    items = []
    seen_titles: set[str] = set()

    for company in companies:
        if len(items) >= 60:
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
                raw_title = _clean(entry.get("title", "")).strip()
                if not raw_title or raw_title in seen_titles:
                    continue
                seen_titles.add(raw_title)
                source = "Google News"
                title = raw_title
                if " - " in raw_title:
                    parts = raw_title.rsplit(" - ", 1)
                    title = parts[0].strip()
                    source = parts[1].strip()
                summary = _clean(entry.get("summary", entry.get("description", ""))).strip()
                link = entry.get("link", "")
                items.append(f"[WATCHLIST — {company}] {_fmt(source, title, summary, link)}")
                count += 1
        except Exception as exc:
            print(f"[fetch_news] Company news error for '{company}': {exc}")

    return items


def fetch_all_news(newsapi_key: str = "") -> str:
    cfg = load_config()
    sources = cfg.get("sources", {})

    def src_on(key: str) -> bool:
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
    if src_on("telegram"):
        channels = cfg.get("telegram_channels", [])
        if channels:
            all_items.extend(fetch_telegram_channels(channels))
    if src_on("web_scraper"):
        all_items.extend(fetch_all_web(
            cfg.get("web_sources", {}),
            cfg.get("custom_scrape_urls", []),
        ))

    # Deduplicate by normalised title
    seen: set[str] = set()
    unique: list[str] = []
    for item in all_items:
        key = item.split(" — ")[0].lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(item)
        if len(unique) >= 80:
            break

    if not unique:
        return "No news items were fetched today. Please check network connectivity and RSS feed availability."

    lines = [f"{i + 1}. {item}" for i, item in enumerate(unique)]
    return "\n".join(lines)
