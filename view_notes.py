#!/usr/bin/env python3
"""
view_notes.py — Generate the Daily Reads briefing site from distilled notes.

Pages generated into docs/:
  index.html    — THE page: every report, newest first, with Crux + Key Risks
                  visible immediately and full analysis one click away
  insights.html — secondary: entity-wise / sector-wise / macro-wise timelines
  sitemap.xml, robots.txt

Usage:
  python view_notes.py
  python view_notes.py --notes-dir path/to/notes --no-open
"""
import argparse
import datetime
import json
import os
import re
import sys
import webbrowser
from collections import Counter

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_NOTES_DIR = os.path.join(REPO_ROOT, "docs", "notes")
DEFAULT_DOCS_DIR = os.path.join(REPO_ROOT, "docs")

SITE_URL = "https://mjitendrafeb-cmd.github.io/jeetz"
SITE_TITLE = "Daily Reads — Report Briefings"
SITE_DESC = ("Every report distilled: the crux, the risks, and the analyst lens — "
             "finance, credit research, macro, and regulatory analysis.")
SYNC_URL = "https://github.com/mjitendrafeb-cmd/jeetz/actions/workflows/daily-reads.yml"

SIGNAL_PRIORITY = {"negative": 0, "watch": 1, "positive": 2, "neutral": 3}
SIGNAL_BORDER = {"negative": "#ef4444", "watch": "#f59e0b", "positive": "#22c55e", "neutral": "#cbd5e1"}
CS_COLOR = {"positive": "#15803d", "negative": "#dc2626", "neutral": "#6b7280", "watch": "#d97706"}
SOURCE_TYPE_LABEL = {
    "broker_research": "Broker Research",
    "regulatory": "Regulatory",
    "academic": "Academic",
    "news": "News",
    "other": "Report",
}

# ── Entity normalization ────────────────────────────────────────────────────
ENTITY_ALIAS = {
    "reserve bank of india": "RBI",
    "securities and exchange board of india": "SEBI",
    "state bank of india": "SBI",
    "larsen & toubro": "L&T",
    "power grid corporation": "Power Grid",
    "power grid corporation of india": "Power Grid",
    "indian banking sector": "Banking Sector",
    "indian economy": "Indian Economy",
}
REGULATOR_PAT = ("rbi", "sebi", "irdai", "pfrda", "nabard", "reserve bank", "ministry",
                 "government", "regulator", "central bank", "federal reserve", "ecb",
                 "fiu-ind", "cert-in", "i4c", "npci")
MACRO_PAT = ("economy", "inflation", "gdp", "interest rate", "currency", "rupee",
             "fiscal", "monetary", "liquidity", "crude", "macro", "bond market",
             "conflict", "india", "china", "mena")
TYPE_LABEL = {"company": "Company", "sector": "Sector", "regulator": "Regulator",
              "macro": "Macro", "other": "Other"}
TYPE_COLOR = {"company": "#2563eb", "sector": "#7c3aed", "regulator": "#15803d",
              "macro": "#c2410c", "other": "#64748b"}


def esc(s):
    return (str(s)
            .replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;")
            .replace("'", "&#39;"))


def fmt_date(date_str):
    try:
        return datetime.date.fromisoformat(date_str).strftime("%d %b %Y")
    except Exception:
        return date_str or ""


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "x"


def load_notes(notes_dir):
    notes = []
    if not os.path.isdir(notes_dir):
        return notes
    for name in sorted(os.listdir(notes_dir)):
        if not name.endswith("_note.json"):
            continue
        try:
            with open(os.path.join(notes_dir, name), encoding="utf-8") as f:
                notes.append(json.load(f))
        except Exception:
            pass
    # newest document first (fall back to ingest date)
    notes.sort(key=lambda n: (n.get("document_date") or n.get("date", ""),
                              n.get("ingested_at", "")), reverse=True)
    return notes


def normalize_note(note):
    out = dict(note)
    if not out.get("title"):
        src = out.get("source_file", "")
        stem = os.path.splitext(src)[0] if src else "Untitled"
        out["title"] = stem.replace("_", " ").replace("-", " ").strip()
    if "executive_summary" not in out:
        old = out.get("summary", "")
        out["executive_summary"] = [old] if old else []
    if "key_takeaways" not in out:
        kt = []
        for t in out.get("takeaways", []):
            kt.append({"takeaway": t, "analyst_lens": ""})
        out["key_takeaways"] = kt
    if "entities_impacted" not in out:
        out["entities_impacted"] = [
            {"entity": e, "impact": ""} for e in out.get("entities", [])
        ]
    for field in ("learning", "stale_items", "duplicate_stories", "tags"):
        if field not in out:
            out[field] = []
    if "source_type" not in out:
        out["source_type"] = "other"
    return out


def note_date(note):
    return note.get("document_date") or note.get("date", "")


def note_signal(note):
    kts = note.get("key_takeaways", [])
    if not kts:
        return "neutral"
    sigs = [kt.get("credit_signal", "neutral").lower() for kt in kts]
    return min(sigs, key=lambda s: SIGNAL_PRIORITY.get(s, 3))


def canonical_name(ei):
    c = (ei.get("canonical") or "").strip()
    if c:
        return c
    name = (ei.get("entity") or "").strip()
    if not name:
        return ""
    m = re.search(r"\(([A-Za-z&]{2,10})\)\s*$", name)
    base = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
    if base.lower() in ENTITY_ALIAS:
        return ENTITY_ALIAS[base.lower()]
    if m and m.group(1).isupper():
        return m.group(1)
    base = re.sub(r"\s+(ltd\.?|limited|corp\.?|corporation of india|corporation)$",
                  "", base, flags=re.I).strip()
    return base


