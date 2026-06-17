#!/usr/bin/env python3
"""
fetch_web.py — Web scraper for rating agency press releases and market data.

Sources:
  - CareEdge Ratings     (careedge.in)
  - CRISIL               (crisil.com)
  - ICRA                 (icra.in)
  - India Ratings        (indiaratings.co.in)
  - BSE Corporate Announcements (bseindia.com API)
  - FIMMDA               (fimmda.org)
  - CCIL                 (ccilindia.com)
  - Screener.in          (screener.in — company financials)

Falls back to targeted Google News queries for sites that block scrapers.
"""

import re
import time
import datetime
import requests
import feedparser
from bs4 import BeautifulSoup


# ── Realistic browser headers to avoid 403 blocks ──
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

_SESSION = requests.Session()
_SESSION.headers.update(_HEADERS)


def _get(url: str, timeout: int = 15) -> requests.Response | None:
    """GET with retry (2 attempts, 3s gap)."""
    for attempt in range(2):
        try:
            r = _SESSION.get(url, timeout=timeout)
            if r.status_code == 200:
                return r
            if r.status_code in (403, 429) and attempt == 0:
                time.sleep(3)
        except Exception as exc:
            if attempt == 0:
                time.sleep(3)
            else:
                print(f"[fetch_web] GET {url} failed: {exc}")
    return None


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return " ".join(text.split())


def _cutoff_24h() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=48)


# ─────────────────────────────────────────────────────────────────────────────
# 1. CAREEDGE RATINGS
# ─────────────────────────────────────────────────────────────────────────────
def fetch_careedge() -> list[str]:
    """CareEdge press releases — tries RSS then HTML scrape."""
    items = []

    # Try RSS first
    for rss_url in [
        "https://www.careedge.in/feed",
        "https://www.careedge.in/rss",
        "https://www.careedge.in/pressrelease/feed",
    ]:
        try:
            feed = feedparser.parse(rss_url)
            if feed.entries:
                for entry in feed.entries[:10]:
                    title = _clean(entry.get("title", "")).strip()
                    summary = _clean(entry.get("summary", "")).strip()
                    url = entry.get("link", "")
                    if title:
                        items.append(f"[RATING — CareEdge] {title} — {summary[:200]} | URL:{url}")
                return items
        except Exception:
            pass

    # Fall back to HTML scrape — try multiple possible URLs
    for html_url in [
        "https://www.careedge.in/press-releases",
        "https://www.careedge.in/news",
        "https://www.careedge.in/media",
    ]:
        try:
            r = _get(html_url)
            if r and r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                for a in soup.find_all("a", href=True)[:30]:
                    text = _clean(a.get_text()).strip()
                    href = a["href"]
                    if len(text) > 30 and any(k in text.lower() for k in
                            ["rating", "upgraded", "downgraded", "assigned", "reaffirmed", "outlook", "watch"]):
                        full_url = href if href.startswith("http") else "https://www.careedge.in" + href
                        items.append(f"[RATING — CareEdge] {text[:200]} | URL:{full_url}")
                        if len(items) >= 10:
                            break
                if items:
                    break
        except Exception as exc:
            print(f"[fetch_web] CareEdge scrape error ({html_url}): {exc}")

    # Final fallback: Google News
    if not items:
        items = _google_news_fallback("CareEdge Ratings rating action upgrade downgrade India", "CareEdge")

    return items


# ─────────────────────────────────────────────────────────────────────────────
# 2. CRISIL
# ─────────────────────────────────────────────────────────────────────────────
def fetch_crisil() -> list[str]:
    # crisil.com redirects infinitely when scraped — use Google News directly
    return _google_news_fallback("CRISIL rating upgrade downgrade outlook India", "CRISIL")[:8]


