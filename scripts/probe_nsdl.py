"""Probe: structure of NSDL 'entire list of Debt Instruments' .xls file.

Goal: can we backfill since-April issuance history (allotment date, coupon,
rating, issuer type) from this file instead of accumulating daily?
"""
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


def main():
    r = S.get(BASE + "/web/api/view/resources-data-sub-page/listing/detailed-list-debt-instruments",
              timeout=(10, 30))
    print("listing status", r.status_code)
    items = r.json()
    target = None
    for it in items:
        print("  ITEM:", repr(it.get("file_name") or it.get("title")), "|", it.get("field_file"))
        name = (it.get("file_name") or "") + " " + (it.get("title") or "")
        if "entire list" in name.lower() and (target is None or (it.get("field_file") or "") > (target.get("field_file") or "")):
            target = it
    if not target:
        print("NO entire-list file found")
        return
    url = BASE + target["field_file"]
    print("TARGET:", url)

    # HEAD-ish: stream first chunk to see type/size
    r = S.get(url, timeout=(10, 120), stream=True)
    print("status", r.status_code, "| content-type", r.headers.get("Content-Type"),
          "| content-length", r.headers.get("Content-Length"))
    first = next(r.iter_content(4096))
    print("magic bytes:", first[:16])
    is_html = b"<" in first[:200].lower()
    print("looks like HTML:", is_html)

    # download fully (bounded)
    buf = io.BytesIO(first)
    total = len(first)
    for chunk in r.iter_content(1 << 20):
        buf.write(chunk)
        total += len(chunk)
        if total > 300 * (1 << 20):
            print("ABORT: file > 300 MB")
            return
    data = buf.getvalue()
    print("downloaded bytes:", len(data))

    if is_html:
        text = data.decode("utf-8", "replace")
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.DOTALL | re.IGNORECASE)
        print("html rows:", len(rows))
        for row in rows[:4]:
            cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip()
                     for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL | re.IGNORECASE)]
            print("  ROW:", cells[:25])
        return

    # real xls -> xlrd
    try:
        import xlrd
        book = xlrd.open_workbook(file_contents=data)
        print("sheets:", book.sheet_names())
        sh = book.sheet_by_index(0)
        print("nrows", sh.nrows, "ncols", sh.ncols)
        for i in range(min(4, sh.nrows)):
            print("  ROW", i, ":", [str(c.value)[:30] for c in sh.row(i)[:25]])
        # find date-ish + coupon + rating columns from header
        header = [str(c.value).strip().lower() for c in sh.row(0)]
        print("HEADER:", header)
        # count rows with an allotment/issue date in Apr-Jul 2026
        idx = [i for i, h in enumerate(header) if "allot" in h or "issue date" in h or "date of issue" in h]
        print("date col candidates:", idx)
        if idx:
            col = idx[0]
            cnt = 0
            samples = []
            for rix in range(1, sh.nrows):
                v = str(sh.cell_value(rix, col))
                if re.search(r"(2026)", v) and re.search(r"(04|05|06|07|APR|MAY|JUN|JUL|apr|may|jun|jul)", v):
                    cnt += 1
                    if len(samples) < 3:
                        samples.append([str(c.value)[:25] for c in sh.row(rix)[:25]])
            print("rows with Apr-Jul 2026 date:", cnt)
            for s_ in samples:
                print("  SAMPLE:", s_)
    except Exception as exc:
        print("xlrd failed:", type(exc).__name__, exc)
        print("first 300 bytes:", data[:300])


if __name__ == "__main__":
    sys.exit(main())