def guess_type(name):
    l = name.lower()
    if any(k in l for k in REGULATOR_PAT):
        return "regulator"
    if "sector" in l or "industry" in l or "banking" in l:
        return "sector"
    if any(k in l for k in MACRO_PAT):
        return "macro"
    return "company"


def entity_type_of(ei, canon):
    t = (ei.get("type") or "").strip().lower()
    if t in ("company", "sector", "regulator", "macro"):
        return t
    if t in ("government",):
        return "regulator"
    return guess_type(canon)


def build_entities(notes):
    entities = {}
    for idx, raw in enumerate(notes):
        n = normalize_note(raw)
        date = note_date(n)
        title = n.get("title", "Untitled")
        dom_sig = note_signal(n)
        row_id = f"r{idx}"

        note_canons = []
        for ei in n.get("entities_impacted", []):
            canon = canonical_name(ei)
            if not canon:
                continue
            key = canon.lower()
            e = entities.setdefault(key, {"name": canon, "type": None,
                                          "type_votes": Counter(), "docs": set(),
                                          "items": []})
            e["type_votes"][entity_type_of(ei, canon)] += 1
            e["docs"].add(idx)
            impact = (ei.get("impact") or "").strip()
            if impact:
                e["items"].append({"date": date, "kind": "impact", "text": impact,
                                   "lens": "", "signal": dom_sig,
                                   "doc_title": title, "row_id": row_id})
            note_canons.append((key, canon))

        for kt in n.get("key_takeaways", []):
            blob = (kt.get("takeaway", "") + " " + kt.get("analyst_lens", "")).lower()
            sig = kt.get("credit_signal", "neutral").lower()
            for key, canon in note_canons:
                if canon.lower() in blob:
                    entities[key]["items"].append({
                        "date": date, "kind": "takeaway",
                        "text": kt.get("takeaway", ""),
                        "lens": kt.get("analyst_lens", ""),
                        "signal": sig, "doc_title": title, "row_id": row_id})

    for e in entities.values():
        e["type"] = e["type_votes"].most_common(1)[0][0] if e["type_votes"] else "company"
        e["items"].sort(key=lambda i: i["date"], reverse=True)
        e["latest"] = max((i["date"] for i in e["items"]), default="")
        e["sig_counts"] = Counter(i["signal"] for i in e["items"])
    return entities


# ── Shared chrome ───────────────────────────────────────────────────────────

