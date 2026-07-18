"""Probe #7: map the India Bond Info CBDServices Angular app — bundle names,
API endpoint strings, and try the discovered endpoints. Runs on GitHub Actions.
Not used by reports.
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
    "Accept": "*/*",
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
    r = get(BASE + "/CBDServices/")
    print(f"index status={r.status_code} len={len(r.text)}", flush=True)
    print(r.text[:2500], flush=True)

    scripts = re.findall(r'src="([^"]+\.js)"', r.text)
    print(f"scripts: {scripts}", flush=True)

    api_hits = set()
    for s in scripts:
        url = s if s.startswith("http") else BASE + "/CBDServices/" + s.lstrip("/")
        try:
            js = get(url).text
        except Exception as exc:
            print(f"JS {url} ERROR {exc}", flush=True)
            continue
        print(f"\nJS {url} len={len(js)}", flush=True)
        # endpoint-ish strings
        for m in re.finditer(r"""["'`]((?:[A-Za-z0-9_./-]*/)?(?:api|rest|service)[A-Za-z0-9_./?=&-]*)["'`]""", js):
            api_hits.add(m.group(1))
        for m in re.finditer(r"""["'`](https?://[^"'`\s]{8,150})["'`]""", js):
            api_hits.add(m.group(1))
        # keywords around issuance
        for kw in ("newIssue", "issuance", "primary", "getIsin", "isinList", "activat", "allotment", "coupon"):
            for i, m in enumerate(re.finditer(kw, js, re.IGNORECASE)):
                st = max(0, m.start() - 200)
                print(f"CTX[{kw}#{i}]: {js[st:m.end() + 300]!r}"[:700], flush=True)
                if i >= 2:
                    break

    print("\nAPI-LIKE STRINGS:", flush=True)
    for h in sorted(api_hits):
        if any(x in h.lower() for x in ("w3.org", "angular", "npmjs", "github", "google")):
            continue
        print(f"  {h[:160]}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
