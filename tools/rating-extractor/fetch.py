#!/usr/bin/env python3
"""Scheduled fetch: search each entity by name, pull its documents, extract, store.

Runs on a GitHub Actions runner (the dev sandbox cannot reach these sites).
Discovery differs per source, all established by reconnaissance:

- India Ratings: GET home/GetSearch?searchKey=<name> -> issuerID +
  pressreleaseList; then GetBankFacilityDataRatingLetter?pressReleaseId=<id>
  for the instrument table. Unauthenticated JSON, no browser.
- ICRA: POST /Home/PostGlobalSearchIndex with an ASP.NET __RequestVerificationToken
  scraped from a page first, then rationale PDFs from
  /Rating/GetRationalReportFilePdf?id=<id>.
- CRISIL: its plain-HTTP search endpoint returns HTTP 500, so the search UI is
  driven with Playwright/Chromium. Rationale pages themselves are plain HTML.

Every failure writes the response it got to captures/_fetch_debug/ so the next
iteration can be built against real evidence rather than guesswork.

Usage:
    python fetch.py                    # the 3 validation entities
    python fetch.py --all              # every entity in entities.csv
    python fetch.py --entity "Bajaj Finance Limited"
    python fetch.py --sources CRISIL ICRA
"""

import argparse
import json
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

import db
from extract import crisil as crisil_parser
from extract import icra as icra_parser
from extract import india_ratings as ir_parser

BASE = Path(__file__).parent
DEBUG_DIR = BASE / "captures" / "_fetch_debug"
DOCS_DIR = BASE / "captures" / "_fetch_docs"

VALIDATION_ENTITIES = [
    "Bajaj Finance Limited",
    "Cholamandalam Investment And Finance Company Limited",
    "Power Finance Corporation Limited",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
}

IR_BASE = "https://www.indiaratings.co.in"
ICRA_BASE = "https://www.icra.in"
CRISIL_BASE = "https://www.crisilratings.com"

# How many of the most recent press releases to pull per entity per source.
MAX_DOCS_PER_ENTITY = 2
POLITE_DELAY_SECONDS = 1.5


def _save_debug(name: str, content: bytes | str) -> str:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    path = DEBUG_DIR / name
    if isinstance(content, str):
        path.write_text(content, errors="ignore")
    else:
        path.write_bytes(content)
    return str(path.relative_to(BASE))


def _save_doc(name: str, content: bytes) -> Path:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    path = DOCS_DIR / name
    path.write_bytes(content)
    return path


def _name_matches(candidate: str, entity: dict) -> bool:
    """Is this search hit actually our entity, not a similarly-named one?"""
    if not candidate:
        return False
    cand = re.sub(r"[^a-z0-9 ]", " ", candidate.lower())
    cand = re.sub(r"\s+", " ", cand).strip()
    names = [entity["name"]] + entity["aliases"]
    for name in names:
        n = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())
        n = re.sub(r"\s+", " ", n).strip()
        if n and (n == cand or n in cand or cand in n):
            return True
    return False


# --------------------------------------------------------------------------
# India Ratings
# --------------------------------------------------------------------------

def fetch_india_ratings(session, entity: dict) -> list[dict]:
    name = entity["name"]
    resp = session.get(f"{IR_BASE}/home/GetSearch",
                       params={"searchKey": name}, timeout=45)
    if resp.status_code != 200:
        print(f"    [IR] search HTTP {resp.status_code}")
        _save_debug(f"ir_search_{entity['id']}.txt", resp.text)
        return []

    try:
        payload = resp.json()
    except ValueError:
        _save_debug(f"ir_search_{entity['id']}.txt", resp.text)
        print("    [IR] search did not return JSON")
        return []

    releases = [
        pr for pr in payload.get("pressreleaseList") or []
        if _name_matches(pr.get("issuerName", ""), entity)
    ]
    if not releases:
        print(f"    [IR] no press releases matched '{name}'")
        return []

    releases.sort(key=lambda pr: pr.get("pressReleaseID") or 0, reverse=True)
    records = []
    for pr in releases[:MAX_DOCS_PER_ENTITY]:
        pr_id = pr.get("pressReleaseID")
        title = pr.get("pressReleaseTitle") or ""
        fac = session.get(f"{IR_BASE}/pressReleases/GetBankFacilityDataRatingLetter",
                          params={"pressReleaseId": pr_id}, timeout=45)
        if fac.status_code != 200:
            print(f"    [IR] facility data HTTP {fac.status_code} for PR {pr_id}")
            continue
        try:
            facilities = fac.json()
        except ValueError:
            _save_debug(f"ir_facility_{pr_id}.txt", fac.text)
            continue

        doc_path = _save_doc(f"india_ratings_{pr_id}.json", fac.content)
        parsed = ir_parser.parse(
            entity["name"], entity["aliases"],
            json.dumps({"title": title, "facilities": facilities}),
        )
        url = (f"{IR_BASE}/pressReleases/GetBankFacilityDataRatingLetter"
               f"?pressReleaseId={pr_id}")
        for rec in parsed:
            rec["_source_url"] = url
            rec["_pub_date"] = rec.get("record_date")
            rec["_doc_path"] = str(doc_path)
            rec["_raw_text"] = fac.text
        print(f"    [IR] PR {pr_id} ({pr.get('prDate')}): {len(parsed)} records")
        records.extend(parsed)
        time.sleep(POLITE_DELAY_SECONDS)
    return records