# ─────────────────────────────────────────────────────────────────────────────
# 3. ICRA
# ─────────────────────────────────────────────────────────────────────────────
def fetch_icra() -> list[str]:
    items = []
    try:
        r = _get("https://www.icra.in/Rating/ShowRatingPressRelease")
        if r:
            soup = BeautifulSoup(r.text, "html.parser")
            for sel in ["h3 a", "h4 a", ".press-release a", "td a", "li a", ".rating-news a"]:
                links = soup.select(sel)
                for a in links[:15]:
                    text = _clean(a.get_text()).strip()
                    href = a.get("href", "")
                    # Skip email addresses and very short/long nav items
                    if "@" in text or len(text) < 20 or len(text) > 300:
                        continue
                    # Must look like a press release title (contains keywords or proper sentence)
                    if not any(k in text.lower() for k in [
                        "rating", "rated", "upgraded", "downgraded", "assigned", "reaffirmed",
                        "outlook", "watch", "ltd", "limited", "india", "bank", "finance", "fund"
                    ]):
                        continue
                    full_url = href if href.startswith("http") else "https://www.icra.in" + href
                    items.append(f"[RATING — ICRA] {text[:200]} | URL:{full_url}")
                if items:
                    break
    except Exception as exc:
        print(f"[fetch_web] ICRA scrape error: {exc}")

    if not items:
        items = _google_news_fallback("ICRA rating upgrade downgrade outlook India", "ICRA")

    return items[:10]


# ─────────────────────────────────────────────────────────────────────────────
# 4. INDIA RATINGS (Fitch group)
# ─────────────────────────────────────────────────────────────────────────────
def fetch_india_ratings() -> list[str]:
    items = []
    for url in [
        "https://www.indiaratings.co.in/PressRelease",
        "https://www.indiaratings.co.in/pressrelease",
        "https://www.indiaratings.co.in/ratings/press-releases",
    ]:
        try:
            r = _get(url)
            if r and r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                for sel in ["h3 a", "h4 a", ".press-title a", "td a", "article a", ".news-list a", "li a", "h2 a"]:
                    links = soup.select(sel)
                    for a in links[:15]:
                        text = _clean(a.get_text()).strip()
                        href = a.get("href", "")
                        if "@" in text or len(text) < 20:
                            continue
                        full_url = href if href.startswith("http") else "https://www.indiaratings.co.in" + href
                        items.append(f"[RATING — India Ratings] {text[:200]} | URL:{full_url}")
                    if items:
                        break
            if items:
                break
        except Exception as exc:
            print(f"[fetch_web] India Ratings scrape error ({url}): {exc}")

    if not items:
        items = _google_news_fallback("India Ratings Fitch rating upgrade downgrade India", "India Ratings")

    return items[:10]


# ─────────────────────────────────────────────────────────────────────────────
# 5. BSE CORPORATE ANNOUNCEMENTS + CORPORATE ACTIONS
# ─────────────────────────────────────────────────────────────────────────────
_BSE_HEADERS = {
    **_HEADERS,
    "Referer": "https://www.bseindia.com/",
    "Origin": "https://www.bseindia.com",
}

_CREDIT_KEYWORDS = {
    "rating", "downgrad", "upgrad", "default", "npa", "borrowing",
    "debenture", "ncds", "ncd", "bond", "credit", "debt", "repayment",
    "restructur", "insolvency", "liquidation", "moratorium", "write-off",
    "write off", "provisioning", "stressed", "resolution",
}


