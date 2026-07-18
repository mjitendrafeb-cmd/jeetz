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


def _computed_analysis(issues, fy_total, quarters) -> list[str]:
    if not issues:
        return []
    lines = []
    total = sum(i["issue_size_cr"] for i in issues)
    latest = issues[0]["allotment_date"]
    lines.append(f"{len(issues)} fresh issuances totalling ₹{_fmt_cr(total)} cr "
                 f"(latest allotment date {_fmt_date(latest)}).")
    biggest = max(issues, key=lambda x: x["issue_size_cr"])
    lines.append(f"Largest deal: {biggest['issuer'].title()} — ₹{_fmt_cr(biggest['issue_size_cr'])} cr"
                 + (f", {biggest['tenure_years']}y tenor" if biggest.get("tenure_years") else "") + ".")
    with_coupon = [i for i in issues if i.get("coupon")]
    if with_coupon:
        w = sum(i["coupon"] * i["issue_size_cr"] for i in with_coupon) / \
            sum(i["issue_size_cr"] for i in with_coupon)
        line = (f"Coupons disclosed for {len(with_coupon)}/{len(issues)} deals — "
                f"value-weighted avg {w:.2f}%")
        if len(with_coupon) >= 2:
            lo = min(with_coupon, key=lambda x: x["coupon"])
            hi = max(with_coupon, key=lambda x: x["coupon"])
            line += (f"; cheapest {lo['issuer'].title()} at {lo['coupon']:.2f}%, "
                     f"costliest {hi['issuer'].title()} at {hi['coupon']:.2f}%")
        lines.append(line + ".")
    tenors = [i["tenure_years"] for i in issues if i.get("tenure_years")]
    if tenors:
        lines.append(f"Tenor range {min(tenors):.1f}y–{max(tenors):.1f}y "
                     f"(median {sorted(tenors)[len(tenors)//2]:.1f}y).")
    if fy_total and fy_total.get("issueSize"):
        lines.append(f"FY{fy_total.get('dataForYear', '')} corporate bond issuance so far: "
                     f"₹{_fmt_cr(float(fy_total['issueSize']))} cr across "
                     f"{fy_total.get('noOfIsin', '?')} ISINs (NSDL).")
    return lines


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
            f"rating {_rating_str(i)}"
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
        return ""


def build_email(issues, fy_total, quarters, watchlist, today) -> str:
    date_str = today.strftime("%d %B %Y")
    rows_html = ""
    watchlist_hits = []
    for i in issues:
        hit = _watchlist_hit(i["issuer"], watchlist)
        if hit:
            watchlist_hits.append(i["issuer"].title())
        star = " ⭐" if hit else ""
        row_bg = "#fff8e1" if hit else "#ffffff"
        rows_html += f"""<tr style="background:{row_bg};">
<td style="padding:7px 10px;border-bottom:1px solid #eee;font-weight:600;">{i['issuer'].title()}{star}</td>
<td style="padding:7px 10px;border-bottom:1px solid #eee;font-family:monospace;font-size:11px;">{i['isin']}</td>
<td style="padding:7px 10px;border-bottom:1px solid #eee;text-align:right;">{_fmt_cr(i['issue_size_cr'])}</td>
<td style="padding:7px 10px;border-bottom:1px solid #eee;text-align:center;">{_coupon_str(i)}</td>
<td style="padding:7px 10px;border-bottom:1px solid #eee;text-align:center;">{i.get('tenure_years') or '—'}</td>
<td style="padding:7px 10px;border-bottom:1px solid #eee;">{_fmt_date(i['allotment_date'])}</td>
<td style="padding:7px 10px;border-bottom:1px solid #eee;">{_fmt_date(i['maturity_date'])}</td>
<td style="padding:7px 10px;border-bottom:1px solid #eee;font-size:11px;">{_rating_str(i)}</td>
</tr>"""

    analysis_items = _computed_analysis(issues, fy_total, quarters)
    analysis_html = "".join(f"<li style='padding:3px 0;'>{a}</li>" for a in analysis_items)

    commentary = _claude_commentary(issues, watchlist_hits)
    commentary_html = ""
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
        empty_html = """<tr><td style="padding:20px;text-align:center;color:#666;font-size:13px;">
No fresh issuances reported on NSDL India Bond Info for this run.</td></tr>"""

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
  <div style="font-size:13px;font-weight:700;color:#cc0000;border-bottom:2px solid #cc0000;padding-bottom:4px;">FRESH ISSUANCES (SOURCE: NSDL INDIA BOND INFO)</div>
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
  <th style="padding:8px 10px;text-align:left;">Allotment</th>
  <th style="padding:8px 10px;text-align:left;">Maturity</th>
  <th style="padding:8px 10px;text-align:left;">Rating</th>
</tr>
{rows_html}{empty_html}
</table>
</td></tr>

<tr><td style="padding:14px 20px 4px;">
  <div style="font-size:13px;font-weight:700;color:#cc0000;border-bottom:2px solid #cc0000;padding-bottom:4px;">MARKET SNAPSHOT</div>
  <ul style="margin:8px 0 0;padding-left:18px;font-family:Arial,sans-serif;font-size:13px;color:#333;">{analysis_html}</ul>
</td></tr>
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
    data = fetch_new_issuances(debug=debug)
    issues = data["issues"]
    print(f"[nsdl_issuance] {len(issues)} issuances fetched")
    for i in issues:
        print(f"  {i['issuer']} | ₹{i['issue_size_cr']} cr | {_coupon_str(i)} | "
              f"allot {_fmt_date(i['allotment_date'])} | tenor {i.get('tenure_years')}y")

    watchlist = _load_watchlist()
    html = build_email(issues, data["fy_total"], data["quarters"], watchlist, today)
    subject = f"NSDL New Debt Issuances — {today.strftime('%d %b %Y')}"
    if not issues:
        subject += " (no fresh issues)"
    send_email(subject, html, gmail_user, gmail_password)


if __name__ == "__main__":
    main()
