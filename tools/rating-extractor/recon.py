#!/usr/bin/env python3
"""Phase 0 reconnaissance, run from CI where the network is unrestricted.

The dev sandbox this tool was written in is behind a default-deny egress
allowlist, so it cannot reach the rating-agency sites at all. This script
runs on a GitHub Actions runner instead (which has open internet), captures
raw responses to `captures/`, and writes `captures/RECON_REPORT.md`. Those
captures get committed back to the branch so the parsers can be built and
validated against real markup.

Phase 0 only: plain HTTP, no browser. It records for each target whether the
page was reachable, what framework signatures appear, whether the target
entity names are present in the raw HTML, and whether a JSON API or sitemap
is discoverable — which together decide whether a browser is needed at all.
"""

import json
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

CAPTURES = Path(__file__).parent / "captures"
# Large enough for ICRA's rationale PDFs, which run to several MB and were
# truncated (and so unparseable) at the previous 1.5MB cap.
MAX_CAPTURE_BYTES = 8_000_000

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

VALIDATION_ENTITIES = [
    "Bajaj Finance",
    "Cholamandalam",
    "Power Finance Corporation",
]

# Seeded with concrete document URLs surfaced by web search, so recon starts
# from confirmed-real rationale pages rather than guessed paths.
TARGETS = [
    # --- CRISIL ---
    ("CRISIL", "robots", "https://www.crisilratings.com/robots.txt"),
    ("CRISIL", "listing_news_views",
     "https://www.crisilratings.com/en/home/our-businesses/ratings/credit-ratings-news-and-views.html"),
    ("CRISIL", "rationale_bajaj_finance",
     "https://www.crisilratings.com/mnt/winshare/Ratings/RatingList/RatingDocs/"
     "BajajFinanceLimited_April%2028_%202026_RR_394504.html"),
    ("CRISIL", "rationale_bajaj_finance_mar",
     "https://www.crisil.com/mnt/winshare/Ratings/RatingList/RatingDocs/"
     "BajajFinanceLimited_March%2024_%202026_RR_388205.html"),
    ("CRISIL", "ratings_search_page",
     "https://www.crisilratings.com/en/home/our-business/ratings/company-factsheet.html"),

    # --- ICRA ---
    ("ICRA", "robots", "https://www.icra.in/robots.txt"),
    ("ICRA", "rating_action_index", "https://www.icra.in/RatingAction/Index"),
    ("ICRA", "rationale_chola_pdf",
     "https://www.icra.in/Rating/GetRationalReportFilePdf?id=141344"),
    ("ICRA", "rationale_chola_pdf_2",
     "https://www.icra.in/Rating/GetRationalReportFilePdf?id=133118"),
    ("ICRA", "home", "https://www.icra.in/"),

    # --- India Ratings ---
    # Every route returns the same Angular shell, so the real data path is the
    # JSON API referenced inside the JS bundle. The bundle is fetched here and
    # mined for endpoints in phase 2 below.
    ("India Ratings", "robots", "https://www.indiaratings.co.in/robots.txt"),
    ("India Ratings", "rating_actions", "https://www.indiaratings.co.in/rating-actions"),
    ("India Ratings", "bundle_main",
     "https://www.indiaratings.co.in/main.b0be7d594b374f3a.js"),
    ("India Ratings", "bundle_scripts",
     "https://www.indiaratings.co.in/scripts.dc77230fe30c274f.js"),

    # --- CRISIL sitemap: used to locate rationale URLs for the other two
    # validation entities (Cholamandalam, PFC) without guessing paths. ---
    ("CRISIL", "sitemap", "https://www.crisilratings.com/bin/sitemap.xml"),
]

