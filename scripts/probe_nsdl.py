"""Probe #22: CP issuance monthly files on nsdl.com — list availability and
inspect columns of the latest file. Runs on GitHub Actions. Not used by reports.
"""

import json
import re
import signal

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://nsdl.com/resources/data/detailed-list-debt-instruments",
}

session = requests.Session()
session.headers.update(HEADERS)
signal.signal(signal.SIGALRM, lambda s, f: (_ for _ in ()).throw(TimeoutError()))


def get(url, params=None):
    signal.alarm(90)
    try:
        return session.get(url, params=params, timeout=(10, 60))
    finally:
        signal.alarm(0)


def main():
    base = "https://nsdl.com/web/api/view/resources-data-sub-page/listing/"
    for label, params in (("all", None), ("2026", {"year": "2026"}),
                         ("apr26", {"year": "2026", "month": "april"})):
        try:
            r = get(base + "issuance-data-cp-cd", params)
            print(f"\n=== issuance-data-cp-cd {label}: {r.status_code} len={len(r.text)}", flush=True)
            if r.status_code == 200:
                print(f"  JSON[:3000]: {json.dumps(r.json())[:3000]}", flush=True)
        except Exception as exc:
            print(f"  ERROR {exc}", flush=True)

    # the April 2026 CP file referenced in the page payload
    url = "https://nsdl.com/nsdl/2026-07/Commercial_Papers_Issuance_in_the_month_of_April_2026.html"
    try:
        r = get(url)
        print(f"\n=== CP file: {r.status_code} len={len(r.text)}", flush=True)
        html = r.text
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL | re.IGNORECASE)
        print(f"  rows: {len(rows)}", flush=True)
        for row in rows[:6]:
            cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip()
                     for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL | re.IGNORECASE)]
            print(f"  ROW: {cells}", flush=True)
        for row in rows[-3:]:
            cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip()
                     for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL | re.IGNORECASE)]
            print(f"  TAILROW: {cells}", flush=True)
    except Exception as exc:
        print(f"  CP file ERROR {exc}", flush=True)


if __name__ == "__main__":
    main()
