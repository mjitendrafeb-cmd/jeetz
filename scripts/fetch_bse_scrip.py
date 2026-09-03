"""fetch_bse_scrip.py — BSE corporate announcements via the per-scrip JSON API.

    GET https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w
        ?pageno=1&strCat=-1&strPrevDate=YYYYMMDD&strToDate=YYYYMMDD
        &strScrip=<scrip>&strSearch=P&strType=C&subcategory=-1

Pilot source, run ADDITIONALLY alongside fetch_web.fetch_bse_rss(), not as
a replacement -- fetch_bse.py's earlier attempt at this same API (bulk,
strScrip="") was confirmed dead in production ("JSON decode failed", 0 rows
from both endpoints on every run) and removed. That failure mode is not
proof this per-scrip, rate-limited shape fails too: a real, differently-
shaped implementation of this exact API (per-entity, 1.5s pacing between
requests) was confirmed working from the same class of environment
(GitHub Actions, ubuntu-latest) via its own committed run history as
recently as the last few days. This module carries that same shape over,
scoped to a small pilot list first (see data/bse_scrip_pilot.json) so it
can be validated against real production logs before any wider rollout.

Only equity-listed pilot entities are covered here -- one scrip code per
company. Debt-only NBFC issuers routinely have MANY scrip codes, one per
NCD series (confirmed: Auxilo Finserve alone has at least two, 974066 and
959662, for two different bond series) -- mapping those needs a separate,
harder pass (BSE's debt-securities master list, not the equity one) and
is deliberately out of scope for this pilot.
"""

import datetime
import json
import os
import re
import time

import requests

_API = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
_ATTACH_LIVE = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/"
_ATTACH_HIST = "https://www.bseindia.com/xml-data/corpfiling/AttachHis/"

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIP_MAP_PATH = os.path.join(_REPO_ROOT, "data", "bse_scrip_pilot.json")

# Mirrors the header shape confirmed working in production for this exact
# API (bfsi-platform/scrapers/bse.py) -- notably simpler than the earlier
# dead attempt's cookie-priming approach, and that simpler version is the
# one with real recent successful runs, not the elaborate one.
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Referer": "https://www.bseindia.com/",
}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def load_scrip_map(path: str = _SCRIP_MAP_PATH) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        print(f"[fetch_bse_scrip] scrip map load failed: {exc}")
        return {}


def _parse_date(v: str | None) -> datetime.date | None:
    if not v:
        return None
    try:
        return datetime.datetime.fromisoformat(v[:19]).date()
    except ValueError:
        return None


def fetch_for_scrip(session: requests.Session, scrip: str, company: str,
                     since: datetime.date, debug: bool = False) -> list[dict]:
    """One company's announcements since `since`. Fails open: any error
    here costs only this one company, never the whole pilot run."""
    params = {
        "pageno": 1, "strCat": "-1", "subcategory": "-1",
        "strPrevDate": since.strftime("%Y%m%d"),
        "strToDate": datetime.date.today().strftime("%Y%m%d"),
        "strScrip": scrip, "strSearch": "P", "strType": "C",
    }
    try:
        r = session.get(_API, params=params, headers=_HEADERS, timeout=30)
    except Exception as exc:
        print(f"[fetch_bse_scrip] {company} ({scrip}): request failed — {exc}")
        return []
    ctype = (r.headers.get("Content-Type") or "").lower()
    if r.status_code != 200:
        print(f"[fetch_bse_scrip] {company} ({scrip}): HTTP {r.status_code}")
        return []
    if "json" not in ctype:
        head = (r.text or "")[:80].replace("\n", " ")
        print(f"[fetch_bse_scrip] {company} ({scrip}): not JSON "
              f"(Content-Type={ctype or 'none'}) — likely a bot-block page: {head!r}")
        return []
    try:
        data = r.json()
    except Exception as exc:
        print(f"[fetch_bse_scrip] {company} ({scrip}): JSON decode failed — {exc}")
        return []

    rows = data.get("Table") if isinstance(data, dict) else None
    rows = rows or []
    out = []
    for row in rows:
        dt = _parse_date(row.get("NEWS_DT"))
        if dt is None or dt < since:
            continue
        subj = _clean(row.get("NEWSSUB") or row.get("HEADLINE") or "")
        if not subj:
            continue
        attach = (row.get("ATTACHMENTNAME") or "").strip()
        out.append({
            "company": company,
            "scrip": scrip,
            "title": subj,
            "category": _clean(row.get("CATEGORYNAME") or ""),
            "pub_date": dt,
            "url": _ATTACH_LIVE + attach if attach else "",
            "attachment_name": attach,
        })
    if debug or rows:
        print(f"[fetch_bse_scrip] {company} ({scrip}): raw={len(rows)} kept={len(out)}")
    return out


def fetch_pilot(lookback_days: int = 2, pace_seconds: float = 1.5,
                 debug: bool = False) -> list[dict]:
    """All pilot companies' announcements since `lookback_days` ago.
    Paced deliberately (default 1.5s between requests, matching the
    confirmed-working reference implementation) -- polite to BSE's
    servers and a more human-like traffic pattern than one bulk request,
    which is the shape that got bot-blocked on every run previously."""
    scrip_map = load_scrip_map()
    if not scrip_map:
        return []
    since = datetime.date.today() - datetime.timedelta(days=lookback_days)
    session = requests.Session()
    all_items = []
    for i, (company, scrip) in enumerate(scrip_map.items()):
        all_items.extend(fetch_for_scrip(session, scrip, company, since, debug=debug))
        if i < len(scrip_map) - 1:
            time.sleep(pace_seconds)
    print(f"[fetch_bse_scrip] pilot run: {len(scrip_map)} companies, "
          f"{len(all_items)} announcement(s) since {since}")
    return all_items


if __name__ == "__main__":
    for it in fetch_pilot(debug=True):
        print(it)
