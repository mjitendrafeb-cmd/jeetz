"""Probe #9: resolve cbdApiPrefixURL from the CBDServices runtime config and
call the new-bond-issues endpoints. Runs on the GitHub Actions runner.
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

    # where does the config come from?
    for kw in ("cbdApiPrefixURL", "getConfigValue", "loadConfig", "assets/"):
        for i, m in enumerate(re.finditer(re.escape(kw), js)):
            s = max(0, m.start() - 250)
            print(f"CTX[{kw}#{i}]: {js[s:m.end() + 400]!r}"[:900], flush=True)
            if i >= 2:
                break

    asset_jsons = sorted(set(re.findall(r"""["'`](assets/[A-Za-z0-9_./-]+\.json)["'`]""", js)))
    print(f"\nasset jsons in bundle: {asset_jsons}", flush=True)

    prefix = None
    candidates = list(asset_jsons) + [
        "assets/config.json", "assets/config/config.json", "assets/app-config.json",
        "assets/appconfig.json", "assets/data/config.json",
    ]
    for a in candidates:
        url = BASE + "/CBDServices/" + a
        try:
            r = get(url)
        except Exception as exc:
            print(f"{a} ERROR {exc}", flush=True)
            continue
        if r.status_code != 200:
            print(f"{a} -> {r.status_code}", flush=True)
            continue
        body = r.text
        print(f"\n{a} -> 200 len={len(body)} body[:800]: {body[:800]!r}", flush=True)
        m = re.search(r'"cbdApiPrefixURL"\s*:\s*"([^"]+)"', body)
        if m:
            prefix = m.group(1)
            print(f"FOUND cbdApiPrefixURL = {prefix}", flush=True)
            break

    if not prefix:
        print("no prefix found; guessing", flush=True)
        prefix = BASE + "/CBDSAPIs"

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
            print(f"  JSON[:5000]: {json.dumps(r.json())[:5000]}", flush=True)
        except Exception:
            print(f"  body[:300]: {r.text[:300]!r}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
