#!/usr/bin/env python3
"""
fetch_ratings.py — Scrape recent rating actions from Indian credit rating agencies.
Returns items tagged [RATING — AgencyName].
"""

import re
import requests
from bs4 import BeautifulSoup

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "")
    return text.strip()


def _scrape_crisil() -> list[str]:
    try:
        url = "https://www.crisil.com/en/home/our-businesses/ratings/credit-ratings-news-and-views.html"
        r = requests.get(url, headers=_HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        items = []
        for a in soup.find_all("a", href=True):
            text = _clean(a.get_text())
            if len(text) < 30:
                continue
            href = a["href"]
            if not href.startswith("http"):
                href = "https://www.crisil.com" + href
            if any(kw in text.lower() for kw in ["rating", "upgrade", "downgrade", "watch", "outlook", "affirm"]):
                items.append(f"[T1]CRISIL: {text[:200]} | URL:{href}")
            if len(items) >= 5:
                break
        return items
    except Exception:
        return []


def _scrape_icra() -> list[str]:
    try:
        url = "https://www.icra.in/RatingAction/Index"
        r = requests.get(url, headers=_HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        items = []
        for row in soup.find_all("tr")[1:6]:
            cols = row.find_all("td")
            if len(cols) >= 2:
                text = _clean(cols[0].get_text() + " — " + cols[1].get_text())
                link = cols[0].find("a")
                href = link["href"] if link and link.get("href") else "https://www.icra.in"
                if not href.startswith("http"):
                    href = "https://www.icra.in" + href
                items.append(f"[T1]ICRA: {text[:200]} | URL:{href}")
        return items
    except Exception:
        return []


def _scrape_india_ratings() -> list[str]:
    try:
        url = "https://www.indiaratings.co.in/rating-actions"
        r = requests.get(url, headers=_HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        items = []
        for a in soup.find_all("a", href=True):
            text = _clean(a.get_text())
            if len(text) < 30:
                continue
            href = a["href"]
            if not href.startswith("http"):
                href = "https://www.indiaratings.co.in" + href
            if any(kw in text.lower() for kw in ["rating", "upgrade", "downgrade", "watch", "outlook", "affirm"]):
                items.append(f"[T1]India Ratings: {text[:200]} | URL:{href}")
            if len(items) >= 5:
                break
        return items
    except Exception:
        return []


def _scrape_care() -> list[str]:
    try:
        url = "https://www.careratings.com/press-releases"
        r = requests.get(url, headers=_HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        items = []
        for a in soup.find_all("a", href=True):
            text = _clean(a.get_text())
            if len(text) < 30:
                continue
            href = a["href"]
            if not href.startswith("http"):
                href = "https://www.careratings.com" + href
            if any(kw in text.lower() for kw in ["rating", "upgrade", "downgrade", "watch", "outlook", "affirm", "reaffirm"]):
                items.append(f"[T1]CARE Ratings: {text[:200]} | URL:{href}")
            if len(items) >= 5:
                break
        return items
    except Exception:
        return []


def _scrape_careedge() -> list[str]:
    try:
        url = "https://www.careedgeratings.com/press-releases"
        r = requests.get(url, headers=_HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        items = []
        for a in soup.find_all("a", href=True):
            text = _clean(a.get_text())
            if len(text) < 30:
                continue
            href = a["href"]
            if not href.startswith("http"):
                href = "https://www.careedgeratings.com" + href
            if any(kw in text.lower() for kw in ["rating", "upgrade", "downgrade", "watch", "outlook", "affirm", "reaffirm"]):
                items.append(f"[T1]CareEdge: {text[:200]} | URL:{href}")
            if len(items) >= 5:
                break
        return items
    except Exception:
        return []


def fetch_all_ratings() -> list[str]:
    items = []
    for fn in [_scrape_crisil, _scrape_icra, _scrape_india_ratings, _scrape_care, _scrape_careedge]:
        result = fn()
        items.extend(result)
        if result:
            print(f"[fetch_ratings] {fn.__name__}: {len(result)} items")
    return items
