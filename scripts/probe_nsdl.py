"""One-off probe of NSDL India Bond Info to map the new-issuance data pages.

Runs on the GitHub Actions runner (this repo's sandbox cannot reach NSDL).
Prints page titles, links, forms and API-looking URLs so the real fetcher
can be written against the actual site structure. Not used by the report.
"""

import re
import sys

import requests
from bs4 import BeautifulSoup

BASE = "https://www.indiabondinfo.nsdl.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

session = requests.Session()
session.headers.update(HEADERS)


def show(url: str, label: str, dump_chars: int = 0, follow_keywords=None):
    print(f"\n{'=' * 70}\nPROBE [{label}] {url}")
    try:
        r = session.get(url, timeout=30, allow_redirects=True)
    except Exception as exc:
        print(f"  ERROR: {exc}")
        return None
    ctype = r.headers.get("content-type", "?")
    print(f"  status={r.status_code} final_url={r.url} type={ctype} len={len(r.text)}")
    if r.status_code != 200:
        print(f"  body[:500]: {r.text[:500]!r}")
        return None
    if "html" not in ctype and "text" not in ctype:
        print(f"  non-HTML body[:500]: {r.text[:500]!r}")
        return r
    soup = BeautifulSoup(r.text, "html.parser")
    if soup.title:
        print(f"  title: {soup.title.get_text(strip=True)}")
    links = []
    for a in soup.find_all("a", href=True):
        text = " ".join(a.get_text(" ", strip=True).split())[:80]
        links.append((a["href"][:200], text))
    print(f"  {len(links)} links:")
    for href, text in links[:120]:
        print(f"    {href}  |  {text}")
    for form in soup.find_all("form"):
        inputs = [
            f"{i.get('name')}={i.get('value', '')!r}"
            for i in form.find_all(["input", "select"])
            if i.get("name")
        ]
        print(f"  FORM action={form.get('action')} method={form.get('method')} inputs={inputs}")
    for s in soup.find_all("script", src=True):
        print(f"  SCRIPT src={s['src']}")
    tables = soup.find_all("table")
    print(f"  {len(tables)} tables")
    for t in tables[:3]:
        rows = t.find_all("tr")
        for row in rows[:4]:
            cells = [" ".join(c.get_text(" ", strip=True).split())[:40] for c in row.find_all(["th", "td"])]
            print(f"    ROW: {cells}")
    if dump_chars:
        body = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
        print(f"  TEXT[:{dump_chars}]: {body[:dump_chars]}")
    return r


def main():
    show(BASE + "/", "home", dump_chars=1500)
    show(BASE + "/bds-web/", "bds-root", dump_chars=1000)
    r = show(BASE + "/bds-web/dataReportsMenu.do", "data-tab", dump_chars=2000)
    # Follow anything issuance-flavoured found on the Data tab
    if r is not None:
        soup = BeautifulSoup(r.text, "html.parser")
        seen = set()
        for a in soup.find_all("a", href=True):
            href, text = a["href"], a.get_text(" ", strip=True).lower()
            blob = (href + " " + text).lower()
            if any(k in blob for k in ("issu", "primary", "activat", "alloc", "report", "data")):
                if href.startswith("javascript") or href in seen:
                    continue
                seen.add(href)
                full = href if href.startswith("http") else BASE + "/bds-web/" + href.lstrip("/")
                show(full, f"follow:{text[:30]}", dump_chars=1200)
                if len(seen) >= 12:
                    break
    # Common guesses for the new-issuance report endpoint
    for guess in (
        "/bds-web/issuanceDataReport.do",
        "/bds-web/newIssueReport.do",
        "/bds-web/dataReportsMenu.do?action=newIssues",
        "/bds-web/primaryMarketData.do",
    ):
        show(BASE + guess, f"guess:{guess}")


if __name__ == "__main__":
    sys.exit(main())
