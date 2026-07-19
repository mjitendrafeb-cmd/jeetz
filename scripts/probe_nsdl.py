"""Probe #21: nsdl.com Detailed List of Debt Instruments — find its API and
check for Commercial Paper data. Runs on GitHub Actions. Not used by reports.
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
    signal.alarm(60)
    try:
        return session.get(url, params=params, timeout=(10, 30))
    finally:
        signal.alarm(0)


def main():
    r = get("https://nsdl.com/resources/data/detailed-list-debt-instruments")
    html = r.text
    print(f"page status={r.status_code} len={len(html)}", flush=True)
    print(f"'Commercial' occurrences in HTML: {len(re.findall('Commercial', html))}", flush=True)
    for i, m in enumerate(re.finditer(r"Commercial", html)):
        s = max(0, m.start() - 150)
        print(f"CTX{i}: {re.sub(r'<[^>]+>', ' ', html[s:m.end() + 250])[:350]!r}", flush=True)
        if i >= 4:
            break

    chunks = re.findall(r'src="(/_next/static/chunks/[^"]+)"', html)
    page_chunks = [c for c in chunks if "detailed-list" in c or "debt" in c.lower()]
    print(f"page chunks: {page_chunks}", flush=True)
    for c in page_chunks or chunks[:4]:
        js = get("https://nsdl.com" + c).text
        found = sorted(set(re.findall(
            r"""[`"'](v1/[A-Za-z0-9_/-]+(?:\?[^`"']{0,120})?)[`"']""", js)))
        found += sorted(set(re.findall(
            r"""\.get\(\s*[`"']([^`"']{4,150})[`"']""", js)))
        if found:
            print(f"\nCHUNK {c}:", flush=True)
            for fnd in found:
                print(f"  {fnd[:150]}", flush=True)
        for kw in ("debt", "instrument", "commercial"):
            m = re.search(kw, js, re.IGNORECASE)
            if m:
                s = max(0, m.start() - 200)
                print(f"  CTX[{kw}]: {js[s:m.end() + 400]!r}"[:650], flush=True)

    # likely API guesses on the nsdl.com backend
    base = "https://nsdl.com/web/api/"
    for path, params in (
            ("v1/debt-instruments/search", {"page": 1, "per_page": 10}),
            ("v1/detailed-list-debt-instruments", None),
            ("v1/debt-instrument-details/search", {"page": 1, "per_page": 10}),
            ("view/debt-instruments/listing", None)):
        try:
            rr = get(base + path, params)
            print(f"\nGUESS {path} -> {rr.status_code} len={len(rr.text)}", flush=True)
            if rr.status_code == 200:
                print(f"  JSON[:2500]: {json.dumps(rr.json())[:2500]}", flush=True)
        except Exception as exc:
            print(f"\nGUESS {path} -> ERROR {exc}", flush=True)


if __name__ == "__main__":
    main()
