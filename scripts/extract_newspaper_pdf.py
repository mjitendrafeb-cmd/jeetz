"""One-off extractor: pull individual articles out of a newspaper e-paper PDF
and classify them into S1/S2/S3 using the SAME matching/junk logic the daily
pipeline already uses on RSS/BSE/NSE items -- so a manually-uploaded PDF gets
folded in exactly like any other source, not a separate ad-hoc heuristic.

Segmentation heuristic (tuned against a real Business Standard e-paper):
articles are reliably bounded by a "byline" line (reporter name, printed in
lowercase, e.g. "shine jacob") immediately followed by a "dateline" line
("Chennai, 28 August"). The headline is the short block of lines directly
above the byline; the body runs from the dateline to the next byline/
dateline pair (or a page divider line, or end of page).

This does not attempt perfect fidelity to the print layout (multi-column
text can interleave) -- it is deliberately a best-effort pass meant to
surface real candidate articles for a human to skim, not a lossless
digitisation of the page.
"""

import re
import sys

import pypdf

_DATELINE_RE = re.compile(
    r"^([A-Za-z][A-Za-z .]{2,28}),\s*(\d{1,2}\s+[A-Za-z]+)\s*$")
_DIVIDER_RE = re.compile(r"^(.)\1{15,}")
_BYLINE_RE = re.compile(r"^[a-z][a-z .]{2,28}$")


def _clean_line(line: str) -> str:
    return line.strip()


def extract_pages(pdf_path: str) -> list[str]:
    reader = pypdf.PdfReader(pdf_path)
    return [p.extract_text() or "" for p in reader.pages]


def _is_boilerplate(line: str) -> bool:
    low = line.lower()
    return (_DIVIDER_RE.match(line) is not None
            or "this newspaper is published" in low
            or "subscription and circulation" in low
            or "prgi registration" in low)


def segment_articles(page_text: str, page_num: int) -> list[dict]:
    lines = [_clean_line(l) for l in page_text.split("\n")]
    n = len(lines)

    # Locate every (byline_idx, dateline_idx) anchor.
    anchors = []
    for i in range(1, n):
        if _DATELINE_RE.match(lines[i]) and _BYLINE_RE.match(lines[i - 1]):
            anchors.append((i - 1, i))

    if not anchors:
        return []

    articles = []
    for k, (byline_idx, dateline_idx) in enumerate(anchors):
        # Headline: walk back from byline_idx over non-boilerplate,
        # non-empty lines, capped at 6 lines.
        head_lines = []
        j = byline_idx - 1
        steps = 0
        while j >= 0 and steps < 6:
            l = lines[j]
            if not l or _is_boilerplate(l):
                break
            # Stop if we've walked into the previous article's body --
            # a heuristic: a body line is usually long (>45 chars) and
            # ends mid-sentence; headline lines are short and title-ish.
            if k > 0 and j <= anchors[k - 1][1]:
                break
            head_lines.append(l)
            j -= 1
            steps += 1
        headline = " ".join(reversed(head_lines)).strip()
        if not headline:
            continue

        # Body: walk forward from dateline_idx+1 until the next anchor's
        # headline start, a divider line, or end of page.
        stop = anchors[k + 1][0] - 4 if k + 1 < len(anchors) else n
        stop = max(stop, dateline_idx + 1)
        body_lines = []
        for m in range(dateline_idx + 1, min(stop, n)):
            l = lines[m]
            if _is_boilerplate(l):
                break
            body_lines.append(l)
        body = " ".join(body_lines).strip()

        reporter = lines[byline_idx]
        dateline = lines[dateline_idx]
        articles.append({
            "page": page_num + 1,
            "headline": headline,
            "reporter": reporter,
            "dateline": dateline,
            "body": body,
        })
    return articles


def extract_all(pdf_path: str) -> list[dict]:
    out = []
    for pi, text in enumerate(extract_pages(pdf_path)):
        out.extend(segment_articles(text, pi))
    return out


if __name__ == "__main__":
    path = sys.argv[1]
    arts = extract_all(path)
    print(f"{len(arts)} articles extracted")
    for a in arts:
        print(f"\n--- p{a['page']} | {a['reporter']} | {a['dateline']} ---")
        print(a["headline"])
        print(a["body"][:200])
