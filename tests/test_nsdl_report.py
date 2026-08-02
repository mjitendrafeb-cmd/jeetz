"""Offline parser/logic tests for the NSDL issuance report pipeline.

NSDL reformats files without notice — these tests catch regressions in the
pure-parsing and analytics code without any network access.
Run: pytest -q tests/
"""

import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import fetch_nsdl_debt_list as fdl               # noqa: E402
import send_nsdl_issuance_report as rep          # noqa: E402


def _dl_rec(isin, issuer, date, coupon, amt, rating, tenure=5.0):
    return {"isin": isin, "issuer": issuer, "allotment_date": date,
            "redemption_date": None, "tenure_years": tenure, "coupon": coupon,
            "amount_cr": amt, "rating": rating,
            "rating_agency": "CRISIL LIMITED" if rating else None}


GSEC = {"curve": {1: 5.85, 3: 6.26, 5: 6.5, 10: 6.84}, "source": "test"}


# ---------------------------------------------------------------- debt list
def test_grade_regex():
    cases = {
        "BBB+ ICRA LIMITED DT 26-02-2026": "BBB+",
        "A CARE RATINGS LIMITED DT 23-12-2025": "A",
        "PROVISIONAL AAA CRISIL DT 01-01-2026": "AAA",
        "AA- CRISIL LIMITED DT 05-05-2026": "AA-",
        "AA+/STABLE CRISIL": "AA+",
        "D BRICKWORK": "D",
        "": None, "NA": None, "NOT RATED": None, "AAAX": None,
    }
    for raw, want in cases.items():
        m = fdl._GRADE_RE.match(raw.upper())
        assert (m.group(1) if m else None) == want, raw


def test_debt_list_date_and_num():
    assert fdl._parse_date("24 April 2026") == datetime.date(2026, 4, 24)
    assert fdl._parse_date("garbage") is None
    assert fdl._num("8.26") == 8.26
    assert fdl._num("1,17,900") == 117900
    assert fdl._num("SENSEX") is None


# ------------------------------------------------------------------- report
def test_rating_band_tokens():
    cases = {
        "CRISIL AA+": rep._BANDS[1],
        "CareEdge B+": rep._BANDS[4],
        "ICRA A1+": rep._BANDS[5],
        "CRISIL AAA": rep._BANDS[0],
        "IND-Ra BBB+ (STABLE)": rep._BANDS[3],
        "Acuité A-": rep._BANDS[2],
    }
    for r, want in cases.items():
        assert rep._rating_band({"ratings": [r]}) == want, r
    assert rep._rating_band({"ratings": []}) == rep._BANDS[6]


def test_segment():
    assert rep._segment({"issuer": "POWER FINANCE CORPORATION LIMITED"}) == "PSU"
    assert rep._segment({"issuer": "HDFC BANK LIMITED"}) == "Bank/FI"
    assert rep._segment({"issuer": "SARVAGRAM FINCARE PRIVATE LIMITED"}) == "NBFC/HFC"
    assert rep._segment({"issuer": "AWAAS HOUSING FINANCE LTD"}) == "NBFC/HFC"
    assert rep._segment({"issuer": "TATA MOTORS LIMITED"}) == "Corporate"
    assert rep._segment({"issuer": "X LTD", "ownership": "PSU"}) == "PSU"


def test_tenor_bucket():
    assert rep._tenor_bucket(0.5) == "≤1y"
    assert rep._tenor_bucket(2.0) == "1–3y"
    assert rep._tenor_bucket(4.9) == "3–5y"
    assert rep._tenor_bucket(7.0) == "5–10y"
    assert rep._tenor_bucket(19.2) == ">10y"
    assert rep._tenor_bucket(None) is None


def test_fy_quarters():
    assert rep._fy_quarter(datetime.date(2026, 7, 24)) == (2027, 2)
    assert rep._fy_quarter(datetime.date(2026, 3, 31)) == (2026, 4)
    assert rep._quarter_start(2027, 2) == datetime.date(2026, 7, 1)
    assert rep._quarter_start(2026, 4) == datetime.date(2026, 1, 1)
    assert rep._quarter_start(2026, 1) == datetime.date(2025, 4, 1)


def test_spread_and_gsec_match():
    i = {"coupon": 8.2, "tenure_years": 10.0}
    assert rep._spread_bps(i, GSEC) == (136, 10)
    assert rep._spread_bps({"coupon": None}, GSEC) is None


def test_curve_lookup_prefers_snapshot():
    hist = {"2026-05-02": {"5": 6.9}}
    lookup = rep._make_curve_lookup(hist, GSEC["curve"])
    assert lookup("2026-05-05") == {5: 6.9}          # within 10 days
    assert lookup("2026-07-20") == GSEC["curve"]     # too far -> fallback


def test_peer_pricing_and_verdict():
    base = datetime.date(2026, 7, 1)
    dl = {"records": [
        _dl_rec(f"P{k}", f"PEER {k} FINANCE LIMITED", base, 8.0 + k * 0.1, 100, "AA")
        for k in range(5)
    ]}
    hist = rep._debt_list_history(dl, GSEC)
    deal = {"isin": "NEW1", "issuer": "FRESH FINANCE LIMITED", "coupon": 9.5,
            "tenure_years": 5.0, "issue_size_cr": 50, "ratings": ["CRISIL AA"],
            "allotment_date": datetime.date(2026, 7, 21)}
    p = rep._peer_pricing(deal, hist, GSEC)
    assert p is not None and p[2] == 5
    assert p[1] == 170                                # median peer: 8.2% vs 6.5
    d, txt, _, n = rep._peer_verdict(deal, hist, GSEC)
    assert d == 130 and "over peers" in txt and n == 5
    cheap = dict(deal, coupon=7.5)
    d2, txt2, _, _ = rep._peer_verdict(cheap, hist, GSEC)
    assert d2 == -70 and "inside peers" in txt2


def test_debt_list_history_uses_issuer_meta():
    dl = {"records": [_dl_rec("I1", "MYSTERY ENTERPRISES LIMITED",
                              datetime.date(2026, 6, 1), 8.0, 100, "AA")]}
    plain = rep._debt_list_history(dl, GSEC)
    assert plain[0]["segment"] == "Corporate"
    meta = {rep._norm("MYSTERY ENTERPRISES LIMITED"): {"segment": "NBFC/HFC"}}
    cached = rep._debt_list_history(dl, GSEC, issuer_meta=meta)
    assert cached[0]["segment"] == "NBFC/HFC"


def test_prev_issuance_needs_earlier_deal():
    dl = {"records": [
        _dl_rec("OLD1", "REPEAT ISSUER LIMITED", datetime.date(2026, 2, 10), 8.55, 150, "AAA"),
        _dl_rec("NEW1", "REPEAT ISSUER LIMITED", datetime.date(2026, 7, 21), 8.20, 200, "AAA"),
    ]}
    hist = rep._debt_list_history(dl, GSEC)
    fresh = {"isin": "NEW1", "issuer": "REPEAT ISSUER LIMITED",
             "allotment_date": datetime.date(2026, 7, 21), "coupon": 8.20}
    prev = rep._prev_issuance(fresh, hist)
    assert prev and prev["isin"] == "OLD1" and prev["coupon"] == 8.55
