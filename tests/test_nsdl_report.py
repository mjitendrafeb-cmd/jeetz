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
import fetch_nsdl_issuance_full as fni           # noqa: E402
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


def test_computed_commentary_rule_based():
    base = datetime.date(2026, 7, 1)
    dl = {"records": [
        _dl_rec(f"P{k}", f"PEER {k} FINANCE LIMITED", base, 8.0 + k * 0.1, 100, "AA")
        for k in range(5)
    ]}
    hist = rep._debt_list_history(dl, GSEC)
    issues = [
        {"isin": "NEW1", "issuer": "FRESH FINANCE LIMITED", "issue_size_cr": 200,
         "allotment_date": datetime.date(2026, 7, 21), "tenure_years": 5.0,
         "coupon": 7.90, "ratings": ["CRISIL AA"]},
        {"isin": "NEW2", "issuer": "STEEL WORKS LIMITED", "issue_size_cr": 100,
         "allotment_date": datetime.date(2026, 7, 21), "tenure_years": 3.0,
         "coupon": 12.0, "ratings": ["ICRA BBB"]},
    ]
    bullets = rep._computed_commentary(issues, ["Fresh Finance"], hist, GSEC)
    assert len(bullets) == 3
    assert "inside peers" in bullets[0]                  # 7.90 vs 8.20 median
    assert "Steel Works" in bullets[1] and "+574 bps" in bullets[1]
    assert "67%" in bullets[2] and "Fresh Finance" in bullets[2]


# ----------------------------------------------------- tenor sanity cap
def test_tenure_years_caps_garbage_maturity():
    allot = datetime.date(2026, 9, 1)
    assert fni._tenure_years(allot, datetime.date(9999, 12, 31)) is None
    assert fni._tenure_years(allot, datetime.date(2033, 9, 1)) == 7.0
    assert fni._tenure_years(allot, None) is None
    assert fni._tenure_years(None, datetime.date(2033, 9, 1)) is None


def test_debt_list_tenure_cap_matches_max_constant():
    assert fdl._MAX_SANE_TENURE_YEARS == 50
    allot = datetime.date(2026, 9, 1)

    def compute(red):
        t = round((red - allot).days / 365.25, 1) if red else None
        if t is not None and not 0 < t <= fdl._MAX_SANE_TENURE_YEARS:
            t = None
        return t

    assert compute(datetime.date(9999, 12, 31)) is None
    assert compute(datetime.date(2033, 9, 1)) == 7.0


# --------------------------------------------------------- split ratings
def test_split_rating_note():
    n = rep._split_rating_note({"ratings": ["CRISIL AA+", "ICRA AA"]})
    assert n and "CRISIL AA+" in n and "ICRA AA" in n
    # long/short-term from the SAME agency is not a split
    assert rep._split_rating_note({"ratings": ["CRISIL AAA", "CRISIL A1+"]}) is None
    # two agencies agreeing is not a split
    assert rep._split_rating_note({"ratings": ["CRISIL AA+", "ICRA AA+"]}) is None
    assert rep._split_rating_note({"ratings": ["CRISIL AAA"]}) is None
    assert rep._split_rating_note({"ratings": []}) is None


# ---------------------------------------------------------- g-sec trend
def test_gsec_trend_note():
    today = datetime.date(2026, 9, 3)
    gsec = {"curve": {1: 5.90, 5: 6.55, 10: 6.90}, "source": "te"}
    hist = {
        "2026-08-27": {"1": 5.85, "5": 6.50, "10": 6.84},
        "2026-09-03": {"1": 5.90, "5": 6.55, "10": 6.90},
    }
    note = rep._gsec_trend_note(gsec, hist, today, lookback_days=7)
    assert note and "27-Aug" in note
    assert "1Y +5bps" in note and "10Y +6bps" in note
    # nothing near the lookback target -> no note
    assert rep._gsec_trend_note(gsec, {"2026-09-03": {"1": 5.90}}, today) is None
    assert rep._gsec_trend_note(None, hist, today) is None
    assert rep._gsec_trend_note(gsec, None, today) is None


# ----------------------------------------------------- issuer concentration
def test_short_name_strips_suffix_not_midword():
    assert rep._short_name("power finance corporation limited") == "Power Finance Corporation"
    assert rep._short_name("rec limited") == "Rec"
    assert rep._short_name("sarvagram fincare private limited") == "Sarvagram Fincare"


def test_concentration_note():
    def rec(isin, issuer, amt, seg, date):
        return {"isin": isin, "issuer": issuer, "amount_cr": amt, "segment": seg,
                "allotment_date": date}

    hist = [
        rec("N1", "power finance corporation limited", 3000, "PSU", "2026-04-10"),
        rec("N2", "rec limited", 500, "PSU", "2026-05-10"),
        rec("N3", "small psu co", 100, "PSU", "2026-06-10"),
        rec("N4", "alpha finance limited", 200, "NBFC/HFC", "2026-04-15"),
        rec("N5", "beta finance limited", 150, "NBFC/HFC", "2026-05-15"),
        rec("N6", "gamma finance limited", 100, "NBFC/HFC", "2026-06-15"),
        rec("N7", "delta finance limited", 50, "NBFC/HFC", "2026-07-15"),
        rec("N8", "solo corp limited", 900, "Corporate", "2026-04-01"),
    ]
    note = rep._concentration_note(hist, datetime.date(2026, 9, 3))
    assert "PSU 100%" in note
    assert "NBFC/HFC 90%" in note
    assert "Corporate" not in note  # single-issuer segment excluded as not meaningful
    assert rep._concentration_note([], datetime.date(2026, 9, 3)) is None
    assert rep._concentration_note(None, datetime.date(2026, 9, 3)) is None


# --------------------------------------------------- quarterly coupon trend
def test_coupon_trend_html():
    gsec = {"curve": {5: 6.5}, "source": "test"}
    today = datetime.date(2026, 9, 3)
    # Q4 FY26 = Jan-Mar26, Q1 FY27 = Apr-Jun26, Q2 FY27 (QTD) = Jul-Sep26
    recs = [
        _dl_rec("N1", "ALPHA FINANCE LIMITED", datetime.date(2026, 2, 5), 8.70, 100, "AA"),
        _dl_rec("N2", "ALPHA FINANCE LIMITED", datetime.date(2026, 5, 5), 8.50, 100, "AA"),
        _dl_rec("N3", "ALPHA FINANCE LIMITED", datetime.date(2026, 8, 5), 8.00, 100, "AA"),
    ]
    hist = rep._debt_list_history({"records": recs}, gsec)
    html = rep._coupon_trend_html(hist, today=today)
    assert "COUPON RATE TREND — QUARTERLY (%)" in html
    assert "8.70%" in html and "8.50%" in html and "8.00%" in html
    assert "▼0.20" in html and "▼0.50" in html
    assert "Q4 FY26" in html and "Q1 FY27" in html and "Q2 FY27 (QTD)" in html

    # a single quarter is no trend
    one = rep._debt_list_history(
        {"records": [_dl_rec("S1", "X FINANCE LIMITED", datetime.date(2026, 9, 1), 8.0, 100, "AA")]},
        gsec)
    assert rep._coupon_trend_html(one, today=today) == ""

    # the shared quarter-bucketing refactor must not change spread trend output
    html_spread = rep._spread_trend_html(hist, today=today)
    assert "+220" in html_spread  # Q4 FY26: 8.70 - 6.50 = 2.20 -> +220bps
