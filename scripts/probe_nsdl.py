"""Probe #5: dump the JS around the ISD search submit handler to learn the
exact querystring; try combined/company+date and 2025 searches.
Runs on the GitHub Actions runner. Not used by reports.
"""

import json
import re
import signal
import sys

import requests

API = "https://nsdl.com/web/api/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://nsdl.com/resources/data/issue-summary-document",
}

session = requests.Session()
session.headers.update(HEADERS)
signal.signal(signal.SIGALRM, lambda s, f: (_ for _ in ()).throw(TimeoutError()))


def get(url, params=None):
    signal.alarm(60)
    try:
        return session.get(url, params=params, timeout=(10, 30))
    finally:
        signal.alarm(0)


def api(label, path, params=None, clip=3500):
    print(f"\n=== {label}: {path} params={params}", flush=True)
    try:
        r = get(API + path, params)
    except Exception as exc:
        print(f"  ERROR {exc}", flush=True)
        return None
    print(f"  status={r.status_code} len={len(r.text)}", flush=True)
    try:
        data = r.json()
        print(f"  JSON[:{clip}]: {json.dumps(data)[:clip]}", flush=True)
        return data
    except Exception:
        print(f"  body[:400]: {r.text[:400]!r}", flush=True)
        return None


def main():
    # ---- JS context dump
    page = get("https://nsdl.com/resources/data/issue-summary-document")
    chunk = None
    for c in re.findall(r'src="(/_next/static/chunks/[^"]+)"', page.text):
        if "issue-summary-document" in c:
            chunk = c
            break
    print(f"chunk={chunk}", flush=True)
    if chunk:
        js = get("https://nsdl.com" + chunk).text
        for kw in ("search?", "URLSearchParams", "toISOString", "format(", "dayjs", "moment",
                   "Please Enter", "handleSearch", "onSubmit", "params"):
            for m in re.finditer(re.escape(kw), js):
                s = max(0, m.start() - 400)
                print(f"\nCTX[{kw}]:\n{js[s:m.end() + 800]}", flush=True)
                break  # first occurrence only

    # ---- API trials
    base = {"isin_code": "", "company_name": "", "issue_type": "", "stage_of_issue": "", "date_from": "", "date_to": ""}
    api("company+dates", "v1/issue-summary-details/search",
        dict(base, company_name="Finance", date_from="2026-01-01", date_to="2026-07-18"))
    api("2025-iso", "v1/issue-summary-details/search",
        dict(base, date_from="2025-01-01", date_to="2025-12-31"))
    api("2025-dmy", "v1/issue-summary-details/search",
        dict(base, date_from="01-01-2025", date_to="31-12-2025"))
    api("company-only-nodates", "v1/issue-summary-details/search",
        {"company_name": "Finance"})
    api("isin", "v1/issue-summary-details/search",
        dict(base, isin_code="INE"))


if __name__ == "__main__":
    sys.exit(main())
