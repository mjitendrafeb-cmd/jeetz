"""Probe #17: extract api.bseindia.com endpoints from the BSE SPA bundles,
focusing on CP / debt-listing feeds. Runs on the GitHub Actions runner.
Not used by reports.
"""

import re
import signal

import requests

H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.bseindia.com/",
}

session = requests.Session()
session.headers.update(H)
signal.signal(signal.SIGALRM, lambda s, f: (_ for _ in ()).throw(TimeoutError()))


def get(url, **kw):
    signal.alarm(45)
    try:
        return session.get(url, timeout=(10, 20), **kw)
    finally:
        signal.alarm(0)


def main():
    shell = get("https://www.bseindia.com/markets/debt/debt_home.aspx").text
    print(f"shell len={len(shell)}", flush=True)
    scripts = re.findall(r'src="([^"]+\.js[^"]*)"', shell)
    print(f"scripts: {scripts}", flush=True)

    endpoints = set()
    for s in scripts:
        url = s if s.startswith("http") else "https://www.bseindia.com" + (
            s if s.startswith("/") else "/" + s)
        try:
            js = get(url).text
        except Exception as exc:
            print(f"JS {url} ERROR {exc}", flush=True)
            continue
        print(f"\nJS {url} len={len(js)}", flush=True)
        for m in re.findall(r"""https?://api\.bseindia\.com/[A-Za-z0-9_/.{}$?=&%-]+""", js):
            endpoints.add(m)
        for m in re.findall(r"""BseIndiaAPI/api/[A-Za-z0-9_/.{}$?=&%-]+""", js):
            endpoints.add(m)

    cps = sorted(e for e in endpoints
                 if re.search(r"cp|commercial|debt|ncd|bond|listing", e, re.IGNORECASE))
    print(f"\n{len(endpoints)} endpoints total; {len(cps)} CP/debt-flavoured:", flush=True)
    for e in cps:
        print(f"  {e[:170]}", flush=True)
    others = sorted(endpoints - set(cps))
    print(f"\nOTHERS ({len(others)}):", flush=True)
    for e in others[:80]:
        print(f"  {e[:150]}", flush=True)


if __name__ == "__main__":
    main()
