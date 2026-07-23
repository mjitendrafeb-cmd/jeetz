"""NSDL 'entire list of Debt Instruments' file (nsdl.com Resources > Data >
Detailed List of Debt Instruments).

Despite the .xls extension the file is tab-separated text (~27 MB, ~46k rows),
refreshed daily with a header:

  COMPANY | ISIN | NAME_OF_THE_INSTRUMENT | DESCRIPTION_IN_NSDL | ISSUE_PRICE |
  FACE_VALUE | DATE_OF_ALLOTMENT | REDEMPTION | COUPON_RATE | FREQUENCY... |
  PUT_CALL_OPTION | CERTIFICATE_NOS | TOTAL_ISSUE_SIZE | REGISTRAR... |
  ADDRESS... | DEFAULTED_IN_REDEMPTION | NAME_OF_DEBENTURE (trustee) |
  CREDIT_RATING_CREDIT_RATING_AGENCY | REMARKS

Rating column format: "BBB+ ICRA LIMITED DT 26-02-2026" (grade, agency, date).
Run standalone for a console dump: python fetch_nsdl_debt_list.py
"""

import csv
import datetime
import io
import re

import requests

BASE = "https://nsdl.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Referer": BASE + "/resources/data/detailed-list-debt-instruments",
}

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"])}

_DATE_RE = re.compile(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})")
_GRADE_RE = re.compile(
    r"^(?:PROVISIONAL\s+|PP-MLD\s+)?"
    r"(AAA|AA\+|AA-|AA|A\+|A-|BBB\+|BBB-|BBB|BB\+|BB-|BB|B\+|B-|A|B|C|D)"
    r"(?=[\s(/]|$)")


def _parse_date(s):
    m = _DATE_RE.match(str(s).strip())
    if not m:
        return None
    mo = _MONTHS.get(m.group(2).lower())
    if not mo:
        return None
    try:
        return datetime.date(int(m.group(3)), mo, int(m.group(1)))
    except ValueError:
        return None


def _num(s):
    try:
        return float(str(s).replace(",", "").replace("%", "").strip())
    except (ValueError, TypeError):
        return None


def fetch_debt_list(debug: bool = False, min_allotment: datetime.date | None = None) -> dict:
    """Parse the latest entire-list file.

    Returns {"as_on": "22.07.2026", "records": [...]}; each record:
    {isin, issuer, allotment_date, redemption_date, tenure_years, coupon,
     amount_cr, rating, rating_agency}. Rows older than `min_allotment`
    (if given) are skipped to bound memory.
    """
    session = requests.Session()
    session.headers.update(HEADERS)
    r = session.get(
        BASE + "/web/api/view/resources-data-sub-page/listing/detailed-list-debt-instruments",
        timeout=(10, 30))
    r.raise_for_status()
    target = None
    for it in r.json():
        if "entire list" not in (it.get("file_name") or "").lower():
            continue
        if target is None or (it.get("field_file") or "") > (target.get("field_file") or ""):
            target = it
    if not target:
        return {"as_on": None, "records": []}
    url = BASE + target["field_file"]
    m = re.search(r"as_on_([\d.]+)\.xls", url)
    as_on = m.group(1) if m else None
    if debug:
        print(f"[nsdl_debt_list] fetching {url}")
    r = session.get(url, timeout=(10, 300))
    r.raise_for_status()
    text = r.content.decode("utf-8", "replace")

    reader = csv.reader(io.StringIO(text), delimiter="\t")
    header = [h.strip().upper() for h in next(reader)]

    def col(name):
        return header.index(name) if name in header else None

    ci = {k: col(k) for k in (
        "COMPANY", "ISIN", "DATE_OF_ALLOTMENT", "REDEMPTION", "COUPON_RATE",
        "TOTAL_ISSUE_SIZE", "CREDIT_RATING_CREDIT_RATING_AGENCY")}
    if ci["ISIN"] is None or ci["DATE_OF_ALLOTMENT"] is None:
        raise ValueError(f"unexpected entire-list header: {header}")

    def cell(row, key):
        i = ci[key]
        return row[i].strip() if i is not None and len(row) > i else ""

    records = []
    total = 0
    for row in reader:
        total += 1
        allot = _parse_date(cell(row, "DATE_OF_ALLOTMENT"))
        if not allot or (min_allotment and allot < min_allotment):
            continue
        red = _parse_date(cell(row, "REDEMPTION"))
        coupon = _num(cell(row, "COUPON_RATE"))
        if coupon is not None and not 0 < coupon < 40:
            coupon = None  # index-linked ("SENSEX"), zero-coupon or junk
        size = _num(cell(row, "TOTAL_ISSUE_SIZE"))
        rating = agency = None
        rat_raw = cell(row, "CREDIT_RATING_CREDIT_RATING_AGENCY")
        gm = _GRADE_RE.match(rat_raw.upper())
        if gm:
            rating = gm.group(1)
            rest = rat_raw[gm.end():].strip()
            agency = re.split(r"\s+DT\s+", rest, maxsplit=1, flags=re.I)[0].strip() or None
        records.append({
            "isin": cell(row, "ISIN"),
            "issuer": cell(row, "COMPANY"),
            "allotment_date": allot,
            "redemption_date": red,
            "tenure_years": round((red - allot).days / 365.25, 1) if red else None,
            "coupon": coupon,
            "amount_cr": round(size / 1e7, 2) if size else None,
            "rating": rating,
            "rating_agency": agency,
        })
    if debug:
        print(f"[nsdl_debt_list] as_on={as_on}: kept {len(records)} of {total} rows"
              + (f" (allotted on/after {min_allotment})" if min_allotment else ""))
    return {"as_on": as_on, "records": records}


if __name__ == "__main__":
    data = fetch_debt_list(debug=True,
                           min_allotment=datetime.date.today() - datetime.timedelta(days=120))
    for rec in data["records"][:10]:
        print(rec)
    print(f"... total {len(data['records'])} records as on {data['as_on']}")
