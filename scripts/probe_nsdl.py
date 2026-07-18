"""Probe #3: exercise nsdl.com's Issue Summary Document API to learn the
response shape and accepted date formats. Runs on the GitHub Actions runner.
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
    "Accept-Language": "en-US,en;q=0.9",
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


def show(label, url, params=None):
    print(f"\n=== {label}: {url} params={params}", flush=True)
    try:
        r = get(url, params)
    except Exception as exc:
        print(f"  ERROR {exc}", flush=True)
        return None
    print(f"  status={r.status_code} type={r.headers.get('content-type')} len={len(r.text)}", flush=True)
    try:
        data = r.json()
    except Exception:
        print(f"  body[:600]: {r.text[:600]!r}", flush=True)
        return None
    txt = json.dumps(data)[:3000]
    print(f"  JSON[:3000]: {txt}", flush=True)
    return data


def main():
    today = datetime.date.today()
    week_ago = today - datetime.timedelta(days=7)

    # empty search — some APIs return everything / latest
    show("empty", API + "v1/issue-summary-details/search")

    found = None
    for fmt, label in (("%Y-%m-%d", "iso"), ("%d-%m-%Y", "dmy-dash"), ("%d/%m/%Y", "dmy-slash")):
        params = {
            "isin_code": "", "company_name": "", "issue_type": "",
            "stage_of_issue": "",
            "date_from": week_ago.strftime(fmt),
            "date_to": today.strftime(fmt),
        }
        data = show(f"search-{label}", API + "v1/issue-summary-details/search", params)
        if data and not found:
            found = data

    # pagination hints
    show("search-page", API + "v1/issue-summary-details/search", {
        "date_from": week_ago.strftime("%Y-%m-%d"),
        "date_to": today.strftime("%Y-%m-%d"),
        "page": 1, "limit": 50,
    })

    # attributes of the first record we can identify
    rec_id = None
    def find_id(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in ("id", "issue_summary_details_id") and isinstance(v, (int, str)):
                    return v
                r = find_id(v)
                if r is not None:
                    return r
        elif isinstance(obj, list):
            for it in obj:
                r = find_id(it)
                if r is not None:
                    return r
        return None

    if found:
        rec_id = find_id(found)
    if rec_id is not None:
        show("attributes", API + "view/issue_summary_attributes/listing",
             {"issue_summary_details_id": rec_id})
    else:
        print("\nNo record id found to fetch attributes for", flush=True)


if __name__ == "__main__":
    sys.exit(main())
