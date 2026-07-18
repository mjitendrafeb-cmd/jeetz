"""Probe #6: learn ISD issue_type options, pagination and attribute payloads;
check indiabondinfo for the debt new-issuance report. Runs on GitHub Actions.
Not used by reports.
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
    signal.alarm(50)
    try:
        return session.get(url, params=params, timeout=(10, 25))
    finally:
        signal.alarm(0)


def api(label, path, params=None, clip=2500):
    print(f"\n=== {label}: params={params}", flush=True)
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
        print(f"  body[:300]: {r.text[:300]!r}", flush=True)
        return None


def main():
    # ---- dropdown options + pagination from the JS chunk
    page = get("https://nsdl.com/resources/data/issue-summary-document")
    chunk = next((c for c in re.findall(r'src="(/_next/static/chunks/[^"]+)"', page.text)
                  if "issue-summary-document" in c), None)
    if chunk:
        js = get("https://nsdl.com" + chunk).text
        for kw in ("issue_type\"", "Debt", "NCD", "Commercial", "option", "page=", "offset", "gL"):
            for i, m in enumerate(re.finditer(re.escape(kw), js)):
                s = max(0, m.start() - 300)
                print(f"\nCTX[{kw}#{i}]:\n{js[s:m.end() + 500]}", flush=True)
                if i >= 1:
                    break

    base = {"isin_code": "", "company_name": "", "issue_type": "", "stage_of_issue": "",
            "date_from": "01-01-2020", "date_to": "31-12-2030"}

    # match-all range; check pagination params
    api("all", "v1/issue-summary-details/search", base)
    api("all-page2", "v1/issue-summary-details/search", dict(base, page=2))
    api("all-limit", "v1/issue-summary-details/search", dict(base, limit=100))
    api("all-offset", "v1/issue-summary-details/search", dict(base, offset=10))

    # debt-flavoured issue types
    for t in ("Debt", "Debt IPO", "Debenture", "NCD", "Debt Private Placement", "Commercial Paper"):
        api(f"type:{t}", "v1/issue-summary-details/search", dict(base, issue_type=t), clip=1200)

    # attributes payload for one known record
    api("attrs-1226", "view/issue_summary_attributes/listing", {"issue_summary_details_id": 1226}, clip=5000)

    # ---- indiabondinfo: the tiny homepage + data reports page
    for u in ("https://www.indiabondinfo.nsdl.com/",
              "https://www.indiabondinfo.nsdl.com/bds-web/dataReportsMenu.do"):
        print(f"\n=== IBI {u}", flush=True)
        try:
            r = get(u)
            print(f"  status={r.status_code} len={len(r.text)}", flush=True)
            print(f"  body[:1500]: {r.text[:1500]!r}", flush=True)
        except Exception as exc:
            print(f"  ERROR {exc}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
