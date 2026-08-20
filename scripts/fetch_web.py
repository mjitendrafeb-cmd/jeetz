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
# NSE / BSE RSS FEEDS — static XML on archive servers, usually not IP-blocked
# like the JSON APIs are.
# ─────────────────────────────────────────────────────────────────────────────
def _load_watchlist_phrases(companies=None) -> list[str]:
    """First two words of each watchlist company (lowercased) — precise enough
    to not match sibling group entities (e.g. 'shriram credit' won't match
    Shriram Finance news).

    companies: explicit company name list to use instead of watchlist.txt.
    Without this, the NSE/BSE exchange feeds (watchlist_only=True) could
    only ever match watchlist.txt's 41 names -- 7:30's own list -- even
    when called from the 7:40 team mail, whose team.json tracks ~370
    entities. 331 of them could never produce an exchange-feed hit
    however many feeds were added or how deep they were scanned, since
    the company just was never in the phrase list being matched against.
    """
    if companies:
        return [" ".join(str(c).lower().split()[:2]) or str(c).lower()
                for c in companies if str(c).strip()]
    import os
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "watchlist.txt")
    phrases: list[str] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    words = line.lower().split()
                    phrases.append(" ".join(words[:2]) if len(words) >= 2 else words[0])
    except Exception:
        pass
    return phrases


# Word-boundary credit keywords for exchange feeds (no generic 'resolution'/'credit'
# substrings — those match routine board/shareholder resolutions).
_EXCHANGE_CREDIT_RE = re.compile(
    r"\b(rating|rated|downgrad\w*|upgrad\w*|default\w*|npa|debenture[s]?|ncd[s]?|"
    r"bond[s]?|commercial paper|borrowing[s]?|fund[- ]?rais\w*|repayment|restructur\w*|"
    r"insolvency|liquidation|moratorium|write[- ]?off|provisioning|stressed|pledge[d]?|"
    r"one[- ]?time settlement|debt)\b",
    re.IGNORECASE,
)

# Routine corporate housekeeping — never credit-relevant.
_EXCHANGE_JUNK_RE = re.compile(
    r"trading window|book closure|record date|investor (meet|presentation|call)|"
    r"analyst meet|newspaper (publication|advertisement)|dividend.{0,40}(tax|tds)|"
    r"tds on dividend|esop|employee stock|allotment of equity shares|postal ballot|"
    r"\bagm\b|\begm\b|annual general meeting|extraordinary general meeting|"
    r"share transfer|\biepf\b|loss of share certificate|duplicate share|"
    r"regulation (39|40|74)|scrutinizer|cessation of|change in senior management|"
    r"company secretary|compliance certificate|shareholder intimation",
    re.IGNORECASE,
)
_EXCHANGE_JUNK_OVERRIDE_RE = re.compile(
    r"auditor|chief financial|cfo|managing director|statutory", re.IGNORECASE
)


def _entry_recent(entry, hours: int = 48) -> bool:
    pub = entry.get("published_parsed") or entry.get("updated_parsed")
    if not pub:
        return True
    import calendar
    return (time.time() - calendar.timegm(pub)) <= hours * 3600


def _exchange_keep(combined: str, watch_phrases: list[str],
                   watchlist_only: bool = False) -> tuple[bool, bool]:
    """Returns (keep, is_watchlist) for an exchange RSS item.

    watchlist_only=True (company announcement feeds): only watchlist companies
    pass, and even those are junk-filtered. False (exchange circulars/notices):
    credit-relevant items pass regardless of company."""
    is_watch = any(p in combined for p in watch_phrases)
    if _EXCHANGE_JUNK_RE.search(combined):
        if is_watch and _EXCHANGE_JUNK_OVERRIDE_RE.search(combined):
            return True, is_watch  # watchlist auditor/CFO/MD events = governance signals
        return False, is_watch
    if watchlist_only:
        return is_watch, is_watch
    is_credit = bool(_EXCHANGE_CREDIT_RE.search(combined))
    return (is_watch or is_credit), is_watch