def fetch_bse_announcements() -> list[str]:
    """BSE announcements filtered for credit-relevant content."""
    items = []
    today = datetime.date.today()
    prev = today - datetime.timedelta(days=2)

    # Try two endpoints — AnnSubCategoryGetData is more reliable
    endpoints = [
        (
            "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
            f"?strCat=-1&strPrevDate={prev.strftime('%Y%m%d')}"
            f"&strScrip=&strSearch=P&strToDate={today.strftime('%Y%m%d')}"
            "&strType=C&subcategory=-1"
        ),
        (
            "https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w"
            f"?strCat=-1&strPrevDate={prev.strftime('%Y%m%d')}"
            f"&strScrip=&strSearch=P&strToDate={today.strftime('%Y%m%d')}"
            "&strType=C&subcategory=-1"
        ),
    ]

    for url in endpoints:
        try:
            r = _SESSION.get(url, timeout=15, headers=_BSE_HEADERS)
            if r.status_code != 200:
                continue
            data = r.json()
            # The response may use Table, Table1, or a list at root
            announcements = []
            if isinstance(data, list):
                announcements = data
            elif isinstance(data, dict):
                for key in ("Table", "Table1", "announcements", "data"):
                    val = data.get(key)
                    if isinstance(val, list) and val:
                        announcements = val
                        break

            print(f"[fetch_web] BSE endpoint {url.split('api/')[1].split('/')[0]}: {len(announcements)} rows")
            count = 0
            for ann in announcements:
                if not isinstance(ann, dict):
                    continue
                headline = _clean(str(ann.get("HEADLINE", ann.get("NEWSSUB", ann.get("headline", ""))))).strip()
                category = str(ann.get("CATEGORYNAME", ann.get("CATEGORY", ann.get("category", "")))).lower()
                company = _clean(str(ann.get("SLONGNAME", ann.get("SCRIP_NAME", ann.get("company", ""))))).strip()
                pdf = str(ann.get("ATTACHMENTNAME", ann.get("PDF_NAME", ""))).strip()

                if not headline or len(headline) < 10:
                    continue
                hl_lower = headline.lower()
                if not any(k in hl_lower or k in category for k in _CREDIT_KEYWORDS):
                    continue

                url_link = f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{pdf}" if pdf else ""
                tag = f"[BSE — {company}]" if company else "[BSE Announcement]"
                items.append(f"{tag} {headline} | URL:{url_link}" if url_link else f"{tag} {headline}")
                count += 1
                if count >= 15:
                    break

            if items:
                break  # got results, no need for fallback endpoint
        except Exception as exc:
            print(f"[fetch_web] BSE announcements error ({url.split('api/')[1].split('/')[0]}): {exc}")

    return items


def fetch_bse_corporate_actions() -> list[str]:
    """BSE corporate actions — NCD allotments, debenture redemptions, rights issues."""
    items = []
    today = datetime.date.today()
    prev = today - datetime.timedelta(days=7)

    try:
        url = (
            "https://api.bseindia.com/BseIndiaAPI/api/DefaultData/w"
            f"?strDate={prev.strftime('%Y%m%d')}&endDate={today.strftime('%Y%m%d')}"
            "&segment=D"  # D = debt/debenture segment
        )
        r = _SESSION.get(url, timeout=15, headers=_BSE_HEADERS)
        if r.status_code == 200:
            data = r.json()
            rows = data if isinstance(data, list) else data.get("Table", data.get("data", []))
            for row in rows[:20]:
                if not isinstance(row, dict):
                    continue
                purpose = _clean(str(row.get("Purpose", row.get("PURPOSE", "")))).strip()
                company = _clean(str(row.get("SCRIP_NAME", row.get("CompanyName", "")))).strip()
                ex_date = str(row.get("Ex_date", row.get("EXDATE", ""))).strip()
                if purpose and company:
                    items.append(f"[BSE CorpAction — {company}] {purpose} (Ex-date: {ex_date})")
    except Exception as exc:
        print(f"[fetch_web] BSE corporate actions error: {exc}")

    return items[:10]


