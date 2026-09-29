"""ICRA — scrape the public rating-actions table."""

from bs4 import BeautifulSoup

from . import base

URL = "https://www.icra.in/RatingAction/Index"
BASE = "https://www.icra.in"


def scrape(companies: list[dict]) -> list[dict]:
    try:
        html = base.fetch_html(URL)
    except Exception as exc:
        print(f"[icra] fetch failed: {exc}")
        return []

    soup = BeautifulSoup(html, "html.parser")
    results = []

    rows = soup.find_all("tr")
    if len(rows) > 1:
        # Table layout: one row per rating action, columns typically include
        # company name, instrument/rating summary, and date.
        for row in rows[1:]:
            cols = row.find_all("td")
            if not cols:
                continue
            text = base.clean(" — ".join(c.get_text() for c in cols))
            for company in companies:
                if base.matches_company(text, company):
                    link = row.find("a", href=True)
                    href = link["href"] if link else URL
                    if not href.startswith("http"):
                        href = BASE + href
                    action = base.build_action("ICRA", company, text, href)
                    action["company_name"] = company["name"]
                    results.append(action)
    else:
        # Fallback: no table found (page may be JS-rendered) — scan links instead.
        for a in soup.find_all("a", href=True):
            text = base.clean(a.get_text())
            if len(text) < 20 or not base.is_rating_related(text):
                continue
            for company in companies:
                if base.matches_company(text, company):
                    href = a["href"]
                    if not href.startswith("http"):
                        href = BASE + href
                    action = base.build_action("ICRA", company, text, href)
                    action["company_name"] = company["name"]
                    results.append(action)

    return results
