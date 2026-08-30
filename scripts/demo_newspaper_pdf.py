"""Renders the newspaper-PDF-extracted items through the REAL newsletter
template (same _np_partb/_html_to_pdf functions the daily send uses) so
they can be previewed exactly as a recipient would see them, instead of
just the console listing classify_newspaper_pdf.py prints.

One-off preview only -- writes a PDF to /tmp, does not send mail, does not
touch any production data file.

Usage: python3 scripts/demo_newspaper_pdf.py <pdf_path> <output_pdf_path>
"""

import datetime
import sys

import extract_newspaper_pdf as ex
import send_team_news as tn


def build_items(pdf_path: str) -> list[dict]:
    articles = ex.extract_all(pdf_path)
    team = tn._load_team()
    rows = [r for r in team.get("rows", []) if r.get("company", "").strip()]
    company_phrases = [r["company"] for r in rows]
    sectors = team.get("sectors", {})
    macro_kw = team.get("macro_keywords", [])

    items = []
    for a in articles:
        it = {
            "tags": "",
            "source": "Newspaper PDF (BS Mumbai)",
            "title": a["headline"],
            "summary": a["body"][:220],
            "wl_company": "",
            "url": "",
            "pub": a["dateline"],
            "companies": [],
        }
        companies = tn._match_companies(it, rows)
        if companies:
            it["companies"] = companies
            it["section"] = "S1"
        else:
            it["section"] = tn._classify_team(it, company_phrases, sectors, macro_kw)
        if it["section"]:
            items.append(it)

    # This particular PDF had zero real watchlist hits -- add one clearly
    # labelled illustrative S1 row so the preview shows what that table
    # looks like too, rather than an S1 page that's just "no news today".
    if not any(it["section"] == "S1" for it in items):
        demo_company = rows[0]["company"] if rows else "Demo Watchlist Entity"
        items.append({
            "tags": "", "source": "Newspaper PDF (BS Mumbai) -- ILLUSTRATIVE, not a real story",
            "title": f"[DEMO ROW] {demo_company} raises fresh NCDs to fund expansion",
            "summary": "Illustrative placeholder showing the S1 table layout -- "
                        "this PDF's own content had no real watchlist match today.",
            "wl_company": "", "url": "", "pub": "", "section": "S1",
            "companies": [demo_company],
        })

    tn._tag_categories(items)
    return items


def main(pdf_path: str, out_path: str) -> None:
    items = build_items(pdf_path)
    by_section = {"S2": [it for it in items if it["section"] == "S2"],
                  "S3": [it for it in items if it["section"] == "S3"]}
    all_companies = {c for it in items for c in it.get("companies", [])}
    person = {
        "name": "Newspaper PDF Preview",
        "sections": {"S1", "S2", "S3"},
        "companies": all_companies,
    }
    html, total, _chosen = tn._np_partb(person, items, by_section)
    today = datetime.date.today()
    full_html = tn._np_build_attachment(
        html, today, for_name="Newspaper PDF Preview",
        coverage_note="Demo: items extracted from an uploaded newspaper PDF")
    pdf = tn._html_to_pdf(full_html)
    if pdf is None:
        print("PDF render failed -- writing HTML instead")
        with open(out_path.replace(".pdf", ".html"), "w") as f:
            f.write(full_html)
        return
    with open(out_path, "wb") as f:
        f.write(pdf)
    print(f"Wrote {out_path} ({len(pdf)//1024} KB), {total} stories shown")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
