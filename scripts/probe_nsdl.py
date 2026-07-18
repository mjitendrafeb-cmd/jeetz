"""Probe #16: find exchange endpoints for fresh Commercial Paper listings.
Scans BSE debt pages for api.bseindia.com endpoints and CP links; tries NSE
archive file patterns. Runs on the GitHub Actions runner. Not used by reports.
"""

import datetime
import re
import signal

import requests

H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.bseindia.com/",
}

session = requests.Session()
session.headers.update(H)
signal.signal(signal.SIGALRM, lambda s, f: (_ for _ in ()).throw(TimeoutError()))


def get(url, **kw):
    signal.alarm(45)
    try:
        return session.get(url, timeout=(10, 20), **kw)
    finally:
        signal.alarm(0)


def scan_page(url):
    print(f"\n=== {url}", flush=True)
    try:
        r = get(url)
    except Exception as exc:
        print(f"  ERROR {exc}", flush=True)
        return
    print(f"  status={r.status_code} len={len(r.text)}", flush=True)
    if r.status_code != 200:
        return
    html = r.text
    for m in sorted(set(re.findall(r"""["'](https?://api\.bseindia\.com/[^"']+)["']""", html))):
        print(f"  API: {m[:180]}", flush=True)
    for m in sorted(set(re.findall(r"""["']([A-Za-z0-9_/.-]*api/[A-Za-z0-9_/?=&{}.-]+)["']""", html)))[:25]:
        print(f"  RELAPI: {m[:160]}", flush=True)
    for href, text in re.findall(r'href="([^"]+)"[^>]*>([^<]{0,60})', html):
        blob = (href + " " + text).lower()
        if "cp" in blob.split("/")[-1][:20] or "commercial" in blob:
            print(f"  LINK: {href[:120]} | {text.strip()[:60]}", flush=True)


def main():
    for u in ("https://www.bseindia.com/markets/debt/debt_home.aspx",
              "https://www.bseindia.com/markets/debt/CPS.aspx",
              "https://www.bseindia.com/markets/debt/cparchives.aspx",
              "https://www.bseindia.com/markets/debt/NewDebtListing.aspx",
              "https://www.bseindia.com/markets/Debt/DebtNewListing.aspx"):
        scan_page(u)

    # BSE API blind guesses for CP/new debt listings
    for u in ("https://api.bseindia.com/BseIndiaAPI/api/DebtNewListing/w",
              "https://api.bseindia.com/BseIndiaAPI/api/CPArchives/w",
              "https://api.bseindia.com/BseIndiaAPI/api/DebtCPOTB/w"):
        print(f"\n=== GUESS {u}", flush=True)
        try:
            r = get(u)
            print(f"  status={r.status_code} body[:300]: {r.text[:300]!r}", flush=True)
        except Exception as exc:
            print(f"  ERROR {exc}", flush=True)

    # NSE archives static files (no cookies needed on nsearchives)
    d = datetime.date(2026, 7, 17)
    for pat in ("https://nsearchives.nseindia.com/content/debt/CP_{d2}.csv",
                "https://nsearchives.nseindia.com/content/debt/cp_{d2}.csv",
                "https://nsearchives.nseindia.com/content/debt/Debt_CP_{d2}.csv",
                "https://nsearchives.nseindia.com/content/debt/NewDebt_{d2}.csv"):
        u = pat.format(d2=d.strftime("%d%m%Y"))
        print(f"\n=== NSE {u}", flush=True)
        try:
            r = get(u, headers={"User-Agent": H["User-Agent"]})
            print(f"  status={r.status_code} body[:300]: {r.text[:300]!r}", flush=True)
        except Exception as exc:
            print(f"  ERROR {exc}", flush=True)


if __name__ == "__main__":
    main()
