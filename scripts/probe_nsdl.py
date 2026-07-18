"""Probe #14: hunt for credit rating grades — advancedSearch dtoString,
rating-action list date formats, isindisplay retry.
Runs on the GitHub Actions runner. Not used by reports.
"""

import base64
import json
import signal

import requests

BASE = "https://www.indiabondinfo.nsdl.com"
PREFIX = BASE + "/bds-service/v1"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": BASE + "/CBDServices/",
}

session = requests.Session()
session.headers.update(HEADERS)
signal.signal(signal.SIGALRM, lambda s, f: (_ for _ in ()).throw(TimeoutError()))


def get(url, params=None):
    signal.alarm(50)
    try:
        return session.get(url, params=params, timeout=(10, 25))
    finally:
        signal.alarm(0)


def show(label, url, params=None, clip=3000):
    print(f"\n=== {label}: {url} {params or ''}", flush=True)
    try:
        r = get(url, params)
        print(f"  status={r.status_code} len={len(r.text)}", flush=True)
        if r.status_code == 200:
            try:
                print(f"  JSON[:{clip}]: {json.dumps(r.json())[:clip]}", flush=True)
            except Exception:
                print(f"  body[:400]: {r.text[:400]!r}", flush=True)
        else:
            print(f"  body[:300]: {r.text[:300]!r}", flush=True)
    except Exception as exc:
        print(f"  ERROR {exc}", flush=True)


def main():
    isin = "INE756I07FT8"  # HDB (rated instrument)

    # 1. advancedSearch: bundle builds GET {bdsService}/advancedSearch?dtoString=<b64 payload>
    payload = {
        "businessSector": [], "couponRateFrom": "", "couponRateTo": "",
        "creditRatingAgencyID": None, "couponType": [], "couponBasis": None,
        "convertibilityA": [], "convertibilityB": [],
        "dateOfAllotmentFrom": "17-07-2026", "dateOfAllotmentTo": "17-07-2026",
        "dateOfMaturityFrom": None, "dateOfMaturityTo": None,
        "freqInterestPayment": [], "instrumentStatus": [], "isin": "",
        "issueCategory": [], "modeOfIssue": [], "nameOfIssuer": "",
        "searchCriteriaCount": "", "typeOfInstrument": [],
        "typeOfIssuerNature": [], "typeOfIssuerOwnership": []}
    dto = base64.b64encode(json.dumps(payload).encode()).decode()
    show("advancedSearch-by-date", f"{PREFIX}/public/bdsinfo/advancedSearch", {"dtoString": dto}, clip=5000)

    payload2 = dict(payload, dateOfAllotmentFrom=None, dateOfAllotmentTo=None, isin=isin)
    dto2 = base64.b64encode(json.dumps(payload2).encode()).decode()
    show("advancedSearch-by-isin", f"{PREFIX}/public/bdsinfo/advancedSearch", {"dtoString": dto2}, clip=5000)

    # 2. rating actions list: try several date formats
    for d in ("17-07-2026", "2026-07-17", "17/07/2026", "17-Jul-2026"):
        show(f"ratingactions:{d}", f"{PREFIX}/public/bdsinfo/getallratingactioncralst", {"date": d}, clip=2000)

    # 3. isindisplay retry
    show("isindisplay", f"{PREFIX}/public/bdsinfo/isindisplay", {"isin": isin}, clip=2500)

    # 4. dropdown for credit rating agencies / categorymap — may reveal rating attr keys
    show("dropdown-cra", f"{PREFIX}/public/bdsinfo/dropdown", {"attrkey": "creditRatingAgency"})
    show("categorymap-rating", f"{PREFIX}/public/bdsinfo/categorymap", {"attributekey": "creditRating"})


if __name__ == "__main__":
    main()