def fetch_nse_rss(companies=None) -> list[str]:
    """NSE corporate announcements / circulars / filings via nsearchives RSS.

    All watchlist_only=True (S1-only) except Circular, same reasoning as
    the BSE feeds: these cover every NSE-listed company (thousands), not
    just the ~370 tracked ones, so a non-watchlist item is not this desk's
    S1/S2/S3 news whatever the filing type."""
    feeds = [
        ("https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml", "NSE Announcement"),
        ("https://nsearchives.nseindia.com/content/RSS/Circulars.xml", "NSE Circular"),
        ("https://nsearchives.nseindia.com/content/RSS/Financial_Results.xml", "NSE Results"),
        ("https://nsearchives.nseindia.com/content/RSS/Corporate_action.xml", "NSE Corporate Action"),
        ("https://nsearchives.nseindia.com/content/RSS/Board_Meetings.xml", "NSE Board Meeting"),
        ("https://nsearchives.nseindia.com/content/RSS/Corporate_Governance.xml", "NSE Corporate Governance"),
        ("https://nsearchives.nseindia.com/content/RSS/Related_Party_Trans.xml", "NSE Related Party Transactions"),
        # Pledge/encumbrance on promoter shares -- directly the kind of
        # signal _EVENTS' DEFAULT/RATING categories care about.
        ("https://nsearchives.nseindia.com/content/RSS/Sast_ReasonForEncumbrance.xml", "NSE Share Encumbrance"),
        ("https://nsearchives.nseindia.com/content/RSS/Shareholding_Pattern.xml", "NSE Shareholding Pattern"),
        ("https://nsearchives.nseindia.com/content/RSS/Share_Transfers.xml", "NSE Share Transfers"),
        ("https://nsearchives.nseindia.com/content/RSS/Voting_Results.xml", "NSE Voting Result"),
        ("https://nsearchives.nseindia.com/content/RSS/Secretarial_Compliance.xml", "NSE Secretarial Compliance"),
        ("https://nsearchives.nseindia.com/content/RSS/Investor_Complaints.xml", "NSE Investor Complaints"),
        ("https://nsearchives.nseindia.com/content/RSS/Annual_Reports.xml", "NSE Annual Report"),
    ]
    watch = _load_watchlist_phrases(companies)
    items: list[str] = []
    for url, tag in feeds:
        try:
            feed = feedparser.parse(url, agent=_HEADERS["User-Agent"])
            # Exchange-wide feed covering thousands of companies -- scan
            # deeper than the plain recency-only Circular feed so a rare
            # watchlist match isn't missed purely by fetch-moment timing.
            scan_cap = 60 if tag == "NSE Circular" else 400
            count = 0
            for entry in feed.entries[:scan_cap]:
                if not _entry_recent(entry, 48):
                    continue
                title = _clean(entry.get("title", "")).strip()
                desc = _clean(entry.get("summary", entry.get("description", ""))).strip()
                if not title:
                    continue
                combined = (title + " " + desc).lower()
                if tag == "NSE Circular":
                    keep, is_watch = _exchange_keep(combined, watch)
                    if not keep:
                        keep = bool(re.search(r"\b(debt|listing)\b", combined))
                else:
                    keep, is_watch = _exchange_keep(combined, watch, watchlist_only=True)
                if not keep:
                    continue
                link = entry.get("link", "")
                prefix = "[WATCHLIST-NSE]" if is_watch else "[T1]"
                items.append(f"{prefix}{tag}: {title} — {desc[:150]} | URL:{link}")
                count += 1
                if count >= 10:
                    break
            print(f"[fetch_web] NSE RSS {tag}: {count} items")
        except Exception as exc:
            print(f"[fetch_web] NSE RSS error ({url}): {exc}")
    # Raised from 20 now that there are 13 feeds (was 3) -- the old cap
    # could silently starve the later feeds if the first couple filled it.
    return items[:80]


