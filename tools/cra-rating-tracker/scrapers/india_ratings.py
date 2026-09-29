"""India Ratings & Research — scrape the public rating-actions listing page."""

from bs4 import BeautifulSoup

from . import base

URL = "https://www.indiaratings.co.in/rating-actions"
BASE = "https://www.indiaratings.co.in"


def scrape(companies: list[dict]) -> list[dict]:
    try:
        html = base.fetch_html(URL)
    except Exception as exc:
        print(f"[india_ratings] fetch failed: {exc}")
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
                action = base.build_action("India Ratings", company, text, href)
                action["company_name"] = company["name"]
                results.append(action)
    return results
