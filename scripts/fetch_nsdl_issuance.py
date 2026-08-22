"""NSDL India Bond Info — new debt issuance data (CBDServices public API).

Data source discovered from the CBDServices Angular app on
https://www.indiabondinfo.nsdl.com/ ("Recent Issues" under Bond Data Reports):

  GET /portal-config/portal-cbd.json          -> {"cbdApiPrefixURL": "/bds-service/v1", ...}
  GET {prefix}/public/bdsinfo/newbondissues   -> [{isin, companyName, issueSize (Rs cr),
                                                  allotmentDate DD-MM-YYYY, maturityDate}]
  GET {prefix}/public/bdsinfo/instruments?isin=X  / {prefix}/public/isins?isin=X
        -> instrument details (coupon, rating, ... shape varies; harvested defensively)

Used only by send_team_news.py (7:40 team mail) for S1 new-issuance items —
not wired into the 7:30 report (scripts/send_credit_report.py), which is not
to be modified.

Run standalone for a console dump: python fetch_nsdl_issuance.py
"""

import datetime
import json
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

    # instruments feed: coupon lives at the start of instrumentDesc
    # ("7.8324% SECURED RATED LISTED REDEEMABLE NON CONVERTIBLE DEBENTURE ...")
    try:
        data = _get_json(session, f"{prefix}/public/bdsinfo/instruments", {"isin": isin})
        if debug:
            print(f"[nsdl_issuance] instruments?isin={isin} -> {json.dumps(data)[:600]}")
        inst = (data.get("instrumentsVo") or {}).get("instruments") or {}
        desc = inst.get("instrumentDesc") or ""
        m = re.match(r"\s*(\d+(?:\.\d+)?)\s*%", desc)
        if m and 0 < float(m.group(1)) < 40:
            detail["coupon"] = float(m.group(1))
        elif re.search(r"\bRESET RATE\b|\bFLOATING\b|\bFRN\b", desc.upper()):
            detail["coupon_text"] = "FRN (reset rate)"
            detail["frn"] = True
        if "UNRATED" in desc.upper():
            detail["rated"] = "Unrated"
        elif "RATED" in desc.upper():
            detail["rated"] = "Rated"
        if inst.get("secured"):
            detail["secured"] = inst["secured"]
        if inst.get("modeOfIssue"):
            detail["mode"] = inst["modeOfIssue"]
        if inst.get("seniorityRepayment"):
            detail["seniority"] = inst["seniorityRepayment"]
        try:
            fv, ip = float(inst.get("faceValue") or 0), float(inst.get("issuePrice") or 0)
            if fv and ip and ip < fv:
                detail["discount_pct"] = round((fv - ip) / fv * 100, 2)
        except (TypeError, ValueError):
            pass
        _harvest(data, detail)
    except Exception as exc:
        if debug:
            print(f"[nsdl_issuance] instruments?isin={isin} failed: {exc}")

    # isins feed: issuer classification (NBFC / PSU / sector); secType also
    # embeds the coupon ("... SR 249 7.8324 NCD 04JL31 ...") as a fallback
    try:
        data = _get_json(session, f"{prefix}/public/isins", {"isin": isin})
        if debug:
            print(f"[nsdl_issuance] isins?isin={isin} -> {json.dumps(data)[:400]}")
        if data.get("issuerTypeNature"):
            detail["issuer_nature"] = str(data["issuerTypeNature"]).strip()
        if data.get("issuerTypeOwner"):
            detail["ownership"] = str(data["issuerTypeOwner"]).strip()
        if data.get("sector"):
            detail["sector"] = str(data["sector"]).strip()
        if "coupon" not in detail:
            m = re.search(r"\b(\d{1,2}\.\d{1,4})\b", data.get("secType") or "")
            if m and 0 < float(m.group(1)) < 40:
                detail["coupon"] = float(m.group(1))
    except Exception as exc:
        if debug:
            print(f"[nsdl_issuance] isins?isin={isin} failed: {exc}")

    return detail


def fetch_new_issuances(debug: bool = False, isin_details: bool = False) -> list[dict]:
    """Return recent NCD/bond allotments from NSDL's public feed.

    Each issue: {isin, issuer, issue_size_cr, allotment_date, maturity_date,
                 tenure_years, coupon, coupon_text, ratings, instrument,
                 secured, rated}

    isin_details=False skips the per-ISIN detail calls (coupon/rating/
    secured) — much faster, useful when only issuer/amount/tenure matter.
    """
    session = _session()
    prefix = _api_prefix(session)
    print(f"[nsdl_issuance] API prefix: {prefix}")

    raw = _get_json(session, f"{prefix}/public/bdsinfo/newbondissues")
    issues = []
    seen_isins = set()
    for rec in raw or []:
        if rec.get("isin") in seen_isins:
            continue
        seen_isins.add(rec.get("isin"))
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
        if isin_details:
            issue.update(_isin_details(session, prefix, issue["isin"], debug=debug))
        issues.append(issue)

    issues.sort(key=lambda x: (x["allotment_date"] or datetime.date.min, -x["issue_size_cr"]),
                reverse=True)
    return issues


def fetch_issue_detail(isin: str, debug: bool = False) -> dict:
    """Targeted coupon/rating/secured lookup for one ISIN — used to avoid
    the two extra HTTP calls per issue for the (usually large) majority of
    issuances that aren't on the watchlist."""
    session = _session()
    prefix = _api_prefix(session)
    return _isin_details(session, prefix, isin, debug=debug)


if __name__ == "__main__":
    for i in fetch_new_issuances(debug=True):
        print(i)