def fetch_nse_corporate_actions() -> list[str]:
    """NSE corporate actions — uses NSE India public API (no auth needed)."""
    items = []
    today = datetime.date.today()
    from_date = today - datetime.timedelta(days=7)

    try:
        # NSE requires a cookie from homepage first
        session = requests.Session()
        session.headers.update({
            **_HEADERS,
            "Referer": "https://www.nseindia.com/",
        })
        session.get("https://www.nseindia.com/", timeout=10)  # get cookies

        url = (
            "https://www.nseindia.com/api/corporates-corporateActions"
            f"?index=equities&from_date={from_date.strftime('%d-%m-%Y')}"
            f"&to_date={today.strftime('%d-%m-%Y')}&csv=false"
        )
        r = session.get(url, timeout=15)
        if r.status_code == 200:
            data = r.json()
            rows = data if isinstance(data, list) else data.get("data", [])
            credit_purposes = {
                "debenture", "ncd", "bond", "rights", "buyback",
                "dividend", "redemption", "interest", "allotment",
            }
            for row in rows[:30]:
                if not isinstance(row, dict):
                    continue
                purpose = _clean(str(row.get("purpose", row.get("subject", "")))).strip()
                company = _clean(str(row.get("symbol", row.get("companyName", "")))).strip()
                ex_date = str(row.get("exDate", row.get("exdate", ""))).strip()
                if not purpose or not company:
                    continue
                if not any(k in purpose.lower() for k in credit_purposes):
                    continue
                items.append(f"[NSE CorpAction — {company}] {purpose} (Ex-date: {ex_date})")
        print(f"[fetch_web] NSE corporate actions: {len(items)} credit-relevant items")
    except Exception as exc:
        print(f"[fetch_web] NSE corporate actions error: {exc}")

    return items[:10]


# ─────────────────────────────────────────────────────────────────────────────
# 6. FIMMDA (Fixed Income & Money Market)
# ─────────────────────────────────────────────────────────────────────────────
def fetch_fimmda() -> list[str]:
    items = []
    for fimmda_url in [
        "https://www.fimmda.org/circulars",
        "https://www.fimmda.org/notices",
        "https://www.fimmda.org/",
    ]:
        try:
            r = _get(fimmda_url)
            if r and r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                for sel in ["h3 a", "h4 a", "td a", "li a", ".circular a", ".notice a"]:
                    links = soup.select(sel)
                    for a in links[:8]:
                        text = _clean(a.get_text()).strip()
                        href = a.get("href", "")
                        if len(text) > 15:
                            full_url = href if href.startswith("http") else "https://www.fimmda.org" + href
                            items.append(f"[FIMMDA] {text[:200]} | URL:{full_url}")
                    if items:
                        break
            if items:
                break
        except Exception as exc:
            print(f"[fetch_web] FIMMDA scrape error ({fimmda_url}): {exc}")

    if not items:
        items = _google_news_fallback("FIMMDA bond yield valuation India fixed income", "FIMMDA")

    return items[:5]


# ─────────────────────────────────────────────────────────────────────────────
# 7. CCIL (Clearing Corporation of India)
# ─────────────────────────────────────────────────────────────────────────────
def fetch_ccil() -> list[str]:
    # CCIL blocks scrapers (403); use Google News fallback directly
    return _google_news_fallback("CCIL India bond market government securities G-sec trading", "CCIL")[:5]


