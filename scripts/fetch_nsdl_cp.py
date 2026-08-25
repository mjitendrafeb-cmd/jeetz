"""NSDL monthly Commercial Paper issuance data (nsdl.com Resources > Data >
Detailed List of Debt Instruments, Commercial Papers and Certificate of Deposit).

  GET /web/api/view/resources-data-sub-page/listing/issuance-data-cp-cd
      -> [{title, month, year, field_file}, ...]   (monthly HTML files)
  GET https://nsdl.com{field_file} -> table with columns:
      Serial No. | Name of Issuer | Issuer Code | Issuer Category | ISIN |
      Security Description | Issuance Date | Maturity Date |
      Residual Tenor (Days) | Issue Price (Rs.) | Yield | Amount Rs. Cr. | IPA

Files are published with a ~2 month lag (e.g. May 2026 available in July 2026).
Run standalone for a console dump: python fetch_nsdl_cp.py
"""

import datetime
import re

import requests

BASE = "https://nsdl.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": BASE + "/resources/data/detailed-list-debt-instruments",
}

_MONTHS = {m.lower(): i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"])}


def _session():
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def _latest_cp_file(session):
    r = session.get(
        BASE + "/web/api/view/resources-data-sub-page/listing/issuance-data-cp-cd",
        timeout=(10, 30))
    r.raise_for_status()
    best = None
    for item in r.json():
        if "commercial" not in (item.get("title") or "").lower():
            continue
        try:
            key = (int(item.get("year") or 0), _MONTHS.get((item.get("month") or "").lower(), 0))
        except ValueError:
            continue
        if key[0] and key[1] and (best is None or key > best[0]):
            best = (key, item)
    return best


def _cell_text(c):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).replace("&amp;", "&").strip()


def _num(s):
    try:
        return float(str(s).replace(",", "").replace("%", "").strip())
    except (ValueError, TypeError):
        return None


def fetch_cp_issuances(debug: bool = False) -> dict:
    """Latest monthly CP issuance file, parsed.

    Returns {"month": "May", "year": 2026, "records": [...]} where each record:
    {issuer, category, isin, description, tenor_days, yield_pct, amount_cr,
     issuance_date, ipa}
    """
    session = _session()
    best = _latest_cp_file(session)
    if not best:
        return {"month": None, "year": None, "records": []}
    (year, month_no), item = best
    url = BASE + item["field_file"]
    if debug:
        print(f"[nsdl_cp] latest file: {item['title']} -> {url}")
    r = session.get(url, timeout=(10, 60))
    r.raise_for_status()

    records = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", r.text, re.DOTALL | re.IGNORECASE):
        cells = [_cell_text(c) for c in
                 re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL | re.IGNORECASE)]
        if len(cells) < 13 or not cells[4].startswith("INE"):
            continue
        yld = _num(cells[10])
        amt = _num(cells[11])
        tenor = _num(cells[8])
        if amt is None:
            continue
        # issuance day: dates come in mixed M/D/Y and D/M/Y formats, but the
        # issuance month is always the file's month — extract the day safely
        issuance_date = None
        m = re.findall(r"\d+", cells[6])
        if len(m) >= 3:
            nums = [int(x) for x in m[:3]]
            day = nums[1] if nums[0] == month_no else (
                nums[0] if nums[1] == month_no else None)
            if day and 1 <= day <= 31:
                try:
                    issuance_date = datetime.date(year, month_no, day)
                except ValueError:
                    pass
        records.append({
            "issuer": cells[1],
            "category": cells[3],
            "isin": cells[4],
            "description": cells[5],
            "issuance_date": issuance_date,
            "tenor_days": int(tenor) if tenor else None,
            "yield_pct": yld,
            "amount_cr": amt,
            "ipa": cells[12],
        })
    month_name = [k for k, v in _MONTHS.items() if v == month_no][0].capitalize()
    if debug:
        print(f"[nsdl_cp] parsed {len(records)} CP records for {month_name} {year}")
    return {"month": month_name, "year": year, "records": records}


if __name__ == "__main__":
    data = fetch_cp_issuances(debug=True)
    for rec in data["records"][:10]:
        print(rec)
    print(f"... total {len(data['records'])} records")
