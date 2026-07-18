"""Probe #12: dump FULL instrument/isin JSON for current new-issue ISINs and
try candidate rating endpoints, to locate credit rating data.
Runs on the GitHub Actions runner. Not used by reports.
"""

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


def get_json(url, params=None):
    signal.alarm(50)
    try:
        r = session.get(url, params=params, timeout=(10, 25))
        print(f"\n=== {r.url}\n  status={r.status_code} len={len(r.text)}", flush=True)
        return r.json()
    except Exception as exc:
        print(f"  ERROR {exc}", flush=True)
        return None
    finally:
        signal.alarm(0)


def main():
    issues = get_json(f"{PREFIX}/public/bdsinfo/newbondissues") or []
    isins = [i["isin"] for i in issues]
    print(f"isins: {isins}", flush=True)

    first = True
    for isin in isins:
        data = get_json(f"{PREFIX}/public/bdsinfo/instruments", {"isin": isin})
        if data is not None:
            txt = json.dumps(data)
            if first:
                # full dump once, in chunks the log can hold
                for off in range(0, min(len(txt), 40000), 4000):
                    print(f"FULL[{off}]: {txt[off:off + 4000]}", flush=True)
                first = False
            else:
                low = txt.lower()
                for kw in ("rating", "crisil", "icra", "care", "cra"):
                    idx = low.find(kw)
                    if idx >= 0:
                        print(f"  {kw}@{idx}: {txt[max(0, idx - 200):idx + 400]}", flush=True)

    # candidate rating endpoints for the first ISIN
    if isins:
        isin = isins[0]
        for path in ("/public/bdsinfo/ratingdetails", "/public/bdsinfo/creditrating",
                     "/public/bdsinfo/ratings", "/public/bdsinfo/coupons",
                     "/public/bdsinfo/coupondetails", "/public/ratings"):
            data = get_json(f"{PREFIX}{path}", {"isin": isin})
            if data is not None:
                print(f"  {path}: {json.dumps(data)[:2500]}", flush=True)


if __name__ == "__main__":
    main()