def fetch_bse_rss(companies=None) -> list[str]:
    """BSE notices and corporate announcements via RSS.

    A company's own filing is the highest-signal S1 item available, and this
    source was contributing almost nothing: "BSE Announcement" returned 0 on
    every run while "BSE Notice" returned a handful. Two causes, both fixed:

    - the request went through feedparser directly, which sends a bare
      urllib User-Agent and gets 403'd by BSE. _feed_entries() reuses the
      shared browser-headed session, which is what the working feeds in
      this file already do.
    - a single hardcoded URL per feed. BSE publishes its feed list at
      bseindia.com/rss-feed.html and moves paths between www and beta, so
      each feed now has CANDIDATES tried in order — a dead path falls
      through instead of silently zeroing the source.

    Items also carry PUB dates now. Without one they were exempt from the
    recency filter and printed DATE UNCONFIRMED.
    """
    feeds = [
        ("BSE Announcement", True, [
            "https://beta.bseindia.com/data/xml/announcements.xml",
            "https://www.bseindia.com/data/xml/corpannouncement.xml",
            "https://www.bseindia.com/data/xml/announcements.xml",
            "https://beta.bseindia.com/data/xml/corpannouncement.xml",
            "https://www.bseindia.com/corporates/ann.xml",
        ]),
        ("BSE Notice", False, [
            "https://beta.bseindia.com/data/xml/notices.xml",
            "https://www.bseindia.com/data/xml/notices.xml",
        ]),
        ("BSE Board Meeting", True, [
            "https://www.bseindia.com/data/xml/boardmeeting.xml",
            "https://beta.bseindia.com/data/xml/boardmeeting.xml",
        ]),
        # S1-only: corporate actions (NCD/bond redemptions, rights issues,
        # buybacks) and financial results are both directly credit-relevant,
        # but only for a watchlist company -- a non-watchlist company's
        # quarterly result is not this desk's S1/S2/S3 news, so both are
        # forced watchlist_only regardless of what _exchange_keep would
        # otherwise pass for a non-watchlist item.
        ("BSE Corporate Action", True, [
            "https://beta.bseindia.com/data/XML/CorpActionFeed.xml",
        ]),
        ("BSE Financial Results", True, [
            "https://beta.bseindia.com/Data/XML/FinancialResultsFeed.xml",
        ]),
        # Governance/promoter-holding signals -- both S1-only, same reasoning
        # as Corporate Action/Financial Results above.
        ("BSE Insider Trading", True, [
            "https://beta.bseindia.com/Data/XML/InsiderTradingFeed.xml",
        ]),
        ("BSE Shareholding Pattern", True, [
            "https://beta.bseindia.com/Data/XML/ShareholdingPattern_Feed.xml",
        ]),
        ("BSE Voting Result", True, [
            "https://beta.bseindia.com/data/XML/VotingResultFeed.xml",
        ]),
        ("BSE Annual Report", True, [
            "https://beta.bseindia.com/Data/XML/AnnualReportFeed.xml",
        ]),
    ]
    watch = _load_watchlist_phrases(companies)
    items: list[str] = []
    for tag, watchlist_only, urls in feeds:
        entries, used = [], ""
        for u in urls:
            entries = _feed_entries(u)
            if entries:
                used = u
                break
        if not entries:
            print(f"[fetch_web] BSE RSS {tag}: no data (tried {len(urls)} url(s))")
            continue

        # These feeds cover EVERY BSE-listed company (thousands), not just
        # the ~370 on the watchlist -- 80 most-recent entries could easily
        # contain zero watchlist matches purely on timing. Scanning further
        # back raises the odds of catching one without touching the output
        # cap (still 12/feed) or the recency filter below.
        scan_cap = 400 if watchlist_only else 80
        count = 0
        for entry in entries[:scan_cap]:
            pub_str, recent = _entry_pub(entry)
            if not recent:
                continue
            title = _clean(entry.get("title", "")).strip()
            desc = _clean(entry.get("summary", entry.get("description", ""))).strip()
            if not title:
                continue
            combined = (title + " " + desc).lower()
            keep, is_watch = _exchange_keep(combined, watch, watchlist_only=watchlist_only)
            if not keep:
                continue
            link = entry.get("link", "")
            date_part = f" | PUB:{pub_str}" if pub_str else ""
            prefix = "[WATCHLIST-BSE]" if is_watch else "[T1]"
            items.append(f"{prefix}{tag}: {title} — {desc[:150]}{date_part} | URL:{link}")
            count += 1
            if count >= 12:
                break
        print(f"[fetch_web] BSE RSS {tag}: {count} items (from {used})")
    # Raised from 30 now that there are 9 feeds (was 3) -- the old cap could
    # silently starve the later feeds (Insider Trading, Shareholding
    # Pattern, etc) if the first couple already filled it.
    return items[:80]


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
            _pub_str, _pub_recent = _entry_pub(entry)
            if not _pub_recent:
                continue
            date_part = f" | PUB:{_pub_str}" if _pub_str else ""
            items.append(f"[RATING — {tag}] {source}: {title} — {summary[:200]}{date_part}{link_part}")
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
            if len(items) >= 15:
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
                if len(items) >= 15:
                    break

    except Exception as exc:
        print(f"[fetch_web] Custom URL scrape error for {url}: {exc}")

    return items


