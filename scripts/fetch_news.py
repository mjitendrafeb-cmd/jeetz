#!/usr/bin/env python3
"""
fetch_news.py — News fetching module for Daily Credit Intelligence Report.
Pulls headlines from RBI, SEBI, Google News, NewsAPI, and company watchlist.
Each item includes a URL where available so Claude can render clickable links.
"""

import os
import re
import json
import time
import datetime
import requests
import feedparser
from bs4 import BeautifulSoup

from fetch_telegram import fetch_telegram_channels
from fetch_web import fetch_all_web


# ---------------------------------------------------------------------------
# Source quality tiers
# ---------------------------------------------------------------------------

SOURCE_TIER = {
    # Tier 1 — Primary / Regulatory
    "RBI": 1, "SEBI": 1, "BSE": 1, "NHB": 1, "RBI-Enforcement": 1,
    "CareEdge": 1, "CRISIL": 1, "ICRA": 1, "CARE Ratings": 1, "India Ratings": 1,
    # Tier 2 — Quality Press
    "Economic Times": 2, "ET": 2, "Mint": 2, "Business Standard": 2,
    "Financial Express": 2, "Bloomberg": 2, "Reuters": 2, "Hindu Business Line": 2,
    "Moneycontrol": 2,
    # Tier 3 — Aggregated / Social
    "Google News": 3, "Telegram": 3,
}


def _get_tier(source: str) -> int:
    for key, tier in SOURCE_TIER.items():
        if key.lower() in source.lower():
            return tier
    return 3


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


def _fetch_article_body(url: str, max_chars: int = 500) -> str:
    """Fetch first 500 chars of article body. Returns empty string on any failure."""
    if not url or not url.startswith("http"):
        return ""
    try:
        r = requests.get(url, timeout=6, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = " ".join(soup.get_text().split())
        return text[:max_chars]
    except Exception:
        return ""


def _fmt(source: str, title: str, summary: str, url: str = "", body: str = "") -> str:
    tier = _get_tier(source)
    tier_tag = f"[T{tier}]" if tier < 3 else ""
    body_part = f" [BODY: {body}]" if body else ""
    link = f" | URL:{url}" if url else ""
    return f"{tier_tag}{source}: {title} — {summary[:200]}{body_part}{link}"


def fetch_rbi_news() -> list[str]:
    try:
        feed = feedparser.parse("https://www.rbi.org.in/scripts/rss.aspx")
        items = []
        for entry in feed.entries[:10]:
            title = _clean(entry.get("title", "")).strip()
            summary = _clean(entry.get("summary", entry.get("description", ""))).strip()
            url = entry.get("link", "")
            if title:
                body = _fetch_article_body(url)
                items.append(_fmt("RBI", title, summary, url, body))
        return items
    except Exception as exc:
        print(f"[fetch_news] RBI RSS error: {exc}")
        return []


def fetch_rbi_enforcement() -> list[str]:
    """Scrape RBI enforcement actions from the last 7 days."""
    try:
        url = "https://www.rbi.org.in/Scripts/EnforcementAction.aspx"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        table = soup.find("table")
        if not table:
            return []
        rows = table.find_all("tr")
        items = []
        cutoff = datetime.date.today() - datetime.timedelta(days=7)
        for row in rows[-10:]:
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            texts = [c.get_text(strip=True) for c in cells]
            # Try to parse a date from the row
            date_found = None
            for text in texts:
                for fmt in ("%d-%b-%Y", "%d/%m/%Y", "%B %d, %Y", "%d %B %Y"):
                    try:
                        date_found = datetime.datetime.strptime(text, fmt).date()
                        break
                    except ValueError:
                        continue
                if date_found:
                    break
            if date_found and date_found < cutoff:
                continue
            entity = texts[0] if texts else "Unknown Entity"
            amount = texts[1] if len(texts) > 1 else ""
            reason = texts[2] if len(texts) > 2 else "regulatory violation"
            items.append(
                f"RBI-Enforcement: Monetary Penalty on {entity} — {amount}, {reason}"
                f" | URL:{url}"
            )
        return items
    except Exception as exc:
        print(f"[fetch_news] RBI enforcement error: {exc}")
        return []


def fetch_sebi_news() -> list[str]:
    try:
        feed = feedparser.parse("https://www.sebi.gov.in/sebirss.xml")
        items = []
        for entry in feed.entries[:10]:
            title = _clean(entry.get("title", "")).strip()
            summary = _clean(entry.get("summary", entry.get("description", ""))).strip()
            url = entry.get("link", "")
            if title:
                body = _fetch_article_body(url)
                items.append(_fmt("SEBI", title, summary, url, body))
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
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=48)
    from_date = (datetime.date.today() - datetime.timedelta(days=2)).strftime('%Y-%m-%d')
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
                "from": from_date,
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
            # Double-check publishedAt is within 48h
            pub_str = article.get("publishedAt", "")
            if pub_str:
                try:
                    pub = datetime.datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                    if pub < cutoff:
                        continue
                except Exception:
                    pass
            source = article.get("source", {}).get("name", "NewsAPI")
            title = _clean(article.get("title", "")).strip()
            description = _clean(article.get("description", "")).strip()
            url = article.get("url", "")
            if title:
                items.append(_fmt(source, title, description, url))
        print(f"[fetch_news] NewsAPI: {len(items)} articles within 48h")
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
            short_name = " ".join(company.split()[:2])
            query = f'{short_name} India finance'
            url = (
                f"https://news.google.com/rss/search"
                f"?q={requests.utils.quote(query)}&hl=en-IN&gl=IN&ceid=IN:en"
            )
            feed = feedparser.parse(url)
            count = 0
            for entry in feed.entries:
                if count >= 3:
                    break
                raw_title = _clean(entry.get("title", "")).strip()
                if not raw_title or raw_title in seen_titles:
                    continue
                summary = _clean(entry.get("summary", entry.get("description", ""))).strip()
                # Only include if company name (first word) appears in title or summary
                first_word = company.lower().split()[0]
                if first_word not in (raw_title + " " + summary).lower():
                    continue
                seen_titles.add(raw_title)
                source = "Google News"
                title = raw_title
                if " - " in raw_title:
                    parts = raw_title.rsplit(" - ", 1)
                    title = parts[0].strip()
                    source = parts[1].strip()
                link = entry.get("link", "")
                items.append(f"[WATCHLIST — {company}] {_fmt(source, title, summary, link)}")
                count += 1
            time.sleep(0.3)
        except Exception as exc:
            print(f"[fetch_news] Company news error for '{company}': {exc}")

    return items