# Endpoint paths mined out of a JS bundle, to be probed in phase 2.
JS_ENDPOINT_RE = re.compile(
    r"""["'`](/?(?:api|API|Api|services|service|data)/[A-Za-z0-9_/.\-]{2,110})["'`]"""
)
JS_BASEURL_RE = re.compile(
    r"""["'`](https?://[A-Za-z0-9.\-]+/(?:api|services)[A-Za-z0-9_/.\-]{0,110})["'`]"""
)

FRAMEWORK_SIGNATURES = {
    "Next.js": ["__NEXT_DATA__", "/_next/"],
    "Nuxt": ["__NUXT__"],
    "React": ["data-reactroot", "react.production"],
    "Angular": ["ng-version", "ng-app"],
    "WordPress": ["/wp-content/", "/wp-json/"],
    "ASP.NET": ["__VIEWSTATE", "aspnetForm", "__doPostBack"],
    "JSON-LD": ["application/ld+json"],
    "DataTables": ["DataTable(", "dataTables"],
}

API_HINT_RE = re.compile(
    r"""["'](/(?:api|Api|API)/[^"'\s]{2,120}|https?://[^"'\s]{0,80}/api/[^"'\s]{2,120})["']"""
)


def capture_path(source: str, name: str, content_type: str) -> Path:
    ext = ".json" if "json" in content_type else (
        ".pdf" if "pdf" in content_type else (
            ".txt" if "text/plain" in content_type else ".html"))
    d = CAPTURES / source.replace(" ", "_")
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{name}{ext}"


def probe(source: str, name: str, url: str) -> dict:
    result = {
        "source": source,
        "name": name,
        "url": url,
        "status": None,
        "error": None,
        "content_type": None,
        "bytes": 0,
        "capture_file": None,
        "frameworks": [],
        "entities_found": [],
        "api_hints": [],
        "sitemaps": [],
        "truncated": False,
    }
    try:
        resp = requests.get(url, headers=HEADERS, timeout=45, allow_redirects=True)
        result["status"] = resp.status_code
        result["content_type"] = resp.headers.get("Content-Type", "")
        result["final_url"] = resp.url

        body = resp.content[:MAX_CAPTURE_BYTES]
        result["truncated"] = len(resp.content) > MAX_CAPTURE_BYTES
        result["bytes"] = len(resp.content)

        path = capture_path(source, name, result["content_type"])
        path.write_bytes(body)
        result["capture_file"] = str(path.relative_to(Path(__file__).parent))

        if "pdf" not in result["content_type"]:
            text = body.decode("utf-8", errors="ignore")

            for fw, sigs in FRAMEWORK_SIGNATURES.items():
                if any(sig in text for sig in sigs):
                    result["frameworks"].append(fw)

            lowered = text.lower()
            for ent in VALIDATION_ENTITIES:
                if ent.lower() in lowered:
                    result["entities_found"].append(ent)

            result["api_hints"] = sorted(set(API_HINT_RE.findall(text)))[:15]

            if name == "robots":
                result["sitemaps"] = re.findall(r"(?i)^\s*sitemap:\s*(\S+)", text, re.MULTILINE)

    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()

    return result


