#!/usr/bin/env python3
"""Parse one locally-saved press release / rating page and store + report results.

This does NOT fetch anything over the network — it's for validating the
extraction logic against a page you saved yourself (View Source, or a
Network-tab response), per the README's "Status: reconnaissance blocked"
workflow.

Usage:
    python ingest_sample.py --source CRISIL --entity "Bajaj Finance Limited" \\
        --url "https://www.crisilratings.com/.../BajajFinance_..._RR_....html" \\
        --file samples/crisil/bajaj_finance.html [--pub-date 2026-03-24]
"""

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import db
from extract import PARSERS

SAMPLES_DIR = Path(__file__).parent / "samples"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True, choices=list(PARSERS.keys()))
    parser.add_argument("--entity", required=True, help="Must match a name in entities.csv")
    parser.add_argument("--url", required=True)
    parser.add_argument("--file", required=True, help="Path to the saved HTML/text file")
    parser.add_argument("--pub-date", help="Press release date, ISO format, if known")
    parser.add_argument("--content-type", default="html", choices=["html", "text", "pdf"])
    args = parser.parse_args()

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"File not found: {file_path}", file=sys.stderr)
        sys.exit(1)
    # PDFs are binary and their parser works from the file path, not decoded
    # text; hashing still uses the bytes so the stored copy is identified the
    # same way as an HTML capture.
    is_pdf = file_path.suffix.lower() == ".pdf"
    if is_pdf:
        raw_bytes = file_path.read_bytes()
        raw_content = raw_bytes.decode("latin-1")
    else:
        raw_content = file_path.read_text(errors="ignore")

    db.init_db()
    with db.get_conn() as conn:
        entity = db.get_entity_by_name(conn, args.entity)
        if entity is None:
            print(f"'{args.entity}' not found in entities.csv / database.", file=sys.stderr)
            print("Add it to entities.csv (or run db.add_entity) first.", file=sys.stderr)
            sys.exit(1)
        aliases = [a.strip() for a in entity["aliases"].split(",") if a.strip()]

        fetched_at = datetime.now(timezone.utc).isoformat()
        stored_copy_dir = SAMPLES_DIR / "_ingested" / args.source.replace(" ", "_")
        stored_copy_dir.mkdir(parents=True, exist_ok=True)
        stored_copy_path = stored_copy_dir / file_path.name
        shutil.copy(file_path, stored_copy_path)

        press_release_id = db.upsert_press_release(
            conn,
            entity_id=entity["id"],
            source=args.source,
            url=args.url,
            pub_date=args.pub_date,
            fetched_at=fetched_at,
            storage_path=str(stored_copy_path),
            raw_text=raw_content,
        )

        parser_input = str(stored_copy_path) if is_pdf else raw_content
        content_type = "pdf" if is_pdf else args.content_type
        records = PARSERS[args.source](entity["name"], aliases, parser_input, content_type)

        if not records:
            print(f"No candidate records found for '{args.entity}' in this file.")
            print("Either the entity/alias text doesn't appear verbatim, or the parser's")
            print("generic text-splitting missed it — inspect the file and adjust extract/common.py.")
            return

        print(f"\n=== {len(records)} candidate record(s) for {args.entity} / {args.source} ===\n")
        for i, rec in enumerate(records, 1):
            rec.setdefault("provenance", "generic_text_fallback")
            rec.setdefault("row_seq", None)
            rec.setdefault("is_sublimit", 0)
            rec.setdefault("previous_amount_rs_cr", None)
            rec["entity_id"] = entity["id"]
            rec["source"] = args.source
            rec["press_release_id"] = press_release_id
            rec["extracted_at"] = fetched_at
            status = db.upsert_rating_record(conn, rec)

            print(f"--- Record {i} ({status}) ---")
            print(f"  Instrument:        {rec['instrument']}")
            print(f"  Date:              {rec['record_date']}")
            print(f"  Amount:            {rec['amount_raw_text']} -> {rec['amount_rs_cr']} Cr")
            print(f"  Rating:            {rec['rating_current']}  (outlook: {rec['outlook_current']})")
            print(f"  Action type:       {rec['action_type']}")
            print(f"  Provenance:        {rec.get('provenance')}")
            print(f"  Confirmed action?: {'YES' if rec['is_confirmed_action'] else 'NO (ambiguous)'}")
            if rec.get("ambiguous_reason"):
                print(f"  Why ambiguous:     {rec['ambiguous_reason']}")
            print(f"  Source text:       \"{rec['evidence_text']}\"")
            print()

        print(f"Stored copy of the source file: {stored_copy_path}")
        print("Verify each record above against that file / the original URL before trusting it.")


if __name__ == "__main__":
    main()
