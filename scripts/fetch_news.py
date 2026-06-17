#!/usr/bin/env python3
"""
fetch_news.py — News fetching module for Daily Credit Intelligence Report.
Pulls headlines from RBI, SEBI, Google News, BSE, rating agencies, Telegram, and company watchlist.
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
# Source quality tiers — used to tag items for Claude
# T1 = Primary/Regulatory, T2 = Quality press, T3 = Aggregated/social
# ---------------------------------------------------------------------------
_TIER1 = {"rbi", "sebi", "bse", "nhb", "rbi-enforcement", "careedge", "crisil", "icra",
           "care ratings", "india ratings", "care", "fimmda", "ccil"}
_TIER2 = {"economic times", "et", "mint", "livemint", "business standard", "financial express",
           "bloomberg", "reuters", "hindu business line", "moneycontrol", "cnbctv18"}


def _source_tier(source: str) -> str:
    s = source.lower()
    if any(t in s for t in _TIER1):
        return "[T1]"
    if any(t in s for t in _TIER2):
        return "[T2]"
    return ""


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


# Patterns to drop at fetch time — live market tickers, intraday moves, stock tips
_SKIP_PATTERNS = re.compile(
    r'\b(sensex|nifty|bse sensex|nse nifty)\b.{0,40}(\+|-)\d+|'
    r'\b(open higher|open lower|opens (flat|green|red)|market open|benchmarks open)\b|'
    r'\bstock(s)? to (buy|sell|watch)\b|'
    r'\b(top (gainers|losers)|multibagger|target price|buy call|sell call)\b|'
    r'\bintraday\b|'
    r'\battend(s)? (investor|analyst) (meet|conference|day)\b|'
    r'\binvestor meet\b|'
    r'\bsets? record date\b|'
    r'\brecord date for (dividend|commercial paper|cp maturity|interest)\b|'
    r'\bcommercial paper maturit\b|'
    r'\bsets? (ex-date|ex date)\b',
    re.IGNORECASE
)


def _is_market_ticker(title: str, summary: str = "") -> bool:
    return bool(_SKIP_PATTERNS.search(title) or _SKIP_PATTERNS.search(summary))


def _fmt(source: str, title: str, summary: str, url: str = "", body: str = "", pub_date: str = "") -> str:
    tier = _source_tier(source)
    body_part = f" [BODY: {body[:400]}]" if body else ""
    date_part = f" | PUB:{pub_date}" if pub_date else ""
    link = f" | URL:{url}" if url else ""
    return f"{tier}{source}: {title} — {summary[:200]}{body_part}{date_part}{link}"


def _fetch_article_body(url: str) -> str:
    """Fetch first 400 chars of article body text. Returns empty string on failure."""
    if not url or not url.startswith("http"):
        return ""
    try:
        r = requests.get(url, timeout=6, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = " ".join(soup.get_text().split())
        return text[:400]
    except Exception:
        return ""


def _fetch_pdf_text(url: str) -> str:
    """Extract text from first 2 pages of a PDF URL. Returns first 600 chars."""
    if not url or not url.lower().endswith(".pdf"):
        return ""
    try:
        import pdfplumber
        import io
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        with pdfplumber.open(io.BytesIO(r.content)) as pdf:
            text = ""
            for page in pdf.pages[:2]:
                text += (page.extract_text() or "") + " "
        return text.strip()[:600]
    except Exception:
        return ""


def fetch_rbi_news() -> list[str]:
    try:
        feed = feedparser.parse("https://www.rbi.org.in/scripts/rss.aspx")
        items = []
        for entry in feed.entries[:20]:
            if not _is_recent(entry, 48):
                continue
            title = _clean(entry.get("title", "")).strip()
            summary = _clean(entry.get("summary", entry.get("description", ""))).strip()
            url = entry.get("link", "")
            pub_date = ""
            pub = entry.get("published_parsed")
            if pub:
                import calendar as _cal
                import time as _time
                try:
                    pub_date = _time.strftime("%d %b", pub)
                except Exception:
                    pass
            if title and not _is_market_ticker(title, summary):
                if url.lower().endswith(".pdf"):
                    body = _fetch_pdf_text(url)
                else:
                    body = _fetch_article_body(url)
                items.append(_fmt("RBI", title, summary, url, body, pub_date))
        print(f"[fetch_news] RBI RSS: {len(items)} items (last 48h)")
        return items
    except Exception as exc:
        print(f"[fetch_news] RBI RSS error: {exc}")
        return []


def fetch_rbi_enforcement() -> list[str]:
    """Scrape RBI enforcement actions page for recent monetary penalties."""
    try:
        url = "https://www.rbi.org.in/Scripts/EnforcementAction.aspx"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        items = []
        cutoff = datetime.date.today() - datetime.timedelta(days=7)
        watchlist = load_watchlist()
        for row in soup.find_all("tr")[1:15]:
            cols = row.find_all("td")
            if len(cols) < 3:
                continue
            entity = _clean(cols[0].get_text())
            penalty = _clean(cols[1].get_text()) if len(cols) > 1 else ""
            date_str = _clean(cols[-1].get_text())
            if not entity:
                continue
            # Try to parse date
            try:
                row_date = datetime.datetime.strptime(date_str, "%d-%b-%Y").date()
                if row_date < cutoff:
                    continue
            except Exception:
                pass
            text = f"RBI monetary penalty on {entity}"
            if penalty:
                text += f" — {penalty}"
            item = f"[T1]RBI-Enforcement: {text} | URL:{url}"
            # Watchlist cross-check: if first word of any watchlist company appears in entity name
            entity_lower = entity.lower()
            for company in watchlist:
                first_word = company.split()[0].lower()
                if len(first_word) > 2 and first_word in entity_lower:
                    item = f"[WATCHLIST — {company}] {item}"
                    break
            items.append(item)
        print(f"[fetch_news] RBI enforcement: {len(items)} items")
        return items
    except Exception as exc:
        print(f"[fetch_news] RBI enforcement error: {exc}")
        return []


def fetch_sebi_news() -> list[str]:
    try:
        feed = feedparser.parse("https://www.sebi.gov.in/sebirss.xml")
        items = []
        for entry in feed.entries[:20]:
            if not _is_recent(entry, 48):
                continue
            title = _clean(entry.get("title", "")).strip()
            summary = _clean(entry.get("summary", entry.get("description", ""))).strip()
            url = entry.get("link", "")
            pub_date = ""
            pub = entry.get("published_parsed")
            if pub:
                import time as _time
                try:
                    pub_date = _time.strftime("%d %b", pub)
                except Exception:
                    pass
            if title and not _is_market_ticker(title, summary):
                if url.lower().endswith(".pdf"):
                    body = _fetch_pdf_text(url)
                else:
                    body = _fetch_article_body(url)
                items.append(_fmt("SEBI", title, summary, url, body, pub_date))
        print(f"[fetch_news] SEBI RSS: {len(items)} items (last 48h)")
        return items
    except Exception as exc:
        print(f"[fetch_news] SEBI RSS error: {exc}")
        return []


# Targeted queries covering all report sections
_GOOGLE_QUERIES = [
    ("RBI", "RBI India monetary policy repo rate liquidity"),
    ("RBI", "RBI circular regulation banking India"),
    ("SEBI", "SEBI India capital market regulation bond"),
    ("Banking", "Indian bank NPA stressed assets credit"),
    ("Banking", "SBI HDFC ICICI Axis bank results earnings"),
    ("NBFC", "NBFC India loan disbursement stress liquidity"),
    ("NBFC", "microfinance MFI India NPA collections"),
    ("HFC", "housing finance India HFC mortgage home loan"),
    ("HFC", "LIC Housing HDFC housing affordable housing"),
    ("Broking", "India broking fintech SEBI regulation stock broker"),
    ("Bonds", "India bond market yield G-sec government securities"),
    ("Bonds", "India corporate bond credit spread debenture"),
    ("CP", "commercial paper India money market CP issuance"),
    ("Securitisation", "India securitisation ABS RMBS PTC pool"),
    ("Ratings", "credit rating upgrade downgrade India CRISIL ICRA CareEdge India Ratings"),
    ("Ratings", "rating watch negative outlook India bond issuer"),
]


def _is_recent(entry, hours: int = 48) -> bool:
    """Return True if entry was published within the last N hours."""
    pub = entry.get("published_parsed")
    if not pub:
        return True  # no date → assume recent
    import calendar
    pub_ts = calendar.timegm(pub)
    return (time.time() - pub_ts) <= hours * 3600


def fetch_google_news() -> list[str]:
    items = []
    seen_titles: set[str] = set()

    for (tag, query) in _GOOGLE_QUERIES:
        try:
            url = (
                f"https://news.google.com/rss/search"
                f"?q={requests.utils.quote(query + ' when:2d')}&hl=en-IN&gl=IN&ceid=IN:en"
            )
            feed = feedparser.parse(url)
            count = 0
            for entry in feed.entries:
                if count >= 2:
                    break
                if not _is_recent(entry, 48):
                    continue
                raw_title = _clean(entry.get("title", "")).strip()
                if not raw_title or raw_title in seen_titles:
                    continue
                summary = _clean(entry.get("summary", entry.get("description", ""))).strip()
                if _is_market_ticker(raw_title, summary):
                    continue
                seen_titles.add(raw_title)
                source = tag
                title = raw_title
                if " - " in raw_title:
                    parts = raw_title.rsplit(" - ", 1)
                    title = parts[0].strip()
                    source = parts[1].strip()
                link = entry.get("link", "")
                pub_date = ""
                pub = entry.get("published_parsed")
                if pub:
                    import time as _time
                    try:
                        pub_date = _time.strftime("%d %b", pub)
                    except Exception:
                        pass
                items.append(_fmt(source, title, summary, link, pub_date=pub_date))
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
            query = f"{short_name} India finance"
            url = (
                f"https://news.google.com/rss/search"
                f"?q={requests.utils.quote(query + ' when:2d')}&hl=en-IN&gl=IN&ceid=IN:en"
            )
            feed = feedparser.parse(url)
            count = 0
            for entry in feed.entries:
                if count >= 3:
                    break
                if not _is_recent(entry, 48):
                    continue
                raw_title = _clean(entry.get("title", "")).strip()
                if not raw_title or raw_title in seen_titles:
                    continue
                summary = _clean(entry.get("summary", entry.get("description", ""))).strip()
                if _is_market_ticker(raw_title, summary):
                    continue
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
                pub_date = ""
                pub = entry.get("published_parsed")
                if pub:
                    import time as _time
                    try:
                        pub_date = _time.strftime("%d %b", pub)
                    except Exception:
                        pass
                items.append(f"[WATCHLIST — {company}] {_fmt(source, title, summary, link, pub_date=pub_date)}")
                count += 1
            time.sleep(0.3)
        except Exception as exc:
            print(f"[fetch_news] Company news error for '{company}': {exc}")

    return items


def _normalise_key(item: str) -> str:
    text = re.sub(r"^\[[^\]]+\]\s*", "", item)  # strip [TAG — x] prefix
    text = re.sub(r"^\[T\d\]", "", text)         # strip tier tag
    return text.split(" — ")[0].lower().strip()[:120]


def fetch_all_news(newsapi_key: str = "") -> tuple[str, dict]:
    """Returns (news_text, source_summary) where source_summary maps source name → item count."""
    cfg = load_config()
    sources = cfg.get("sources", {})

    def src_on(key: str) -> bool:
        return sources.get(key, True)

    # Load 5-day seen-headline filter
    seen_keys: set[str] = set()
    _seen_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "seen_headlines.json"
    )
    today_str = str(datetime.date.today())
    try:
        with open(_seen_path, encoding="utf-8") as f:
            data = json.load(f)
        if "days" in data:
            for d, keys in data["days"].items():
                if d < today_str:
                    seen_keys.update(keys)
        elif data.get("date", "") < today_str:
            seen_keys = set(data.get("keys", []))
    except Exception:
        pass

    all_items: list[str] = []
    summary: dict[str, int] = {}

    def _add(key: str, items: list[str]) -> None:
        summary[key] = len(items)
        all_items.extend(items)

    if src_on("rbi_rss"):
        rbi = fetch_rbi_news()
        enf = fetch_rbi_enforcement()
        summary["RBI RSS"] = len(rbi)
        summary["RBI Enforcement"] = len(enf)
        all_items.extend(rbi)
        all_items.extend(enf)

    if src_on("sebi_rss"):
        _add("SEBI RSS", fetch_sebi_news())

    if src_on("rating_agencies"):
        try:
            from fetch_ratings import fetch_all_ratings
            _add("Rating Agencies", fetch_all_ratings())
        except Exception as exc:
            summary["Rating Agencies"] = 0
            print(f"[fetch_news] Rating agencies error: {exc}")

    if src_on("google_news"):
        _add("Google News", fetch_google_news())

    if src_on("newsapi"):
        _add("NewsAPI", fetch_newsapi_news(newsapi_key))

    if src_on("company_watchlist"):
        _add("Watchlist (Google)", fetch_company_news())
        try:
            from fetch_bse import fetch_bse_announcements, fetch_bse_financials
            watchlist = load_watchlist()
            if src_on("bse_announcements"):
                _add("BSE Announcements", fetch_bse_announcements(watchlist))
            _add("BSE Financials", fetch_bse_financials(watchlist))
        except Exception as exc:
            summary["BSE"] = 0
            print(f"[fetch_news] BSE error: {exc}")

    if src_on("telegram"):
        channels = cfg.get("telegram_channels", [])
        if channels:
            _add("Telegram", fetch_telegram_channels(channels))
        else:
            summary["Telegram"] = 0

    if src_on("web_scraper"):
        try:
            _add("Web Scraper", fetch_all_web(
                cfg.get("web_sources", {}),
                cfg.get("custom_scrape_urls", []),
            ))
        except Exception as exc:
            summary["Web Scraper"] = 0
            print(f"[fetch_news] Web scraper error: {exc}")

    # Deduplicate within this batch
    dedup_seen: set[str] = set()
    unique: list[str] = []
    for item in all_items:
        key = _normalise_key(item)
        if not key:
            key = item[:120].lower()
        if key not in dedup_seen:
            dedup_seen.add(key)
            unique.append(item)
        if len(unique) >= 200:
            break

    pre_dedup = len(unique)
    if seen_keys:
        unique = [item for item in unique if _normalise_key(item) not in seen_keys]
        print(f"[fetch_news] After 5-day dedup filter: {len(unique)} items (was {pre_dedup})")

    summary["__total__"] = len(unique)
    summary["__pre_dedup__"] = pre_dedup

    if not unique:
        return "No news items were fetched today. Please check network connectivity and RSS feed availability.", summary

    lines = [f"{i + 1}. {item}" for i, item in enumerate(unique)]
    return "\n".join(lines), summary
