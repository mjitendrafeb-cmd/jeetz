"""NSDL India Bond Info — new debt issuance data (CBDServices public API).

Data source discovered from the CBDServices Angular app on
https://www.indiabondinfo.nsdl.com/ ("Recent Issues" under Bond Data Reports):

  GET /portal-config/portal-cbd.json          -> {"cbdApiPrefixURL": "/bds-service/v1", ...}
  GET {prefix}/public/bdsinfo/newbondissues   -> [{isin, companyName, issueSize (Rs cr),
                                                  allotmentDate DD-MM-YYYY, maturityDate}]
  GET {prefix}/public/bdsinfo/currentissuance -> FY totals {issueSize, noOfIsin, dataForYear}
  GET {prefix}/public/bdsinfo/issuancedashboard -> quarterly totals
  GET {prefix}/public/bdsinfo/instruments?isin=X  / {prefix}/public/isins?isin=X
        -> instrument details (coupon, rating, ... shape varies; harvested defensively)

Run standalone for a console dump: python fetch_nsdl_issuance.py
"""

import datetime
import json
import os
import re

import requests

BASE = "https://www.indiabondinfo.nsdl.com"
FALLBACK_PREFIX = "/bds-service/v1"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": BASE + "/CBDServices/",
}


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def _get_json(session, url, params=None, timeout=(10, 30)):
    r = session.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _api_prefix(session) -> str:
    try:
        cfg = _get_json(session, BASE + "/portal-config/portal-cbd.json")
        prefix = cfg.get("cbdApiPrefixURL") or FALLBACK_PREFIX
    except Exception as exc:
        print(f"[nsdl_issuance] portal-config failed ({exc}); using fallback prefix")
        prefix = FALLBACK_PREFIX
    if prefix.startswith("/"):
        prefix = BASE + prefix
    return prefix.rstrip("/")


def _parse_date(s: str):
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.datetime.strptime(s.strip(), fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


def _tenure_years(allot, maturity):
    if not allot or not maturity:
        return None
    return round((maturity - allot).days / 365.25, 1)


_COUPON_KEY = re.compile(r"coupon|interest.?rate", re.IGNORECASE)
_RATING_KEY = re.compile(r"rating", re.IGNORECASE)
_INSTR_KEY = re.compile(r"instrument.?(type|desc)|security.?type", re.IGNORECASE)
_FREQ_KEY = re.compile(r"freq|frequency", re.IGNORECASE)


def _harvest(obj, out):
    """Recursively pull coupon/rating/instrument-type fields out of unknown JSON."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                _harvest(v, out)
                continue
            if v in (None, "", "null", "NA", "N.A."):
                continue
            sv = str(v).strip()
            if _COUPON_KEY.search(k) and "coupon" not in out:
                m = re.search(r"\d+(?:\.\d+)?", sv)
                if m and 0 < float(m.group()) < 40:
                    out["coupon"] = float(m.group())
                elif sv and not sv.isdigit():
                    out.setdefault("coupon_text", sv[:60])
            elif _RATING_KEY.search(k) and len(sv) < 80:
                out.setdefault("ratings", [])
                if sv not in out["ratings"] and not sv.replace(".", "").isdigit():
                    out["ratings"].append(sv)
            elif _INSTR_KEY.search(k) and "instrument" not in out:
                out["instrument"] = sv[:80]
            elif _FREQ_KEY.search(k) and "frequency" not in out:
                out["frequency"] = sv[:40]
    elif isinstance(obj, list):
        for it in obj:
            _harvest(it, out)


def _isin_details(session, prefix, isin, debug=False):
    detail = {}
    for path, params in ((f"{prefix}/public/bdsinfo/instruments", {"isin": isin}),
                         (f"{prefix}/public/isins", {"isin": isin})):
        try:
            data = _get_json(session, path, params)
        except Exception as exc:
            if debug:
                print(f"[nsdl_issuance] {path}?isin={isin} failed: {exc}")
            continue
        if debug:
            print(f"[nsdl_issuance] {path}?isin={isin} -> {json.dumps(data)[:1000]}")
        _harvest(data, detail)
        if "coupon" in detail and "ratings" in detail:
            break
    return detail


def fetch_new_issuances(debug: bool = False) -> dict:
    """Return {"issues": [...], "fy_total": {...}, "quarters": [...]}.

    Each issue: {isin, issuer, issue_size_cr, allotment_date, maturity_date,
                 tenure_years, coupon, ratings, instrument, frequency}
    """
    session = _session()
    prefix = _api_prefix(session)
    print(f"[nsdl_issuance] API prefix: {prefix}")

    raw = _get_json(session, f"{prefix}/public/bdsinfo/newbondissues")
    issues = []
    for rec in raw or []:
        allot = _parse_date(rec.get("allotmentDate", ""))
        mat = _parse_date(rec.get("maturityDate", ""))
        issue = {
            "isin": rec.get("isin", ""),
            "issuer": (rec.get("companyName") or "").strip(),
            "issue_size_cr": float(rec.get("issueSize") or 0),
            "allotment_date": allot,
            "maturity_date": mat,
            "tenure_years": _tenure_years(allot, mat),
        }
        issue.update(_isin_details(session, prefix, issue["isin"], debug=debug))
        issues.append(issue)

    fy_total, quarters = {}, []
    try:
        fy_total = _get_json(session, f"{prefix}/public/bdsinfo/currentissuance")
    except Exception as exc:
        print(f"[nsdl_issuance] currentissuance failed: {exc}")
    try:
        quarters = _get_json(session, f"{prefix}/public/bdsinfo/issuancedashboard")
    except Exception as exc:
        print(f"[nsdl_issuance] issuancedashboard failed: {exc}")

    issues.sort(key=lambda x: (x["allotment_date"] or datetime.date.min, -x["issue_size_cr"]),
                reverse=True)
    return {"issues": issues, "fy_total": fy_total, "quarters": quarters}


if __name__ == "__main__":
    data = fetch_new_issuances(debug=True)
    for i in data["issues"]:
        print(i)
    print(data["fy_total"])
    print(data["quarters"])
