"""Probe #15: does NSDL CBD carry Commercial Paper data?
- advancedSearch with compact-JSON dtoString (the app uses btoa(JSON.stringify))
- dropdown/categorymap keys for instrument types
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


def show(label, url, params=None, clip=2500):
    print(f"\n=== {label}", flush=True)
    try:
        r = get(url, params)
        print(f"  status={r.status_code} len={len(r.text)}", flush=True)
        try:
            print(f"  JSON[:{clip}]: {json.dumps(r.json())[:clip]}", flush=True)
        except Exception:
            print(f"  body[:300]: {r.text[:300]!r}", flush=True)
        return r
    except Exception as exc:
        print(f"  ERROR {exc}", flush=True)
        return None


def adv(label, payload, clip=4000):
    dto = base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    show(f"advancedSearch:{label}", f"{PREFIX}/public/bdsinfo/advancedSearch",
         {"dtoString": dto}, clip=clip)


BASE_PAYLOAD = {
    "businessSector": [], "couponRateFrom": "", "couponRateTo": "",
    "creditRatingAgencyID": None, "couponType": [], "couponBasis": None,
    "convertibilityA": [], "convertibilityB": [],
    "dateOfAllotmentFrom": None, "dateOfAllotmentTo": None,
    "dateOfMaturityFrom": None, "dateOfMaturityTo": None,
    "freqInterestPayment": [], "instrumentStatus": [], "isin": "",
    "issueCategory": [], "modeOfIssue": [], "nameOfIssuer": "",
    "searchCriteriaCount": "", "typeOfInstrument": [],
    "typeOfIssuerNature": [], "typeOfIssuerOwnership": []}


def main():
    # instrument-type vocabularies
    for key in ("typeOfInstrument", "instrumentType", "instrument_type", "TYPE_OF_INSTRUMENT"):
        show(f"dropdown:{key}", f"{PREFIX}/public/bdsinfo/dropdown", {"attrkey": key}, clip=1200)
        show(f"categorymap:{key}", f"{PREFIX}/public/bdsinfo/categorymap",
             {"attributekey": key}, clip=1200)

    # advancedSearch attempts
    adv("by-date", dict(BASE_PAYLOAD, dateOfAllotmentFrom="17-07-2026",
                        dateOfAllotmentTo="17-07-2026"))
    adv("by-date-iso", dict(BASE_PAYLOAD, dateOfAllotmentFrom="2026-07-17",
                            dateOfAllotmentTo="2026-07-17"))
    adv("cp-type", dict(BASE_PAYLOAD, typeOfInstrument=["Commercial Paper"],
                        dateOfAllotmentFrom="2026-07-01", dateOfAllotmentTo="2026-07-18"))
    adv("isin-only", dict(BASE_PAYLOAD, isin="INE756I07FT8"))


if __name__ == "__main__":
    main()
