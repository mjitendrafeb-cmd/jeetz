"""One-time backfill for data/team_company_history.json from the existing
docs/archive/*.html editions -- run once at rollout of the "first mention"
S1 flag so day-1 doesn't wrongly flag every already-familiar watchlist
company as brand new. Only scans each archive's S1 block (the company
column there is a real company name; S2/S3 use category labels like
"General", which must not be seeded in as if they were companies).

Usage: python3 scripts/backfill_company_history.py
"""

import glob
import json
import os
import re

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ARCHIVE_GLOB = os.path.join(_ROOT, "docs", "archive", "*.html")
_OUT_PATH = os.path.join(_ROOT, "data", "team_company_history.json")

_COMPANY_RE = re.compile(r'class="company">([^<&]+)')


def _s1_block(html: str) -> str:
    s1 = re.search(r'id=["\']s1["\']', html)
    s2 = re.search(r'id=["\']s2["\']', html)
    if not s1:
        return ""
    end = s2.start() if s2 else len(html)
    return html[s1.start():end]


def main() -> None:
    history: dict[str, str] = {}
    for path in sorted(glob.glob(_ARCHIVE_GLOB)):
        date = os.path.splitext(os.path.basename(path))[0]
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            continue
        with open(path, encoding="utf-8") as f:
            html = f.read()
        for m in _COMPANY_RE.finditer(_s1_block(html)):
            company = m.group(1).strip()
            if company and company not in history:
                history[company] = date
    with open(_OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, sort_keys=True)
    print(f"Backfilled {len(history)} companies from "
          f"{len(glob.glob(_ARCHIVE_GLOB))} archive editions -> {_OUT_PATH}")


if __name__ == "__main__":
    main()
