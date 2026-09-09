#!/usr/bin/env python3
"""Run all agency scrapers against the watchlist and store new rating actions.

Usage:
    python fetch.py            # scrape for every watchlist company
    python fetch.py --company "Example Finance Ltd"
"""

import argparse
import sys
from datetime import datetime, timezone

import db
from scrapers import AGENCIES


def _company_dicts(conn, only_name=None):
    rows = db.list_companies(conn)
    companies = []
    for row in rows:
        if only_name and row["name"].lower() != only_name.lower():
            continue
        aliases = [a.strip() for a in row["aliases"].split(",") if a.strip()]
        companies.append({"id": row["id"], "name": row["name"], "aliases": aliases})
    return companies


def run(only_name=None) -> dict:
    """Scrape every agency and store new rating actions. Returns counts per agency."""
    db.init_db()
    counts = {agency: 0 for agency in AGENCIES}

    with db.get_conn() as conn:
        companies = _company_dicts(conn, only_name)
        if not companies:
            print("No matching watchlist companies found.")
            return counts

        name_to_id = {c["name"]: c["id"] for c in companies}
        fetched_at = datetime.now(timezone.utc).isoformat()

        for agency, scrape_fn in AGENCIES.items():
            try:
                found = scrape_fn(companies)
            except Exception as exc:
                print(f"[fetch] {agency} scraper crashed: {exc}")
                continue

            for action in found:
                company_id = name_to_id.get(action.pop("company_name"))
                if company_id is None:
                    continue
                action["company_id"] = company_id
                action["fetched_at"] = fetched_at
                db.upsert_rating_action(conn, action)

            counts[agency] = len(found)
            print(f"[fetch] {agency}: {len(found)} matching item(s)")

    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company", help="Only scrape for this watchlist company (exact name)")
    args = parser.parse_args()

    result = run(only_name=args.company)
    total = sum(result.values())
    print(f"Done. {total} matching item(s) found across {len(result)} agencies.")
    sys.exit(0)
