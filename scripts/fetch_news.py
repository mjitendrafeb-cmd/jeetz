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


# ---------------------------------------------------------------------------
# Language filter — English-only desk
# ---------------------------------------------------------------------------
# Script blocks for the Indian languages that actually show up in these feeds,
# plus Arabic (Urdu). Matching on script is far more reliable than word lists:
# a headline in Devanagari is unambiguous, whereas transliterated Hindi in
# Latin script is rare in these sources.
_INDIC_SCRIPT_RE = re.compile(
    "["
    "\u0900-\u097F"   # Devanagari  — Hindi, Marathi, Nepali
    "\u0980-\u09FF"   # Bengali / Assamese
    "\u0A00-\u0A7F"   # Gurmukhi    — Punjabi
    "\u0A80-\u0AFF"   # Gujarati
    "\u0B00-\u0B7F"   # Odia
    "\u0B80-\u0BFF"   # Tamil
    "\u0C00-\u0C7F"   # Telugu
    "\u0C80-\u0CFF"   # Kannada
    "\u0D00-\u0D7F"   # Malayalam
    "\u0D80-\u0DFF"   # Sinhala
    "\u0600-\u06FF"   # Arabic      — Urdu
    "]"
)

# Regional-language mastheads. Their copy is occasionally syndicated in Latin
# script, so the script test alone would miss them.
_REGIONAL_DOMAIN_RE = re.compile(
    r"(navbharattimes|maharashtratimes|amarujala|jagran|bhaskar|livehindustan|"
    r"patrika|lokmat|loksatta|abplive\.com/hindi|aajtak|zeenews\.india\.com/hindi|"
    r"hindi\.|/hindi/|marathi\.|/marathi/|tamil\.|/tamil/|telugu\.|/telugu/|"
    r"kannada\.|/kannada/|malayalam\.|/malayalam/|bangla\.|/bangla/|gujarati\.|"
    r"/gujarati/|eenadu|sakshi\.com|dinamalar|dinakaran|mathrubhumi|manoramaonline|"
    r"anandabazar|prabhatkhabar|divyabhaskar|sandesh\.com|gujaratsamachar)",
    re.IGNORECASE,
)


def _is_non_english(item: str) -> bool:
    """True when a fetched line is regional-language content."""
    if _REGIONAL_DOMAIN_RE.search(item):
        return True
    # Ignore the URL when script-testing: percent-encoding never carries
    # Indic characters, but a slug might, and that is not the headline.
    text = re.sub(r"\|\s*URL:\S+", " ", item)
    hits = len(_INDIC_SCRIPT_RE.findall(text))
    if not hits:
        return False
    letters = sum(1 for c in text if c.isalpha()) or 1
    # A stray glyph in an otherwise English headline (a rupee-adjacent
    # transliteration, a quoted name) should not condemn the item.
    return hits / letters > 0.15


# Individual-company share-price moves. S2-S5 are the industry / sector /
# economy sections — an entity's intraday move belongs in none of them, and
# the 7:30 prompt already lists this under SKIP ("intraday moves, top
# gainers/losers"). The existing _SKIP_PATTERNS only caught index-level moves
# (Sensex/Nifty), so company-level ones walked straight through:
#   "Godfrey Phillips shares jump 7% as Samir Modi seeks peace with mother"
#   "Zydus Wellness Share Price Falls Over 3% After Q1 Net Profit Declines"
# Deliberately requires a shares/stock token NEAR a move verb, so "raises Rs
# 500 crore via share sale" and "RBI allows banks to issue shares" survive.
_STOCK_MOVE_RE = re.compile(
    r"\b(shares?|stock|share price|scrip|m-?cap)\b[^.|]{0,40}?\b"
    r"(jump|rall(y|ies|ied)|surg|soar|zoom|spike|climb|gain|rise|rises|risen|"
    r"advanc|drop|fall|fell|slip|slid|declin|tank|plunge|crash|slump|tumbl|"
    r"sink|sank|dip)\w*"
    r"|\b(jump|rall(y|ies)|surg|soar|zoom|spike|climb|gain|drop|fall|slip|"
    r"declin|tank|plunge|crash|slump|tumbl)\w*\b[^.|]{0,25}\b(shares?|stock|share price)\b"
    r"|\bsell[- ]?off\b"
    r"|\bshares?\s+(up|down)\s+\d"
    r"|\b(hits?|touch\w*|scal\w*)\s+(52[- ]week|record|all[- ]time|lifetime)\s+(high|low)\b",
    re.IGNORECASE,
)