# --------------------------------------------------------------------------
# ICRA
# --------------------------------------------------------------------------

def _icra_token(session) -> str | None:
    resp = session.get(f"{ICRA_BASE}/", timeout=45)
    soup = BeautifulSoup(resp.text, "html.parser")
    field = soup.find("input", attrs={"name": "__RequestVerificationToken"})
    if field and field.get("value"):
        return field["value"]
    _save_debug("icra_home_no_token.html", resp.text)
    return None


def fetch_icra(session, entity: dict) -> list[dict]:
    token = _icra_token(session)
    if not token:
        print("    [ICRA] no __RequestVerificationToken on the home page")
        return []

    resp = session.post(
        f"{ICRA_BASE}/Home/PostGlobalSearchIndex",
        data={
            "__RequestVerificationToken": token,
            "KeyWord": entity["name"],
            "PageType": "Rating",
            "pageNumber": 1,
        },
        headers={"X-Requested-With": "XMLHttpRequest"},
        timeout=45,
    )
    if resp.status_code != 200:
        print(f"    [ICRA] search HTTP {resp.status_code}")
        _save_debug(f"icra_search_{entity['id']}.html", resp.text)
        return []

    # The response is an HTML fragment; rationale PDFs are linked by report id.
    ids = re.findall(r"GetRationalReportFilePdf\?id=(\d+)", resp.text)
    if not ids:
        ids = re.findall(r"ShowRationalReportFilePdf/(\d+)", resp.text)
    if not ids:
        path = _save_debug(f"icra_search_{entity['id']}.html", resp.text)
        print(f"    [ICRA] no rationale ids in search response -> {path}")
        return []

    records = []
    for report_id in list(dict.fromkeys(ids))[:MAX_DOCS_PER_ENTITY]:
        url = f"{ICRA_BASE}/Rating/GetRationalReportFilePdf?id={report_id}"
        doc = session.get(url, timeout=90)
        if doc.status_code != 200 or not doc.content.startswith(b"%PDF"):
            print(f"    [ICRA] report {report_id} was not a PDF "
                  f"(HTTP {doc.status_code})")
            continue
        doc_path = _save_doc(f"icra_{report_id}.pdf", doc.content)
        parsed = icra_parser.parse(entity["name"], entity["aliases"], str(doc_path))
        for rec in parsed:
            rec["_source_url"] = url
            rec["_pub_date"] = rec.get("record_date")
            rec["_doc_path"] = str(doc_path)
            rec["_raw_text"] = doc.content.decode("latin-1")
        print(f"    [ICRA] report {report_id}: {len(parsed)} records")
        records.extend(parsed)
        time.sleep(POLITE_DELAY_SECONDS)
    return records


# --------------------------------------------------------------------------
# CRISIL (browser-driven search; its HTTP search endpoint returns 500)
# --------------------------------------------------------------------------

def _crisil_rationale_urls(entity: dict) -> list[str]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("    [CRISIL] playwright not installed; skipping discovery")
        return []

    urls = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent=HEADERS["User-Agent"])
        try:
            page.goto(f"{CRISIL_BASE}/en/home/our-business/ratings/"
                      "company-factsheet.html", timeout=60000)
            page.wait_for_timeout(3000)

            # Selector is unverified from the sandbox, so several plausible
            # ones are tried and the rendered page is saved when none work,
            # giving the next iteration real evidence to work from.
            candidates = [
                "input#input_search", "input#global-search-id",
                "input[type='search']", "input[placeholder*='Search']",
                ".global-search-class input",
            ]
            filled = False
            for sel in candidates:
                try:
                    if page.locator(sel).count():
                        page.fill(sel, entity["name"], timeout=8000)
                        page.keyboard.press("Enter")
                        filled = True
                        print(f"    [CRISIL] searched via {sel!r}")
                        break
                except Exception:
                    continue

            if not filled:
                _save_debug(f"crisil_search_page_{entity['id']}.html", page.content())
                print("    [CRISIL] could not find the search input; page saved")
                browser.close()
                return []

            page.wait_for_timeout(6000)
            html = page.content()
            _save_debug(f"crisil_results_{entity['id']}.html", html)

            for href in re.findall(r'href=["\']([^"\']*RatingDocs/[^"\']+)["\']', html):
                urls.append(href if href.startswith("http") else CRISIL_BASE + href)

            if not urls:
                for link in page.locator("a").all():
                    href = link.get_attribute("href") or ""
                    if "RatingDocs" in href:
                        urls.append(href if href.startswith("http")
                                    else CRISIL_BASE + href)
        except Exception as exc:
            print(f"    [CRISIL] browser discovery failed: {exc}")
        finally:
            browser.close()

    return list(dict.fromkeys(urls))


