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

from fetch_telegram import fetch_telegram_channels
from fetch_web import fetch_all_web

# Only accept articles published within this many hours
_MAX_AGE_HOURS = 48


def _is_recent(entry) -> bool:
    """Return True if the feed entry was published within _MAX_AGE_HOURS."""
    for field in ("published_parsed", "updated_parsed"):
        t = entry.get(field)
        if t:
            try:
                pub = datetime.datetime(*t[:6], tzinfo=datetime.timezone.utc)
                age = datetime.datetime.now(datetime.timezone.utc) - pub
                return age.total_seconds() <= _MAX_AGE_HOURS * 3600
            except Exception:
                pass
    # No date field — exclude to avoid surfacing old undated articles
    return False


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
            if not _is_recent(entry):
                continue
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
            gn_url = "https://news.google.com/rss/search?q=RBI+India+monetary+policy+regulation&hl=en-IN&gl=IN&ceid=IN:en&when=2d"
            feed = feedparser.parse(gn_url)
            for entry in feed.entries[:10]:
                if not _is_recent(entry):
                    continue
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
        for entry in feed.entries[:20]:
            if not _is_recent(entry):
                continue
            title = _clean(entry.get("title", "")).strip()
            summary = _clean(entry.get("summary", entry.get("description", ""))).strip()
            url = entry.get("link", "")
            if title:
                items.append(_fmt("SEBI", title, summary, url))
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
    ("Macro", "India GDP growth inflation RBI monetary policy outlook"),
    ("Macro", "India IIP CPI WPI data economic indicators"),
    ("Macro", "India forex reserve rupee dollar current account"),
    ("Macro", "India fiscal deficit government borrowing budget"),
    ("Macro", "global economy US Fed interest rate India impact"),
]


def fetch_google_news() -> list[str]:
    items = []
    seen_titles: set[str] = set()

    for (tag, query) in _GOOGLE_QUERIES:
        try:
            url = (
                f"https://news.google.com/rss/search"
                f"?q={requests.utils.quote(query)}&hl=en-IN&gl=IN&ceid=IN:en&when=2d"
            )
            feed = feedparser.parse(url)
            count = 0
            max_per_query = 4 if tag == "Macro" else 3
            for entry in feed.entries:
                if count >= max_per_query:
                    break
                if not _is_recent(entry):
                    continue
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


def _short_name(company: str) -> str:
    suffixes = [
        "private limited", "pvt limited", "pvt. limited", "pvt ltd",
        "pvt. ltd.", "limited", "ltd.", "ltd", "llp", "co limited",
        "company limited", "finance company", "financial services",
        "services private", "solutions private", "capital private",
    ]
    name = company.lower()
    for s in suffixes:
        name = name.replace(s, "")
    name = name.strip(" .,")
    words = [w for w in company.split() if w.lower() not in {
        "private", "limited", "pvt", "ltd", "the", "and", "&", "co",
        "company", "services", "solutions", "finance", "financial",
    }]
    return " ".join(words[:4]) if words else company.split()[0]