def _normalise_key(item: str) -> str:
    """Strip [TAG] prefix and take first 120 chars lowercase for dedup keying."""
    text = re.sub(r"^\[[^\]]+\]\s*", "", item)
    # Also strip tier tags like [T1]
    text = re.sub(r"^\[T\d\]\s*", "", text)
    return text.lower().strip()[:120]


def fetch_all_news(newsapi_key: str = "") -> str:
    cfg = load_config()
    sources = cfg.get("sources", {})

    def src_on(key: str) -> bool:
        return sources.get(key, True)

    all_items: list[str] = []

    # 1. RBI RSS + enforcement
    if src_on("rbi_rss"):
        all_items.extend(fetch_rbi_news())
        all_items.extend(fetch_rbi_enforcement())

    # 2. SEBI RSS
    if src_on("sebi_rss"):
        all_items.extend(fetch_sebi_news())

    # 3. Rating agencies
    if src_on("rating_agencies"):
        from fetch_ratings import fetch_rating_agency_news
        all_items.extend(fetch_rating_agency_news())

    # 4. Google News
    if src_on("google_news"):
        all_items.extend(fetch_google_news())

    if src_on("newsapi"):
        all_items.extend(fetch_newsapi_news(newsapi_key))

    # 5. Company watchlist + BSE announcements + BSE financials
    if src_on("company_watchlist"):
        all_items.extend(fetch_company_news())
        from fetch_bse import fetch_bse_announcements, fetch_bse_financials
        watchlist = load_watchlist()
        if src_on("bse_announcements"):
            all_items.extend(fetch_bse_announcements(watchlist))
        all_items.extend(fetch_bse_financials(watchlist))

    # 6. Telegram
    if src_on("telegram"):
        channels = cfg.get("telegram_channels", [])
        if channels:
            all_items.extend(fetch_telegram_channels(channels))

    # 7. Web scraper (OFF by default)
    if src_on("web_scraper"):
        all_items.extend(fetch_all_web(
            cfg.get("web_sources", {}),
            cfg.get("custom_scrape_urls", []),
        ))

    # Load seen headlines for rolling 5-day dedup
    seen_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "seen_headlines.json")
    try:
        with open(seen_path) as f:
            data = json.load(f)
        # Support both old format {"date":..., "keys":[...]} and new {"days":{...}}
        if "days" in data:
            today_str = str(datetime.date.today())
            all_keys: set[str] = set()
            for d, keys in data["days"].items():
                if d < today_str:  # only filter previous days, not today
                    all_keys.update(keys)
            seen_keys = all_keys
        elif data.get("date", "") < str(datetime.date.today()):
            seen_keys = set(data.get("keys", []))
        else:
            seen_keys = set()  # same day, skip filter
    except Exception:
        seen_keys = set()

    # Deduplicate by normalised headline — strip tag prefix like [TELEGRAM — @x] or [WATCHLIST — Co]
    seen: set[str] = set()
    unique: list[str] = []
    for item in all_items:
        key = _normalise_key(item)
        if not key:
            key = item[:120].lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)
        if len(unique) >= 150:
            break

    # Apply seen headlines filter (rolling 5-day dedup)
    unique = [item for item in unique if _normalise_key(item) not in seen_keys]

    if not unique:
        return "No news items were fetched today. Please check network connectivity and RSS feed availability."

    lines = [f"{i + 1}. {item}" for i, item in enumerate(unique)]
    return "\n".join(lines)