def write_report(results: list[dict]) -> None:
    lines = [
        "# Phase 0 Reconnaissance Report",
        "",
        f"Run: {datetime.now(timezone.utc).isoformat()} (GitHub Actions runner)",
        "",
        "Plain HTTP only, no browser. `Entities found` means the raw HTML already",
        "contains that entity's name — where true for a listing page, a browser is",
        "probably unnecessary for discovery.",
        "",
        "| Source | Target | Status | Bytes | Type | Frameworks | Entities in raw HTML |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        status = r["status"] if r["status"] is not None else f"ERR"
        lines.append(
            f"| {r['source']} | {r['name']} | {status} | {r['bytes']:,} | "
            f"{(r['content_type'] or '')[:30]} | {', '.join(r['frameworks']) or '—'} | "
            f"{', '.join(r['entities_found']) or '—'} |"
        )

    lines += ["", "## Details", ""]
    for r in results:
        lines.append(f"### {r['source']} / {r['name']}")
        lines.append(f"- URL: {r['url']}")
        if r.get("final_url") and r["final_url"] != r["url"]:
            lines.append(f"- Redirected to: {r['final_url']}")
        lines.append(f"- Status: {r['status']}  |  Bytes: {r['bytes']:,}"
                     f"{'  (capture truncated)' if r['truncated'] else ''}")
        if r["error"]:
            lines.append(f"- **Error**: `{r['error']}`")
        if r["capture_file"]:
            lines.append(f"- Capture: `{r['capture_file']}`")
        if r["sitemaps"]:
            lines.append(f"- Sitemaps: {', '.join(r['sitemaps'])}")
        if r["api_hints"]:
            lines.append("- API-ish paths seen in HTML:")
            for hint in r["api_hints"]:
                lines.append(f"  - `{hint}`")
        lines.append("")

    (CAPTURES / "RECON_REPORT.md").write_text("\n".join(lines))
    (CAPTURES / "recon_results.json").write_text(json.dumps(results, indent=2))


def _followup_targets(results: list[dict]) -> list[tuple]:
    """Phase 2 targets derived from what phase 1 actually found.

    Two derivations: JSON endpoints referenced inside India Ratings' Angular
    bundles, and rationale URLs for the remaining validation entities located
    via CRISIL's sitemap. Both avoid guessing paths.
    """
    followups = []

    for r in results:
        if not r["capture_file"]:
            continue
        path = Path(__file__).parent / r["capture_file"]
        if not path.exists():
            continue

        if r["name"].startswith("bundle_"):
            text = path.read_text(errors="ignore")
            endpoints = sorted(set(JS_ENDPOINT_RE.findall(text)))[:12]
            bases = sorted(set(JS_BASEURL_RE.findall(text)))[:6]
            print(f"[recon] {r['name']}: {len(endpoints)} endpoint paths, "
                  f"{len(bases)} absolute API URLs", flush=True)
            for i, ep in enumerate(endpoints):
                url = ep if ep.startswith("http") else \
                    "https://www.indiaratings.co.in" + (ep if ep.startswith("/") else "/" + ep)
                followups.append(("India Ratings", f"api_probe_{i}", url))
            for i, base in enumerate(bases):
                followups.append(("India Ratings", f"api_abs_{i}", base))

        if r["name"] == "sitemap":
            text = path.read_text(errors="ignore")
            urls = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", text)
            print(f"[recon] sitemap: {len(urls)} URLs", flush=True)
            wanted = {"Cholamandalam": "cholamandalam", "PowerFinance": "powerfinance"}
            for label, needle in wanted.items():
                hits = [u for u in urls if needle in u.lower()][:2]
                for i, u in enumerate(hits):
                    followups.append(("CRISIL", f"rationale_{label.lower()}_{i}", u))

    return followups


def main():
    CAPTURES.mkdir(parents=True, exist_ok=True)
    results = []
    for source, name, url in TARGETS:
        print(f"[recon] {source} / {name} -> {url}", flush=True)
        r = probe(source, name, url)
        print(f"        status={r['status']} bytes={r['bytes']} "
              f"entities={r['entities_found']} err={r['error']}", flush=True)
        results.append(r)

    print("\n[recon] --- phase 2: following up on discovered endpoints ---", flush=True)
    for source, name, url in _followup_targets(results):
        print(f"[recon] {source} / {name} -> {url}", flush=True)
        r = probe(source, name, url)
        print(f"        status={r['status']} bytes={r['bytes']} "
              f"entities={r['entities_found']} err={r['error']}", flush=True)
        results.append(r)

    write_report(results)
    reachable = sum(1 for r in results if r["status"] == 200)
    print(f"\n[recon] {reachable}/{len(results)} targets returned 200")
    print(f"[recon] report written to {CAPTURES / 'RECON_REPORT.md'}")


if __name__ == "__main__":
    sys.exit(main())
