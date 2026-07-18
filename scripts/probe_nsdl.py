"""Probe #10: resolve the portal-config name/prefix, read cbdApiPrefixURL,
call the new-bond-issues endpoint. Runs on the GitHub Actions runner.
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
    idx = get(BASE + "/CBDServices/").text
    script = re.search(r'src="(main-[^"]+\.js)"', idx).group(1)
    js = get(BASE + "/CBDServices/" + script).text

    for kw in ("portal-config", ".loadConfig(", "loadConfig("):
        for i, m in enumerate(re.finditer(re.escape(kw), js)):
            s = max(0, m.start() - 350)
            print(f"CTX[{kw}#{i}]: {js[s:m.end() + 350]!r}"[:900], flush=True)
            if i >= 3:
                break

    prefix = None
    for name in ("config", "portal", "cbd", "prod", "production", "app", "bds", "CBDServices"):
        for root in (BASE, BASE + "/CBDServices"):
            url = f"{root}/portal-config/{name}.json"
            try:
                r = get(url)
            except Exception as exc:
                print(f"{url} ERROR {exc}", flush=True)
                continue
            ok = r.status_code == 200 and "cbdApiPrefixURL" in r.text
            print(f"{url} -> {r.status_code} len={len(r.text)}{' HIT' if ok else ''}", flush=True)
            if r.status_code == 200 and len(r.text) < 3000 and r.text.strip().startswith(("{", "[")):
                print(f"  body: {r.text[:1500]}", flush=True)
            if ok:
                prefix = re.search(r'"cbdApiPrefixURL"\s*:\s*"([^"]+)"', r.text).group(1)
                break
        if prefix:
            break

    print(f"\nprefix={prefix}", flush=True)
    if not prefix:
        return
    if prefix.startswith("/"):
        prefix = BASE + prefix

    for path in ("/public/bdsinfo/newbondissues",
                 "/public/bdsinfo/issuancedashboard",
                 "/public/bdsinfo/currentissuance"):
        url = prefix.rstrip("/") + path
        print(f"\n=== {url}", flush=True)
        try:
            r = get(url)
        except Exception as exc:
            print(f"  ERROR {exc}", flush=True)
            continue
        print(f"  status={r.status_code} type={r.headers.get('content-type')} len={len(r.text)}", flush=True)
        try:
            print(f"  JSON[:6000]: {json.dumps(r.json())[:6000]}", flush=True)
        except Exception:
            print(f"  body[:300]: {r.text[:300]!r}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