def fetch_company_news() -> list[str]:
    companies = load_watchlist()
    if not companies:
        return []

    items = []
    seen_titles: set[str] = set()

    for company in companies:
        if len(items) >= 60:
            break
        short = _short_name(company)
        try:
            for query in [
                f'"{short}" India finance credit rating',
                f'"{short}" India',
            ]:
                url = (
                    f"https://news.google.com/rss/search"
                    f"?q={requests.utils.quote(query)}&hl=en-IN&gl=IN&ceid=IN:en&when=2d"
                )
                feed = feedparser.parse(url)
                count = 0
                for entry in feed.entries:
                    if count >= 2:
                        break
                    if not _is_recent(entry):
                        continue
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
                if count > 0:
                    break
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

    # Custom RSS feeds added via management console
    custom_rss = cfg.get("custom_rss_feeds", [])
    for feed_url in custom_rss:
        try:
            feed = feedparser.parse(feed_url)
            count = 0
            for entry in feed.entries:
                if not _is_recent(entry):
                    continue
                title = entry.get("title", "").strip()
                summary = entry.get("summary", entry.get("description", "")).strip()
                summary = re.sub(r"<[^>]+>", " ", summary)
                summary = " ".join(summary.split())[:200]
                url = entry.get("link", "")
                text = f"[CUSTOM RSS] {title}"
                if summary:
                    text += f" — {summary}"
                if url:
                    text += f" | URL: {url}"
                all_items.append(text)
                count += 1
                if count >= 10:
                    break
            print(f"[custom_rss] {feed_url}: {count} items")
        except Exception as exc:
            print(f"[custom_rss] Failed {feed_url}: {exc}")

    # --- Pre-filter 1: minimum text length ---
    # Telegram-PDF items get a lower threshold (caption may be short, content is in PDF text)
    def _long_enough(item: str) -> bool:
        threshold = 40 if "[TELEGRAM" in item else 80
        return len(item.strip()) >= threshold
    all_items = [item for item in all_items if _long_enough(item)]

    # --- Pre-filter 2: block non-credit noise ---
    _BLOCK_TERMS = [
        "ipo ", " ipo", "stock tip", "dividend declared", "agm ", " agm",
        "product launch", "csr ", " csr", "corporate social", "award ",
        " award", "felicitat", "merger rumour", "takeover rumour",
        "celebrity", "bollywood", "cricket", "sports",
    ]
    _CREDIT_TERMS = [
        # Rating actions
        "rating", "downgrad", "upgrad", "reaffirm", "outlook", "watchlist",
        "credit watch", "rating action", "placed on",
        # Asset quality / stress
        "npa", "gnpa", "nnpa", "asset quality", "provisioning", "write-off",
        "write-down", "haircut", "moratorium", "standstill", "deferral",
        "stressed asset", "sma", "special mention", "fraud", "divergence",
        # Capital / funding / liquidity
        "capital", "liquidity", "funding", "solvency", "net worth",
        "capital adequacy", "car ", "tier 1", "tier 2", "leverage",
        # Debt instruments (S4)
        "bond", "debenture", "ncd", "g-sec", "gsec", "t-bill", "tbill",
        "commercial paper", "cp ", "yield", "spread", "coupon", "maturity",
        "debt", "securitis", "securitiz", "pass-through", "ptc ",
        "repo ", "reverse repo", "ois ", "mclr", "base rate",
        "auction", "fimmda", "ccil", "fpi ", "fii ",
        # Regulatory (S3)
        "rbi", "sebi", "nhb", "irdai", "pfrda", "sidbi", "nabard", "exim",
        "circular", "notification", "regulation", "directive", "master direction",
        "penalty", "enforcement", "licence", "registration cancel",
        "pca ", "prompt corrective", "fema", "pmla", "kyc", "aml",
        "neft", "rtgs", "upi", "payment system",
        # Sectors (S2)
        "nbfc", "hfc", "mfi", "microfinance", "co-lending", "colending",
        "bank", "lender", "fintech", "broking", "broker", "aif ", "pms ",
        "mutual fund", "insurance", "insurer", "priority sector",
        "credit growth", "loan growth", "deposit", "nim ", "net interest",
        "slippage", "collection efficiency", "disbursement",
        # Insolvency / legal (S2/S3)
        "insolvency", "ibc", "nclt", "nclat", "resolution", "liquidat",
        "bankruptcy", "one-time settlement", "ots ",
        # Macro (S5)
        "gdp", "gva", "cpi", "wpi", "iip", "inflation", "deflation",
        "monetary policy", "mpc ", "rate cut", "rate hike", "interest rate",
        "fiscal", "fiscal deficit", "current account", "trade deficit",
        "forex reserve", "rupee", "dollar", "exchange rate",
        "fed ", "federal reserve", "ecb ", "global growth", "recession",
        "pmi ", "purchasing manager",
        # Guarantees / credit enhancement
        "guarantee", "credit enhancement", "partial credit", "escrow",
        "letter of credit", "lc ", "bank guarantee",
        # General credit signals
        "default", "restructur", "debt ", "interest coverage",
    ]

    def _is_credit_relevant(item: str) -> bool:
        lower = item.lower()
        if any(t in lower for t in _BLOCK_TERMS):
            return False
        # Watchlist items always pass
        if item.startswith("[WATCHLIST"):
            return True
        # Telegram-PDF items pass if the PDF text was extracted (likely a research report)
        if item.startswith("[TELEGRAM-PDF"):
            return True
        # Plain Telegram text: apply credit filter
        if item.startswith("[TELEGRAM"):
            return any(t in lower for t in _CREDIT_TERMS)
        # All other sources: must match credit terms
        return any(t in lower for t in _CREDIT_TERMS)

    all_items = [item for item in all_items if _is_credit_relevant(item)]

    # --- Pre-filter 3: skip headlines already covered in the previous report ---
    try:
        import json as _json, os as _os
        _seen_path = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "data", "seen_headlines.json")
        with open(_seen_path, encoding="utf-8") as _f:
            _prev = set(_json.load(_f).get("keys", []))
        def _already_seen(item: str) -> bool:
            text = re.sub(r"^\[[^\]]+\]\s*", "", item)
            key = text.lower().strip()[:120]
            return key in _prev
        before = len(all_items)
        all_items = [item for item in all_items if not _already_seen(item)]
        print(f"[fetch_news] Seen-headlines filter: dropped {before - len(all_items)} already-covered items")
    except FileNotFoundError:
        pass  # first run — no history yet
    except Exception as exc:
        print(f"[fetch_news] Seen-headlines filter skipped: {exc}")

    # Deduplicate by normalised headline — strip tag prefix like [TELEGRAM — @x] or [WATCHLIST — Co]
    seen: set[str] = set()
    unique: list[str] = []
    for item in all_items:
        # Strip leading [TAG — value] prefix before keying
        text = re.sub(r"^\[[^\]]+\]\s*", "", item)
        key = text.split(" — ")[0].lower().strip()[:120]
        if not key:
            key = item[:120].lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)
        if len(unique) >= 100:  # hard cap: 100 items max to Claude
            break

    print(f"[fetch_news] Final feed: {len(unique)} items after all filters")
    if not unique:
        return "No news items were fetched today. Please check network connectivity and RSS feed availability."

    lines = [f"{i + 1}. {item}" for i, item in enumerate(unique)]
    return "\n".join(lines)
