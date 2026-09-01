"""One-off preview: renders the S1 "first mention" flag and S2 "Affects
your entities" tag through the real newsletter template, using a mix of
real watchlist companies and illustrative headline text (clearly labelled)
so the layout can be checked without waiting for a real day's news to
happen to contain both cases.

Usage: python3 scripts/demo_new_features.py <output_pdf_path>
"""

import datetime
import sys

import send_team_news as tn


def main(out_path: str) -> None:
    team = tn._load_team()
    rows = [r for r in team.get("rows", []) if r.get("company", "").strip()]
    history = tn._load_company_history()

    # Pick a company NOT in history (a real first-mention case) and two
    # companies sharing a sector (for the "Affects" cross-reference).
    never_seen = next(r for r in rows if r["company"] not in history)
    familiar = next(r for r in rows if r["company"] in history)
    same_sector = [r for r in rows if r.get("sector") == familiar.get("sector")][:3]

    items = [
        {
            "tags": "WATCHLIST", "source": "BSE Announcement",
            "title": f"{never_seen['company']} allots NCDs worth Rs 150 crore",
            "summary": "ILLUSTRATIVE headline -- demonstrates the first-mention badge.",
            "url": "https://example.com", "pub": "01 Sep 2026",
            "companies": [never_seen["company"]], "section": "S1",
        },
        {
            "tags": "WATCHLIST", "source": "ET BFSI",
            "title": f"{familiar['company']} reports steady Q1 collections",
            "summary": "ILLUSTRATIVE headline -- a familiar company, no badge.",
            "url": "https://example.com", "pub": "01 Sep 2026",
            "companies": [familiar["company"]], "section": "S1",
        },
        {
            "tags": "", "source": "RBI Circular",
            "title": f"RBI tightens exposure norms for {familiar.get('sector','BFSI')} lenders",
            "summary": "ILLUSTRATIVE headline -- demonstrates the Affects-your-entities tag.",
            "url": "https://example.com", "pub": "01 Sep 2026",
            "section": "S2", "sectors": {familiar.get("sector", tn._DEFAULT_SECTOR)},
            "category": "Regulatory & Policy", "companies": [],
        },
    ]
    tn._tag_categories(items)

    by_section = {"S2": [it for it in items if it["section"] == "S2"], "S3": []}
    new_companies = {never_seen["company"]}
    company_sector = {r["company"]: tn._row_sector(r) for r in rows}
    person = {
        "name": "Feature Preview",
        "sections": {"S1", "S2", "S3"},
        "companies": {r["company"] for r in same_sector} | {never_seen["company"], familiar["company"]},
        "sectors": {familiar.get("sector", tn._DEFAULT_SECTOR)},
    }
    html, total, _chosen = tn._np_partb(person, items, by_section,
                                         new_companies=new_companies,
                                         company_sector=company_sector)
    today = datetime.date.today()
    full_html = tn._np_build_attachment(
        html, today, for_name="Feature Preview",
        coverage_note="Demo: first-mention flag + Affects-your-entities tag")
    pdf = tn._html_to_pdf(full_html)
    with open(out_path, "wb") as f:
        f.write(pdf)
    print(f"Wrote {out_path} ({len(pdf)//1024} KB), {total} stories shown")
    print(f"first-mention company: {never_seen['company']}")
    print(f"affects companies (same sector, {familiar.get('sector')}): "
          f"{[r['company'] for r in same_sector]}")


if __name__ == "__main__":
    main(sys.argv[1])
