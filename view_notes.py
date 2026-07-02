#!/usr/bin/env python3
"""
view_notes.py — Generate the Daily Reads knowledge-base site from distilled notes.

Pages generated into docs/:
  index.html    — dashboard home (stats, signals needing attention, entities in focus)
  library.html  — document library table (search / filter / expand)
  insights.html — knowledge views: entity-wise, sector-wise, macro-wise timelines
  digest.html   — weekly digest of top credit signals
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
SITE_TITLE = "Daily Reads — Knowledge Notes"
SITE_DESC = ("Personal knowledge library — distilled notes from daily reading "
             "in finance, credit research, macro, and regulatory analysis.")
SYNC_URL = "https://github.com/mjitendrafeb-cmd/jeetz/actions/workflows/daily-reads.yml"

SIGNAL_PRIORITY = {"negative": 0, "watch": 1, "positive": 2, "neutral": 3}
SIGNAL_BORDER = {"negative": "#ef4444", "watch": "#f59e0b", "positive": "#22c55e", "neutral": "#e2e8f0"}
CS_COLOR = {"positive": "#15803d", "negative": "#dc2626", "neutral": "#6b7280", "watch": "#d97706"}
SOURCE_TYPE_META = {
    "broker_research": {"label": "Broker Research", "bg": "#eff6ff", "fg": "#2563eb", "bd": "#bfdbfe"},
    "regulatory":      {"label": "Regulatory",      "bg": "#f0fdf4", "fg": "#15803d", "bd": "#bbf7d0"},
    "academic":        {"label": "Academic",         "bg": "#faf5ff", "fg": "#7c3aed", "bd": "#ddd6fe"},
    "news":            {"label": "News",             "bg": "#fff7ed", "fg": "#c2410c", "bd": "#fed7aa"},
    "other":           {"label": "Other",            "bg": "#f8fafc", "fg": "#64748b", "bd": "#e2e8f0"},
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
                 "government", "regulator", "central bank", "federal reserve", "ecb")
MACRO_PAT = ("economy", "inflation", "gdp", "interest rate", "currency", "rupee",
             "fiscal", "monetary", "liquidity", "crude", "macro", "bond market")
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
        return date_str


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "x"


def load_watchlist():
    path = os.path.join(REPO_ROOT, "watchlist.txt")
    if not os.path.isfile(path):
        return set()
    entries = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                entries.add(line.lower())
    return entries


def check_watchlist(note, watchlist):
    if not watchlist:
        return False
    title = (note.get("title") or "").lower()
    entities = " ".join(ei.get("entity", "").lower() for ei in note.get("entities_impacted", []))
    tags = " ".join(t.lower() for t in note.get("tags", []))
    blob = " ".join([title, entities, tags])
    return any(w in blob for w in watchlist)


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
    notes.sort(key=lambda n: n.get("ingested_at", ""), reverse=True)
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
        for r in out.get("risk_analysis", []):
            kt.append({"takeaway": r, "analyst_lens": "(risk)"})
        for i in out.get("key_implications", []):
            kt.append({"takeaway": i, "analyst_lens": "(implication)"})
        out["key_takeaways"] = kt

    if "entities_impacted" not in out:
        out["entities_impacted"] = [
            {"entity": e, "impact": ""} for e in out.get("entities", [])
        ]

    for field in ("monitoring_points", "learning", "related_topics"):
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
    """Aggregate all notes into entity timelines.

    Returns dict canon_key -> {name, type, docs:set, items:[...]} where items are
    {date, kind: impact|takeaway, text, lens, signal, doc_title, row_id}.
    """
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

        # attach takeaways that mention one of this note's entities
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


# ── Shared page chrome ──────────────────────────────────────────────────────

BASE_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  background:#f3f2f1;color:#323130;font-size:14px;line-height:1.5;min-height:100vh}
.suite-bar{background:#0078d4;min-height:48px;padding:0 20px}
.suite-inner{max-width:1400px;margin:0 auto;min-height:48px;
  display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.suite-brand{color:#fff;font-size:15px;font-weight:700;
  display:flex;align-items:center;gap:8px;white-space:nowrap}
.suite-nav{display:flex;align-items:stretch;gap:2px;margin-left:10px}
.nav-lnk{color:rgba(255,255,255,.85);text-decoration:none;font-size:13px;font-weight:600;
  padding:14px 12px;border-bottom:2px solid transparent;white-space:nowrap}
.nav-lnk:hover{color:#fff;background:rgba(255,255,255,.08)}
.nav-lnk.active{color:#fff;border-bottom-color:#fff}
.suite-actions{margin-left:auto;display:flex;align-items:center;gap:8px}
.suite-btn{color:rgba(255,255,255,.9);background:rgba(255,255,255,.1);
  border:1px solid rgba(255,255,255,.22);padding:6px 14px;border-radius:2px;
  font-size:12px;font-weight:600;cursor:pointer;text-decoration:none;
  display:inline-flex;align-items:center;gap:5px;white-space:nowrap;
  transition:background .15s}
.suite-btn:hover{background:rgba(255,255,255,.2)}
.sync-btn{background:#107c10;color:#fff;border-color:#0e6b0e;font-weight:700}
.sync-btn:hover{background:#0e6b0e}
mark{background:#fff100;color:#323130;border-radius:1px;padding:0 1px}
.toast{position:fixed;bottom:24px;right:24px;background:#323130;color:#fff;
  padding:12px 20px;border-radius:2px;font-size:13px;font-weight:600;
  box-shadow:0 4px 16px rgba(0,0,0,.25);z-index:999;opacity:0;
  transform:translateY(8px);transition:all .25s;pointer-events:none}
.toast.show{opacity:1;transform:translateY(0)}
.toast.ok{border-left:3px solid #107c10}
"""

SHARE_JS = """
function showToast(msg,type){
  var t=document.getElementById('toast');
  if(!t)return;
  t.textContent=msg;t.className='toast '+(type||'ok');t.classList.add('show');
  setTimeout(function(){t.classList.remove('show');},3000);
}
function doShare(){
  var url=window.location.href;
  if(navigator.clipboard){
    navigator.clipboard.writeText(url).then(function(){showToast('Link copied to clipboard','ok');})
      .catch(function(){prompt('Copy this link:',url);});
  }else{prompt('Copy this link:',url);}
}
"""


