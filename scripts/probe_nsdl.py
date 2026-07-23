"""Probe 26: NSDL entire-list debt instruments TSV — header + since-April rows."""
import csv
import io
import re
import sys

import requests

BASE = "https://nsdl.com"
S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Referer": BASE + "/resources/data/detailed-list-debt-instruments",
})

MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"])}


def parse_date(s):
    m = re.match(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", str(s).strip())
    if not m:
        return None
    mo = MONTHS.get(m.group(2).lower())
    if not mo:
        return None
    return (int(m.group(3)), mo, int(m.group(1)))


def main():
    r = S.get(BASE + "/web/api/view/resources-data-sub-page/listing/detailed-list-debt-instruments",
              timeout=(10, 30))
    target = None
    for it in r.json():
        name = (it.get("file_name") or "")
        if "entire list" in name.lower() and (target is None or (it.get("field_file") or "") > (target.get("field_file") or "")):
            target = it
    url = BASE + target["field_file"]
    print("TARGET:", url)
    r = S.get(url, timeout=(10, 300))
    text = r.content.decode("utf-8", "replace")
    print("bytes:", len(r.content))
    lines = text.splitlines()
    print("lines:", len(lines))
    header = lines[0].split("\t")
    print("NCOLS:", len(header))
    for i, h in enumerate(header):
        print(f"  COL {i}: {h!r}")

    reader = csv.reader(io.StringIO(text), delimiter="\t")
    next(reader)
    # find allotment-date column by name
    alo = [i for i, h in enumerate(header) if "allot" in h.lower()]
    print("allot col candidates:", alo, [header[i] for i in alo])
    ai = alo[0] if alo else None
    total = 0
    recent = 0
    samples = []
    bad = 0
    for row in reader:
        total += 1
        if ai is None or len(row) <= ai:
            bad += 1
            continue
        d = parse_date(row[ai])
        if not d:
            bad += 1
            continue
        if d >= (2026, 4, 1):
            recent += 1
            if len(samples) < 5:
                samples.append(row)
    print(f"rows total={total} recent(since Apr 2026)={recent} unparseable-date={bad}")
    for s_ in samples:
        print("SAMPLE:")
        for i, v in enumerate(s_):
            if v.strip():
                print(f"    [{i}] {header[i][:35]!r} = {v[:70]!r}")


if __name__ == "__main__":
    sys.exit(main())
