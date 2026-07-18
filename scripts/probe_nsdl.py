"""Probe #13: enumerate every bdsService endpoint template in the CBDServices
bundle, then call the rating/coupon-flavoured ones for a current new-issue ISIN.
Runs on the GitHub Actions runner. Not used by reports.
"""

import json
import re
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


def main():
    idx = get(BASE + "/CBDServices/").text
    script = re.search(r'src="(main-[^"]+\.js)"', idx).group(1)
    js = get(BASE + "/CBDServices/" + script).text

    # every template appended to a cbdApiUrl base: `)}/something?...`
    templates = sorted(set(re.findall(r"cbdApiUrl\.\w+\)\}(/[A-Za-z0-9_/]+(?:\?[^`]{0,80})?)`", js)))
    print(f"{len(templates)} endpoint templates:", flush=True)
    for t in templates:
        print(f"  {t}", flush=True)

    issues = get(f"{PREFIX}/public/bdsinfo/newbondissues").json()
    isin = issues[0]["isin"] if issues else "INE756I07FT8"
    print(f"\ntest isin: {isin}", flush=True)

    for t in templates:
        if not re.search(r"rating|coupon|redemption|cra|grade", t, re.IGNORECASE):
            continue
        path = t.split("?")[0]
        url = f"{PREFIX}/public/bdsinfo{path}" if not path.startswith("/public") else f"{PREFIX}{path}"
        for params in ({"isin": isin},):
            print(f"\n=== {url} {params}", flush=True)
            try:
                r = get(url, params)
                print(f"  status={r.status_code} len={len(r.text)}", flush=True)
                if r.status_code == 200:
                    print(f"  JSON[:3000]: {json.dumps(r.json())[:3000]}", flush=True)
            except Exception as exc:
                print(f"  ERROR {exc}", flush=True)


if __name__ == "__main__":
    main()
