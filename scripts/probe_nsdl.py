"""Probe #8: extract the CBDServices API base URL and the new-bond-issues
endpoints from the Angular bundle, then call them and print sample JSON.
Runs on the GitHub Actions runner. Not used by reports.
"""

import json
import re
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


def show_json(label, url):
    print(f"\n=== {label}: {url}", flush=True)
    try:
        r = get(url)
    except Exception as exc:
        print(f"  ERROR {exc}", flush=True)
        return
    print(f"  status={r.status_code} type={r.headers.get('content-type')} len={len(r.text)}", flush=True)
    try:
        print(f"  JSON[:4000]: {json.dumps(r.json())[:4000]}", flush=True)
    except Exception:
        print(f"  body[:400]: {r.text[:400]!r}", flush=True)


def main():
    idx = get(BASE + "/CBDServices/").text
    script = re.search(r'src="(main-[^"]+\.js)"', idx).group(1)
    js = get(BASE + "/CBDServices/" + script).text
    print(f"bundle len={len(js)}", flush=True)

    for kw in ("getCbdApiUrl", "cbdApiUrl=", "cbdApiUrl:", "bdsService", "newbondissues",
               "getnewBondIssuesList", "environment", "apiBaseUrl", "baseUrl"):
        for i, m in enumerate(re.finditer(re.escape(kw), js)):
            s = max(0, m.start() - 250)
            print(f"\nCTX[{kw}#{i}]: {js[s:m.end() + 600]!r}"[:1100], flush=True)
            if i >= 2:
                break

    # Try likely bases with the discovered endpoint names
    for base in (BASE + "/CBDSAPIs/bdsService",
                 BASE + "/CBDServices/api/bdsService",
                 BASE + "/bdsService",
                 BASE + "/api/bdsService"):
        show_json("dash@" + base, base + "/issuancedashboard")


if __name__ == "__main__":
    sys.exit(main())
