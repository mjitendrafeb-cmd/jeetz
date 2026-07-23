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
        if data.get("cin"):
            detail["cin"] = str(data["cin"]).strip()
            # Government-promoted companies carry GOI/SGC in the CIN
            if "GOI" in detail["cin"].upper() and "ownership" not in detail:
                detail["ownership"] = "PSU"
        if "coupon" not in detail:
            m = re.search(r"\b(\d{1,2}\.\d{1,4})\b", data.get("secType") or "")
            if m and 0 < float(m.group(1)) < 40:
                detail["coupon"] = float(m.group(1))
    except Exception as exc:
        if debug:
            print(f"[nsdl_issuance] isins?isin={isin} failed: {exc}")

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
    seen_isins = set()
    for rec in raw or []:
        # the feed occasionally repeats an ISIN
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
        issue.update(_isin_details(session, prefix, issue["isin"], debug=debug))
        issues.append(issue)

    # Rating actions feed (date must be ISO YYYY-MM-DD) — carries per-ISIN
    # rating + agency for actions filed on/around the allotment dates.
    _CRA_SHORT = (("CRISIL", "CRISIL"), ("ICRA", "ICRA"), ("CARE", "CareEdge"),
                  ("INDIA RATING", "IND-Ra"), ("BRICKWORK", "Brickwork"),
                  ("ACUITE", "Acuité"), ("INFOMERICS", "Infomerics"))

    def _cra_short(name: str) -> str:
        up = (name or "").upper()
        for key, short in _CRA_SHORT:
            if key in up:
                return short
        return (name or "").strip()[:20]

    try:
        dates = sorted({i["allotment_date"] for i in issues if i["allotment_date"]},
                       reverse=True)
        lookback = []
        for d in dates[:2]:
            lookback += [d - datetime.timedelta(days=n) for n in range(0, 31)]
        by_isin, by_issuer = {}, {}
        for d in sorted(set(lookback), reverse=True):
            try:
                actions = _get_json(
                    session, f"{prefix}/public/bdsinfo/getallratingactioncralst",
                    {"date": d.strftime("%Y-%m-%d")}) or []
            except Exception:
                continue
            grade_re = re.compile(r"^(AAA|AA[+-]?|A[+-]?|BBB[+-]?|BB[+-]?|B[+-]?|C|D|"
                                  r"A[1-4]\+?)(\s*\(.*\))?$", re.IGNORECASE)
            for a in actions:
                if not isinstance(a, dict) or not a.get("rating"):
                    continue
                # only actual grades count — skip WITHDRAWN / SUSPENDED etc.
                if not grade_re.match(a["rating"].strip()):
                    continue
                tag = f"{_cra_short(a.get('craName'))} {a['rating'].strip()}"
                key = (a.get("isin") or "").strip()
                if key:
                    by_isin.setdefault(key, [])
                    if tag not in by_isin[key]:
                        by_isin[key].append(tag)
                name = re.sub(r"\s+", " ", (a.get("issuer") or "").strip().upper())
                if name:
                    by_issuer.setdefault(name, [])
                    if tag not in by_issuer[name]:
                        by_issuer[name].append(tag)
        for issue in issues:
            tags = by_isin.get(issue["isin"]) or \
                by_issuer.get(re.sub(r"\s+", " ", issue["issuer"].upper()))
            if tags:
                existing = issue.setdefault("ratings", [])
                for t in tags:
                    if t not in existing:
                        existing.append(t)
        if debug:
            print(f"[nsdl_issuance] rating actions matched: "
                  f"{[(i['isin'], i.get('ratings')) for i in issues]}")
    except Exception as exc:
        if debug:
            print(f"[nsdl_issuance] rating actions lookup failed: {exc}")

    fy_total, prev_total, quarters = {}, {}, []
    try:
        fy_total = _get_json(session, f"{prefix}/public/bdsinfo/currentissuance")
    except Exception as exc:
        print(f"[nsdl_issuance] currentissuance failed: {exc}")
    try:
        prev_total = _get_json(session, f"{prefix}/public/bdsinfo/previousissuance")
    except Exception as exc:
        print(f"[nsdl_issuance] previousissuance failed: {exc}")
    try:
        quarters = _get_json(session, f"{prefix}/public/bdsinfo/issuancedashboard")
    except Exception as exc:
        print(f"[nsdl_issuance] issuancedashboard failed: {exc}")

    issues.sort(key=lambda x: (x["allotment_date"] or datetime.date.min, -x["issue_size_cr"]),
                reverse=True)
    return {"issues": issues, "fy_total": fy_total, "prev_total": prev_total,
            "quarters": quarters, "gsec": fetch_gsec_curve(session, debug=debug)}


def fetch_gsec_curve(session=None, debug: bool = False):
    """Best-effort India G-sec yield curve (1/2/3/5/7/10Y) so new-issue
    coupons can be benchmarked against the closest-tenor G-sec.

    Tries worldgovernmentbonds.com; falls back to a manual "gsec_yields"
    dict (e.g. {"1": 5.9, "3": 6.0, "5": 6.1, "10": 6.3}) or legacy
    "gsec_10y_yield" in config.json.
    Returns {"curve": {tenor_years: yield_pct}, "source": str} or None.
    """
    session = session or _session()
    # tradingeconomics' India bond page carries a static table of tenors:
    # <tr data-symbol="GIND2Y:IND"> ... <td id="p">5.94</td>
    try:
        r = session.get("https://tradingeconomics.com/india/government-bond-yield",
                        timeout=(10, 20))
        if debug:
            print(f"[nsdl_issuance] te gsec fetch: status={r.status_code}")
        if r.status_code == 200:
            curve = {}
            for tenor, val in re.findall(
                    r'data-symbol="GIND(\d{1,2})YR?:IND"\s*>.{0,400}?<td id="p">\s*(\d{1,2}\.\d{1,4})',
                    r.text, re.DOTALL):
                if 3 < float(val) < 12:
                    curve[int(tenor)] = float(val)
            if not curve:
                m = re.search(r"India 10Y Bond Yield \w+ to (\d{1,2}\.\d{1,2})%", r.text)
                if m:
                    curve = {10: float(m.group(1))}
            if debug:
                print(f"[nsdl_issuance] gsec curve parsed: {curve}")
            if curve:
                return {"curve": curve, "source": "tradingeconomics.com"}
    except Exception as exc:
        if debug:
            print(f"[nsdl_issuance] te gsec fetch failed: {exc}")
    try:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(base, "config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        manual = cfg.get("gsec_yields") or {}
        curve = {int(k): float(v) for k, v in manual.items() if float(v) > 0}
        if not curve and cfg.get("gsec_10y_yield"):
            curve = {10: float(cfg["gsec_10y_yield"])}
        if curve:
            return {"curve": curve, "source": "config.json (manual)"}
    except Exception:
        pass
    return None


if __name__ == "__main__":
    data = fetch_new_issuances(debug=True)
    for i in data["issues"]:
        print(i)
    print(data["fy_total"])
    print(data["quarters"])
