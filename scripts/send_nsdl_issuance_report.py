#!/usr/bin/env python3
"""NSDL New Debt Issuance Report — daily email.

Pulls fresh primary-market debt issuances (tenure, amount, coupon where
disclosed) from NSDL India Bond Info's public CBDServices API, flags watchlist
entities, adds computed borrowing-cost analysis plus optional Claude
commentary, and emails it to the recipients in config.json.

Env: GMAIL_USER, GMAIL_APP_PASSWORD, optional ANTHROPIC_API_KEY,
     optional NSDL_DEBUG=true (dump raw per-ISIN JSON to logs).
"""

import datetime
import json
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from fetch_nsdl_issuance import fetch_new_issuances
from fetch_nsdl_cp import fetch_cp_issuances

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_config() -> dict:
    try:
        with open(os.path.join(_REPO_ROOT, "config.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _recipients() -> list[str]:
    cfg = _load_config()
    recs = cfg.get("recipients") or [cfg.get("recipient")] or []
    return [r for r in recs if r]


_STOP = re.compile(r"\b(limited|ltd|private|pvt|company|co|corporation|corp|india|the)\b\.?",
                   re.IGNORECASE)


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", _STOP.sub("", name.lower()).replace(".", " ")).strip()


def _load_watchlist() -> list[tuple[str, str]]:
    out = []
    try:
        with open(os.path.join(_REPO_ROOT, "watchlist.txt"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    out.append((line, _norm(line)))
    except Exception:
        pass
    return out


def _watchlist_hit(issuer: str, watchlist) -> str:
    n = _norm(issuer)
    if not n:
        return ""
    for original, wn in watchlist:
        if wn and (wn in n or n in wn):
            return original
    return ""


def _fmt_cr(v: float) -> str:
    return f"{v:,.0f}" if v >= 10 else f"{v:,.1f}"


def _fmt_date(d) -> str:
    return d.strftime("%d-%b-%Y") if d else "—"


def _coupon_str(i: dict) -> str:
    if i.get("coupon"):
        return f"{i['coupon']:.2f}%"
    if i.get("coupon_text"):
        return i["coupon_text"]
    return "—"


def _rating_str(i: dict) -> str:
    r = i.get("ratings") or []
    return "; ".join(r[:2]) if r else "—"


_RATING_TOKEN = re.compile(
    r"\b(AAA|AA\+|AA-|AA|A\+|A-|BBB\+|BBB-|BBB|BB\+|BB-|BB|B\+|B-|"
    r"A1\+|A1|A2\+|A2|A3\+|A3|A4\+|A4|C|D|A)\b")

_BANDS = ["AAA", "AA band (AA+/AA/AA-)", "A band (A+/A/A-)", "BBB band",
          "Below investment grade", "Short-term (A1+/A1/...)",
          "Not rated / available"]


def _rating_band(i: dict) -> str:
    tokens = []
    for r in i.get("ratings") or []:
        tokens += _RATING_TOKEN.findall(r.upper().replace("(", " ").replace(")", " "))
    for t in tokens:
        if t == "AAA":
            return _BANDS[0]
    for t in tokens:
        if t in ("AA+", "AA", "AA-"):
            return _BANDS[1]
    for t in tokens:
        if t in ("A+", "A", "A-"):
            return _BANDS[2]
    for t in tokens:
        if t in ("BBB+", "BBB", "BBB-"):
            return _BANDS[3]
    for t in tokens:
        if t in ("BB+", "BB", "BB-", "B+", "B-", "C", "D"):
            return _BANDS[4]
    for t in tokens:
        if t.startswith(("A1", "A2", "A3", "A4")):
            return _BANDS[5]
    return _BANDS[6]


def _type_str(i: dict) -> str:
    parts = []
    if i.get("issuer_nature") and i["issuer_nature"] != "Other":
        parts.append(i["issuer_nature"])
    elif i.get("sector"):
        parts.append(i["sector"])
    if i.get("ownership") and "psu" in i["ownership"].lower().replace(" ", ""):
        parts.append(i["ownership"])
    if i.get("secured"):
        parts.append(i["secured"])
    if i.get("rated"):
        parts.append(i["rated"])
    if i.get("ratings"):
        parts.append("; ".join(i["ratings"][:1]))
    if i.get("discount_pct"):
        parts.append(f"issued at {i['discount_pct']}% discount")
    return " · ".join(parts) if parts else "—"


def _gsec_match(gsec: dict | None, tenure):
    """Closest curve tenor for an issue's tenure -> (tenor_years, yield) or None."""
    curve = (gsec or {}).get("curve") or {}
    if not curve or not tenure:
        return None
    tenor = min(curve, key=lambda t: abs(t - tenure))
    return tenor, curve[tenor]


def _spread_bps(i: dict, gsec) -> tuple[int, int] | None:
    """(spread_bps, matched_tenor) vs closest-tenor G-sec, or None."""
    if not i.get("coupon"):
        return None
    m = _gsec_match(gsec, i.get("tenure_years"))
    if not m:
        return None
    tenor, y = m
    return round((i["coupon"] - y) * 100), tenor


_SEGMENTS = ["PSU", "Bank/FI", "NBFC/HFC", "Corporate"]


def _segment(i: dict) -> str:
    """Issuer cohort: PSU, Bank/FI, NBFC/HFC or Corporate — from ownership,
    CIN (GOI = government promoted), issuer nature and name."""
    own = (i.get("ownership") or "").strip().lower()
    cin = (i.get("cin") or "").upper()
    nature = (i.get("issuer_nature") or "").strip().lower()
    name = (i.get("issuer") or "").lower()
    if ("psu" in own and "non" not in own) or "GOI" in cin:
        return "PSU"
    if "bank" in nature or re.search(r"\bbank\b", name):
        return "Bank/FI"
    if "nbfc" in nature or "hfc" in nature or "housing finance" in name \
            or "home finance" in name or re.search(r"\bfinance\b|\bfinserv\b|\bfincorp\b|"
                                                   r"\bcapital\b|\bcredit\b", name):
        return "NBFC/HFC"
    return "Corporate"


_HISTORY_PATH = os.path.join(_REPO_ROOT, "data", "nsdl_issuance_history.json")
_HISTORY_DAYS = 45
_MATRIX_WINDOW_DAYS = 30


def _update_history(issues, gsec) -> list[dict]:
    """Merge today's issues into the rolling history file (deduped by ISIN,
    pruned to _HISTORY_DAYS) and return the trailing records."""
    try:
        with open(_HISTORY_PATH, encoding="utf-8") as f:
            hist = {r["isin"]: r for r in json.load(f).get("records", [])}
    except Exception:
        hist = {}
    for i in issues:
        if not i.get("allotment_date"):
            continue
        sp = _spread_bps(i, gsec)
        hist[i["isin"]] = {
            "isin": i["isin"],
            "issuer": i["issuer"],
            "allotment_date": i["allotment_date"].isoformat(),
            "amount_cr": i["issue_size_cr"],
            "coupon": i.get("coupon"),
            "tenure_years": i.get("tenure_years"),
            "band": _rating_band(i),
            "segment": _segment(i),
            "spread_bps": sp[0] if sp else None,
            "ratings": i.get("ratings") or [],
        }
    cutoff = (datetime.date.today() - datetime.timedelta(days=_HISTORY_DAYS)).isoformat()
    records = sorted((r for r in hist.values() if r["allotment_date"] >= cutoff),
                     key=lambda r: r["allotment_date"], reverse=True)
    try:
        os.makedirs(os.path.dirname(_HISTORY_PATH), exist_ok=True)
        with open(_HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump({"records": records}, f, indent=1)
    except Exception as exc:
        print(f"[nsdl_issuance] history save failed: {exc}")
    return records


def _cohort_matrix_html(records) -> str:
    """Borrowing-cost matrix over the trailing window: rating band rows ×
    issuer segment columns; each cell = weighted avg coupon, avg spread,
    amount and deal count."""
    cutoff = (datetime.date.today() - datetime.timedelta(days=_MATRIX_WINDOW_DAYS)).isoformat()
    window = [r for r in records
              if r["allotment_date"] >= cutoff and r.get("coupon")]
    if not window:
        return ""

    cells: dict[tuple[str, str], list] = {}
    for r in window:
        cells.setdefault((r["band"], r["segment"]), []).append(r)

    used_segments = [s for s in _SEGMENTS if any(k[1] == s for k in cells)]
    used_bands = [b for b in _BANDS if any(k[0] == b for k in cells)]
    if not used_segments:
        return ""

    header = "".join(f'<th style="padding:7px 10px;">{s}</th>' for s in used_segments)
    rows_html = ""
    for band in used_bands:
        row = (f'<td style="padding:7px 10px;border-bottom:1px solid #eee;'
               f'font-weight:700;">{band.split(" (")[0]}</td>')
        for seg in used_segments:
            g = cells.get((band, seg))
            if not g:
                row += ('<td style="padding:7px 10px;border-bottom:1px solid #eee;'
                        'text-align:center;color:#bbb;">—</td>')
                continue
            amt = sum(x["amount_cr"] for x in g)
            wac = sum(x["coupon"] * x["amount_cr"] for x in g) / amt
            sps = [(x["spread_bps"], x["amount_cr"]) for x in g if x.get("spread_bps") is not None]
            sp_txt = ""
            if sps:
                wsp = sum(s * w for s, w in sps) / sum(w for _, w in sps)
                sp_txt = f"<br><span style='color:#888;font-size:10.5px;'>{wsp:+.0f} bps vs G-sec</span>"
            row += (f'<td style="padding:7px 10px;border-bottom:1px solid #eee;'
                    f'text-align:center;"><b>{wac:.2f}%</b>{sp_txt}'
                    f"<br><span style='color:#888;font-size:10.5px;'>₹{_fmt_cr(amt)} cr · "
                    f"{len(g)} deal{'s' if len(g) > 1 else ''}</span></td>")
        rows_html += f"<tr>{row}</tr>"

    return f"""
<tr><td style="padding:14px 20px 4px;">
  <div style="font-size:13px;font-weight:700;color:#cc0000;border-bottom:2px solid #cc0000;padding-bottom:4px;">WHO BORROWS AT WHAT RATE — LAST {_MATRIX_WINDOW_DAYS} DAYS</div>
  <div style="margin-top:5px;font-family:Arial,sans-serif;font-size:11.5px;color:#666;">
  Value-weighted avg coupon by rating band × issuer segment, with spread over tenor-matched G-sec
  ({len(window)} rated deals tracked; matrix fills as daily history accumulates).</div>
</td></tr>
<tr><td style="padding:8px 20px;">
<table width="100%" cellpadding="0" cellspacing="0" style="font-family:Arial,Helvetica,sans-serif;font-size:12px;border:1px solid #e5e5e5;">
<tr style="background:#1a1a1a;color:#fff;"><th style="padding:7px 10px;text-align:left;">Rating band</th>{header}</tr>
{rows_html}
</table>
</td></tr>"""


def _is_financial(i: dict) -> bool:
    blob = " ".join(str(i.get(k, "")) for k in ("issuer_nature", "ownership", "sector")).lower()
    return any(k in blob for k in ("nbfc", "hfc", "bank", "financial", "finance"))


def _computed_analysis(issues, fy_total, quarters, prev_total=None, gsec=None) -> list[str]:
    if not issues:
        return []
    lines = []
    total = sum(i["issue_size_cr"] for i in issues)

    # today's total with NBFC/financial vs corporate split
    fin = [i for i in issues if _is_financial(i)]
    corp = [i for i in issues if not _is_financial(i)]
    split_bits = []
    if fin:
        split_bits.append(f"NBFC/financials ₹{_fmt_cr(sum(i['issue_size_cr'] for i in fin))} cr "
                          f"({len(fin)})")
    if corp:
        split_bits.append(f"corporates/others ₹{_fmt_cr(sum(i['issue_size_cr'] for i in corp))} cr "
                          f"({len(corp)})")
    lines.append(f"{len(issues)} fresh issuances totalling ₹{_fmt_cr(total)} cr — "
                 + ", ".join(split_bits) + ".")

    # rating-band coupon averages, benchmarked to 10Y G-sec where available
    with_coupon = [i for i in issues if i.get("coupon")]
    band_groups: dict[str, list] = {}
    for i in with_coupon:
        band_groups.setdefault(_rating_band(i), []).append(i)
    curve = (gsec or {}).get("curve") or {}
    band_bits = []
    for band in _BANDS:
        g = band_groups.get(band)
        if g:
            avg = sum(x["coupon"] * x["issue_size_cr"] for x in g) / \
                sum(x["issue_size_cr"] for x in g)
            bit = f"{band.split(' (')[0]} {avg:.2f}%"
            spreads = [(_spread_bps(x, gsec), x["issue_size_cr"]) for x in g]
            spreads = [(s[0], w) for s, w in spreads if s]
            if spreads:
                wavg = sum(s * w for s, w in spreads) / sum(w for _, w in spreads)
                bit += f" ({wavg:+.0f} bps vs tenor-matched G-sec)"
            band_bits.append(bit)
    if band_bits:
        lines.append("Weighted avg coupon: " + " · ".join(band_bits) + ".")
    if curve:
        pts = " · ".join(f"{t}Y {curve[t]:.2f}%" for t in sorted(curve))
        lines.append(f"G-sec curve: {pts} (source: {gsec.get('source', 'n/a')}). "
                     f"Spreads use the closest tenor to each ISIN.")

    # FY-to-date vs last FY
    if fy_total and fy_total.get("issueSize"):
        fy_line = (f"Corporate bond issuance FY{fy_total.get('dataForYear', '')} so far: "
                   f"₹{_fmt_cr(float(fy_total['issueSize']))} cr "
                   f"({fy_total.get('noOfIsin', '?')} ISINs)")
        if prev_total and prev_total.get("issueSize"):
            fy_line += (f" vs FY{prev_total.get('dataForYear', '')} total "
                        f"₹{_fmt_cr(float(prev_total['issueSize']))} cr "
                        f"({prev_total.get('noOfIsin', '?')} ISINs)")
        lines.append(fy_line + ". (Source: NSDL)")
    return lines


def _cp_section_html(cp, watchlist) -> str:
    """Compact monthly CP summary: stats, tenor-bucket yields, top deals and
    all watchlist issuers. cp = {"month","year","records"}."""
    recs = (cp or {}).get("records") or []
    if not recs:
        return ""
    month_label = f"{cp['month']} {cp['year']}".upper()
    total = sum(r["amount_cr"] for r in recs)
    with_yield = [r for r in recs if r.get("yield_pct")]

    buckets = (("≤ 91d", 0, 91), ("92–182d", 92, 182), ("183–365d", 183, 366))
    bucket_bits = []
    for label, lo, hi in buckets:
        g = [r for r in with_yield if r.get("tenor_days") and lo <= r["tenor_days"] <= hi]
        if g:
            w = sum(r["yield_pct"] * r["amount_cr"] for r in g) / sum(r["amount_cr"] for r in g)
            bucket_bits.append(f"{label} {w:.2f}% ({len(g)})")
    stats = (f"{len(recs)} CPs totalling ₹{_fmt_cr(total)} cr in {cp['month']} {cp['year']}."
             + (" Weighted avg yield by tenor: " + " · ".join(bucket_bits) + "."
                if bucket_bits else ""))

    # top 10 by size, plus every watchlist issuer
    by_size = sorted(recs, key=lambda r: -r["amount_cr"])
    shown, seen_isins = [], set()
    for r in by_size[:10]:
        shown.append(r)
        seen_isins.add(r["isin"])
    wl_rows = [r for r in recs
               if _watchlist_hit(r["issuer"], watchlist) and r["isin"] not in seen_isins]
    shown += wl_rows

    rows_html = ""
    for r in shown:
        hit = _watchlist_hit(r["issuer"], watchlist)
        star = " ⭐" if hit else ""
        row_bg = "#fff8e1" if hit else "#ffffff"
        rows_html += f"""<tr style="background:{row_bg};">
<td style="padding:6px 10px;border-bottom:1px solid #eee;font-weight:600;">{r['issuer'].title()}{star}</td>
<td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:right;">{_fmt_cr(r['amount_cr'])}</td>
<td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:center;">{f"{r['yield_pct']:.2f}%" if r.get('yield_pct') else '—'}</td>
<td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:center;">{r.get('tenor_days') or '—'}</td>
<td style="padding:6px 10px;border-bottom:1px solid #eee;font-size:11px;">{r.get('ipa') or '—'}</td>
</tr>"""

    note = ""
    if len(recs) > len(shown):
        note = (f"<div style='margin-top:5px;font-family:Arial,sans-serif;font-size:10.5px;"
                f"color:#888;'>Showing top 10 by size{' + watchlist issuers' if wl_rows else ''}; "
                f"{len(recs) - len(shown)} more CPs in the month.</div>")

    return f"""
<tr><td style="padding:14px 20px 4px;">
  <div style="font-size:13px;font-weight:700;color:#cc0000;border-bottom:2px solid #cc0000;padding-bottom:4px;">CP ISSUANCES — {month_label} (LATEST NSDL MONTHLY FILE)</div>
  <div style="margin-top:6px;font-family:Arial,sans-serif;font-size:12.5px;color:#333;">{stats}</div>
</td></tr>
<tr><td style="padding:8px 20px;">
<table width="100%" cellpadding="0" cellspacing="0" style="font-family:Arial,Helvetica,sans-serif;font-size:12px;border:1px solid #e5e5e5;">
<tr style="background:#1a1a1a;color:#fff;">
  <th style="padding:7px 10px;text-align:left;">Issuer</th>
  <th style="padding:7px 10px;text-align:right;">₹ cr</th>
  <th style="padding:7px 10px;">Yield</th>
  <th style="padding:7px 10px;">Tenor (d)</th>
  <th style="padding:7px 10px;text-align:left;">IPA</th>
</tr>
{rows_html}
</table>
{note}
<div style='margin-top:4px;font-family:Arial,sans-serif;font-size:10px;color:#999;'>
NSDL publishes CP issuance monthly with a ~2 month lag; this is the latest available month.</div>
</td></tr>"""


_CLAUDE_ERROR = {"msg": ""}


def _claude_commentary(issues, watchlist_hits) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key or not issues:
        return ""
    try:
        import anthropic
        rows = "\n".join(
            f"- {i['issuer']} | ISIN {i['isin']} | ₹{_fmt_cr(i['issue_size_cr'])} cr | "
            f"coupon {_coupon_str(i)} | allotted {_fmt_date(i['allotment_date'])} | "
            f"matures {_fmt_date(i['maturity_date'])} | tenor {i.get('tenure_years') or '?'}y | "
            f"type {_type_str(i)}"
            for i in issues
        )
        wl = ", ".join(watchlist_hits) if watchlist_hits else "none"
        prompt = (
            "You are a senior credit analyst at an Indian rating agency. Below are today's "
            "fresh corporate debt issuances from NSDL's primary-market data (amounts in ₹ crore).\n\n"
            f"{rows}\n\nWatchlist (rated-entity) issuers in today's batch: {wl}.\n\n"
            "Write 3-5 crisp analyst bullets (plain text, each starting with '• ') on: who is "
            "borrowing at better rates for comparable tenors and why that might be (rating, "
            "ownership, sector); anything notable about tenor/size choices; and what a credit "
            "analyst tracking NBFCs/HFCs should take away. Do not repeat the raw table. "
            "If coupons are missing, infer only what the sizes/tenors/issuer mix supports."
        )
        client = anthropic.Anthropic(api_key=api_key)
        cfg_model = _load_config().get("model", "claude-sonnet-5")
        msg = client.messages.create(model=cfg_model, max_tokens=1000,
                                     messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    except Exception as exc:
        print(f"[nsdl_issuance] Claude commentary skipped: {exc}")
        if "credit balance" in str(exc).lower():
            _CLAUDE_ERROR["msg"] = ("AI commentary unavailable — the Anthropic API account "
                                    "is out of credits (top up at console.anthropic.com → "
                                    "Plans &amp; Billing).")
        return ""


def build_email(issues, fy_total, quarters, watchlist, today,
                prev_total=None, gsec=None, cp=None, history=None) -> str:
    date_str = today.strftime("%d %B %Y")
    watchlist_hits = []
    banded: dict[str, list] = {}
    for i in issues:
        banded.setdefault(_rating_band(i), []).append(i)

    rows_html = ""
    for band in _BANDS:
        group = banded.get(band)
        if not group:
            continue
        group.sort(key=lambda x: -x["issue_size_cr"])
        band_total = sum(g["issue_size_cr"] for g in group)
        rows_html += f"""<tr style="background:#3d3d3d;color:#fff;">
<td colspan="6" style="padding:6px 10px;font-weight:700;font-size:12px;letter-spacing:0.5px;">
{band.upper()} &nbsp;·&nbsp; {len(group)} issue{'s' if len(group) > 1 else ''} · ₹{_fmt_cr(band_total)} cr</td></tr>"""
        for i in group:
            hit = _watchlist_hit(i["issuer"], watchlist)
            if hit:
                watchlist_hits.append(i["issuer"].title())
            star = " ⭐" if hit else ""
            row_bg = "#fff8e1" if hit else "#ffffff"
            rating = "; ".join((i.get("ratings") or [])[:2]) or "Not rated / available"
            sp = _spread_bps(i, gsec)
            spread_html = (f"<div style='font-size:10px;color:#888;'>{sp[0]:+d} bps vs {sp[1]}Y G-sec</div>"
                           if sp else "")
            rows_html += f"""<tr style="background:{row_bg};">
<td style="padding:7px 10px;border-bottom:1px solid #eee;font-weight:600;">{i['issuer'].title()}{star}</td>
<td style="padding:7px 10px;border-bottom:1px solid #eee;font-family:monospace;font-size:11px;">{i['isin']}</td>
<td style="padding:7px 10px;border-bottom:1px solid #eee;text-align:right;">{_fmt_cr(i['issue_size_cr'])}</td>
<td style="padding:7px 10px;border-bottom:1px solid #eee;text-align:center;">{_coupon_str(i)}{spread_html}</td>
<td style="padding:7px 10px;border-bottom:1px solid #eee;text-align:center;">{i.get('tenure_years') or '—'}</td>
<td style="padding:7px 10px;border-bottom:1px solid #eee;font-size:11px;">{rating}</td>
</tr>"""

    allot_dates = sorted({i["allotment_date"] for i in issues if i.get("allotment_date")})
    allot_str = ""
    if allot_dates:
        allot_str = " — ALLOTMENT " + _fmt_date(allot_dates[-1]).upper()
        if len(allot_dates) > 1:
            allot_str = (" — ALLOTMENT " + _fmt_date(allot_dates[0]).upper()
                         + " TO " + _fmt_date(allot_dates[-1]).upper())

    analysis_items = _computed_analysis(issues, fy_total, quarters, prev_total, gsec)
    analysis_html = "".join(f"<li style='padding:3px 0;'>{a}</li>" for a in analysis_items)

    commentary = _claude_commentary(issues, watchlist_hits)
    commentary_html = ""
    if not commentary and _CLAUDE_ERROR["msg"]:
        commentary_html = f"""
<tr><td style="padding:10px 20px 0;">
  <div style="font-family:Arial,sans-serif;font-size:11px;color:#a15c00;background:#fff3cd;
              border:1px solid #ffe69c;border-radius:4px;padding:8px 10px;">{_CLAUDE_ERROR['msg']}</div>
</td></tr>"""
    if commentary:
        bullets = "".join(f"<li style='padding:3px 0;'>{b.strip().lstrip('•').strip()}</li>"
                          for b in commentary.split("\n") if b.strip())
        commentary_html = f"""
<tr><td style="padding:14px 20px 4px;">
  <div style="font-size:13px;font-weight:700;color:#cc0000;border-bottom:2px solid #cc0000;padding-bottom:4px;">ANALYST COMMENTARY</div>
  <ul style="margin:8px 0 0;padding-left:18px;font-size:13px;color:#333;">{bullets}</ul>
</td></tr>"""

    wl_note = ""
    if watchlist_hits:
        wl_note = (f"<div style='margin-top:6px;font-size:12px;color:#8a6d00;'>⭐ Watchlist issuer(s) "
                   f"in today's batch: <b>{', '.join(sorted(set(watchlist_hits)))}</b></div>")

    empty_html = ""
    if not issues:
        empty_html = """<tr><td colspan="6" style="padding:20px;text-align:center;color:#666;font-size:13px;">
No fresh issuances reported on NSDL India Bond Info for this run.</td></tr>"""
    excluded_note = ""

    return f"""<html><body style="margin:0;padding:0;background:#f0f0f0;font-family:Georgia,'Times New Roman',serif;">
<div style="max-width:760px;margin:0 auto;background:#ffffff;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#1a1a1a;">
<tr><td style="padding:16px 20px;text-align:center;">
  <div style="font-size:24px;font-weight:700;color:#ffffff;letter-spacing:1px;">NSDL NEW DEBT ISSUANCES</div>
  <div style="font-size:12px;color:#cccccc;padding-top:4px;">Primary market — who borrowed, how much, at what rate &nbsp;·&nbsp; {date_str}</div>
</td></tr>
</table>

<table width="100%" cellpadding="0" cellspacing="0">
<tr><td style="padding:16px 20px 4px;">
  <div style="font-size:13px;font-weight:700;color:#cc0000;border-bottom:2px solid #cc0000;padding-bottom:4px;">FRESH ISSUANCES{allot_str} (SOURCE: NSDL INDIA BOND INFO)</div>
  {wl_note}
</td></tr>
<tr><td style="padding:8px 20px;">
<table width="100%" cellpadding="0" cellspacing="0" style="font-family:Arial,Helvetica,sans-serif;font-size:12.5px;border:1px solid #e5e5e5;">
<tr style="background:#1a1a1a;color:#fff;">
  <th style="padding:8px 10px;text-align:left;">Issuer</th>
  <th style="padding:8px 10px;text-align:left;">ISIN</th>
  <th style="padding:8px 10px;text-align:right;">₹ cr</th>
  <th style="padding:8px 10px;">Coupon</th>
  <th style="padding:8px 10px;">Tenor (y)</th>
  <th style="padding:8px 10px;text-align:left;">Rating / Type</th>
</tr>
{rows_html}{empty_html}
</table>
{excluded_note}
</td></tr>

<tr><td style="padding:14px 20px 4px;">
  <div style="font-size:13px;font-weight:700;color:#cc0000;border-bottom:2px solid #cc0000;padding-bottom:4px;">MARKET SNAPSHOT</div>
  <ul style="margin:8px 0 0;padding-left:18px;font-family:Arial,sans-serif;font-size:13px;color:#333;">{analysis_html}</ul>
</td></tr>
{_cohort_matrix_html(history or [])}
{_cp_section_html(cp, watchlist)}
{commentary_html}

<tr><td style="padding:16px 20px;font-family:Arial,sans-serif;font-size:10px;color:#999;">
Source: NSDL India Bond Info (indiabondinfo.nsdl.com) public corporate bond database. Coupon/rating
shown where disclosed via the ISIN detail feed; “—” means not yet published. Amounts in ₹ crore.
</td></tr>
</table>

<table width="100%" cellpadding="0" cellspacing="0" style="background:#1a1a1a;">
<tr><td style="padding:8px 20px;text-align:center;font-size:10px;color:#555;">
  <span style="color:#cc0000;font-weight:700;">NSDL Issuance Tracker</span> — {date_str}<br>
  <em>&#128274; Confidential — Internal Use Only</em>
</td></tr>
</table>
</div></body></html>"""


def send_email(subject: str, html_body: str, gmail_user: str, gmail_password: str) -> None:
    recipients = _recipients()
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_password)
        server.sendmail(gmail_user, recipients, msg.as_string())
    print(f"[nsdl_issuance] Email sent to {', '.join(recipients)}")


def main() -> None:
    gmail_user = os.environ["GMAIL_USER"]
    gmail_password = os.environ["GMAIL_APP_PASSWORD"]
    debug = os.environ.get("NSDL_DEBUG", "").lower() == "true"
    today = datetime.date.today()

    print("[nsdl_issuance] Fetching NSDL new issuance data...")
    try:
        cp_data = fetch_cp_issuances(debug=debug)
    except Exception as exc:
        print(f"[nsdl_issuance] CP fetch failed: {exc}")
        cp_data = None
    data = fetch_new_issuances(debug=debug)
    issues = data["issues"]
    print(f"[nsdl_issuance] {len(issues)} issuances fetched")
    for i in issues:
        print(f"  {i['issuer']} | ₹{i['issue_size_cr']} cr | {_coupon_str(i)} | "
              f"allot {_fmt_date(i['allotment_date'])} | tenor {i.get('tenure_years')}y")

    watchlist = _load_watchlist()
    history = _update_history(issues, data.get("gsec"))
    print(f"[nsdl_issuance] history: {len(history)} records in trailing window")
    html = build_email(issues, data["fy_total"], data["quarters"], watchlist, today,
                       prev_total=data.get("prev_total"), gsec=data.get("gsec"),
                       cp=cp_data, history=history)
    subject = f"NSDL New Debt Issuances — {today.strftime('%d %b %Y')}"
    if not issues:
        subject += " (no fresh issues)"
    send_email(subject, html, gmail_user, gmail_password)


if __name__ == "__main__":
    main()
