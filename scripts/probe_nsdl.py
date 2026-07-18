"""Probe #2: extract the backend API endpoints used by nsdl.com's
Issue Summary Document page (Next.js app) by scanning its JS chunks,
then hit the discovered endpoints with plausible search payloads.
Runs on the GitHub Actions runner. Not used by reports.
"""

import json
import re
import signal
import sys

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

session = requests.Session()
session.headers.update(HEADERS)


class HardTimeout(Exception):
    pass


signal.signal(signal.SIGALRM, lambda s, f: (_ for _ in ()).throw(HardTimeout()))


def get(url, **kw):
    signal.alarm(60)
    try:
        return session.get(url, timeout=(10, 30), **kw)
    finally:
        signal.alarm(0)


def post(url, **kw):
    signal.alarm(60)
    try:
        return session.post(url, timeout=(10, 30), **kw)
    finally:
        signal.alarm(0)


URL_RE = re.compile(r"""https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+""")
PATH_RE = re.compile(r"""["'](/[A-Za-z0-9._~/?#\[\]@!$&'*+,;=%-]*(?:api|API|service|Service|isd|ISD|issue|Issue|debt|Debt)[A-Za-z0-9._~/?#\[\]@!$&'*+,;=%-]*)["']""")
FETCH_RE = re.compile(r"""(?:fetch|axios[.\w]*|\.post|\.get)\s*\(\s*[`"']([^`"']{4,200})[`"']""")


def scan_js(url):
    print(f"\n--- JS {url}", flush=True)
    try:
        r = get(url)
    except Exception as exc:
        print(f"  ERROR {exc}", flush=True)
        return
    if r.status_code != 200:
        print(f"  status={r.status_code}", flush=True)
        return
    text = r.text
    print(f"  len={len(text)}", flush=True)
    hits = set(URL_RE.findall(text))
    for h in sorted(hits):
        if "w3.org" in h or "reactjs.org" in h or "nextjs.org" in h:
            continue
        print(f"  URL: {h[:180]}", flush=True)
    for m in sorted(set(PATH_RE.findall(text))):
        print(f"  PATH: {m[:180]}", flush=True)
    for m in sorted(set(FETCH_RE.findall(text))):
        print(f"  FETCH: {m[:180]}", flush=True)
    # show context around 'issue-summary' / 'isd' / 'api' mentions
    for kw in ("issue_summary", "issueSummary", "isd", "stage_of_issue", "date_from"):
        for m in re.finditer(kw, text):
            s = max(0, m.start() - 150)
            print(f"  CTX[{kw}]: {text[s:m.end() + 250]!r}"[:600], flush=True)
            break


def main():
    page = "https://nsdl.com/resources/data/issue-summary-document"
    r = get(page)
    print(f"page status={r.status_code} len={len(r.text)}", flush=True)
    chunks = re.findall(r'src="(/_next/static/chunks/[^"]+)"', r.text)
    print(f"{len(chunks)} chunks", flush=True)
    # page-specific chunk first, then the rest
    chunks.sort(key=lambda c: ("issue-summary-document" not in c, "resources/data" not in c))
    for c in chunks[:8]:
        scan_js("https://nsdl.com" + c)

    # Embedded RSC/next data in the HTML often carries API hosts too
    for h in sorted(set(URL_RE.findall(r.text))):
        if "nsdl" in h and "nsdl.com/" not in h.split("//", 1)[1][:20]:
            print(f"  HTML-URL: {h[:180]}", flush=True)
    for m in sorted(set(PATH_RE.findall(r.text))):
        print(f"  HTML-PATH: {m[:180]}", flush=True)

    # Common Next.js server route guesses
    for guess in (
        "https://nsdl.com/api/issue-summary-document",
        "https://nsdl.com/api/isd",
        "https://nsdl.com/api/resources/data/issue-summary-document",
    ):
        try:
            rr = get(guess)
            print(f"GUESS {guess} -> {rr.status_code} {rr.text[:200]!r}", flush=True)
        except Exception as exc:
            print(f"GUESS {guess} -> ERROR {exc}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
