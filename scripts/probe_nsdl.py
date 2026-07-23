"""Probe #23: (a) detailed-list CP files (fresher than monthly issuance?),
(b) corporatebondissuance?year= for since-April backfill.
Runs on GitHub Actions. Not used by reports.
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


def get(url, params=None, timeout=(10, 60)):
    signal.alarm(90)
    try:
        return session.get(url, params=params, timeout=timeout)
    finally:
        signal.alarm(0)


def main():
    # (a) all datasets on the detailed-list page: find CP 'detailed list' files
    r = get("https://nsdl.com/resources/data/detailed-list-debt-instruments")
    html = r.text
    print(f"page {r.status_code} len={len(html)}", flush=True)
    for m in sorted(set(re.findall(r'\\\\"field_file\\\\":\\\\"([^"\\\\]+)\\\\"', html))):
        print(f"  FILE: {m}", flush=True)
    # dataset names with nearby titles
    for ds in ("commercialDetailDataSet", "debtInstrumentDataSet", "certificateOfDepositDataSet",
               "debtListInstrumentDataSet"):
        i = html.find(ds)
        print(f"\nDS {ds} at {i}", flush=True)
    for m in re.finditer(r'Detailed[^"\\\\]{0,120}', html):
        print(f"  TITLE: {m.group(0)[:150]}", flush=True)

    # other listing slugs
    for slug in ("detailed-list-debt-instruments", "commercial-paper", "detailed-list-cp",
                 "debt-instruments", "cp-detailed-list"):
        try:
            rr = get(f"https://nsdl.com/web/api/view/resources-data-sub-page/listing/{slug}")
            body = rr.text[:600]
            print(f"\nLISTING {slug} -> {rr.status_code} len={len(rr.text)} {body[:400]!r}", flush=True)
        except Exception as exc:
            print(f"\nLISTING {slug} -> ERROR {exc}", flush=True)

    # (b) India Bond Info: corporate bond issuance by year — backfill candidate
    prefix = "https://www.indiabondinfo.nsdl.com/bds-service/v1/public/bdsinfo"
    session.headers["Referer"] = "https://www.indiabondinfo.nsdl.com/CBDServices/"
    try:
        rr = get(prefix + "/corporatebondissuancedropdown")
        print(f"\ndropdown -> {rr.status_code} {rr.text[:500]!r}", flush=True)
        years = []
        try:
            years = rr.json()
        except Exception:
            pass
    except Exception as exc:
        print(f"dropdown ERROR {exc}", flush=True)
        years = []
    candidates = []
    for y in (years if isinstance(years, list) else []):
        candidates.append(y if isinstance(y, str) else json.dumps(y))
    candidates += ["2026-27", "2026", "FY2026-27"]
    for y in candidates[:6]:
        try:
            rr = get(prefix + "/corporatebondissuance", {"year": y})
            print(f"\nissuance year={y!r} -> {rr.status_code} len={len(rr.text)}", flush=True)
            if rr.status_code == 200:
                print(f"  JSON[:2500]: {json.dumps(rr.json())[:2500]}", flush=True)
        except Exception as exc:
            print(f"issuance year={y!r} ERROR {exc}", flush=True)


if __name__ == "__main__":
    main()