# ─────────────────────────────────────────────────────────────────────────────
# GOOGLE NEWS FALLBACK for rating agency content
# ─────────────────────────────────────────────────────────────────────────────
def _google_news_fallback(query: str, tag: str, limit: int = 5) -> list[str]:
    try:
        url = (
            f"https://news.google.com/rss/search"
            f"?q={requests.utils.quote(query)}&hl=en-IN&gl=IN&ceid=IN:en&when=2d"
        )
        feed = feedparser.parse(url)
        items = []
        for entry in feed.entries[:limit]:
            raw_title = _clean(entry.get("title", "")).strip()
            if not raw_title:
                continue
            title = raw_title
            source = tag
            if " - " in raw_title:
                parts = raw_title.rsplit(" - ", 1)
                title = parts[0].strip()
                source = parts[1].strip()
            summary = _clean(entry.get("summary", "")).strip()
            link = entry.get("link", "")
            link_part = f" | URL:{link}" if link else ""
            items.append(f"[RATING — {tag}] {source}: {title} — {summary[:200]}{link_part}")
        return items
    except Exception as exc:
        print(f"[fetch_web] Google News fallback error for {tag}: {exc}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# CUSTOM URL SCRAPER — generic, works on any website
# ─────────────────────────────────────────────────────────────────────────────
def fetch_custom_url(url: str) -> list[str]:
    """
    Generic scraper for any URL. Extracts headlines from h1-h4 tags and
    prominent anchor links. Filters for credit-relevant content.
    """
    from urllib.parse import urlparse
    domain = urlparse(url).netloc.replace("www.", "")
    items = []

    try:
        r = _get(url)
        if not r:
            print(f"[fetch_web] Could not fetch {url}")
            return []

        soup = BeautifulSoup(r.text, "html.parser")

        # Remove nav, footer, sidebar noise
        for tag in soup(["nav", "footer", "aside", "script", "style", "header"]):
            tag.decompose()

        seen: set[str] = set()

        # Extract from headings first (most reliable)
        for heading in soup.find_all(["h1", "h2", "h3", "h4"]):
            text = _clean(heading.get_text()).strip()
            if len(text) < 20 or text.lower() in seen:
                continue
            # Look for an anchor inside or near the heading
            a = heading.find("a", href=True) or heading.find_next_sibling("a", href=True)
            href = a["href"] if a else ""
            if href and not href.startswith("http"):
                href = f"https://{domain}{href if href.startswith('/') else '/' + href}"
            link_part = f" | URL:{href}" if href else ""
            seen.add(text.lower())
            items.append(f"[WEB — {domain}] {text[:200]}{link_part}")
            if len(items) >= 10:
                break

        # If headings didn't yield enough, try article/card links
        if len(items) < 5:
            for a in soup.find_all("a", href=True):
                text = _clean(a.get_text()).strip()
                if len(text) < 25 or text.lower() in seen:
                    continue
                href = a["href"]
                if not href.startswith("http"):
                    href = f"https://{domain}{href if href.startswith('/') else '/' + href}"
                seen.add(text.lower())
                items.append(f"[WEB — {domain}] {text[:200]} | URL:{href}")
                if len(items) >= 10:
                    break

    except Exception as exc:
        print(f"[fetch_web] Custom URL scrape error for {url}: {exc}")

    return items


def fetch_custom_urls(urls: list[str]) -> list[str]:
    """Fetch all custom URLs with a 1s gap between requests."""
    all_items: list[str] = []
    for url in urls:
        print(f"[fetch_web] Scraping custom URL: {url}")
        all_items.extend(fetch_custom_url(url))
        time.sleep(1)
    return all_items


# ─────────────────────────────────────────────────────────────────────────────
# NSE DEBT SEGMENT CIRCULARS
# ─────────────────────────────────────────────────────────────────────────────
def fetch_nse_debt_circulars() -> list[str]:
    """NSE debt segment circulars — falls back to Google News."""
    items = []
    try:
        session = requests.Session()
        session.headers.update({
            **_HEADERS,
            "Referer": "https://www.nseindia.com/",
        })
        try:
            session.get("https://www.nseindia.com/", timeout=10)
            r = session.get("https://www.nseindia.com/regulations/circulars", timeout=15)
            if r and r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                count = 0
                for a in soup.find_all("a", href=True):
                    text = _clean(a.get_text()).strip()
                    href = a["href"]
                    if len(text) < 20:
                        continue
                    if not any(k in text.lower() for k in ["debt", "bond", "debenture", "ncd", "circular"]):
                        continue
                    full_url = href if href.startswith("http") else "https://www.nseindia.com" + href
                    items.append(f"[T1]NSE: {text[:200]} | URL:{full_url}")
                    count += 1
                    if count >= 5:
                        break
        except Exception:
            pass
        if not items:
            raise Exception("fallback to Google News")
    except Exception:
        pass
    if not items:
        try:
            url = (
                "https://news.google.com/rss/search"
                f"?q={requests.utils.quote('NSE India debt circular bond debenture when:2d')}"
                "&hl=en-IN&gl=IN&ceid=IN:en"
            )
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:
                raw_title = _clean(entry.get("title", "")).strip()
                if not raw_title:
                    continue
                title = raw_title
                if " - " in raw_title:
                    parts = raw_title.rsplit(" - ", 1)
                    title = parts[0].strip()
                link = entry.get("link", "")
                link_part = f" | URL:{link}" if link else ""
                items.append(f"[T1]NSE: {title}{link_part}")
        except Exception as exc:
            print(f"[fetch_web] NSE debt circulars Google fallback error: {exc}")
    return items[:5]


# ─────────────────────────────────────────────────────────────────────────────
# RBI DBIE MACRO DATA
# ─────────────────────────────────────────────────────────────────────────────
def fetch_rbi_dbie() -> list[str]:
    """RBI DBIE macro data via Google News fallback."""
    items = []
    try:
        queries = [
            ("RBI repo rate CRR liquidity India monetary policy when:2d", "T1", "RBI-DBIE"),
            ("India CPI inflation GDP IIP data release when:2d", "T2", "Macro"),
        ]
        for query, tier, tag in queries:
            try:
                url = (
                    "https://news.google.com/rss/search"
                    f"?q={requests.utils.quote(query)}&hl=en-IN&gl=IN&ceid=IN:en"
                )
                feed = feedparser.parse(url)
                count = 0
                for entry in feed.entries[:5]:
                    raw_title = _clean(entry.get("title", "")).strip()
                    if not raw_title:
                        continue
                    title = raw_title
                    if " - " in raw_title:
                        parts = raw_title.rsplit(" - ", 1)
                        title = parts[0].strip()
                    link = entry.get("link", "")
                    link_part = f" | URL:{link}" if link else ""
                    items.append(f"[{tier}]{tag}: {title}{link_part}")
                    count += 1
                    if count >= 3:
                        break
            except Exception as exc:
                print(f"[fetch_web] RBI DBIE query error: {exc}")
    except Exception as exc:
        print(f"[fetch_web] RBI DBIE error: {exc}")
    return items[:5]


# ─────────────────────────────────────────────────────────────────────────────
# BOND ISSUANCES TRACKER
# ─────────────────────────────────────────────────────────────────────────────
def fetch_bond_issuances() -> list[str]:
    """Track bond/NCD/CP/securitisation issuances via Google News."""
    items = []
    try:
        import datetime as _dt
        year = _dt.date.today().year
        queries = [
            f"India NCD bond issuance allotment debenture {year} when:2d",
            f"India commercial paper issuance money market {year} when:2d",
            f"India securitisation ABS PTC issuance {year} when:2d",
        ]
        for query in queries:
            try:
                url = (
                    "https://news.google.com/rss/search"
                    f"?q={requests.utils.quote(query)}&hl=en-IN&gl=IN&ceid=IN:en"
                )
                feed = feedparser.parse(url)
                count = 0
                for entry in feed.entries[:3]:
                    raw_title = _clean(entry.get("title", "")).strip()
                    if not raw_title:
                        continue
                    title = raw_title
                    if " - " in raw_title:
                        parts = raw_title.rsplit(" - ", 1)
                        title = parts[0].strip()
                    link = entry.get("link", "")
                    link_part = f" | URL:{link}" if link else ""
                    items.append(f"[S4]Bond Markets: {title}{link_part}")
                    count += 1
                    if count >= 3:
                        break
            except Exception as exc:
                print(f"[fetch_web] Bond issuances query error: {exc}")
    except Exception as exc:
        print(f"[fetch_web] Bond issuances error: {exc}")
    return items[:9]


# ─────────────────────────────────────────────────────────────────────────────
# MCA CHARGE FILINGS
# ─────────────────────────────────────────────────────────────────────────────
def fetch_mca_charges() -> list[str]:
    """MCA charge filings via Google News (site requires login)."""
    items = []
    try:
        url = (
            "https://news.google.com/rss/search"
            f"?q={requests.utils.quote('MCA India charge creation satisfaction ROC filing NBFC HFC when:2d')}"
            "&hl=en-IN&gl=IN&ceid=IN:en"
        )
        feed = feedparser.parse(url)
        for entry in feed.entries[:5]:
            raw_title = _clean(entry.get("title", "")).strip()
            if not raw_title:
                continue
            title = raw_title
            if " - " in raw_title:
                parts = raw_title.rsplit(" - ", 1)
                title = parts[0].strip()
            link = entry.get("link", "")
            link_part = f" | URL:{link}" if link else ""
            items.append(f"[MCA] {title}{link_part}")
    except Exception as exc:
        print(f"[fetch_web] MCA charges error: {exc}")
    # Try MCA site (best-effort, likely fails)
    try:
        r = _get("https://www.mca.gov.in/content/mca/global/en/mca/master-data/GSTINandPAN.html", timeout=10)
        # If we get here, it returned something but we just ignore it for now
    except Exception:
        pass
    return items[:5]


# ─────────────────────────────────────────────────────────────────────────────
# NSDL DEBENTURE DEFAULTS
# ─────────────────────────────────────────────────────────────────────────────
def fetch_nsdl_defaults() -> list[str]:
    """NSDL debenture trustee defaults — tries scrape then Google News fallback."""
    items = []
    try:
        r = _get("https://www.nsdl.co.in/debenture-trustee-default.php", timeout=15)
        if r and r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            for row in soup.find_all("tr")[1:10]:
                cols = row.find_all("td")
                if not cols:
                    continue
                text = _clean(" | ".join(c.get_text() for c in cols)).strip()
                if len(text) > 10:
                    items.append(f"[T1]NSDL: {text[:200]}")
                if len(items) >= 5:
                    break
    except Exception:
        pass
    if not items:
        try:
            url = (
                "https://news.google.com/rss/search"
                f"?q={requests.utils.quote('NSDL debenture trustee default India bond when:2d')}"
                "&hl=en-IN&gl=IN&ceid=IN:en"
            )
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:
                raw_title = _clean(entry.get("title", "")).strip()
                if not raw_title:
                    continue
                title = raw_title
                if " - " in raw_title:
                    parts = raw_title.rsplit(" - ", 1)
                    title = parts[0].strip()
                link = entry.get("link", "")
                link_part = f" | URL:{link}" if link else ""
                items.append(f"[T1]NSDL: {title}{link_part}")
        except Exception as exc:
            print(f"[fetch_web] NSDL defaults Google fallback error: {exc}")
    return items[:5]


# ─────────────────────────────────────────────────────────────────────────────
# MOSPI / MACRO DATA RELEASE CALENDAR
# ─────────────────────────────────────────────────────────────────────────────
def fetch_macro_releases() -> list[str]:
    """Fetch macro data releases based on typical Indian release calendar."""
    import datetime as _dt
    items = []
    today = _dt.date.today()
    day = today.day
    month_name = today.strftime("%B")
    year = today.year

    try:
        # Check proximity to typical release dates
        release_dates = {
            "CPI": 12,
            "IIP": 12,
            "WPI": 14,
        }
        gdp_days = range(28, 32)

        targeted_queries = []
        for indicator, release_day in release_dates.items():
            if abs(day - release_day) <= 2:
                targeted_queries.append(
                    (f"India {indicator} data {month_name} {year} release MOSPI when:2d", indicator)
                )
        if day in gdp_days:
            targeted_queries.append(
                (f"India GDP data {month_name} {year} release MOSPI when:2d", "GDP")
            )

        for query, indicator in targeted_queries:
            try:
                url = (
                    "https://news.google.com/rss/search"
                    f"?q={requests.utils.quote(query)}&hl=en-IN&gl=IN&ceid=IN:en"
                )
                feed = feedparser.parse(url)
                for entry in feed.entries[:3]:
                    raw_title = _clean(entry.get("title", "")).strip()
                    if not raw_title:
                        continue
                    title = raw_title
                    if " - " in raw_title:
                        parts = raw_title.rsplit(" - ", 1)
                        title = parts[0].strip()
                    link = entry.get("link", "")
                    link_part = f" | URL:{link}" if link else ""
                    items.append(f"[T2]Macro-Release: {title}{link_part}")
            except Exception as exc:
                print(f"[fetch_web] Macro release query error for {indicator}: {exc}")

        # Always run general query
        try:
            general_url = (
                "https://news.google.com/rss/search"
                f"?q={requests.utils.quote('India macro data GDP CPI IIP release MOSPI when:2d')}"
                "&hl=en-IN&gl=IN&ceid=IN:en"
            )
            feed = feedparser.parse(general_url)
            for entry in feed.entries[:3]:
                raw_title = _clean(entry.get("title", "")).strip()
                if not raw_title:
                    continue
                title = raw_title
                if " - " in raw_title:
                    parts = raw_title.rsplit(" - ", 1)
                    title = parts[0].strip()
                link = entry.get("link", "")
                link_part = f" | URL:{link}" if link else ""
                items.append(f"[T2]Macro-Release: {title}{link_part}")
        except Exception as exc:
            print(f"[fetch_web] Macro general query error: {exc}")

    except Exception as exc:
        print(f"[fetch_web] Macro releases error: {exc}")

    return items


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────
def fetch_all_web(sources: dict | None = None, custom_urls: list[str] | None = None) -> list[str]:
    """
    Fetch from all configured web sources + any custom URLs.
    sources dict maps source key → True/False (from config.json web_sources).
    custom_urls is the list from config.json custom_scrape_urls.
    """
    if sources is None:
        sources = {}

    def on(key: str) -> bool:
        return sources.get(key, True)

    all_items: list[str] = []

    if on("careedge"):
        print("[fetch_web] Fetching CareEdge...")
        all_items.extend(fetch_careedge())

    if on("crisil"):
        print("[fetch_web] Fetching CRISIL...")
        all_items.extend(fetch_crisil())
        time.sleep(1)

    if on("icra"):
        print("[fetch_web] Fetching ICRA...")
        all_items.extend(fetch_icra())
        time.sleep(1)

    if on("india_ratings"):
        print("[fetch_web] Fetching India Ratings...")
        all_items.extend(fetch_india_ratings())
        time.sleep(1)

    if on("bse"):
        print("[fetch_web] Fetching BSE announcements...")
        all_items.extend(fetch_bse_announcements())
        print("[fetch_web] Fetching BSE corporate actions...")
        all_items.extend(fetch_bse_corporate_actions())

    if on("nse"):
        print("[fetch_web] Fetching NSE corporate actions...")
        all_items.extend(fetch_nse_corporate_actions())

    if on("fimmda"):
        print("[fetch_web] Fetching FIMMDA...")
        all_items.extend(fetch_fimmda())
        time.sleep(1)

    if on("ccil"):
        print("[fetch_web] Fetching CCIL...")
        all_items.extend(fetch_ccil())

    if on("nse_circulars"):
        print("[fetch_web] Fetching NSE debt circulars...")
        all_items.extend(fetch_nse_debt_circulars())

    if on("rbi_dbie"):
        print("[fetch_web] Fetching RBI DBIE macro data...")
        all_items.extend(fetch_rbi_dbie())

    if on("bond_issuances"):
        print("[fetch_web] Fetching bond issuances...")
        all_items.extend(fetch_bond_issuances())

    if on("mca_charges"):
        print("[fetch_web] Fetching MCA charges...")
        all_items.extend(fetch_mca_charges())

    if on("nsdl_defaults"):
        print("[fetch_web] Fetching NSDL defaults...")
        all_items.extend(fetch_nsdl_defaults())

    if on("macro_releases"):
        print("[fetch_web] Fetching macro releases...")
        all_items.extend(fetch_macro_releases())

    if custom_urls:
        print(f"[fetch_web] Fetching {len(custom_urls)} custom URL(s)...")
        all_items.extend(fetch_custom_urls(custom_urls))

    print(f"[fetch_web] Total web items fetched: {len(all_items)}")
    return all_items