# ---------------------------------------------------------------------------
# EXTRA RSS FEEDS — regulators, financial press, sector trade press
#
# Why RSS and not the HTML scraper: the custom-URL scraper depends on a site's
# markup, so business-standard.com and financialexpress.com have been failing
# on every run ("Could not fetch") and contributing nothing. RSS is stable,
# survives bot protection, and carries a publication date — which also lets
# the 48h recency filter work on press items for the first time.
#
# Each source lists CANDIDATE urls tried in order. Feeds move and get retired,
# so a dead url falls through to the next instead of killing the source. Every
# feed logs its own item count; the Saturday quality report lists any source
# returning 0 so nothing rots silently.
# ---------------------------------------------------------------------------

def _gnews_site_feed(query: str) -> str:
    """A Google News RSS search scoped to a site (or topic) — used as the
    LAST candidate for every source below. This isn't a guess: Google News
    RSS is the one path already proven reliable in this codebase (link
    resolution hit 40/40 in the 2026-08-04 run), so a source whose own feed
    URL is wrong, moved, or bot-blocked still gets real coverage instead of
    silently contributing nothing."""
    return (f"https://news.google.com/rss/search?q={requests.utils.quote(query + ' when:2d')}"
            f"&hl=en-IN&gl=IN&ceid=IN:en")


