"""Probe #24: full detailed-list file listing; inspect the CP detailed-list
file for issue dates/yields. Runs on GitHub Actions. Not used by reports.
"""

import json
import re
import signal

import requests

H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
}

session = requests.Session()
session.headers.update(H)
signal.signal(signal.SIGALRM, lambda s, f: (_ for _ in ()).throw(TimeoutError()))


def get(url, params=None):
    signal.alarm(120)
    try:
        return session.get(url, params=params, timeout=(10, 90))
    finally:
        signal.alarm(0)


def main():
    r = get("https://nsdl.com/web/api/view/resources-data-sub-page/listing/detailed-list-debt-instruments")
    items = r.json()
    print(f"listing: {len(items)} items", flush=True)
    for it in items:
        print(f"  {it.get('title')!r} | file_name={it.get('file_name')!r} | "
              f"{it.get('field_file')} | ext={it.get('extension')}", flush=True)

    cp_items = [it for it in items if "commercial" in
                (it.get("file_name", "") + it.get("title", "")).lower()]
    for it in cp_items[:1]:
        url = "https://nsdl.com" + it["field_file"]
        print(f"\nFETCH {url}", flush=True)
        rr = get(url)
        print(f"  status={rr.status_code} len={len(rr.content)} "
              f"type={rr.headers.get('content-type')}", flush=True)
        body = rr.content[:200]
        print(f"  first bytes: {body!r}", flush=True)
        if b"<" in body[:10] or it["extension"] == "html":
            rows = re.findall(rb"<tr[^>]*>(.*?)</tr>", rr.content, re.DOTALL | re.IGNORECASE)
            print(f"  rows={len(rows)}", flush=True)
            for row in rows[:5] + rows[-2:]:
                cells = [re.sub(rb"\s+", b" ", re.sub(rb"<[^>]+>", b" ", c)).strip().decode("utf-8", "ignore")
                         for c in re.findall(rb"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL | re.IGNORECASE)]
                print(f"  ROW: {cells[:14]}", flush=True)
        elif it["extension"] in ("xls", "xlsx"):
            # xls: peek text strings for header names
            text = rr.content.decode("latin-1", "ignore")
            for kw in ("Issue", "Yield", "Maturity", "Allot", "ISIN"):
                idx = text.find(kw)
                if idx >= 0:
                    print(f"  XLS ctx[{kw}]: {text[idx:idx + 120]!r}", flush=True)


if __name__ == "__main__":
    main()