def suite_bar(active):
    def lnk(href, label, key):
        cls = "nav-lnk active" if key == active else "nav-lnk"
        return f'<a class="{cls}" href="{href}">{label}</a>'
    return (
        '<div class="suite-bar"><div class="suite-inner">'
        '<div class="suite-brand">&#128218; Daily Reads</div>'
        '<nav class="suite-nav">'
        + lnk("index.html", "Dashboard", "dashboard")
        + lnk("library.html", "Library", "library")
        + lnk("insights.html", "Insights", "insights")
        + lnk("digest.html", "Weekly Digest", "digest")
        + '</nav>'
        '<div class="suite-actions">'
        f'<a href="{SYNC_URL}" target="_blank" class="suite-btn sync-btn" '
        'title="Opens GitHub Actions — click Run workflow to pull new files from Drive">'
        '&#8635; Sync from Drive</a>'
        '<button class="suite-btn" onclick="doShare()">&#128279; Share</button>'
        '</div></div></div>'
    )


def sig_dot(sig, count=None):
    color = CS_COLOR.get(sig, "#6b7280")
    txt = f"&nbsp;{count}" if count is not None else ""
    return (f'<span style="display:inline-flex;align-items:center;gap:3px;font-size:11px;'
            f'font-weight:700;color:{color}">'
            f'<span style="width:8px;height:8px;border-radius:50%;background:{color};'
            f'display:inline-block"></span>{txt}</span>')


# ── Library page (document table) ───────────────────────────────────────────