_EXTRA_RSS_FEEDS = [
    # (label, tier, cap, [candidate urls])
    # ── Tier 1: regulators, tribunals, official statistics ──────────────
    # None of these bodies confirms a public RSS feed, and the 2026-08-04
    # run showed IBBI/IRDAI/MOSPI/NCLT/CCI all returning nothing from every
    # direct-URL guess. Go straight to the proven Google News path instead
    # of stacking more unverifiable .gov.in guesses.
    ("IBBI", "T1", 8, [_gnews_site_feed("site:ibbi.gov.in OR insolvency IBBI CIRP order India")]),
    ("NHB", "T1", 6, [
        "https://nhb.org.in/rss.xml",
        "https://nhb.org.in/feed/",
        _gnews_site_feed("National Housing Bank NHB India notification"),
    ]),
    ("IRDAI", "T1", 6, [_gnews_site_feed("IRDAI insurance regulator India circular OR notification")]),
    ("MOSPI", "T1", 6, [_gnews_site_feed("MOSPI India GDP CPI IIP data release")]),
    ("PIB", "T1", 10, [
        "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3",
        "https://www.pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3",
        "https://pib.gov.in/rss/lreleng.xml",
        _gnews_site_feed("PIB Ministry of Finance India press release"),
    ]),
    ("NCLT", "T1", 6, [_gnews_site_feed("NCLT India tribunal order insolvency company")]),
    # Labelled with a suffix so the S3 source rule cannot also swallow CCIL,
    # which is a bond-market (S4) source. cci.gov.in's own TLS cert failed
    # verification in testing (not a wrong URL, an SSL_CERTIFICATE issue on
    # their end) -- weakening TLS verification to work around that is not an
    # acceptable trade, so this source is Google-News-only.
    ("CCI-India", "T1", 5, [_gnews_site_feed("Competition Commission of India CCI order merger approval")]),

    # ── Tier 2: financial press ─────────────────────────────────────────
    # Every direct RSS guess for these returned nothing in testing -- could
    # be a wrong path or bot-blocking (Cloudflare etc). One more plausible
    # direct guess each, then the Google News fallback so the source is
    # never truly at zero.
    ("Business Standard", "T2", 12, [
        "https://www.business-standard.com/rss/finance-103.rss",
        "https://www.business-standard.com/rss/latest.rss",
        "https://www.business-standard.com/rss/economy-policy-102.rss",
        _gnews_site_feed("site:business-standard.com banking finance NBFC"),
    ]),
    ("Business Standard Markets", "T2", 8, [
        "https://www.business-standard.com/rss/markets-106.rss",
        _gnews_site_feed("site:business-standard.com markets bonds"),
    ]),
    ("Financial Express", "T2", 10, [
        "https://www.financialexpress.com/business/banking-finance/feed/",
        "https://www.financialexpress.com/feed/",
        _gnews_site_feed("site:financialexpress.com banking finance NBFC"),
    ]),
    ("Economic Times Banking", "T2", 12, [
        "https://economictimes.indiatimes.com/industry/banking/finance/rssfeeds/13358259.cms",
        "https://economictimes.indiatimes.com/industry/banking/finance/banking/rssfeeds/13358319.cms",
    ]),
    ("Economic Times Bonds", "T2", 8, [
        "https://economictimes.indiatimes.com/markets/bonds/rssfeeds/2146843.cms",
    ]),
    ("Livemint Money", "T2", 10, [
        "https://www.livemint.com/rss/money",
        "https://www.livemint.com/rss/markets",
        "https://www.livemint.com/static/rss/money.xml",
        _gnews_site_feed("site:livemint.com banking finance NBFC"),
    ]),
    ("Livemint Companies", "T2", 8, [
        "https://www.livemint.com/rss/companies",
        _gnews_site_feed("site:livemint.com companies results"),
    ]),
    ("Moneycontrol", "T2", 10, [
        "https://www.moneycontrol.com/rss/business.xml",
        "https://www.moneycontrol.com/rss/latestnews.xml",
        "https://www.moneycontrol.com/rss/economy.xml",
        _gnews_site_feed("site:moneycontrol.com banking finance NBFC"),
    ]),
    ("Hindu BusinessLine", "T2", 10, [
        "https://www.thehindubusinessline.com/money-and-banking/feeder/default.rss",
        "https://www.thehindubusinessline.com/feeder/default.rss",
    ]),
    ("Business Today", "T2", 8, [
        "https://www.businesstoday.in/rssfeeds/?id=225",
        "https://www.businesstoday.in/rssfeeds/?id=home",
        _gnews_site_feed("site:businesstoday.in banking finance NBFC"),
    ]),
    ("NDTV Profit", "T2", 8, [
        "https://feeds.feedburner.com/ndtvprofit-latest",
        "https://www.ndtvprofit.com/feed",
    ]),
    ("CNBC-TV18", "T2", 8, [
        "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/business.xml",
        "https://www.cnbctv18.com/rss/business.xml",
        _gnews_site_feed("site:cnbctv18.com banking finance NBFC"),
    ]),

    # ── Tier 4: fintech / NBFC funding trade press ──────────────────────
    # A funding round IS a liquidity event for an unlisted NBFC, and these
    # outlets break those before the mainstream press picks them up. Plain
    # /feed/ (WordPress default) returned nothing for all three in testing,
    # which reads as bot-blocking rather than a wrong URL -- Google News
    # fallback added rather than guessing more WordPress paths.
    ("Entrackr", "T2", 6, [
        "https://entrackr.com/feed/",
        _gnews_site_feed("site:entrackr.com NBFC fintech funding"),
    ]),
    ("Inc42", "T2", 6, [
        "https://inc42.com/feed/",
        _gnews_site_feed("site:inc42.com NBFC fintech funding round"),
    ]),
    # Indian debt-market trade publication, requested as a source. Added as
    # RSS rather than to config.json's custom_scrape_urls: the generic HTML
    # scraper depends on a site's markup (which is why business-standard
    # and financialexpress fail on every run) and, more importantly, emits
    # NO publication date — undated items are exempt from the recency
    # filter, which is exactly how July stories were surviving in the
    # Weekend Edition. RSS carries a date and survives bot-blocking.
    #
    # Both direct URLs are unverified: debtcircle.in is unreachable from
    # the build sandbox, so these are the two standard WordPress paths. If
    # both are wrong the Google News fallback still returns the site's
    # content, which is the whole point of the candidate-list design.
    ("DebtCircle", "T2", 8, [
        "https://debtcircle.in/feed/",
        "https://debtcircle.in/rss/",
        _gnews_site_feed("site:debtcircle.in bond NCD debt market India"),
    ]),
    # Previously only reached via the generic HTML scraper (fetch_custom_url):
    # capped at 15 headlines/day, one fetch/day, no publish date so it never
    # got the 48h recency check the RSS sources below get. Both feed URLs
    # were supplied directly by the user (the second is confirmed the live
    # "recent stories" feed); the Google News fallback stays behind them as
    # a safety net, same pattern as every other entry in this list.
    ("ET BFSI", "T2", 10, [
        "https://bfsi.economictimes.indiatimes.com/rss/recentstories",
        "https://bfsi.economictimes.indiatimes.com/rss/articles",
        "https://bfsi.economictimes.indiatimes.com/rss",
        _gnews_site_feed("site:bfsi.economictimes.indiatimes.com"),
    ]),
    ("Medianama", "T2", 5, [
        "https://www.medianama.com/feed/",
        _gnews_site_feed("site:medianama.com fintech NBFC RBI"),
    ]),
]


