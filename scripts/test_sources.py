#!/usr/bin/env python3
"""
test_sources.py — Tests every configured news source and prints a report.
Run via: python scripts/test_sources.py
Or trigger via GitHub Actions → "Test News Sources" workflow.
"""

import time
import json
import os
import requests
import feedparser
from bs4 import BeautifulSoup
from datetime import date

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
}

results = []

def check(name, fn):
    try:
        result = fn()
        if result:
            results.append(("✅", name, result[:120]))
        else:
            results.append(("❌", name, "No data returned"))
    except Exception as e:
        results.append(("❌", name, f"Error — {str(e)[:100]}"))
    time.sleep(0.5)

def rss_first(url):
    feed = feedparser.parse(url)
    if feed.entries:
        e = feed.entries[0]
        return e.get("title", "").strip()[:120]
    return None

def scrape_first(url, selectors=None):
    r = requests.get(url, headers=HEADERS, timeout=15)
    if r.status_code != 200:
        raise Exception(f"HTTP {r.status_code}")
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["nav", "footer", "script", "style"]):
        tag.decompose()
    for sel in (selectors or ["h3 a", "h4 a", "h2 a", "article a", "td a", "li a"]):
        for a in soup.select(sel):
            t = a.get_text().strip()
            if len(t) > 25:
                return t[:120]
    return None

# ── 1. RSS Feeds ──────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("  SOURCE CONNECTIVITY TEST")
print(f"  Run date: {date.today()}")
print("="*60)

print("\n📡 RSS FEEDS")
check("RBI RSS",            lambda: rss_first("https://www.rbi.org.in/scripts/rss.aspx"))
check("SEBI RSS",           lambda: rss_first("https://www.sebi.gov.in/sebirss.xml"))
check("Google News — RBI",  lambda: rss_first("https://news.google.com/rss/search?q=RBI+India+banking+credit&hl=en-IN&gl=IN&ceid=IN:en"))
check("Google News — NBFC", lambda: rss_first("https://news.google.com/rss/search?q=NBFC+India+NPA+stress&hl=en-IN&gl=IN&ceid=IN:en"))
check("Google News — Bonds",lambda: rss_first("https://news.google.com/rss/search?q=India+bond+yield+G-sec&hl=en-IN&gl=IN&ceid=IN:en"))
check("Google News — HFC",  lambda: rss_first("https://news.google.com/rss/search?q=housing+finance+India+HFC+mortgage&hl=en-IN&gl=IN&ceid=IN:en"))
check("Google News — Ratings",lambda: rss_first("https://news.google.com/rss/search?q=credit+rating+India+CRISIL+ICRA+CareEdge&hl=en-IN&gl=IN&ceid=IN:en"))

# ── 2. NewsAPI ────────────────────────────────────────────────────────────────
print("\n📰 NEWSAPI")
newsapi_key = os.environ.get("NEWSAPI_KEY", "")
if not newsapi_key:
    results.append(("⚠️", "NewsAPI", "NEWSAPI_KEY secret not set — skipped"))
else:
    def _newsapi():
        r = requests.get(
            "https://newsapi.org/v2/everything",
            params={"q": "RBI OR NBFC India", "language": "en", "pageSize": 1},
            headers={"X-Api-Key": newsapi_key},
            timeout=15,
        )
        r.raise_for_status()
        arts = r.json().get("articles", [])
        return arts[0]["title"] if arts else None
    check("NewsAPI", _newsapi)

# ── 3. Web Scraper — Rating Agencies ─────────────────────────────────────────
print("\n🌐 WEB SCRAPER — RATING AGENCIES")

check("CareEdge RSS",      lambda: rss_first("https://www.careedge.in/feed"))
check("CareEdge HTML",     lambda: scrape_first("https://www.careedge.in/pressrelease"))
check("CRISIL",            lambda: scrape_first("https://www.crisil.com/en/home/our-businesses/ratings/credit-rating-news.html"))
check("ICRA",              lambda: scrape_first("https://www.icra.in/Rating/ShowRatingPressRelease"))
check("India Ratings",     lambda: scrape_first("https://www.indiaratings.co.in/pressrelease"))
check("FIMMDA",            lambda: scrape_first("https://www.fimmda.org/modules/circulars"))
check("CCIL",              lambda: scrape_first("https://www.ccilindia.com/MarketData/Pages/GSecMarket.aspx"))

def _bse_api():
    today = date.today()
    url = (
        f"https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w"
        f"?strCat=-1&strPrevDate=20250101&strScrip=&strSearch=P"
        f"&strToDate={today.strftime('%Y%m%d')}&strType=C&subcategory=-1"
    )
    h = {**HEADERS, "Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com"}
    r = requests.get(url, headers=h, timeout=15)
    if r.status_code != 200:
        raise Exception(f"HTTP {r.status_code}")
    rows = r.json().get("Table", [])
    return rows[0].get("HEADLINE", "") if rows else None

check("BSE Announcements API", _bse_api)

# ── 4. Google News Fallback (for blocked scrapers) ───────────────────────────
print("\n🔄 GOOGLE NEWS FALLBACK (rating agencies)")
check("CRISIL via Google News",        lambda: rss_first("https://news.google.com/rss/search?q=CRISIL+rating+upgrade+downgrade+India&hl=en-IN&gl=IN&ceid=IN:en"))
check("ICRA via Google News",          lambda: rss_first("https://news.google.com/rss/search?q=ICRA+rating+upgrade+downgrade+India&hl=en-IN&gl=IN&ceid=IN:en"))
check("India Ratings via Google News", lambda: rss_first("https://news.google.com/rss/search?q=India+Ratings+Fitch+rating+India&hl=en-IN&gl=IN&ceid=IN:en"))
check("CareEdge via Google News",      lambda: rss_first("https://news.google.com/rss/search?q=CareEdge+Ratings+rating+India&hl=en-IN&gl=IN&ceid=IN:en"))

# ── 5. Watchlist companies (sample 3) ────────────────────────────────────────
print("\n🏢 WATCHLIST COMPANY NEWS (sample)")
check("Shriram Credit",    lambda: rss_first('https://news.google.com/rss/search?q=%22Shriram+Credit%22+India+rating&hl=en-IN&gl=IN&ceid=IN:en'))
check("SMFG India Credit", lambda: rss_first('https://news.google.com/rss/search?q=%22SMFG+India+Credit%22+India&hl=en-IN&gl=IN&ceid=IN:en'))
check("Indostar Capital",  lambda: rss_first('https://news.google.com/rss/search?q=%22Indostar+Capital%22+India+rating&hl=en-IN&gl=IN&ceid=IN:en'))

# ── SUMMARY ──────────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("  SUMMARY")
print("="*60)
working = [r for r in results if r[0] == "✅"]
broken  = [r for r in results if r[0] == "❌"]
warn    = [r for r in results if r[0] == "⚠️"]

print(f"\n✅ WORKING ({len(working)}):")
for _, name, sample in working:
    print(f"   • {name}")
    print(f"     Sample: {sample}")

print(f"\n❌ NOT WORKING ({len(broken)}):")
for _, name, reason in broken:
    print(f"   • {name}: {reason}")

if warn:
    print(f"\n⚠️  WARNINGS ({len(warn)}):")
    for _, name, reason in warn:
        print(f"   • {name}: {reason}")

print(f"\n{'='*60}")
print(f"  {len(working)}/{len(results)} sources returning data")
print(f"{'='*60}\n")