def fetch_crisil(session, entity: dict) -> list[dict]:
    urls = _crisil_rationale_urls(entity)
    if not urls:
        print("    [CRISIL] no rationale URLs discovered")
        return []

    records = []
    for url in urls[:MAX_DOCS_PER_ENTITY]:
        resp = session.get(url, timeout=60)
        if resp.status_code != 200:
            print(f"    [CRISIL] HTTP {resp.status_code} for {url}")
            continue
        doc_name = re.sub(r"[^A-Za-z0-9_.-]", "_", url.split("/")[-1])[:120]
        doc_path = _save_doc(f"crisil_{doc_name}", resp.content)
        parsed = crisil_parser.parse(entity["name"], entity["aliases"], resp.text)
        for rec in parsed:
            rec["_source_url"] = url
            rec["_pub_date"] = rec.get("record_date")
            rec["_doc_path"] = str(doc_path)
            rec["_raw_text"] = resp.text
        print(f"    [CRISIL] {url.split('/')[-1][:60]}: {len(parsed)} records")
        records.extend(parsed)
        time.sleep(POLITE_DELAY_SECONDS)
    return records


FETCHERS = {
    "India Ratings": fetch_india_ratings,
    "ICRA": fetch_icra,
    "CRISIL": fetch_crisil,
}


def store(conn, entity: dict, source: str, records: list[dict]) -> int:
    fetched_at = datetime.now(timezone.utc).isoformat()
    stored = 0
    for rec in records:
        raw_text = rec.pop("_raw_text", "")
        url = rec.pop("_source_url", None)
        doc_path = rec.pop("_doc_path", None)
        pub_date = rec.pop("_pub_date", None)

        press_release_id = db.upsert_press_release(
            conn, entity_id=entity["id"], source=source, url=url,
            pub_date=pub_date, fetched_at=fetched_at,
            storage_path=doc_path, raw_text=raw_text,
        )
        rec.setdefault("provenance", None)
        rec.setdefault("row_seq", None)
        rec.setdefault("is_sublimit", 0)
        rec.setdefault("previous_amount_rs_cr", None)
        rec["entity_id"] = entity["id"]
        rec["source"] = source
        rec["press_release_id"] = press_release_id
        rec["extracted_at"] = fetched_at
        if db.upsert_rating_record(conn, rec) != "duplicate_skipped":
            stored += 1
    return stored


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--all", action="store_true", help="Every entity in entities.csv")
    parser.add_argument("--entity", action="append", help="Specific entity name (repeatable)")
    parser.add_argument("--sources", nargs="+", default=list(FETCHERS),
                        choices=list(FETCHERS))
    parser.add_argument("--limit", type=int, help="Cap the number of entities")
    args = parser.parse_args()

    db.init_db()
    with db.get_conn() as conn:
        all_rows = db.list_entities(conn)
        entities = []
        for row in all_rows:
            entities.append({
                "id": row["id"],
                "name": row["name"],
                "aliases": [a.strip() for a in row["aliases"].split(",") if a.strip()],
            })

    if args.entity:
        wanted = {e.lower() for e in args.entity}
        entities = [e for e in entities if e["name"].lower() in wanted]
    elif not args.all:
        wanted = {e.lower() for e in VALIDATION_ENTITIES}
        entities = [e for e in entities if e["name"].lower() in wanted]

    if args.limit:
        entities = entities[:args.limit]

    if not entities:
        print("No matching entities. Check entities.csv / --entity spelling.")
        return 1

    print(f"Fetching {len(entities)} entit{'y' if len(entities)==1 else 'ies'} "
          f"from {', '.join(args.sources)}\n")

    session = requests.Session()
    session.headers.update(HEADERS)

    summary = {}
    for entity in entities:
        print(f"== {entity['name']}")
        for source in args.sources:
            try:
                records = FETCHERS[source](session, entity)
            except Exception as exc:
                print(f"    [{source}] fetch failed: {exc}")
                traceback.print_exc()
                records = []
            if records:
                with db.get_conn() as conn:
                    stored = store(conn, entity, source, records)
                print(f"    [{source}] stored {stored} new record(s)")
                summary[source] = summary.get(source, 0) + stored
            time.sleep(POLITE_DELAY_SECONDS)
        print()

    print("=== summary ===")
    for source in args.sources:
        print(f"  {source}: {summary.get(source, 0)} new record(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