def _feed_entries(url: str):
    """Fetch through the shared session (real browser headers) rather than
    letting feedparser do its own bare request, which gets 403'd."""
    try:
        r = _get(url)
        if not r:
            return []
        parsed = feedparser.parse(r.content)
        return parsed.entries or []
    except Exception:
        return []


# Recency window for feed entries, in hours. Set once per run by
# fetch_all_web() rather than threaded through a dozen fetchers. Defaults
# to 48h, which is what every caller used when this was hardcoded, so the
# 7:30 report is unaffected; the Monday Weekend Edition raises it to 96h
# so Friday's items are not filtered out of the one edition meant to
# cover the weekend.
_WINDOW_HOURS = 48


def _entry_pub(entry) -> tuple[str, bool]:
    """Return (formatted date, within the current recency window).
    Undated entries are kept — the caller cannot prove they are stale."""
    pub = entry.get("published_parsed") or entry.get("updated_parsed")
    if not pub:
        return "", True
    try:
        age = time.time() - time.mktime(pub)
        return time.strftime("%d %b", pub), age <= _WINDOW_HOURS * 3600
    except Exception:
        return "", True


def fetch_extra_rss() -> list[str]:
    items: list[str] = []
    dead: list[str] = []
    for label, tier, cap, urls in _EXTRA_RSS_FEEDS:
        entries = []
        for u in urls:
            entries = _feed_entries(u)
            if entries:
                break
        if not entries:
            dead.append(label)
            print(f"[fetch_web] RSS {label}: no data (tried {len(urls)} url(s))")
            continue

        kept = 0
        for e in entries:
            if kept >= cap:
                break
            title = _clean(e.get("title", "")).strip()
            if len(title) < 20:
                continue
            pub_str, recent = _entry_pub(e)
            if not recent:
                continue
            summary = _clean(e.get("summary", e.get("description", ""))).strip()
            link = e.get("link", "")
            date_part = f" | PUB:{pub_str}" if pub_str else ""
            link_part = f" | URL:{link}" if link else ""
            items.append(
                f"[{tier}]{label}: {title} — {summary[:180]}{date_part}{link_part}"
            )
            kept += 1
        print(f"[fetch_web] RSS {label}: {kept} items")
    if dead:
        print(f"[fetch_web] RSS feeds returning nothing: {', '.join(dead)}")
    print(f"[fetch_web] Extra RSS total: {len(items)} items")
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
                _pub_str, _pub_recent = _entry_pub(entry)
                if not _pub_recent:
                    continue
                date_part = f" | PUB:{_pub_str}" if _pub_str else ""
                items.append(f"[T1]NSE: {title}{date_part}{link_part}")
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
                    _pub_str, _pub_recent = _entry_pub(entry)
                    if not _pub_recent:
                        continue
                    date_part = f" | PUB:{_pub_str}" if _pub_str else ""
                    items.append(f"[{tier}]{tag}: {title}{date_part}{link_part}")
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
                    _pub_str, _pub_recent = _entry_pub(entry)
                    if not _pub_recent:
                        continue
                    date_part = f" | PUB:{_pub_str}" if _pub_str else ""
                    items.append(f"[S4]Bond Markets: {title}{date_part}{link_part}")
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
            _pub_str, _pub_recent = _entry_pub(entry)
            if not _pub_recent:
                continue
            date_part = f" | PUB:{_pub_str}" if _pub_str else ""
            items.append(f"[MCA] {title}{date_part}{link_part}")
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
                _pub_str, _pub_recent = _entry_pub(entry)
                if not _pub_recent:
                    continue
                date_part = f" | PUB:{_pub_str}" if _pub_str else ""
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
                    _pub_str, _pub_recent = _entry_pub(entry)
                    if not _pub_recent:
                        continue
                    date_part = f" | PUB:{_pub_str}" if _pub_str else ""
                    items.append(f"[T2]Macro-Release: {title}{date_part}{link_part}")
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
                _pub_str, _pub_recent = _entry_pub(entry)
                if not _pub_recent:
                    continue
                date_part = f" | PUB:{_pub_str}" if _pub_str else ""
                items.append(f"[T2]Macro-Release: {title}{date_part}{link_part}")
        except Exception as exc:
            print(f"[fetch_web] Macro general query error: {exc}")

    except Exception as exc:
        print(f"[fetch_web] Macro releases error: {exc}")

    return items


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────
def fetch_all_web(sources: dict | None = None, custom_urls: list[str] | None = None,
                  days_back: int = 2, companies=None) -> list[str]:
    """
    Fetch from all configured web sources + any custom URLs.
    sources dict maps source key → True/False (from config.json web_sources).
    custom_urls is the list from config.json custom_scrape_urls.

    companies: passed through to fetch_nse_rss/fetch_bse_rss so their
    watchlist_only feeds match against the CALLER's actual entity list
    (team.json's ~370 for 7:40) instead of always falling back to
    watchlist.txt's 41 -- see _load_watchlist_phrases.
    """
    if sources is None:
        sources = {}

    global _WINDOW_HOURS
    _WINDOW_HOURS = 24 * max(1, int(days_back or 2))

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
        print("[fetch_web] Fetching NSE RSS feeds...")
        all_items.extend(fetch_nse_rss(companies))

    if on("bse"):
        print("[fetch_web] Fetching BSE RSS feeds...")
        all_items.extend(fetch_bse_rss(companies))

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

    if on("extra_rss"):
        print("[fetch_web] Fetching extra RSS feeds (regulators, press, trade)...")
        all_items.extend(fetch_extra_rss())

    # Kept as a fallback: the scrapers still cover sites with no usable feed.
    if custom_urls:
        print(f"[fetch_web] Fetching {len(custom_urls)} custom URL(s)...")
        all_items.extend(fetch_custom_urls(custom_urls))

    print(f"[fetch_web] Total web items fetched: {len(all_items)}")
    return all_items
