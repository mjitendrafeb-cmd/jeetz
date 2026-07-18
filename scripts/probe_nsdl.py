"""Probe #18: grep the BSE SPA bundle for Debt/CP API method names and try
the most promising ones against api.bseindia.com. Runs on GitHub Actions.
Not used by reports.
"""

import datetime
import json
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
    signal.alarm(60)
    try:
        return session.get(url, timeout=(10, 25), **kw)
    finally:
        signal.alarm(0)


def main():
    shell = get("https://www.bseindia.com/markets/debt/debt_home.aspx").text
    script = re.search(r'src="([^"]+main[^"]*\.js[^"]*)"', shell).group(1)
    url = script if script.startswith("http") else "https://www.bseindia.com" + (
        script if script.startswith("/") else "/" + script)
    js = get(url).text
    print(f"bundle len={len(js)}", flush=True)

    # quoted strings that look like API method names
    names = set()
    for m in re.findall(r'"([A-Za-z][A-Za-z0-9_]{2,40})/w"', js):
        names.add(m)
    for m in re.findall(r'"([A-Za-z0-9_]*(?:CP|Debt|debt|Comm|NCB|NCD|Listing)[A-Za-z0-9_]*)"', js):
        if 3 < len(m) < 45:
            names.add(m)
    hits = sorted(n for n in names
                  if re.search(r"cp|debt|comm|ncd|ncb|listing", n, re.IGNORECASE))
    print(f"{len(hits)} candidate names:", flush=True)
    for n in hits[:120]:
        print(f"  {n}", flush=True)

    # context around 'CP' API-ish usages
    for i, m in enumerate(re.finditer(r'[A-Za-z0-9_]*CP[A-Za-z0-9_]*/w', js)):
        s = max(0, m.start() - 150)
        print(f"CTX{i}: {js[s:m.end() + 150]!r}"[:400], flush=True)
        if i >= 8:
            break

    # try promising method names as GET .../api/<name>/w
    tried = 0
    for n in hits:
        if not re.search(r"cp|debtnew|newdebt|debtlisting", n, re.IGNORECASE):
            continue
        u = f"https://api.bseindia.com/BseIndiaAPI/api/{n}/w"
        try:
            r = get(u)
            body = r.text[:150].replace("\n", " ")
            print(f"TRY {n} -> {r.status_code} {body!r}", flush=True)
        except Exception as exc:
            print(f"TRY {n} -> ERROR {exc}", flush=True)
        tried += 1
        if tried >= 15:
            break


if __name__ == "__main__":
    main()
