"""CRISIL Ratings — scrape the public ratings news & views listing page."""

from bs4 import BeautifulSoup

from . import base

URL = "https://www.crisilratings.com/en/home/our-businesses/ratings/credit-ratings-news-and-views.html"
BASE = "https://www.crisilratings.com"


def scrape(companies: list[dict]) -> list[dict]:
    try:
        html = base.fetch_html(URL)
    except Exception as exc:
        print(f"[crisil] fetch failed: {exc}")
        return []

    soup = BeautifulSoup(html, "html.parser")
    results = []
    for a in soup.find_all("a", href=True):
        text = base.clean(a.get_text())
        if len(text) < 20 or not base.is_rating_related(text):
            continue
        for company in companies:
            if base.matches_company(text, company):
                href = a["href"]
                if not href.startswith("http"):
                    href = BASE + href
                action = base.build_action("CRISIL", company, text, href)
                action["company_name"] = company["name"]
                results.append(action)
    return results
