"""Probe #11 (final): read /portal-config/portal-cbd.json, then dump samples
from newbondissues / currentissuance / issuancedashboard.
Runs on the GitHub Actions runner. Not used by reports.
"""

import json
import signal
import sys

import requests

BASE = "https://www.indiabondinfo.nsdl.com"

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


def get(url, **kw):
    signal.alarm(60)
    try:
        return session.get(url, timeout=(10, 30), **kw)
    finally:
        signal.alarm(0)


def main():
    r = get(BASE + "/portal-config/portal-cbd.json")
    print(f"portal-cbd.json status={r.status_code} len={len(r.text)}", flush=True)
    print(r.text[:2000], flush=True)
    cfg = r.json()
    prefix = cfg.get("cbdApiPrefixURL", "")
    print(f"\ncbdApiPrefixURL={prefix!r}", flush=True)
    if prefix.startswith("/"):
        prefix = BASE + prefix

    for path in ("/public/bdsinfo/newbondissues",
                 "/public/bdsinfo/currentissuance",
                 "/public/bdsinfo/issuancedashboard"):
        url = prefix.rstrip("/") + path
        print(f"\n=== {url}", flush=True)
        try:
            rr = get(url)
        except Exception as exc:
            print(f"  ERROR {exc}", flush=True)
            continue
        print(f"  status={rr.status_code} type={rr.headers.get('content-type')} len={len(rr.text)}", flush=True)
        try:
            data = rr.json()
            txt = json.dumps(data)
            print(f"  JSON[:8000]: {txt[:8000]}", flush=True)
            if isinstance(data, list) and data:
                print(f"  N={len(data)} FIRST KEYS: {list(data[0].keys())}", flush=True)
        except Exception:
            print(f"  body[:300]: {rr.text[:300]!r}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
