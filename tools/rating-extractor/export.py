#!/usr/bin/env python3
"""Export the rating_records table to CSV or XLSX.

Usage:
    python export.py --format csv --out exports/ratings.csv
    python export.py --format xlsx --out exports/ratings.xlsx
"""

import argparse
import csv
from pathlib import Path

import db

COLUMNS = [
    "entity_name", "source", "instrument", "record_date",
    "amount_rs_cr", "previous_amount_rs_cr", "amount_raw_text", "is_sublimit",
    "rating_previous", "rating_current",
    "outlook_previous", "outlook_current",
    "action_type", "is_confirmed_action", "ambiguous", "ambiguous_reason", "provenance", "row_seq",
    "press_release_date", "press_release_url", "evidence_text", "extracted_at",
]


def rows_as_dicts():
    db.init_db()
    with db.get_conn() as conn:
        rows = db.all_rating_records(conn)
    return [{col: row[col] for col in COLUMNS} for row in rows]


def export_csv(out_path: Path):
    rows = rows_as_dicts()
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} row(s) to {out_path}")


def export_xlsx(out_path: Path):
    from openpyxl import Workbook

    rows = rows_as_dicts()
    wb = Workbook()
    ws = wb.active
    ws.title = "Rating Records"
    ws.append(COLUMNS)
    for row in rows:
        ws.append([row[col] for col in COLUMNS])
    wb.save(out_path)
    print(f"Wrote {len(rows)} row(s) to {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=["csv", "xlsx"], required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if args.format == "csv":
        export_csv(out_path)
    else:
        export_xlsx(out_path)