def _is_market_ticker(title: str, summary: str = "") -> bool:
    # Stock-move framing is tested on the HEADLINE only — a summary that
    # mentions a share move in passing should not condemn a real story.
    return bool(_SKIP_PATTERNS.search(title) or _SKIP_PATTERNS.search(summary)
                or _STOCK_MOVE_RE.search(title))


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


_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# RBI migrated to website.rbi.org.in — old scripts/rss.aspx serves nothing.
_RBI_FEEDS = [
    "https://website.rbi.org.in/web/rbi/press-releases/rss",
    "https://website.rbi.org.in/web/rbi/notifications/rss",
    "https://www.rbi.org.in/pressreleases_rss.xml",
    "https://www.rbi.org.in/notifications_rss.xml",
]


def fetch_rbi_news() -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    body_fetches = 0
    for feed_url in _RBI_FEEDS:
        try:
            feed = feedparser.parse(feed_url, agent=_UA)
            for entry in feed.entries[:20]:
                if not _is_recent(entry, 48):
                    continue
                title = _clean(entry.get("title", "")).strip()
                if not title or title.lower() in seen:
                    continue
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
                if _is_market_ticker(title, summary):
                    continue
                body = ""
                if body_fetches < 8:
                    body = _fetch_pdf_text(url) if url.lower().endswith(".pdf") else _fetch_article_body(url)
                    body_fetches += 1
                seen.add(title.lower())
                items.append(_fmt("RBI", title, summary, url, body, pub_date))
        except Exception as exc:
            print(f"[fetch_news] RBI feed error ({feed_url}): {exc}")
        if len(items) >= 15:
            break

    # RSS endpoints are flaky — always guarantee RBI coverage via Google News.
    if not items:
        try:
            query = "RBI press release OR notification OR circular OR master direction when:2d"
            url = (
                f"https://news.google.com/rss/search"
                f"?q={requests.utils.quote(query)}&hl=en-IN&gl=IN&ceid=IN:en"
            )
            feed = feedparser.parse(url, agent=_UA)
            for entry in feed.entries[:10]:
                raw_title = _clean(entry.get("title", "")).strip()
                if not raw_title or raw_title.lower() in seen:
                    continue
                summary = _clean(entry.get("summary", "")).strip()
                if _is_market_ticker(raw_title, summary):
                    continue
                title = raw_title.rsplit(" - ", 1)[0].strip() if " - " in raw_title else raw_title
                seen.add(raw_title.lower())
                items.append(_fmt("RBI", title, summary, entry.get("link", "")))
        except Exception as exc:
            print(f"[fetch_news] RBI Google fallback error: {exc}")

    print(f"[fetch_news] RBI RSS: {len(items)} items (last 48h)")
    return items


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


def _is_recent(entry, hours: int = 48, assume: bool = True) -> bool:
    """Return True if entry was published within the last N hours.

    assume controls undated entries: True for primary feeds (RBI RSS
    sometimes omits dates), False for Google News (always dated, so a
    missing date means something is off — drop it).
    """
    pub = entry.get("published_parsed")
    if not pub:
        return assume
    import calendar
    pub_ts = calendar.timegm(pub)
    return (time.time() - pub_ts) <= hours * 3600


def _parse_gnews(url: str, label: str):
    """Fetch a Google News RSS URL with a browser UA and timeout, then parse.

    feedparser.parse(url) fetches with its own default user-agent and no
    timeout — Google silently serves empty results to that UA, which made
    Google News return 0 items with no error. Fetch explicitly instead.
    """
    resp = requests.get(url, headers={"User-Agent": _UA}, timeout=15)
    feed = feedparser.parse(resp.content)
    if resp.status_code != 200 or not feed.entries:
        print(f"[fetch_news] Google News empty for '{label}' "
              f"(HTTP {resp.status_code}, {len(feed.entries)} entries)")
    return feed


