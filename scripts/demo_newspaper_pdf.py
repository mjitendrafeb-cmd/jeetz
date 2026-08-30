"""Renders the newspaper-PDF-extracted items into the same newsletter page
frame/CSS the daily send uses (tn._np_build_attachment/_html_to_pdf), with
one deliberate difference from the shared _np_s1_row: a PDF page has no
web URL to link to, so each row shows the actual newspaper clipping
(cropped from the real page raster via extract_newspaper_pdf.clip_articles)
instead of a "Source Link" hyperlink.

One-off preview only -- writes a PDF to /tmp, does not send mail, does not
touch any production data file.

Usage: python3 scripts/demo_newspaper_pdf.py <pdf_path> <output_pdf_path>
"""

import base64
import datetime
import sys

import extract_newspaper_pdf as ex
import send_team_news as tn


def _pdf_row(company_or_category: str, it: dict) -> str:
    """Same table-row shape/CSS classes as tn._np_s1_row (so it inherits
    the real stylesheet), but with the actual newspaper clipping image in
    the link column instead of an <a> -- a PDF page has no web URL to
    link to, so the clipping IS the source reference here."""
    esc = tn._esc
    if it.get("clip_png"):
        b64 = base64.b64encode(it["clip_png"]).decode("ascii")
        link_cell = (f'<img src="data:image/png;base64,{b64}" '
                     f'style="max-width:280px;border:1px solid #ccc;'
                     f'border-radius:3px;" />'
                     f'<div style="font-size:8px;color:#999;margin-top:2px;">'
                     f'p.{it.get("page","?")} &middot; {esc(it.get("pub",""))}</div>')
    else:
        link_cell = (f'<span>{esc(it["title"])}</span>'
                     f'<div style="font-size:8px;color:#999;">no clip found '
                     f'&middot; p.{it.get("page","?")}</div>')
    summary = esc(it["summary"]) or "&mdash;"
    return (f'<tr><td class="company">{esc(company_or_category)}</td>'
            f'<td class="link">{link_cell}</td>'
            f'<td class="summary">{summary}</td></tr>')


def _pdf_section_html(sid: str, sbcls: str, title: str, rows: list[str]) -> str:
    table = ('<div class="s1wrap"><table class="s1tbl">'
             '<thead><tr><th>Company / Category</th><th>Clipping</th>'
             '<th>Summary</th></tr></thead>'
             f'<tbody>{"".join(rows)}</tbody></table></div>'
             if rows else '<p class="empty">No news in this category today.</p>')
    return f'<div id="{sid}" data-section="banner" class="sb {sbcls}">{title}</div>{table}'


def build_items(pdf_path: str) -> list[dict]:
    articles = ex.extract_all(pdf_path)
    ex.clip_articles(pdf_path, articles)
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
            "page": a["page"],
            "clip_png": a.get("clip_png"),
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
            "companies": [demo_company], "page": "-", "clip_png": None,
        })

    tn._tag_categories(items)
    return items


def main(pdf_path: str, out_path: str) -> None:
    items = build_items(pdf_path)
    n_clipped = sum(1 for it in items if it.get("clip_png"))
    print(f"[demo] {n_clipped}/{len(items)} articles matched to a real page clipping")

    s1_items = [it for it in items if it["section"] == "S1"]
    s2_items = [it for it in items if it["section"] == "S2"]
    s3_items = [it for it in items if it["section"] == "S3"]

    sections_html = []
    sections_html.append(_pdf_section_html(
        "s1", "sb1", "&#9733; S1 &mdash; MY RATED ENTITIES &amp; WATCHLIST",
        [_pdf_row(", ".join(it["companies"]) or "Watchlist", it) for it in s1_items]))
    sections_html.append(_pdf_section_html(
        "s2", "sb2", "S2 &mdash; SECTOR &amp; REGULATION",
        [_pdf_row(it.get("category") or "General", it) for it in s2_items]))
    sections_html.append(_pdf_section_html(
        "s3", "sb3", "S3 &mdash; MACROECONOMIC &amp; MARKETS",
        [_pdf_row(it.get("category") or "General", it) for it in s3_items]))
    html = "\n".join(sections_html)
    total = len(items)
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