BASE_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  background:#f6f7f9;color:#1e2430;font-size:15px;line-height:1.6}
.top{background:#fff;border-bottom:1px solid #e6e8ec;position:sticky;top:0;z-index:10}
.top-in{max-width:900px;margin:0 auto;padding:12px 20px;display:flex;
  align-items:center;gap:12px;flex-wrap:wrap}
.brand{font-size:17px;font-weight:800;color:#1e2430;text-decoration:none;white-space:nowrap}
.upd{font-size:12px;color:#8a919c}
.top-actions{margin-left:auto;display:flex;gap:8px;align-items:center}
.btn{border:1px solid #d6dae0;background:#fff;color:#3a4150;padding:7px 14px;
  border-radius:6px;font-size:13px;font-weight:600;cursor:pointer;text-decoration:none;
  display:inline-flex;align-items:center;gap:5px;white-space:nowrap;transition:all .15s}
.btn:hover{background:#f0f2f5}
.btn.sync{background:#107c10;border-color:#0e6b0e;color:#fff}
.btn.sync:hover{background:#0e6b0e}
mark{background:#fff100;border-radius:2px;padding:0 1px}
.toast{position:fixed;bottom:24px;right:24px;background:#1e2430;color:#fff;
  padding:12px 20px;border-radius:8px;font-size:13px;font-weight:600;
  box-shadow:0 4px 16px rgba(0,0,0,.25);z-index:999;opacity:0;
  transform:translateY(8px);transition:all .25s;pointer-events:none}
.toast.show{opacity:1;transform:translateY(0)}
"""

SHARE_JS = """
function showToast(msg){
  var t=document.getElementById('toast');
  if(!t)return;
  t.textContent=msg;t.classList.add('show');
  setTimeout(function(){t.classList.remove('show');},3000);
}
function doShare(){
  var url=window.location.href;
  if(navigator.clipboard){
    navigator.clipboard.writeText(url).then(function(){showToast('Link copied to clipboard');})
      .catch(function(){prompt('Copy this link:',url);});
  }else{prompt('Copy this link:',url);}
}
"""


def top_bar(updated, count, page="home"):
    back = ('<a class="brand" href="index.html">&#128218; Daily Reads</a>' if page != "home"
            else '<span class="brand">&#128218; Daily Reads</span>')
    entity_link = ('' if page == "insights"
                   else '<a class="btn" href="insights.html">By Entity &rarr;</a>')
    return (
        f'<div class="top"><div class="top-in">'
        f'{back}'
        f'<span class="upd">{count} report{"s" if count != 1 else ""} &middot; updated {updated}</span>'
        f'<div class="top-actions">'
        f'<a class="btn sync" href="{SYNC_URL}" target="_blank" '
        f'title="Opens GitHub Actions — click Run workflow to pull new files from Drive">'
        f'&#8635; Sync from Drive</a>'
        f'{entity_link}'
        f'<button class="btn" onclick="doShare()">&#128279; Share</button>'
        f'</div></div></div>'
    )


# ── Main briefing page ──────────────────────────────────────────────────────

def render_doc(raw_note, idx):
    n = normalize_note(raw_note)
    rid = f"r{idx}"
    title = n.get("title", "Untitled")
    date = note_date(n)
    category = n.get("category", "Other")
    st_label = SOURCE_TYPE_LABEL.get((n.get("source_type") or "other").lower(), "Report")
    source = n.get("source_file", "")
    kts = n.get("key_takeaways", [])
    sig = note_signal(n)
    border = SIGNAL_BORDER.get(sig, "#cbd5e1")

    crux = n.get("executive_summary") or []
    crux_fallback = not crux
    if crux_fallback:
        crux = [kt.get("takeaway", "") for kt in kts]

    risks = [kt for kt in kts
             if kt.get("credit_signal", "").lower() in ("negative", "watch")]
    positives = [kt for kt in kts
                 if kt.get("credit_signal", "").lower() not in ("negative", "watch")]
    entities = n.get("entities_impacted", [])
    learning = n.get("learning", [])
    dupes = n.get("duplicate_stories", [])

    search_blob = " ".join([
        title, category, source,
        " ".join(n.get("tags", [])),
        " ".join(crux),
        " ".join(kt.get("takeaway", "") + " " + kt.get("analyst_lens", "") for kt in kts),
        " ".join(ei.get("canonical", "") or ei.get("entity", "") for ei in entities),
    ]).lower().replace('"', "'")

    crux_items = "".join(f"<li>{esc(b)}</li>" for b in crux)
    crux_title = "&#128204; Crux of the Report" if not crux_fallback else "&#128204; Key Points"

    risk_html = ""
    if risks:
        items = ""
        for kt in risks:
            cs = kt.get("credit_signal", "").lower()
            color = CS_COLOR.get(cs, "#6b7280")
            lens = kt.get("analyst_lens", "")
            lens_html = f'<div class="risk-lens">{esc(lens)}</div>' if lens else ""
            items += (
                f'<div class="risk-item" style="border-left-color:{color}">'
                f'<div class="risk-sig" style="color:{color}">&#x25CF; {esc(cs.upper())}</div>'
                f'<div class="risk-tw">{esc(kt.get("takeaway", ""))}</div>'
                f'{lens_html}</div>'
            )
        risk_html = (f'<div class="sec"><div class="sec-t risk-t">&#9888; Risk Analysis '
                     f'<span class="sec-n">{len(risks)}</span></div>{items}</div>')

    # Full analysis (collapsed): remaining takeaways + entities + learnings
    more_parts = []
    if positives:
        rows = ""
        for kt in positives:
            cs = kt.get("credit_signal", "").lower()
            color = CS_COLOR.get(cs, "#6b7280")
            rows += (
                f'<div class="risk-item" style="border-left-color:{color}">'
                f'<div class="risk-sig" style="color:{color}">&#x25CF; {esc(cs.upper())}</div>'
                f'<div class="risk-tw">{esc(kt.get("takeaway", ""))}</div>'
                + (f'<div class="risk-lens">{esc(kt.get("analyst_lens", ""))}</div>'
                   if kt.get("analyst_lens") else "")
                + '</div>'
            )
        more_parts.append(f'<div class="sec"><div class="sec-t">Other Takeaways</div>{rows}</div>')
    if entities:
        rows = "".join(
            f'<tr><td class="ent-c">{esc(ei.get("canonical") or ei.get("entity", ""))}</td>'
            f'<td>{esc(ei.get("impact", ""))}</td></tr>'
            for ei in entities
        )
        more_parts.append(
            f'<div class="sec"><div class="sec-t">Who Is Impacted</div>'
            f'<div class="tblw"><table class="ent-tbl">'
            f'<tbody>{rows}</tbody></table></div></div>'
        )
    if learning:
        items = "".join(f"<li>{esc(l)}</li>" for l in learning)
        more_parts.append(
            f'<div class="sec"><div class="sec-t">What Can I Learn</div>'
            f'<ul class="crux learn">{items}</ul></div>'
        )
    if dupes:
        items = "".join(f"<li>{esc(s)}</li>" for s in dupes)
        more_parts.append(
            f'<div class="sec"><div class="sec-t" style="color:#6d28d9">Already Covered Earlier</div>'
            f'<ul class="crux" style="color:#5b21b6">{items}</ul></div>'
        )
    more_html = "".join(more_parts)
    more_btn = ""
    if more_html:
        more_btn = (
            f'<button class="more-btn" id="{rid}-btn" onclick="toggleMore(\'{rid}\')">'
            f'Full analysis &#9662;</button>'
            f'<div class="more" id="{rid}-more" hidden>{more_html}</div>'
        )

    month = (date or "")[:7]
    key = slugify(os.path.splitext(source)[0] if source else title)
    week_ago = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    is_new = (n.get("ingested_at", "")[:10] or n.get("date", "")) >= week_ago
    new_chip = '<span class="new-chip">NEW</span>' if is_new else ""

    return (
        f'<article class="doc" id="{rid}" data-search="{esc(search_blob)}" '
        f'data-key="{key}" data-month="{month}" '
        f'style="border-left-color:{border}">'
        f'<div class="doc-top">'
        f'<h2 class="doc-t">{esc(title)}{new_chip}</h2>'
        f'<div class="doc-btns">'
        f'<button class="read-btn" data-key="{key}" '
        f'onclick="toggleRead(\'{key}\')">&#10003; Mark as read</button>'
        f'<button class="del-btn" data-key="{key}" '
        f'onclick="toggleDelete(\'{key}\')">&#128465;</button>'
        f'</div>'
        f'</div>'
        f'<div class="doc-meta">{esc(fmt_date(date))} &middot; {esc(st_label)} &middot; '
        f'{esc(category)} &middot; <span class="doc-src">{esc(source)}</span></div>'
        f'<div class="sec"><div class="sec-t">{crux_title}</div>'
        f'<ul class="crux">{crux_items}</ul></div>'
        f'{risk_html}'
        f'{more_btn}'
        f'</article>'
    )


def build_jsonld(notes):
    articles = []
    for note in notes[:30]:
        n = normalize_note(note)
        articles.append({
            "@type": "Article",
            "headline": n.get("title", ""),
            "datePublished": n.get("date", ""),
            "description": (n.get("executive_summary") or [""])[0],
            "keywords": ", ".join(n.get("tags", [])),
        })
    ld = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": SITE_TITLE,
        "description": SITE_DESC,
        "url": SITE_URL + "/",
        "hasPart": articles,
    }
    return json.dumps(ld, ensure_ascii=False, indent=None)


def month_label(ym):
    try:
        return datetime.date.fromisoformat(ym + "-01").strftime("%b %Y")
    except Exception:
        return ym or "Undated"


def generate_briefing(notes):
    now_str = datetime.datetime.now().strftime("%d %b %Y, %H:%M")
    total = len(notes)
    jsonld = build_jsonld(notes)

    month_counts = Counter((note_date(n) or "")[:7] for n in notes)
    months = sorted(month_counts.keys(), reverse=True)
    month_items = (f'<div class="side-i m-i active" data-month="all" '
                   f'onclick="setMonth(\'all\')">All months '
                   f'<span class="cnt">{total}</span></div>')
    for m in months:
        month_items += (f'<div class="side-i m-i" data-month="{m}" '
                        f'onclick="setMonth(\'{m}\')">{esc(month_label(m))} '
                        f'<span class="cnt">{month_counts[m]}</span></div>')

    toc_items = ""
    for idx, raw in enumerate(notes):
        n = normalize_note(raw)
        sig = note_signal(n)
        color = CS_COLOR.get(sig, "#6b7280") if sig != "neutral" else "#9aa1ab"
        source = n.get("source_file", "")
        key = slugify(os.path.splitext(source)[0] if source else n.get("title", ""))
        month = (note_date(n) or "")[:7]
        toc_items += (
            f'<a class="toc-i" href="#r{idx}" data-key="{key}" data-month="{month}">'
            f'<span class="toc-dot" style="background:{color}"></span>'
            f'<span class="toc-t">{esc(n.get("title", "Untitled"))}</span>'
            f'<span class="toc-d">{esc(fmt_date(note_date(n)))}</span></a>'
        )

    docs_html = "\n".join(render_doc(n, i) for i, n in enumerate(notes))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(SITE_TITLE)}</title>
<meta name="description" content="{esc(SITE_DESC)}">
<link rel="canonical" href="{SITE_URL}/">
<meta property="og:type" content="website">
<meta property="og:url" content="{SITE_URL}/">
<meta property="og:title" content="{esc(SITE_TITLE)}">
<meta property="og:description" content="{esc(SITE_DESC)}">
<script type="application/ld+json">{jsonld}</script>
<style>
{BASE_CSS}
.shell{{max-width:1320px;margin:0 auto;padding:18px 18px;display:flex;gap:22px}}
aside{{width:198px;flex-shrink:0;position:sticky;top:66px;align-self:flex-start}}
.side-sec{{background:#fff;border:1px solid #e6e8ec;border-radius:10px;
  padding:6px 0 8px;margin-bottom:14px}}
.side-h{{font-size:10.5px;font-weight:800;text-transform:uppercase;letter-spacing:.7px;
  color:#8a919c;padding:9px 15px 5px}}
.side-i{{display:flex;justify-content:space-between;align-items:center;gap:8px;
  padding:8px 15px;font-size:13px;font-weight:600;color:#3a4150;cursor:pointer;
  border-left:3px solid transparent;transition:background .1s}}
.side-i:hover{{background:#f0f2f5}}
.side-i.active{{background:#eef4ff;color:#2563eb;border-left-color:#2563eb}}
.cnt{{font-size:11px;color:#8a919c;background:#f0f2f5;padding:1px 8px;border-radius:9px}}
.side-i.active .cnt{{background:#dbe7ff;color:#2563eb}}
main{{flex:1;min-width:0}}
.searchrow{{margin-bottom:14px}}
#search{{width:100%;border:1px solid #d6dae0;background:#fff;color:#1e2430;
  padding:11px 16px;border-radius:8px;font-size:14px;outline:none}}
#search:focus{{border-color:#2563eb;box-shadow:0 0 0 2px #2563eb22}}
#search::placeholder{{color:#9aa1ab}}
.toc{{background:#fff;border:1px solid #e6e8ec;border-radius:10px;
  padding:8px 0;margin-bottom:20px}}
.toc-h{{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;
  color:#8a919c;padding:8px 18px 4px}}
.toc-i{{display:flex;align-items:baseline;gap:9px;padding:7px 18px;
  text-decoration:none;transition:background .1s}}
.toc-i:hover{{background:#f0f2f5}}
.toc-dot{{width:8px;height:8px;border-radius:50%;flex-shrink:0;align-self:center}}
.toc-t{{font-size:13.5px;font-weight:600;color:#1e2430;flex:1;min-width:0}}
.toc-d{{font-size:11.5px;color:#9aa1ab;white-space:nowrap}}
.doc{{background:#fff;border:1px solid #e6e8ec;border-left-width:4px;
  border-radius:10px;padding:20px 24px;margin-bottom:18px;scroll-margin-top:70px}}
.doc-top{{display:flex;align-items:flex-start;gap:14px;justify-content:space-between}}
.doc-t{{font-size:18px;font-weight:800;line-height:1.35;color:#111726}}
.new-chip{{background:#dcfce7;color:#15803d;font-size:10px;font-weight:800;
  letter-spacing:.5px;padding:2px 8px;border-radius:9px;margin-left:8px;
  vertical-align:3px;white-space:nowrap}}
.doc-btns{{display:flex;gap:6px;flex-shrink:0;align-items:flex-start}}
.read-btn{{border:1px solid #d6dae0;background:#fff;color:#5b6472;
  padding:6px 12px;border-radius:6px;font-size:12px;font-weight:600;cursor:pointer;
  white-space:nowrap;flex-shrink:0;transition:all .15s}}
.read-btn:hover{{background:#f0fdf4;border-color:#86efac;color:#15803d}}
.del-btn{{border:1px solid #d6dae0;background:#fff;color:#8a919c;
  padding:6px 10px;border-radius:6px;font-size:12px;font-weight:600;cursor:pointer;
  white-space:nowrap;flex-shrink:0;transition:all .15s}}
.del-btn:hover{{background:#fef2f2;border-color:#fca5a5;color:#dc2626}}
.doc-meta{{font-size:12.5px;color:#8a919c;margin:5px 0 4px}}
.doc-src{{color:#b4bac2}}
.sec{{margin-top:16px}}
.sec-t{{font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.7px;
  color:#5b6472;margin-bottom:9px;display:flex;align-items:center;gap:7px}}
.sec-t.risk-t{{color:#b45309}}
.sec-n{{background:#fef3c7;color:#b45309;font-size:11px;padding:1px 8px;border-radius:9px}}
.crux{{padding-left:22px}}
.crux li{{margin-bottom:8px;line-height:1.62;color:#242b38}}
.learn li{{color:#0c4a6e}}
.risk-item{{border-left:3px solid #e6e8ec;padding:2px 0 2px 14px;margin-bottom:13px}}
.risk-sig{{font-size:10.5px;font-weight:800;letter-spacing:.5px;margin-bottom:3px}}
.risk-tw{{font-weight:600;line-height:1.55;color:#1e2430}}
.risk-lens{{font-size:13.5px;color:#5b6472;margin-top:4px;line-height:1.55}}
.more-btn{{margin-top:14px;border:1px solid #d6dae0;background:#f8f9fb;color:#3a4150;
  padding:8px 16px;border-radius:6px;font-size:13px;font-weight:600;cursor:pointer}}
.more-btn:hover{{background:#eef0f4}}
.tblw{{overflow-x:auto}}
.ent-tbl{{width:100%;border-collapse:collapse;font-size:13.5px}}
.ent-tbl td{{padding:8px 12px 8px 0;vertical-align:top;border-bottom:1px solid #f0f2f5;
  line-height:1.55}}
.ent-c{{font-weight:700;white-space:nowrap;width:1%;padding-right:18px;color:#1e2430}}
mark.hl{{background:#fde047;color:#111726;border-radius:2px;padding:0 1px}}
#empty{{text-align:center;padding:60px 20px;color:#8a919c;display:none}}
@media(max-width:820px){{
  .shell{{flex-direction:column;padding:12px}}
  aside{{width:100%;position:static;display:flex;gap:10px}}
  .side-sec{{flex:1;min-width:0;margin-bottom:0}}
  .m-i,.side-i{{padding:7px 12px}}
  .doc{{padding:16px 16px}}.toc-d{{display:none}}
}}
@media print{{.top,.searchrow,.toc,.more-btn,aside,.read-btn{{display:none!important}}
  .more{{display:block!important}}body{{background:#fff}}}}
</style>
</head>
<body>

{top_bar(now_str, total, "home")}

<div class="shell">
  <aside>
    <div class="side-sec">
      <div class="side-h">View</div>
      <div class="side-i active" id="v-briefing" onclick="setView('briefing')">
        &#128229; Briefing <span class="cnt" id="cnt-briefing"></span></div>
      <div class="side-i" id="v-archive" onclick="setView('archive')">
        &#9989; Archive <span class="cnt" id="cnt-archive"></span></div>
      <div class="side-i" id="v-trash" onclick="setView('trash')">
        &#128465; Trash <span class="cnt" id="cnt-trash"></span></div>
    </div>
    <div class="side-sec">
      <div class="side-h">Months</div>
      {month_items}
    </div>
  </aside>
  <main>
    <div class="searchrow">
      <input id="search" type="search"
             placeholder="Search reports, risks, companies&#8230;"
             oninput="doSearch(this.value)" autocomplete="off">
    </div>
    <div class="toc" id="toc">
      <div class="toc-h">In this briefing</div>
      {toc_items}
    </div>
    {docs_html}
    <div id="empty">Nothing here — try another view, month, or search.</div>
  </main>
</div>
<div class="toast" id="toast"></div>

<script>
{SHARE_JS}
(function(){{
  var READ_KEY='dailyreads_read';
  var DEL_KEY='dailyreads_deleted';
  var state={{view:'briefing',month:'all',q:''}};

  function getSet(k){{
    try{{return new Set(JSON.parse(localStorage.getItem(k)||'[]'));}}
    catch(e){{return new Set();}}
  }}
  function saveSet(k,s){{localStorage.setItem(k,JSON.stringify(Array.from(s)));}}
  function getRead(){{return getSet(READ_KEY);}}
  function saveRead(s){{saveSet(READ_KEY,s);}}
  function getDel(){{return getSet(DEL_KEY);}}
  function saveDel(s){{saveSet(DEL_KEY,s);}}

  function clearMarks(root){{
    root.querySelectorAll('mark.hl').forEach(function(m){{
      var p=m.parentNode;
      p.replaceChild(document.createTextNode(m.textContent),m);
      p.normalize();
    }});
  }}
  function highlight(el,q){{
    if(!q)return;
    var re=new RegExp('('+q.replace(/[.*+?^${{}}()|[\\]\\\\]/g,'\\\\$&')+')','gi');
    var walker=document.createTreeWalker(el,NodeFilter.SHOW_TEXT,null);
    var nodes=[];
    while(walker.nextNode())nodes.push(walker.currentNode);
    nodes.forEach(function(n){{
      var pn=n.parentNode;
      if(!n.nodeValue.trim())return;
      if(pn.nodeName==='MARK'||pn.nodeName==='BUTTON'||pn.nodeName==='SCRIPT')return;
      var v=n.nodeValue;
      re.lastIndex=0;
      if(!re.test(v))return;
      re.lastIndex=0;
      var frag=document.createDocumentFragment(),last=0,m;
      while((m=re.exec(v))){{
        frag.appendChild(document.createTextNode(v.slice(last,m.index)));
        var mk=document.createElement('mark');
        mk.className='hl';mk.textContent=m[0];
        frag.appendChild(mk);
        last=m.index+m[0].length;
      }}
      frag.appendChild(document.createTextNode(v.slice(last)));
      pn.replaceChild(frag,n);
    }});
  }}

  function apply(){{
    var read=getRead(),del=getDel();
    var q=state.q.toLowerCase().trim();
    var vis=0,nB=0,nA=0,nT=0;
    document.querySelectorAll('.doc').forEach(function(d){{
      clearMarks(d);
      var key=d.dataset.key;
      var isDel=del.has(key);
      var isRead=read.has(key);
      if(isDel)nT++;else if(isRead)nA++;else nB++;
      var viewOk;
      if(state.view==='trash')viewOk=isDel;
      else if(state.view==='archive')viewOk=isRead&&!isDel;
      else viewOk=!isRead&&!isDel;
      var monthOk=state.month==='all'||d.dataset.month===state.month;
      var qOk=!q||d.dataset.search.includes(q);
      var show=viewOk&&monthOk&&qOk;
      d.style.display=show?'':'none';
      var btn=d.querySelector('.read-btn');
      var dbtn=d.querySelector('.del-btn');
      if(btn){{
        btn.style.display=isDel?'none':'';
        btn.innerHTML=isRead?'&#8617; Move to briefing':'&#10003; Mark as read';
      }}
      if(dbtn)dbtn.innerHTML=isDel?'&#8617; Restore':'&#128465;';
      if(show){{
        vis++;
        var more=document.getElementById(d.id+'-more');
        var mbtn=document.getElementById(d.id+'-btn');
        if(q&&more){{more.hidden=false;if(mbtn)mbtn.innerHTML='Hide full analysis \\u25B4';}}
        if(q)highlight(d,q);
      }}
    }});
    document.getElementById('cnt-briefing').textContent=nB;
    document.getElementById('cnt-archive').textContent=nA;
    document.getElementById('cnt-trash').textContent=nT;
    document.querySelectorAll('.toc-i').forEach(function(t){{
      var id=t.getAttribute('href').slice(1);
      var d=document.getElementById(id);
      t.style.display=(d&&d.style.display!=='none')?'':'none';
    }});
    document.getElementById('toc').style.display=(q||state.view!=='briefing')?'none':'';
    document.getElementById('empty').style.display=vis?'none':'block';
    document.getElementById('v-briefing').classList.toggle('active',state.view==='briefing');
    document.getElementById('v-archive').classList.toggle('active',state.view==='archive');
    document.getElementById('v-trash').classList.toggle('active',state.view==='trash');
    document.querySelectorAll('.m-i').forEach(function(mi){{
      mi.classList.toggle('active',mi.dataset.month===state.month);
    }});
  }}

  window.setView=function(v){{state.view=v;apply();window.scrollTo(0,0);}};
  window.setMonth=function(m){{state.month=m;apply();window.scrollTo(0,0);}};
  window.doSearch=function(q){{state.q=q;apply();}};
  window.toggleRead=function(key){{
    var r=getRead();
    if(r.has(key)){{r.delete(key);showToast('Moved back to briefing');}}
    else{{r.add(key);showToast('Marked as read — moved to Archive');}}
    saveRead(r);
    apply();
  }};
  window.toggleDelete=function(key){{
    var d=getDel();
    if(d.has(key)){{d.delete(key);showToast('Restored');}}
    else{{d.add(key);showToast('Moved to Trash — restore anytime from the Trash view');}}
    saveDel(d);
    apply();
  }};
  window.toggleMore=function(id){{
    var m=document.getElementById(id+'-more');
    var b=document.getElementById(id+'-btn');
    if(!m)return;
    var open=!m.hidden;
    m.hidden=open;
    if(b)b.innerHTML=open?'Full analysis \\u25BE':'Hide full analysis \\u25B4';
  }};

  if(window.location.hash){{
    var el=document.getElementById(window.location.hash.slice(1));
    if(el&&getRead().has(el.dataset.key))state.view='archive';
  }}
  apply();
  if(window.location.hash){{
    var el2=document.getElementById(window.location.hash.slice(1));
    if(el2)setTimeout(function(){{el2.scrollIntoView({{block:'start'}});}},50);
  }}
}})();
</script>
</body>
</html>"""


# ── Insights page (entity / sector / macro views) ───────────────────────────

def sig_dot(sig, count=None):
    color = CS_COLOR.get(sig, "#6b7280")
    txt = f"&nbsp;{count}" if count is not None else ""
    return (f'<span style="display:inline-flex;align-items:center;gap:3px;font-size:11px;'
            f'font-weight:700;color:{color}">'
            f'<span style="width:8px;height:8px;border-radius:50%;background:{color};'
            f'display:inline-block"></span>{txt}</span>')


def render_entity_card(e):
    slug = slugify(e["name"])
    tcol = TYPE_COLOR.get(e["type"], "#64748b")
    tlabel = TYPE_LABEL.get(e["type"], "Other")

    dots = ""
    for sig in ("negative", "watch", "positive", "neutral"):
        c = e["sig_counts"].get(sig, 0)
        if c:
            dots += sig_dot(sig, c) + " "

    rows = ""
    for it in e["items"]:
        color = CS_COLOR.get(it["signal"], "#6b7280")
        kind_lbl = "Impact" if it["kind"] == "impact" else "Takeaway"
        lens = (f'<div style="font-size:12px;color:#5b6472;margin-top:3px">{esc(it["lens"])}</div>'
                if it.get("lens") else "")
        rows += (
            f'<tr>'
            f'<td class="tl-date">{esc(fmt_date(it["date"]))}</td>'
            f'<td class="tl-sig"><span style="color:{color};font-size:10px;font-weight:700;'
            f'text-transform:uppercase">&#x25CF; {esc(it["signal"])}</span><br>'
            f'<span class="tl-kind">{kind_lbl}</span></td>'
            f'<td class="tl-text">{esc(it["text"])}{lens}</td>'
            f'<td class="tl-src"><a href="index.html#{it["row_id"]}">'
            f'{esc(it["doc_title"][:48])}{"&#8230;" if len(it["doc_title"]) > 48 else ""}</a></td>'
            f'</tr>'
        )

    search_blob = (e["name"] + " " + " ".join(i["text"] for i in e["items"])).lower().replace('"', "'")

    return (
        f'<div class="ent-card" id="e-{slug}" data-type="{e["type"]}" '
        f'data-search="{esc(search_blob)}">'
        f'<div class="ent-hd" onclick="toggleEnt(\'e-{slug}\')">'
        f'<span class="ent-ico" id="e-{slug}-ico">&#8250;</span>'
        f'<span class="ent-name">{esc(e["name"])}</span>'
        f'<span class="ent-type" style="color:{tcol};background:{tcol}14;border-color:{tcol}40">{tlabel}</span>'
        f'<span class="ent-sigs">{dots}</span>'
        f'<span class="ent-meta">{len(e["docs"])} doc{"s" if len(e["docs"]) != 1 else ""}'
        f'{" &middot; last " + esc(fmt_date(e["latest"])) if e["latest"] else ""}</span>'
        f'</div>'
        f'<div class="ent-bd" id="e-{slug}-bd" hidden>'
        f'<div class="tbl-wrap"><table class="tl-table"><thead><tr>'
        f'<th style="width:11%">Date</th><th style="width:11%">Signal</th>'
        f'<th>Insight</th><th style="width:22%">Source</th>'
        f'</tr></thead><tbody>{rows}</tbody></table></div>'
        f'</div></div>'
    )


def generate_insights(entities, total_notes):
    now_str = datetime.datetime.now().strftime("%d %b %Y, %H:%M")
    ents = sorted(entities.values(), key=lambda e: (-len(e["docs"]), -len(e["items"]), e["name"]))

    counts = Counter()
    for e in ents:
        if e["type"] == "sector":
            counts["sectors"] += 1
        elif e["type"] in ("regulator", "macro"):
            counts["macro"] += 1
        else:
            counts["companies"] += 1

    cards = "".join(render_entity_card(e) for e in ents)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>By Entity — Daily Reads</title>
<meta name="description" content="Entity-wise, sector-wise and macro-wise credit insights.">
<link rel="canonical" href="{SITE_URL}/insights.html">
<style>
{BASE_CSS}
.wrap{{max-width:900px;margin:0 auto;padding:20px}}
.tab-bar{{display:flex;gap:4px;border-bottom:2px solid #e6e8ec;margin-bottom:6px;
  align-items:center;flex-wrap:wrap}}
.tab{{padding:9px 16px;font-size:13px;font-weight:600;color:#5b6472;cursor:pointer;
  border-bottom:2px solid transparent;margin-bottom:-2px;background:none;border-top:none;
  border-left:none;border-right:none}}
.tab:hover{{color:#2563eb}}
.tab.active{{color:#2563eb;border-bottom-color:#2563eb}}
.tab .tcnt{{font-size:11px;color:#9aa1ab;margin-left:4px}}
#esearch{{margin-left:auto;border:1px solid #d6dae0;background:#fff;color:#1e2430;
  padding:7px 12px;border-radius:6px;font-size:13px;outline:none;width:230px;margin-bottom:4px}}
#esearch:focus{{border-color:#2563eb}}
.ent-card{{background:#fff;border:1px solid #e6e8ec;border-radius:8px;margin-top:10px;
  overflow:hidden}}
.ent-hd{{display:flex;align-items:center;gap:10px;padding:12px 16px;cursor:pointer;
  transition:background .1s;flex-wrap:wrap}}
.ent-hd:hover{{background:#f0f2f5}}
.ent-ico{{font-size:18px;color:#2563eb;line-height:1;transition:transform .18s;
  display:inline-block;flex-shrink:0}}
.ent-ico.open{{transform:rotate(90deg)}}
.ent-name{{font-size:14px;font-weight:700;color:#1e2430}}
.ent-type{{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.4px;
  padding:2px 8px;border-radius:10px;border:1px solid}}
.ent-sigs{{display:inline-flex;gap:8px;align-items:center}}
.ent-meta{{margin-left:auto;font-size:11px;color:#9aa1ab;white-space:nowrap}}
.ent-bd{{border-top:1px solid #e6e8ec;background:#f8f9fb;padding:12px 16px}}
.tbl-wrap{{overflow-x:auto}}
.tl-table{{width:100%;border-collapse:collapse;font-size:13px;background:#fff;
  border:1px solid #e6e8ec}}
.tl-table thead th{{padding:7px 12px;text-align:left;font-size:10px;font-weight:700;
  text-transform:uppercase;letter-spacing:.4px;color:#5b6472;
  background:#f8f9fb;border-bottom:1px solid #e6e8ec}}
.tl-table td{{padding:9px 12px;vertical-align:top;border-bottom:1px solid #f0f2f5;
  line-height:1.55}}
.tl-date{{font-size:12px;color:#5b6472;white-space:nowrap}}
.tl-kind{{font-size:10px;color:#b4bac2}}
.tl-text{{color:#1e2430}}
.tl-src a{{color:#2563eb;text-decoration:none;font-size:12px}}
.tl-src a:hover{{text-decoration:underline}}
#empty{{text-align:center;padding:50px 20px;color:#9aa1ab;display:none}}
@media(max-width:700px){{.ent-meta{{display:none}}.tl-src{{display:none}}
  .tl-table thead th:last-child{{display:none}}#esearch{{width:100%;margin-left:0}}}}
</style>
</head>
<body>

{top_bar(now_str, total_notes, "insights")}

<div class="wrap">
  <div class="tab-bar">
    <button class="tab active" id="tab-companies" onclick="setTab('companies')">
      &#127970; Companies<span class="tcnt">{counts.get("companies", 0)}</span></button>
    <button class="tab" id="tab-sectors" onclick="setTab('sectors')">
      &#128202; Sectors<span class="tcnt">{counts.get("sectors", 0)}</span></button>
    <button class="tab" id="tab-macro" onclick="setTab('macro')">
      &#127758; Macro &amp; Policy<span class="tcnt">{counts.get("macro", 0)}</span></button>
    <input id="esearch" type="search" placeholder="Search entities &amp; insights&#8230;"
           oninput="setQ(this.value)" autocomplete="off">
  </div>
  <div id="cards">{cards or '<div style="padding:40px;text-align:center;color:#9aa1ab">No entities yet.</div>'}</div>
  <div id="empty">No entities match your filter.</div>
</div>
<div class="toast" id="toast"></div>

<script>
{SHARE_JS}
(function(){{
  var TAB_TYPES={{companies:['company','other'],sectors:['sector'],macro:['regulator','macro']}};
  var state={{tab:'companies',q:''}};

  window.toggleEnt=function(id){{
    var bd=document.getElementById(id+'-bd');
    var ico=document.getElementById(id+'-ico');
    if(!bd)return;
    var isOpen=!bd.hidden;
    bd.hidden=isOpen;
    if(ico)ico.classList.toggle('open',!isOpen);
  }};

  function apply(){{
    var types=TAB_TYPES[state.tab]||[];
    var q=state.q.toLowerCase().trim();
    var vis=0;
    document.querySelectorAll('.ent-card').forEach(function(c){{
      var typeOk=types.indexOf(c.dataset.type)!==-1;
      var qOk=!q||c.dataset.search.includes(q);
      var show=(q?qOk:typeOk&&qOk);
      c.style.display=show?'':'none';
      if(show)vis++;
    }});
    document.getElementById('empty').style.display=vis?'none':'block';
    ['companies','sectors','macro'].forEach(function(t){{
      document.getElementById('tab-'+t).classList.toggle('active',t===state.tab&&!q);
    }});
  }}

  window.setTab=function(t){{
    state.tab=t;state.q='';
    var s=document.getElementById('esearch');if(s)s.value='';
    apply();
  }};
  window.setQ=function(v){{state.q=v;apply();}};

  apply();
  if(window.location.hash){{
    var id=window.location.hash.slice(1);
    var card=document.getElementById(id);
    if(card){{
      var t=card.dataset.type;
      for(var tab in TAB_TYPES){{
        if(TAB_TYPES[tab].indexOf(t)!==-1){{state.tab=tab;break;}}
      }}
      apply();
      toggleEnt(id);
      setTimeout(function(){{card.scrollIntoView({{block:'start'}});}},50);
    }}
  }}
}})();
</script>
</body>
</html>"""


# ── Sitemap / robots ────────────────────────────────────────────────────────

def generate_sitemap(notes, out_path):
    lastmod = max((n.get("date", "") for n in notes), default="")
    pages = [("", "1.0"), ("insights.html", "0.8")]
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for page, prio in pages:
        lm = f"<lastmod>{lastmod}</lastmod>" if lastmod else ""
        lines.append(f'  <url><loc>{SITE_URL}/{page}</loc>{lm}'
                     f'<changefreq>daily</changefreq><priority>{prio}</priority></url>')
    lines.append('</urlset>')
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def write_robots(docs_dir):
    path = os.path.join(docs_dir, "robots.txt")
    content = f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def main():
    p = argparse.ArgumentParser(description="Generate the Daily Reads briefing site")
    p.add_argument("--notes-dir", default=DEFAULT_NOTES_DIR)
    p.add_argument("--out", default=os.path.join(DEFAULT_DOCS_DIR, "index.html"),
                   help="Path of index.html (other pages go in the same directory)")
    p.add_argument("--no-open", action="store_true", help="Don't open browser")
    args = p.parse_args()

    notes_dir = os.path.expanduser(args.notes_dir)
    notes = load_notes(notes_dir)

    if not notes:
        print(f"No notes found in: {notes_dir}")
        sys.exit(0)

    docs_dir = os.path.dirname(os.path.abspath(args.out)) or DEFAULT_DOCS_DIR
    os.makedirs(docs_dir, exist_ok=True)

    entities = build_entities(notes)

    pages = {
        os.path.join(docs_dir, "index.html"): generate_briefing(notes),
        os.path.join(docs_dir, "insights.html"): generate_insights(entities, len(notes)),
    }
    for path, html in pages.items():
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"Generated: {path}")

    # retired pages from the old multi-tab layout
    for old in ("library.html", "digest.html"):
        old_path = os.path.join(docs_dir, old)
        if os.path.isfile(old_path):
            os.remove(old_path)
            print(f"Removed: {old_path}")

    sitemap_path = os.path.join(docs_dir, "sitemap.xml")
    generate_sitemap(notes, sitemap_path)
    print(f"Generated: {sitemap_path}")

    robots_path = write_robots(docs_dir)
    print(f"Generated: {robots_path}")

    print(f"\n{len(notes)} note(s), {len(entities)} entities aggregated.")

    if not args.no_open:
        webbrowser.open(f"file:///{os.path.join(docs_dir, 'index.html').replace(os.sep, '/')}")


if __name__ == "__main__":
    main()
