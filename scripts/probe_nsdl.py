"""Probe #4: find real Issue Summary Document records to learn field names,
date semantics and the attributes payload. Runs on the GitHub Actions runner.
Not used by reports.
"""

import datetime
import json
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


def show(label, path, params=None, clip=4000):
    print(f"\n=== {label}: {path} params={params}", flush=True)
    signal.alarm(60)
    try:
        r = session.get(API + path, params=params, timeout=(10, 30))
    except Exception as exc:
        print(f"  ERROR {exc}", flush=True)
        return None
    finally:
        signal.alarm(0)
    print(f"  status={r.status_code} len={len(r.text)}", flush=True)
    try:
        data = r.json()
    except Exception:
        print(f"  body[:500]: {r.text[:500]!r}", flush=True)
        return None
    print(f"  JSON[:{clip}]: {json.dumps(data)[:clip]}", flush=True)
    return data


def main():
    base = {"isin_code": "", "company_name": "", "issue_type": "", "stage_of_issue": "", "date_from": "", "date_to": ""}

    found = None
    for name in ("HDB Financial", "REC Limited", "Power Finance", "Bajaj Finance", "HDFC"):
        p = dict(base, company_name=name)
        data = show(f"name:{name}", "v1/issue-summary-details/search", p, clip=5000)
        if data and data.get("data"):
            found = data
            break

    # Broad date ranges to learn which format actually matches records
    today = datetime.date.today()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%m-%d-%Y"):
        p = dict(base, date_from=datetime.date(2026, 1, 1).strftime(fmt), date_to=today.strftime(fmt))
        d = show(f"range2026:{fmt}", "v1/issue-summary-details/search", p, clip=2500)
        if d and d.get("data") and not found:
            found = d

    if found:
        recs = found["data"]
        print(f"\nFIRST RECORD KEYS: {list(recs[0].keys()) if isinstance(recs[0], dict) else recs[0]}", flush=True)
        rid = None
        if isinstance(recs[0], dict):
            for k in ("id", "issue_summary_details_id", "isd_id"):
                if k in recs[0]:
                    rid = recs[0][k]
                    break
        if rid is not None:
            show("attributes", "view/issue_summary_attributes/listing",
                 {"issue_summary_details_id": rid}, clip=6000)


if __name__ == "__main__":
    sys.exit(main())