def fetch_google_news() -> list[str]:
    items = []
    seen_titles: set[str] = set()

    for (tag, query) in _GOOGLE_QUERIES:
        try:
            url = (
                f"https://news.google.com/rss/search"
                f"?q={requests.utils.quote(query + ' when:2d')}&hl=en-IN&gl=IN&ceid=IN:en"
            )
            feed = _parse_gnews(url, query)
            count = 0
            for entry in feed.entries:
                if count >= 3:
                    break
                if not _is_recent(entry, 48, assume=False):
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


def fetch_company_news(per_company_cap: int = 3) -> list[str]:
    """per_company_cap: how many stories to keep from each company's
    Google News results. Default 3 = the 7:30 report's long-standing
    behaviour (do not change). The 7:40 team mail passes a wider value
    because it has its own mechanical junk filter to absorb the noise."""
    companies = load_watchlist()
    if not companies:
        return []

    items = []
    seen_titles: set[str] = set()

    # Query EVERY company (no global early-break) so a long watchlist isn't
    # starved — with 340 names the old `len(items) >= 60` cap stopped after
    # ~30 companies. Per-company output is capped at 2, and generate_report's
    # 100k-char input cap trims the tail if the total ever gets large.
    empty_streak = 0
    for company in companies:
        try:
            short_name = " ".join(company.split()[:2])
            query = f"{short_name} India finance"
            url = (
                f"https://news.google.com/rss/search"
                f"?q={requests.utils.quote(query + ' when:2d')}&hl=en-IN&gl=IN&ceid=IN:en"
            )
            feed = _parse_gnews(url, short_name)
            # Google throttles rapid-fire requests by returning empty feeds.
            # If many queries come back empty in a row, back off harder.
            if not feed.entries:
                empty_streak += 1
                if empty_streak >= 15:
                    time.sleep(2.0)
                    empty_streak = 0
            else:
                empty_streak = 0
            count = 0
            for entry in feed.entries:
                # Google often ranks technical-chart noise above the real
                # story, so a tight cap can drop genuine results (this lost an
                # Indostar Q1 item). A wider cap costs no extra requests —
                # same one query per company, we just keep more of its results.
                if count >= per_company_cap:
                    break
                if not _is_recent(entry, 48, assume=False):
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


def fetch_all_news(newsapi_key: str = "", apply_seen: bool = True,
                   per_company_cap: int = 3) -> tuple[str, dict]:
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
                    # Re-normalise on load: legacy keys included the summary
                    # text after " — ", which _normalise_key strips — without
                    # this the filter never matched and old items recurred.
                    seen_keys.update(_normalise_key(k) for k in keys)
        elif data.get("date", "") < today_str:
            seen_keys = {_normalise_key(k) for k in data.get("keys", [])}
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
        _add("Watchlist (Google)", fetch_company_news(per_company_cap))
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

    # Drop non-English items before anything else looks at them. Google News
    # India and several aggregator feeds mix in Hindi/Marathi/Tamil/Bengali
    # copy, which this desk does not read. Applied here, at the one point
    # every fetcher converges, so both the 7:30 and 7:40 mails are covered.
    pre_lang = len(all_items)
    all_items = [i for i in all_items if not _is_non_english(i)]
    if pre_lang != len(all_items):
        print(f"[fetch_news] Dropped {pre_lang - len(all_items)} non-English/regional items")

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
    if not apply_seen:
        seen_keys = set()  # caller keeps its own memory (e.g. team mailer)
    if seen_keys:
        unique = [item for item in unique if _normalise_key(item) not in seen_keys]
        print(f"[fetch_news] After 30-day dedup filter: {len(unique)} items (was {pre_dedup})")

    summary["__total__"] = len(unique)
    summary["__pre_dedup__"] = pre_dedup

    if not unique:
        return "No news items were fetched today. Please check network connectivity and RSS feed availability.", summary

    lines = [f"{i + 1}. {item}" for i, item in enumerate(unique)]
    return "\n".join(lines), summary
