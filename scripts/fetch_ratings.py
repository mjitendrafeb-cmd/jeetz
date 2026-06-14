#!/usr/bin/env python3
"""
fetch_ratings.py — Scrape recent rating actions from Indian rating agencies.
Returns list of strings tagged [RATING — AgencyName].
"""

import requests
from bs4 import BeautifulSoup


_HEADERS = {"User-Agent": "Mozilla/5.0"}


def _scrape_crisil() -> list[str]:
    try:
        url = "https://www.crisil.com/en/home/our-businesses/ratings/credit-ratings-news-and-views.html"
        r = requests.get(url, headers=_HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        items = []
        for a in soup.find_all("a", href=True):
            title = a.get_text(strip=True)
            if not title or len(title) < 10:
                continue
            href = a["href"]
            if not href.startswith("http"):
                href = "https://www.crisil.com" + href
            items.append(
                f"[RATING — CRISIL] Source: {title} — CRISIL rating action | URL:{href}"
            )
            if len(items) >= 5:
                break
        return items
    except Exception:
        return []


def _scrape_icra() -> list[str]:
    try:
        url = "https://www.icra.in/Ratting/ShowRatting"
        r = requests.get(url, headers=_HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        items = []
        for a in soup.find_all("a", href=True):
            title = a.get_text(strip=True)
            if not title or len(title) < 10:
                continue
            href = a["href"]
            if not href.startswith("http"):
                href = "https://www.icra.in" + href
            items.append(
                f"[RATING — ICRA] Source: {title} — ICRA rating action | URL:{href}"
            )
            if len(items) >= 5:
                break
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
            title = a.get_text(strip=True)
            if not title or len(title) < 10:
                continue
            href = a["href"]
            if not href.startswith("http"):
                href = "https://www.indiaratings.co.in" + href
            items.append(
                f"[RATING — India Ratings] Source: {title} — India Ratings action | URL:{href}"
            )
            if len(items) >= 5:
                break
        return items
    except Exception:
        return []


def _scrape_care_ratings() -> list[str]:
    try:
        url = "https://www.careratings.com/press-releases"
        r = requests.get(url, headers=_HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        items = []
        for a in soup.find_all("a", href=True):
            title = a.get_text(strip=True)
            if not title or len(title) < 10:
                continue
            href = a["href"]
            if not href.startswith("http"):
                href = "https://www.careratings.com" + href
            items.append(
                f"[RATING — CARE Ratings] Source: {title} — CARE Ratings action | URL:{href}"
            )
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
            title = a.get_text(strip=True)
            if not title or len(title) < 10:
                continue
            href = a["href"]
            if not href.startswith("http"):
                href = "https://www.careedgeratings.com" + href
            items.append(
                f"[RATING — CareEdge] Source: {title} — CareEdge rating action | URL:{href}"
            )
            if len(items) >= 5:
                break
        return items
    except Exception:
        return []


def fetch_rating_agency_news() -> list[str]:
    """Scrape recent rating actions from all Indian rating agencies."""
    items = []
    items.extend(_scrape_crisil())
    items.extend(_scrape_icra())
    items.extend(_scrape_india_ratings())
    items.extend(_scrape_care_ratings())
    items.extend(_scrape_careedge())
    return items
