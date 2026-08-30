"""One-off driver: extract articles from a newspaper e-paper PDF and run
them through the SAME S1/S2/S3 classification the daily pipeline uses on
every other source (watchlist company matching, junk/geography/relevance
filters, sector and macro keywords) -- purely mechanical, no AI API call.

Usage: python3 scripts/classify_newspaper_pdf.py <pdf_path>
"""

import sys

import extract_newspaper_pdf as ex
import send_team_news as tn


def main(pdf_path: str) -> None:
    articles = ex.extract_all(pdf_path)
    print(f"[classify] {len(articles)} articles extracted from PDF\n")

    team = tn._load_team()
    rows = [r for r in team.get("rows", []) if r.get("company", "").strip()]
    company_phrases = [r["company"] for r in rows]
    sectors = team.get("sectors", {})
    macro_kw = team.get("macro_keywords", [])

    results = {"S1": [], "S2": [], "S3": [], None: []}
    for a in articles:
        it = {
            "tags": "",
            "source": "Newspaper PDF (BS Mumbai)",
            "title": a["headline"],
            "summary": a["body"][:220],
            "wl_company": "",
            "url": f"pdf-page-{a['page']}",
            "pub": a["dateline"],
        }
        companies = tn._match_companies(it, rows)
        if companies:
            it["companies"] = companies
            it["section"] = "S1"
        else:
            it["section"] = tn._classify_team(it, company_phrases, sectors, macro_kw)
        results[it["section"]].append((it, companies))

    for sec in ("S1", "S2", "S3"):
        print(f"=== {sec} ({len(results[sec])}) ===")
        for it, companies in results[sec]:
            tag = f" [{', '.join(companies)}]" if companies else ""
            print(f"  p{it['url'].split('-')[-1]} | {it['title'][:90]}{tag}")
        print()

    dropped = results[None]
    print(f"=== Dropped / not relevant ({len(dropped)}) ===")
    for it, _ in dropped:
        print(f"  p{it['url'].split('-')[-1]} | {it['title'][:90]}")


if __name__ == "__main__":
    main(sys.argv[1])