def render_row(raw_note, idx, watchlist=None):
    note = normalize_note(raw_note)
    title = note.get("title", "Untitled")
    date = note.get("date", "")
    doc_date = note.get("document_date") or ""
    category = note.get("category", "Other")
    source = note.get("source_file", "")
    sentiment = note.get("sentiment", "neutral").lower()
    key_takeaways = note.get("key_takeaways", [])
    entities_impacted = note.get("entities_impacted", [])
    learning = note.get("learning", [])
    tags = note.get("tags", [])
    duplicate_stories = note.get("duplicate_stories", [])

    exec_summary = note.get("executive_summary") or []
    preview = (exec_summary[0] if exec_summary
               else (key_takeaways[0].get("takeaway", "") if key_takeaways else ""))

    search_blob = " ".join([
        title, source, category, sentiment,
        " ".join(tags),
        " ".join(exec_summary),
        " ".join(kt.get("takeaway", "") + " " + kt.get("analyst_lens", "")
                 for kt in key_takeaways),
        " ".join(ei.get("entity", "") + " " + ei.get("impact", "")
                 for ei in entities_impacted),
        " ".join(learning),
    ]).lower().replace('"', "'")

    tags_csv = ",".join(tags)
    cid = f"r{idx}"

    dominant_sig = note_signal(note)
    lborder = SIGNAL_BORDER.get(dominant_sig, "#e2e8f0")
    wl_hit = check_watchlist(note, watchlist or set())

    kt_rows = ""
    for kt in key_takeaways:
        cs = kt.get("credit_signal", "").lower()
        cs_col = CS_COLOR.get(cs, "#6b7280")
        cs_badge = (f'<span style="font-size:10px;font-weight:700;color:{cs_col};'
                    f'text-transform:uppercase">&#x25CF; {esc(cs)}</span><br>') if cs else ""
        kt_rows += (f'<tr><td class="kc tw"><div style="margin-bottom:3px">{cs_badge}</div>'
                    f'{esc(kt.get("takeaway",""))}</td>'
                    f'<td class="kc al">{esc(kt.get("analyst_lens",""))}</td></tr>')

    ei_rows = "".join(
        f'<tr><td class="kc tw">{esc(ei.get("canonical") or ei.get("entity",""))}</td>'
        f'<td class="kc">{esc(ei.get("impact",""))}</td></tr>'
        for ei in entities_impacted
    )
    learn_items = "".join(f"<li>{esc(l)}</li>" for l in learning)
    tag_chips = "".join(f'<span class="tc-sm">{esc(t)}</span>' for t in tags[:8])

    exp_parts = []
    if exec_summary:
        crux_items = "".join(f"<li>{esc(s)}</li>" for s in exec_summary)
        exp_parts.append(
            f'<div class="exp-sect"><div class="exp-sh">&#128204; Crux of the Report</div>'
            f'<ul class="blist crux">{crux_items}</ul></div>'
        )
    if kt_rows:
        exp_parts.append(
            f'<div class="exp-sect"><div class="exp-sh">Key Takeaways &amp; Analyst Lens</div>'
            f'<div class="tbl-wrap"><table class="dt"><thead><tr>'
            f'<th style="width:44%">Takeaway</th><th>Analyst Lens</th>'
            f'</tr></thead><tbody>{kt_rows}</tbody></table></div></div>'
        )
    if ei_rows:
        exp_parts.append(
            f'<div class="exp-sect"><div class="exp-sh">Companies &amp; Sectors Impacted</div>'
            f'<div class="tbl-wrap"><table class="dt"><thead><tr>'
            f'<th style="width:30%">Entity</th><th>Impact</th>'
            f'</tr></thead><tbody>{ei_rows}</tbody></table></div></div>'
        )
    if learn_items:
        exp_parts.append(
            f'<div class="exp-sect"><div class="exp-sh">What Can I Learn?</div>'
            f'<ul class="blist learn">{learn_items}</ul></div>'
        )
    if duplicate_stories:
        dup_items = "".join(f"<li>{esc(s)}</li>" for s in duplicate_stories)
        exp_parts.append(
            f'<div class="exp-sect"><div class="exp-sh" style="color:#6d28d9">'
            f'&#10006; Already Covered in Previous Notes</div>'
            f'<ul class="blist" style="color:#5b21b6">{dup_items}</ul></div>'
        )
    expanded_html = "".join(exp_parts)

    wl_badge = ' <span class="wl-badge">&#9733; Watchlist</span>' if wl_hit else ""
    dup_badge = ' <span class="dup-badge">&#8635; Repeat</span>' if duplicate_stories else ""

    return (
        f'<tr class="doc-row" id="{cid}" onclick="toggleRow(\'{cid}\')" '
        f'data-category="{esc(category)}" data-sentiment="{esc(sentiment)}" '
        f'data-date="{esc(date)}" data-docdate="{esc(doc_date)}" '
        f'data-tags="{esc(tags_csv)}" data-search="{esc(search_blob)}">'
        f'<td class="col-name" style="border-left:3px solid {lborder}">'
        f'<div class="name-inner">'
        f'<span class="row-ico" id="{cid}-ico">&#8250;</span>'
        f'<span class="doc-title" data-raw="{esc(title)}">{esc(title)}</span>'
        f'{wl_badge}{dup_badge}'
        f'</div>'
        f'<div class="row-tags">{tag_chips}</div>'
        f'</td>'
        f'<td class="col-abstract">'
        f'<span data-raw="{esc(preview)}">'
        f'{esc(preview[:200])}{"&#8230;" if len(preview) > 200 else ""}'
        f'</span></td>'
        f'<td class="col-date">{esc(fmt_date(doc_date or date))}</td>'
        f'</tr>'
        f'<tr class="exp-row" id="{cid}-exp">'
        f'<td colspan="3"><div class="exp-content">{expanded_html}</div></td>'
        f'</tr>'
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


def generate_library(notes):
    now_str = datetime.datetime.now().strftime("%d %b %Y, %H:%M")
    total = len(notes)

    cat_counts = Counter(n.get("category", "Other") for n in notes)
    cats = sorted(cat_counts.items(), key=lambda x: -x[1])

    cat_items = (f'<li class="cat-item active" data-cat="all" onclick="setCat(this,\'all\')">'
                 f'All <span class="cnt">{total}</span></li>\n')
    for cat, cnt in cats:
        safe_cat = cat.replace("'", "\\'")
        cat_items += (f'<li class="cat-item" data-cat="{esc(cat)}" '
                      f"onclick=\"setCat(this,'{safe_cat}')\">"
                      f'{esc(cat)} <span class="cnt">{cnt}</span></li>\n')

    cat_options = f'<option value="all">All Notes ({total})</option>\n'
    for cat, cnt in cats:
        cat_options += f'<option value="{esc(cat)}">{esc(cat)} ({cnt})</option>\n'

    watchlist = load_watchlist()
    rows_html = "\n".join(render_row(n, i, watchlist) for i, n in enumerate(notes))
    jsonld = build_jsonld(notes)

    sig_counts = Counter()
    for n in notes:
        for kt in normalize_note(n).get("key_takeaways", []):
            sig_counts[kt.get("credit_signal", "neutral").lower()] += 1
    sig_bar_parts = []
    for sig, label in [("negative", "Negative"), ("watch", "Watch"),
                       ("positive", "Positive"), ("neutral", "Neutral")]:
        cnt = sig_counts.get(sig, 0)
        if cnt:
            color = CS_COLOR[sig]
            sig_bar_parts.append(
                f'<span class="sig-pill" style="color:{color}">'
                f'<span class="sig-dot" style="background:{color}"></span>'
                f'{cnt} {label}</span>'
            )
    signal_bar_html = "".join(sig_bar_parts)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Library — Daily Reads</title>
<meta name="description" content="{esc(SITE_DESC)}">
<link rel="canonical" href="{SITE_URL}/library.html">
<script type="application/ld+json">{jsonld}</script>
<style>
{BASE_CSS}
/* ── Command bar ── */
.cmd-bar{{background:#fff;border-bottom:1px solid #edebe9;padding:6px 20px;
  box-shadow:0 1px 3px rgba(0,0,0,.06)}}
.cmd-inner{{max-width:1400px;margin:0 auto;display:flex;align-items:center;
  gap:8px;flex-wrap:wrap}}
.cmd-sel{{border:1px solid #8a8886;background:#fff;color:#323130;
  padding:6px 10px;border-radius:2px;font-size:13px;outline:none;cursor:pointer;
  min-width:140px}}
.cmd-sel:focus{{border-color:#0078d4;box-shadow:0 0 0 1px #0078d4}}
.search-wrap{{position:relative}}
.search-ico{{position:absolute;left:8px;top:50%;transform:translateY(-50%);
  color:#8a8886;font-size:14px;pointer-events:none;line-height:1}}
#search{{border:1px solid #8a8886;background:#fff;color:#323130;
  padding:6px 10px 6px 28px;border-radius:2px;font-size:13px;outline:none;width:220px}}
#search:focus{{border-color:#0078d4;box-shadow:0 0 0 1px #0078d4}}
#search::placeholder{{color:#a19f9d}}
.date-lbl{{font-size:12px;color:#605e5c;white-space:nowrap}}
.date-in{{border:1px solid #8a8886;background:#fff;color:#323130;
  padding:6px 8px;border-radius:2px;font-size:12px;outline:none;width:130px}}
.date-in:focus{{border-color:#0078d4}}
.cmd-sep{{color:#e1dfdd;user-select:none}}
.sort-sel{{border:1px solid #8a8886;background:#fff;color:#323130;
  padding:6px 8px;border-radius:2px;font-size:12px;outline:none}}
#stats-lbl{{font-size:12px;color:#605e5c;margin-left:auto;white-space:nowrap}}
/* ── Layout ── */
.layout{{display:flex;max-width:1400px;margin:0 auto;padding:16px 20px;gap:18px}}
aside{{width:188px;flex-shrink:0;position:sticky;top:0;align-self:flex-start}}
.aside-sec{{background:#fff;border:1px solid #edebe9;border-radius:2px;overflow:hidden}}
.aside-title{{font-size:11px;font-weight:700;text-transform:uppercase;
  letter-spacing:.6px;color:#605e5c;padding:10px 12px 6px}}
.cat-item{{list-style:none;padding:7px 12px;cursor:pointer;font-size:13px;
  display:flex;justify-content:space-between;align-items:center;color:#323130;
  transition:background .1s;border-left:2px solid transparent}}
.cat-item:hover{{background:#f3f2f1}}
.cat-item.active{{background:#deecf9;color:#0078d4;font-weight:600;
  border-left-color:#0078d4}}
.cnt{{font-size:11px;color:#605e5c;background:#f3f2f1;
  padding:1px 7px;border-radius:10px}}
.cat-item.active .cnt{{background:#c7e0f4;color:#0078d4}}
/* ── Signal bar ── */
.signal-bar{{display:flex;align-items:center;gap:16px;padding:0 0 10px;flex-wrap:wrap}}
.sig-pill{{display:inline-flex;align-items:center;gap:5px;font-size:12px;font-weight:600}}
.sig-dot{{width:8px;height:8px;border-radius:50%;flex-shrink:0}}
/* ── Table ── */
main{{flex:1;min-width:0}}
.doc-table-wrap{{background:#fff;border:1px solid #edebe9;border-radius:2px;overflow:hidden}}
.doc-table{{width:100%;border-collapse:collapse}}
.doc-table thead th{{padding:10px 14px;text-align:left;font-size:11px;font-weight:700;
  color:#605e5c;background:#faf9f8;border-bottom:2px solid #edebe9;
  text-transform:uppercase;letter-spacing:.4px;white-space:nowrap}}
.doc-row{{border-bottom:1px solid #f3f2f1;transition:background .1s;cursor:pointer}}
.doc-row:hover td{{background:#f3f2f1}}
.doc-row.exp-open td{{background:#faf9f8}}
.col-name{{padding:11px 14px;width:32%;vertical-align:top}}
.col-abstract{{padding:11px 14px;width:58%;color:#605e5c;font-size:13px;
  line-height:1.5;vertical-align:top;cursor:pointer}}
.col-date{{padding:11px 14px;width:10%;font-size:12px;color:#605e5c;
  white-space:nowrap;vertical-align:top;cursor:pointer}}
.name-inner{{display:flex;align-items:flex-start;gap:6px;margin-bottom:4px;cursor:pointer}}
.row-ico{{font-size:18px;color:#0078d4;flex-shrink:0;line-height:1;
  transition:transform .18s;display:inline-block;cursor:pointer}}
.row-ico.open{{transform:rotate(90deg)}}
.name-inner:hover .row-ico{{color:#004ea8}}
.doc-title{{font-size:13px;font-weight:600;color:#323130;line-height:1.4}}
.row-tags{{display:flex;flex-wrap:wrap;gap:3px;padding-left:24px;margin-top:3px}}
.tc-sm{{font-size:10px;padding:1px 6px;border-radius:10px;
  background:#f3f2f1;color:#605e5c;border:1px solid #edebe9}}
.wl-badge{{background:#fff4ce;color:#7a4e00;border:1px solid #f8e7ab;
  font-size:10px;font-weight:700;padding:2px 7px;border-radius:10px;white-space:nowrap}}
.dup-badge{{background:#f0f0f0;color:#605e5c;border:1px solid #d2d0ce;
  font-size:10px;font-weight:600;padding:2px 7px;border-radius:10px;white-space:nowrap}}
/* ── Expanded row ── */
.exp-row{{display:none;background:#faf9f8}}
.exp-content{{padding:14px 20px 18px 40px;border-top:1px solid #edebe9}}
.exp-sect{{margin-bottom:14px}}
.exp-sh{{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;
  color:#8a8886;margin-bottom:8px;padding-bottom:4px;border-bottom:1px solid #edebe9}}
.tbl-wrap{{overflow-x:auto}}
.dt{{width:100%;border-collapse:collapse;font-size:13px}}
.dt thead th{{padding:7px 12px;text-align:left;font-size:10px;font-weight:700;
  text-transform:uppercase;letter-spacing:.4px;color:#605e5c;
  background:#faf9f8;border-bottom:1px solid #edebe9}}
.kc{{padding:9px 12px;vertical-align:top;border-bottom:1px solid #f3f2f1;
  line-height:1.55;font-size:13px;color:#323130}}
.tw{{font-weight:600;width:40%}}
.al{{color:#605e5c}}
.blist{{padding-left:20px}}
.blist li{{margin-bottom:5px;line-height:1.6;font-size:13px;color:#323130}}
.learn li{{color:#075985}}
.crux li{{color:#1e293b;font-weight:500}}
#empty{{text-align:center;padding:60px 20px;display:none;
  color:#605e5c;background:#fff;border-top:1px solid #edebe9}}
@media(max-width:900px){{
  aside{{display:none}}.layout{{padding:12px}}.col-abstract{{display:none}}
}}
@media(max-width:600px){{
  .col-date{{display:none}}#search{{width:140px}}
}}
@media print{{
  .suite-bar,.cmd-bar,.signal-bar,aside{{display:none!important}}
  .exp-row{{display:table-row!important}}body{{background:#fff}}
  .doc-table-wrap{{border:none}}
}}
</style>
</head>
<body>

{suite_bar("library")}

<div class="cmd-bar">
  <div class="cmd-inner">
    <select id="cat-sel" class="cmd-sel" onchange="setCatSel(this.value)">
      {cat_options}
    </select>
    <div class="search-wrap">
      <span class="search-ico">&#9906;</span>
      <input id="search" type="search" placeholder="Search notes&#8230;"
             oninput="setQ(this.value)" autocomplete="off">
    </div>
    <span class="date-lbl">Doc date</span>
    <input type="date" id="date-from" class="date-in" onchange="setDateFrom(this.value)">
    <span class="cmd-sep">&ndash;</span>
    <input type="date" id="date-to" class="date-in" onchange="setDateTo(this.value)">
    <select id="sort-sel" class="sort-sel" onchange="setSort(this.value)">
      <option value="newest">Newest first</option>
      <option value="oldest">Oldest first</option>
    </select>
    <span id="stats-lbl">Updated {now_str}</span>
  </div>
</div>

<div class="layout">
  <aside>
    <div class="aside-sec">
      <div class="aside-title">Categories</div>
      <ul id="cat-list">{cat_items}</ul>
    </div>
  </aside>
  <main>
    <div class="signal-bar">{signal_bar_html}</div>
    <div class="doc-table-wrap">
      <table class="doc-table">
        <thead><tr>
          <th>Name</th><th>Abstract</th><th>Date</th>
        </tr></thead>
        <tbody id="table-body">{rows_html}</tbody>
      </table>
      <div id="empty">No notes match your filter.</div>
    </div>
  </main>
</div>
<div class="toast" id="toast"></div>

<script>
{SHARE_JS}
(function(){{
  var TOTAL={total};
  var state={{q:'',cat:'all',sort:'newest',dateFrom:'',dateTo:''}};

  var params=new URLSearchParams(window.location.search);
  if(params.get('q'))state.q=params.get('q');
  if(params.get('category'))state.cat=params.get('category');
  if(params.get('sort'))state.sort=params.get('sort');
  if(params.get('from'))state.dateFrom=params.get('from');
  if(params.get('to'))state.dateTo=params.get('to');

  function applyInit(){{
    if(state.q){{var el=document.getElementById('search');if(el)el.value=state.q;}}
    if(state.sort!=='newest'){{var s=document.getElementById('sort-sel');if(s)s.value=state.sort;}}
    if(state.cat!=='all'){{
      var cs=document.getElementById('cat-sel');if(cs)cs.value=state.cat;
      document.querySelectorAll('.cat-item').forEach(function(li){{
        li.classList.toggle('active',li.dataset.cat===state.cat);
      }});
    }}
    if(state.dateFrom){{var f=document.getElementById('date-from');if(f)f.value=state.dateFrom;}}
    if(state.dateTo){{var t=document.getElementById('date-to');if(t)t.value=state.dateTo;}}
    apply();
    if(window.location.hash){{
      var id=window.location.hash.slice(1);
      var row=document.getElementById(id);
      if(row&&document.getElementById(id+'-exp')){{
        toggleRow(id);
        setTimeout(function(){{row.scrollIntoView({{block:'center'}});}},50);
      }}
    }}
  }}

  function escH(t){{return String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}
  function hlText(txt,q){{
    if(!q)return escH(txt);
    var re=new RegExp('('+q.replace(/[.*+?^${{}}()|[\\]\\\\]/g,'\\\\$&')+')','gi');
    return escH(txt).replace(re,'<mark>$1</mark>');
  }}

  function apply(){{
    var rows=Array.from(document.querySelectorAll('.doc-row'));
    var q=state.q.toLowerCase().trim();
    var cat=state.cat,dateFrom=state.dateFrom,dateTo=state.dateTo;
    var tbody=document.getElementById('table-body');

    if(state.sort==='oldest'){{
      rows.sort(function(a,b){{return (a.dataset.docdate||a.dataset.date).localeCompare(b.dataset.docdate||b.dataset.date);}});
    }}else{{
      rows.sort(function(a,b){{return (b.dataset.docdate||b.dataset.date).localeCompare(a.dataset.docdate||a.dataset.date);}});
    }}
    rows.forEach(function(r){{
      tbody.appendChild(r);
      var exp=document.getElementById(r.id+'-exp');
      if(exp)tbody.appendChild(exp);
    }});

    var vis=0;
    rows.forEach(function(r){{
      var catOk=cat==='all'||r.dataset.category===cat;
      var searchOk=!q||r.dataset.search.includes(q);
      var dd=r.dataset.docdate||r.dataset.date||'';
      var show=catOk&&searchOk&&(!dateFrom||dd>=dateFrom)&&(!dateTo||dd<=dateTo);
      r.style.display=show?'':'none';
      var exp=document.getElementById(r.id+'-exp');
      if(exp)exp.style.display=(!show)?'none':(exp.dataset.open==='1'?'table-row':'none');
      if(show){{
        vis++;
        var titleEl=r.querySelector('.doc-title');
        var absEl=r.querySelector('.col-abstract span');
        if(titleEl)titleEl.innerHTML=hlText(titleEl.dataset.raw||'',q);
        if(absEl)absEl.innerHTML=hlText(absEl.dataset.raw||'',q);
      }}
    }});

    var lbl=document.getElementById('stats-lbl');
    var filtered=q||cat!=='all'||dateFrom||dateTo;
    lbl.textContent=filtered?('Showing '+vis+' of '+TOTAL+' notes'):(TOTAL+' note'+(TOTAL===1?'':'s'));
    document.getElementById('empty').style.display=vis?'none':'block';

    var p=new URLSearchParams();
    if(q)p.set('q',state.q);
    if(cat!=='all')p.set('category',cat);
    if(state.sort!=='newest')p.set('sort',state.sort);
    if(dateFrom)p.set('from',dateFrom);
    if(dateTo)p.set('to',dateTo);
    history.replaceState(null,'',p.toString()?'?'+p.toString():window.location.pathname);

    document.querySelectorAll('.cat-item').forEach(function(li){{
      li.classList.toggle('active',li.dataset.cat===state.cat);
    }});
  }}

  window.setCat=function(el,cat){{
    state.cat=cat;
    var cs=document.getElementById('cat-sel');if(cs)cs.value=cat;
    apply();
  }};
  window.setCatSel=function(val){{state.cat=val;apply();}};
  window.setSort=function(val){{state.sort=val;apply();}};
  window.setQ=function(val){{state.q=val;apply();}};
  window.setDateFrom=function(v){{state.dateFrom=v;apply();}};
  window.setDateTo=function(v){{state.dateTo=v;apply();}};

  window.toggleRow=function(id){{
    var exp=document.getElementById(id+'-exp');
    var ico=document.getElementById(id+'-ico');
    var row=document.getElementById(id);
    if(!exp)return;
    var isOpen=exp.dataset.open==='1';
    exp.dataset.open=isOpen?'0':'1';
    exp.style.display=isOpen?'none':'table-row';
    if(ico)ico.classList.toggle('open',!isOpen);
    if(row)row.classList.toggle('exp-open',!isOpen);
  }};

  applyInit();
}})();
</script>
</body>
</html>"""


# ── Dashboard page ──────────────────────────────────────────────────────────

def generate_dashboard(notes, entities):
    now_str = datetime.datetime.now().strftime("%d %b %Y, %H:%M")
    today = datetime.date.today()
    week_ago = (today - datetime.timedelta(days=7)).isoformat()

    total_docs = len(notes)
    docs_week = sum(1 for n in notes if note_date(n) >= week_ago)

    all_tws = []
    for idx, raw in enumerate(notes):
        n = normalize_note(raw)
        d = note_date(n)
        for kt in n.get("key_takeaways", []):
            all_tws.append({
                "date": d, "signal": kt.get("credit_signal", "neutral").lower(),
                "takeaway": kt.get("takeaway", ""), "lens": kt.get("analyst_lens", ""),
                "doc_title": n.get("title", ""), "row_id": f"r{idx}",
            })
    total_tws = len(all_tws)
    sig_all = Counter(t["signal"] for t in all_tws)
    sig_week = Counter(t["signal"] for t in all_tws if t["date"] >= week_ago)

    def tile(num, label, sub="", color="#0f172a"):
        sub_html = f'<div class="tile-sub">{sub}</div>' if sub else ""
        return (f'<div class="tile"><div class="tile-n" style="color:{color}">{num}</div>'
                f'<div class="tile-l">{label}</div>{sub_html}</div>')

    tiles = (
        tile(total_docs, "Documents", f"+{docs_week} this week" if docs_week else "")
        + tile(total_tws, "Takeaways")
        + tile(len(entities), "Entities tracked")
        + tile(sig_all.get("negative", 0), "Negative signals",
               f"+{sig_week.get('negative', 0)} this week" if sig_week.get("negative") else "",
               CS_COLOR["negative"])
        + tile(sig_all.get("watch", 0), "Watch signals",
               f"+{sig_week.get('watch', 0)} this week" if sig_week.get("watch") else "",
               CS_COLOR["watch"])
    )

    # Needs attention: recent negative/watch takeaways
    attn = [t for t in all_tws if t["signal"] in ("negative", "watch")]
    attn.sort(key=lambda t: (t["date"], -SIGNAL_PRIORITY.get(t["signal"], 3)), reverse=True)
    attn_html = ""
    for t in attn[:8]:
        color = CS_COLOR.get(t["signal"], "#6b7280")
        attn_html += (
            f'<a class="attn-item" href="library.html#{t["row_id"]}">'
            f'<span class="attn-dot" style="background:{color}"></span>'
            f'<span class="attn-body"><span class="attn-tw">{esc(t["takeaway"])}</span>'
            f'<span class="attn-src">{esc(t["doc_title"])} &middot; {esc(fmt_date(t["date"]))}</span>'
            f'</span></a>'
        )
    if not attn_html:
        attn_html = '<div class="empty-sec">No negative or watch signals yet.</div>'

    # Entities in focus: most-mentioned
    ents_sorted = sorted(entities.values(), key=lambda e: (-len(e["docs"]), e["name"]))
    ent_html = ""
    for e in ents_sorted[:14]:
        tcol = TYPE_COLOR.get(e["type"], "#64748b")
        neg = e["sig_counts"].get("negative", 0)
        wat = e["sig_counts"].get("watch", 0)
        warn = ""
        if neg:
            warn = f'<span class="ent-warn" style="color:{CS_COLOR["negative"]}">&#x25CF;{neg}</span>'
        elif wat:
            warn = f'<span class="ent-warn" style="color:{CS_COLOR["watch"]}">&#x25CF;{wat}</span>'
        ent_html += (
            f'<a class="ent-chip" href="insights.html#e-{slugify(e["name"])}" '
            f'style="border-color:{tcol}33">'
            f'<span class="ent-chip-name">{esc(e["name"])}</span>'
            f'<span class="ent-chip-n" style="background:{tcol}18;color:{tcol}">{len(e["docs"])}</span>'
            f'{warn}</a>'
        )

    # Recent documents
    recent_html = ""
    dated = sorted(enumerate(notes), key=lambda p: note_date(p[1]), reverse=True)
    for idx, raw in dated[:6]:
        n = normalize_note(raw)
        sig = note_signal(n)
        color = SIGNAL_BORDER.get(sig, "#e2e8f0")
        exec_s = n.get("executive_summary") or []
        kts = n.get("key_takeaways", [])
        preview = exec_s[0] if exec_s else (kts[0].get("takeaway", "") if kts else "")
        recent_html += (
            f'<a class="doc-item" href="library.html#r{idx}" style="border-left-color:{color}">'
            f'<span class="doc-item-t">{esc(n.get("title", "Untitled"))}</span>'
            f'<span class="doc-item-p">{esc(preview[:140])}{"&#8230;" if len(preview) > 140 else ""}</span>'
            f'<span class="doc-item-d">{esc(fmt_date(note_date(n)))}</span>'
            f'</a>'
        )

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
<style>
{BASE_CSS}
.wrap{{max-width:1100px;margin:0 auto;padding:22px 20px}}
.pg-sub{{font-size:12px;color:#605e5c;margin-bottom:16px}}
.tiles{{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:22px}}
.tile{{background:#fff;border:1px solid #edebe9;border-radius:2px;
  padding:14px 20px;min-width:150px;flex:1}}
.tile-n{{font-size:26px;font-weight:700;line-height:1.2}}
.tile-l{{font-size:11px;color:#605e5c;text-transform:uppercase;letter-spacing:.5px;margin-top:2px}}
.tile-sub{{font-size:11px;color:#107c10;font-weight:600;margin-top:3px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
.panel{{background:#fff;border:1px solid #edebe9;border-radius:2px;overflow:hidden}}
.panel-hd{{padding:12px 16px;border-bottom:1px solid #edebe9;
  display:flex;align-items:center;justify-content:space-between}}
.panel-t{{font-size:13px;font-weight:700;color:#323130}}
.panel-lnk{{font-size:12px;color:#0078d4;text-decoration:none}}
.panel-lnk:hover{{text-decoration:underline}}
.panel-bd{{padding:8px 0}}
.attn-item{{display:flex;gap:10px;padding:10px 16px;text-decoration:none;
  border-bottom:1px solid #f3f2f1;transition:background .1s;align-items:flex-start}}
.attn-item:hover{{background:#f3f2f1}}
.attn-item:last-child{{border-bottom:none}}
.attn-dot{{width:9px;height:9px;border-radius:50%;flex-shrink:0;margin-top:5px}}
.attn-body{{display:flex;flex-direction:column;gap:2px;min-width:0}}
.attn-tw{{font-size:13px;font-weight:600;color:#323130;line-height:1.45}}
.attn-src{{font-size:11px;color:#8a8886}}
.ent-wrap{{display:flex;flex-wrap:wrap;gap:8px;padding:14px 16px}}
.ent-chip{{display:inline-flex;align-items:center;gap:6px;background:#fff;
  border:1px solid #e2e8f0;border-radius:16px;padding:5px 11px;text-decoration:none;
  font-size:12px;font-weight:600;color:#323130;transition:box-shadow .12s}}
.ent-chip:hover{{box-shadow:0 1px 5px rgba(0,0,0,.12)}}
.ent-chip-n{{font-size:10px;font-weight:700;padding:1px 7px;border-radius:9px}}
.ent-warn{{font-size:10px;font-weight:700}}
.doc-item{{display:flex;flex-direction:column;gap:3px;padding:11px 16px;
  border-left:3px solid #e2e8f0;border-bottom:1px solid #f3f2f1;
  text-decoration:none;transition:background .1s}}
.doc-item:hover{{background:#f3f2f1}}
.doc-item:last-child{{border-bottom:none}}
.doc-item-t{{font-size:13px;font-weight:600;color:#323130}}
.doc-item-p{{font-size:12px;color:#605e5c;line-height:1.5}}
.doc-item-d{{font-size:11px;color:#8a8886}}
.empty-sec{{padding:24px 16px;color:#8a8886;font-size:13px;text-align:center}}
@media(max-width:800px){{.grid{{grid-template-columns:1fr}}}}
</style>
</head>
<body>

{suite_bar("dashboard")}

<div class="wrap">
  <div class="pg-sub">Updated {now_str} &middot; {total_docs} document{'s' if total_docs != 1 else ''} in the library</div>
  <div class="tiles">{tiles}</div>
  <div class="grid">
    <div class="panel" style="grid-column:1/-1">
      <div class="panel-hd"><span class="panel-t">&#9888; Needs Attention — Negative &amp; Watch Signals</span>
        <a class="panel-lnk" href="digest.html">Weekly digest &rarr;</a></div>
      <div class="panel-bd">{attn_html}</div>
    </div>
    <div class="panel">
      <div class="panel-hd"><span class="panel-t">&#127919; Entities in Focus</span>
        <a class="panel-lnk" href="insights.html">All insights &rarr;</a></div>
      <div class="ent-wrap">{ent_html or '<div class="empty-sec">No entities yet.</div>'}</div>
    </div>
    <div class="panel">
      <div class="panel-hd"><span class="panel-t">&#128196; Latest Documents</span>
        <a class="panel-lnk" href="library.html">Full library &rarr;</a></div>
      <div class="panel-bd">{recent_html or '<div class="empty-sec">No documents yet.</div>'}</div>
    </div>
  </div>
</div>
<div class="toast" id="toast"></div>
<script>{SHARE_JS}</script>
</body>
</html>"""


# ── Insights page (entity / sector / macro views) ───────────────────────────

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
        lens = (f'<div style="font-size:12px;color:#605e5c;margin-top:3px">{esc(it["lens"])}</div>'
                if it.get("lens") else "")
        rows += (
            f'<tr>'
            f'<td class="tl-date">{esc(fmt_date(it["date"]))}</td>'
            f'<td class="tl-sig"><span style="color:{color};font-size:10px;font-weight:700;'
            f'text-transform:uppercase">&#x25CF; {esc(it["signal"])}</span><br>'
            f'<span class="tl-kind">{kind_lbl}</span></td>'
            f'<td class="tl-text">{esc(it["text"])}{lens}</td>'
            f'<td class="tl-src"><a href="library.html#{it["row_id"]}">'
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


def generate_insights(entities):
    now_str = datetime.datetime.now().strftime("%d %b %Y, %H:%M")
    ents = sorted(entities.values(), key=lambda e: (-len(e["docs"]), -len(e["items"]), e["name"]))

    counts = Counter()
    for e in ents:
        if e["type"] == "company":
            counts["companies"] += 1
        elif e["type"] == "sector":
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
<title>Insights — Daily Reads</title>
<meta name="description" content="Entity-wise, sector-wise and macro-wise credit insights.">
<link rel="canonical" href="{SITE_URL}/insights.html">
<style>
{BASE_CSS}
.wrap{{max-width:1100px;margin:0 auto;padding:20px}}
.pg-sub{{font-size:12px;color:#605e5c;margin-bottom:14px}}
.tab-bar{{display:flex;gap:4px;border-bottom:2px solid #edebe9;margin-bottom:6px;
  align-items:center;flex-wrap:wrap}}
.tab{{padding:9px 16px;font-size:13px;font-weight:600;color:#605e5c;cursor:pointer;
  border-bottom:2px solid transparent;margin-bottom:-2px;background:none;border-top:none;
  border-left:none;border-right:none}}
.tab:hover{{color:#0078d4}}
.tab.active{{color:#0078d4;border-bottom-color:#0078d4}}
.tab .tcnt{{font-size:11px;color:#8a8886;margin-left:4px}}
#esearch{{margin-left:auto;border:1px solid #8a8886;background:#fff;color:#323130;
  padding:6px 12px;border-radius:2px;font-size:13px;outline:none;width:230px;margin-bottom:4px}}
#esearch:focus{{border-color:#0078d4;box-shadow:0 0 0 1px #0078d4}}
.ent-card{{background:#fff;border:1px solid #edebe9;border-radius:2px;margin-top:10px;
  overflow:hidden}}
.ent-hd{{display:flex;align-items:center;gap:10px;padding:12px 16px;cursor:pointer;
  transition:background .1s;flex-wrap:wrap}}
.ent-hd:hover{{background:#f3f2f1}}
.ent-ico{{font-size:18px;color:#0078d4;line-height:1;transition:transform .18s;
  display:inline-block;flex-shrink:0}}
.ent-ico.open{{transform:rotate(90deg)}}
.ent-name{{font-size:14px;font-weight:700;color:#323130}}
.ent-type{{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.4px;
  padding:2px 8px;border-radius:10px;border:1px solid}}
.ent-sigs{{display:inline-flex;gap:8px;align-items:center}}
.ent-meta{{margin-left:auto;font-size:11px;color:#8a8886;white-space:nowrap}}
.ent-bd{{border-top:1px solid #edebe9;background:#faf9f8;padding:12px 16px}}
.tbl-wrap{{overflow-x:auto}}
.tl-table{{width:100%;border-collapse:collapse;font-size:13px;background:#fff;
  border:1px solid #edebe9}}
.tl-table thead th{{padding:7px 12px;text-align:left;font-size:10px;font-weight:700;
  text-transform:uppercase;letter-spacing:.4px;color:#605e5c;
  background:#faf9f8;border-bottom:1px solid #edebe9}}
.tl-table td{{padding:9px 12px;vertical-align:top;border-bottom:1px solid #f3f2f1;
  line-height:1.55}}
.tl-date{{font-size:12px;color:#605e5c;white-space:nowrap}}
.tl-kind{{font-size:10px;color:#a19f9d}}
.tl-text{{color:#323130}}
.tl-src a{{color:#0078d4;text-decoration:none;font-size:12px}}
.tl-src a:hover{{text-decoration:underline}}
#empty{{text-align:center;padding:50px 20px;color:#8a8886;display:none}}
@media(max-width:700px){{.ent-meta{{display:none}}.tl-src{{display:none}}
  .tl-table thead th:last-child{{display:none}}#esearch{{width:100%;margin-left:0}}}}
</style>
</head>
<body>

{suite_bar("insights")}

<div class="wrap">
  <div class="pg-sub">Everything the library knows, re-assembled by entity, sector and macro theme &middot; Updated {now_str}</div>
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
  <div id="cards">{cards or '<div style="padding:40px;text-align:center;color:#8a8886">No entities yet.</div>'}</div>
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
      // switch to the tab containing this entity
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


# ── Weekly digest ───────────────────────────────────────────────────────────

def generate_digest(notes):
    today = datetime.date.today()
    week_ago = (today - datetime.timedelta(days=7)).isoformat()
    week_end = today.strftime("%d %b %Y")
    week_start = (today - datetime.timedelta(days=7)).strftime("%d %b")

    recent = [n for n in notes if note_date(n) >= week_ago]

    CS_STYLE = {
        "negative": {"label": "Negative Signal", "bg": "#fef2f2", "fg": "#dc2626", "bd": "#fecaca"},
        "watch":    {"label": "Watch",            "bg": "#fffbeb", "fg": "#d97706", "bd": "#fde68a"},
        "positive": {"label": "Positive Signal",  "bg": "#f0fdf4", "fg": "#15803d", "bd": "#bbf7d0"},
        "neutral":  {"label": "Neutral",          "bg": "#f8fafc", "fg": "#64748b", "bd": "#e2e8f0"},
    }

    all_tws = []
    for n in recent:
        note = normalize_note(n)
        for kt in note.get("key_takeaways", []):
            sig = kt.get("credit_signal", "neutral").lower()
            all_tws.append({
                "takeaway": kt.get("takeaway", ""),
                "analyst_lens": kt.get("analyst_lens", ""),
                "credit_signal": sig,
                "source_title": note.get("title", ""),
                "source_date": note_date(note),
                "priority": SIGNAL_PRIORITY.get(sig, 3),
            })

    all_tws.sort(key=lambda x: (x["priority"], x["source_date"]))
    top_tws = all_tws[:15]

    groups = {sig: [t for t in top_tws if t["credit_signal"] == sig]
              for sig in ["negative", "watch", "positive", "neutral"]}

    sections_html = ""
    for sig in ["negative", "watch", "positive", "neutral"]:
        items = groups[sig]
        if not items:
            continue
        c = CS_STYLE[sig]
        rows = ""
        for t in items:
            rows += (
                f'<div style="border:1px solid {c["bd"]};border-radius:10px;'
                f'padding:14px 16px;margin-bottom:10px;background:#fff">'
                f'<div style="font-size:12px;color:{c["fg"]};font-weight:700;margin-bottom:6px">'
                f'&#x25CF; {esc(t["source_title"])} &middot; '
                f'<span style="color:#94a3b8;font-weight:400">{esc(fmt_date(t["source_date"]))}</span>'
                f'</div>'
                f'<div style="font-size:13px;font-weight:600;color:#0f172a;margin-bottom:5px">'
                f'{esc(t["takeaway"])}</div>'
                f'<div style="font-size:12px;color:#475569">{esc(t["analyst_lens"])}</div>'
                f'</div>'
            )
        label = f'{c["label"]} ({len(items)})'
        sections_html += (
            f'<div style="margin-bottom:28px">'
            f'<div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;'
            f'color:{c["fg"]};background:{c["bg"]};border:1px solid {c["bd"]};'
            f'padding:6px 14px;border-radius:20px;display:inline-block;margin-bottom:12px">'
            f'{esc(label)}</div>{rows}</div>'
        )

    neg_cnt = len([t for t in all_tws if t["credit_signal"] == "negative"])
    watch_cnt = len([t for t in all_tws if t["credit_signal"] == "watch"])
    pos_cnt = len([t for t in all_tws if t["credit_signal"] == "positive"])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Weekly Digest — {esc(week_start)}–{esc(week_end)}</title>
<style>
{BASE_CSS}
.content{{max-width:800px;margin:0 auto;padding:28px 20px}}
.pg-hd{{margin-bottom:18px}}
.pg-hd h1{{font-size:18px;font-weight:700;color:#0f172a}}
.pg-hd small{{font-size:12px;color:#64748b}}
.stat-row{{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:16px 20px;
  margin-bottom:24px;display:flex;gap:28px;flex-wrap:wrap}}
.stat{{text-align:center}}.stat-n{{font-size:22px;font-weight:700;color:#0f172a}}
.stat-l{{font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:.5px}}
@media print{{.suite-bar{{display:none}}body{{background:#fff}}}}
</style>
</head>
<body>
{suite_bar("digest")}
<div class="content">
  <div class="pg-hd"><h1>Weekly Digest</h1>
  <small>{esc(week_start)} – {esc(week_end)} &middot; Top credit signals</small></div>
  <div class="stat-row">
    <div class="stat"><div class="stat-n">{len(recent)}</div><div class="stat-l">Notes this week</div></div>
    <div class="stat"><div class="stat-n">{len(all_tws)}</div><div class="stat-l">Total takeaways</div></div>
    <div class="stat"><div class="stat-n">{neg_cnt}</div><div class="stat-l">Negative</div></div>
    <div class="stat"><div class="stat-n">{watch_cnt}</div><div class="stat-l">Watch</div></div>
    <div class="stat"><div class="stat-n">{pos_cnt}</div><div class="stat-l">Positive</div></div>
  </div>
  {sections_html or '<p style="color:#94a3b8;text-align:center;padding:40px 0">No notes from the past 7 days.</p>'}
</div>
<div class="toast" id="toast"></div>
<script>{SHARE_JS}</script>
</body>
</html>"""


# ── Sitemap / robots ────────────────────────────────────────────────────────

def generate_sitemap(notes, out_path):
    lastmod = max((n.get("date", "") for n in notes), default="")
    pages = [("", "1.0"), ("library.html", "0.9"), ("insights.html", "0.9"),
             ("digest.html", "0.7")]
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
    p = argparse.ArgumentParser(description="Generate GitHub Pages knowledge base from notes")
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
        os.path.join(docs_dir, "index.html"): generate_dashboard(notes, entities),
        os.path.join(docs_dir, "library.html"): generate_library(notes),
        os.path.join(docs_dir, "insights.html"): generate_insights(entities),
        os.path.join(docs_dir, "digest.html"): generate_digest(notes),
    }
    for path, html in pages.items():
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"Generated: {path}")

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
