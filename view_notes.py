#!/usr/bin/env python3
"""
view_notes.py — Generate docs/index.html + docs/sitemap.xml from all distilled notes.

Usage:
  python view_notes.py
  python view_notes.py --notes-dir path/to/notes --out docs/index.html --no-open
"""
import argparse
import datetime
import json
import os
import sys
import webbrowser
from collections import Counter

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_NOTES_DIR = os.path.join(REPO_ROOT, "docs", "notes")
DEFAULT_OUT = os.path.join(REPO_ROOT, "docs", "index.html")

SITE_URL = "https://mjitendrafeb-cmd.github.io/jeetz"
SITE_TITLE = "Daily Reads — Knowledge Notes"
SITE_DESC = ("Personal knowledge library — distilled notes from daily reading "
             "in finance, credit research, macro, and regulatory analysis.")

SENTIMENT_COLORS = {
    "positive": {"fg": "#15803d", "bg": "#f0fdf4", "bd": "#bbf7d0"},
    "negative": {"fg": "#dc2626", "bg": "#fef2f2", "bd": "#fecaca"},
    "neutral":  {"fg": "#6b7280", "bg": "#f9fafb", "bd": "#e5e7eb"},
    "mixed":    {"fg": "#b45309", "bg": "#fffbeb", "bd": "#fde68a"},
}
TAG_COLORS = ["#3b82f6","#8b5cf6","#ec4899","#f97316","#14b8a6","#64748b","#a16207","#0891b2"]
SIGNAL_PRIORITY = {"negative": 0, "watch": 1, "positive": 2, "neutral": 3}
SIGNAL_BORDER = {"negative": "#ef4444", "watch": "#f59e0b", "positive": "#22c55e", "neutral": "#e2e8f0"}
SOURCE_TYPE_META = {
    "broker_research": {"label": "Broker Research", "bg": "#eff6ff", "fg": "#2563eb", "bd": "#bfdbfe"},
    "regulatory":      {"label": "Regulatory",      "bg": "#f0fdf4", "fg": "#15803d", "bd": "#bbf7d0"},
    "academic":        {"label": "Academic",         "bg": "#faf5ff", "fg": "#7c3aed", "bd": "#ddd6fe"},
    "news":            {"label": "News",             "bg": "#fff7ed", "fg": "#c2410c", "bd": "#fed7aa"},
    "other":           {"label": "Other",            "bg": "#f8fafc", "fg": "#64748b", "bd": "#e2e8f0"},
}


def esc(s):
    return (str(s)
            .replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;")
            .replace("'", "&#39;"))


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
    entities = " ".join(ei.get("entity","").lower() for ei in note.get("entities_impacted",[]))
    tags = " ".join(t.lower() for t in note.get("tags",[]))
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

    # title: fall back to readable version of source filename
    if not out.get("title"):
        src = out.get("source_file", "")
        stem = os.path.splitext(src)[0] if src else "Untitled"
        out["title"] = stem.replace("_", " ").replace("-", " ").strip()

    # executive_summary
    if "executive_summary" not in out:
        old = out.get("summary", "")
        out["executive_summary"] = [old] if old else []

    # key_takeaways
    if "key_takeaways" not in out:
        kt = []
        for t in out.get("takeaways", []):
            kt.append({"takeaway": t, "analyst_lens": ""})
        for r in out.get("risk_analysis", []):
            kt.append({"takeaway": r, "analyst_lens": "(risk)"})
        for i in out.get("key_implications", []):
            kt.append({"takeaway": i, "analyst_lens": "(implication)"})
        out["key_takeaways"] = kt

    # entities_impacted
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


def tag_chip(text, color):
    return f'<span class="chip" style="--cc:{color}">{esc(text)}</span>'


def sentiment_badge(sentiment):
    s = sentiment.lower()
    c = SENTIMENT_COLORS.get(s, SENTIMENT_COLORS["neutral"])
    return (f'<span class="sent-badge" '
            f'style="color:{c["fg"]};background:{c["bg"]};border-color:{c["bd"]}">'
            f'{esc(s)}</span>')


def source_type_badge(st):
    m = SOURCE_TYPE_META.get((st or "other").lower(), SOURCE_TYPE_META["other"])
    return (f'<span class="stype-badge" '
            f'style="color:{m["fg"]};background:{m["bg"]};border-color:{m["bd"]}">'
            f'{esc(m["label"])}</span>')


def fmt_date(date_str):
    try:
        return datetime.date.fromisoformat(date_str).strftime("%d %b %Y")
    except Exception:
        return date_str


def render_card(raw_note, idx, watchlist=None):
    note = normalize_note(raw_note)

    title = note.get("title", "Untitled")
    sentiment = note.get("sentiment", "neutral").lower()
    source = note.get("source_file", "")
    date = note.get("date", "")
    doc_date = note.get("document_date") or ""
    freshness = note.get("freshness", "").lower()
    stale_items = note.get("stale_items", [])
    duplicate_stories = note.get("duplicate_stories", [])
    category = note.get("category", "Other")
    tags = note.get("tags", [])
    relevance = note.get("relevance", [])
    exec_summary = note.get("executive_summary", [])
    key_takeaways = note.get("key_takeaways", [])
    entities_impacted = note.get("entities_impacted", [])
    learning = note.get("learning", [])

    # Preview text: first key takeaway
    preview = key_takeaways[0].get("takeaway", "") if key_takeaways else (exec_summary[0] if exec_summary else "")

    # Searchable blob
    search_blob = " ".join([
        title, source, category, sentiment,
        " ".join(tags), " ".join(relevance),
        " ".join(exec_summary),
        " ".join(kt.get("takeaway","") + " " + kt.get("analyst_lens","") for kt in key_takeaways),
        " ".join(ei.get("entity","") + " " + ei.get("impact","") for ei in entities_impacted),
        " ".join(learning),
    ]).lower().replace('"', "'")

    # Tags
    source_type = note.get("source_type", "other")
    tags_csv = ",".join(tags)
    tag_row = "".join(tag_chip(t, TAG_COLORS[hash(t) % len(TAG_COLORS)]) for t in tags)

    CS_COLOR = {"positive": "#15803d", "negative": "#dc2626", "neutral": "#6b7280", "watch": "#d97706"}
    cid = f"c{idx}"
    has_dupes = bool(duplicate_stories)

    # Dominant credit signal → card left-border color
    if key_takeaways:
        sigs = [kt.get("credit_signal", "neutral").lower() for kt in key_takeaways]
        dominant_sig = min(sigs, key=lambda s: SIGNAL_PRIORITY.get(s, 3))
    else:
        dominant_sig = "neutral"
    card_border = SIGNAL_BORDER.get(dominant_sig, "#e2e8f0")

    # ── Expanded sections ──────────────────────────────────────────────

    # 1. Key Takeaways & Analyst Lens (with credit_signal)
    kt_html = ""
    if key_takeaways:
        rows = ""
        for kt in key_takeaways:
            cs = kt.get("credit_signal", "").lower()
            cs_col = CS_COLOR.get(cs, "#6b7280")
            cs_badge = (f'<span style="font-size:10px;font-weight:700;color:{cs_col};'
                        f'text-transform:uppercase;letter-spacing:.4px">&#x25CF; {esc(cs)}</span><br>'
                        ) if cs else ""
            rows += (
                f'<tr><td class="kc tw"><div style="margin-bottom:3px">{cs_badge}</div>{esc(kt.get("takeaway",""))}</td>'
                f'<td class="kc al">{esc(kt.get("analyst_lens",""))}</td></tr>'
            )
        full_table = (f'<div class="tbl-wrap"><table class="dt">'
                      f'<thead><tr><th style="width:44%">Takeaway</th><th>Analyst Lens</th></tr></thead>'
                      f'<tbody>{rows}</tbody></table></div>')
        if has_dupes:
            kt_html = (f'<div class="sect"><div class="sh">Key Takeaways &amp; Analyst Lens</div>'
                       f'<div id="{cid}-dupc" style="padding:8px 0;color:#6d28d9;font-size:13px">'
                       f'{len(key_takeaways)} takeaway(s) — overlaps with earlier notes. '
                       f'<a href="#" onclick="expandDupe(\'{cid}\');return false" '
                       f'style="color:#6366f1;font-size:12px;text-decoration:none">Show anyway →</a>'
                       f'</div><div id="{cid}-dupt" hidden>{full_table}</div></div>')
        else:
            kt_html = (f'<div class="sect"><div class="sh">Key Takeaways &amp; Analyst Lens</div>'
                       f'{full_table}</div>')

    # 2. Companies & Sectors Impacted
    ei_html = ""
    if entities_impacted:
        rows = "".join(
            f'<tr><td class="kc tw">{esc(ei.get("entity",""))}</td>'
            f'<td class="kc">{esc(ei.get("impact",""))}</td></tr>'
            for ei in entities_impacted
        )
        ei_html = (f'<div class="sect"><div class="sh">Companies &amp; Sectors Impacted</div>'
                   f'<div class="tbl-wrap"><table class="dt">'
                   f'<thead><tr><th style="width:30%">Entity</th><th>Impact</th></tr></thead>'
                   f'<tbody>{rows}</tbody></table></div></div>')

    # 4. What Can I Learn?
    learn_html = ""
    if learning:
        items = "".join(f"<li>{esc(l)}</li>" for l in learning)
        learn_html = (f'<div class="sect"><div class="sh">What Can I Learn?</div>'
                      f'<ul class="blist learn">{items}</ul></div>')

    # 5. Relevance footer
    rel_html = ""
    if relevance:
        chips = "".join(f'<span class="rel-chip">{esc(r)}</span>' for r in relevance)
        rel_html = f'<div class="rel-row">Relevance: {chips}</div>'

    body = kt_html + ei_html + learn_html + rel_html

    # Freshness / duplicate badge
    wl_hit = check_watchlist(note, watchlist or set())
    wl_badge = '<span class="wl-badge">&#9733; Watchlist</span>' if wl_hit else ""
    freshness_html = ""
    if has_dupes and freshness == "stale":
        freshness_html = '<span class="fresh-badge stale">&#9888; Older &amp; repeated news</span>'
    elif has_dupes:
        freshness_html = '<span class="fresh-badge stale">&#9888; Has repeated stories</span>'
    elif freshness == "stale":
        freshness_html = '<span class="fresh-badge stale">&#9888; Contains older news</span>'
    elif freshness == "mixed":
        freshness_html = '<span class="fresh-badge mixed">&#9432; Mixed freshness</span>'

    # Duplicate stories warning (shown at top of body)
    dupe_html = ""
    if duplicate_stories:
        items = "".join(f"<li>{esc(s)}</li>" for s in duplicate_stories)
        dupe_html = (f'<div class="sect">'
                     f'<div class="sh" style="color:#6d28d9">&#10006; Already Covered in Previous Notes</div>'
                     f'<ul class="blist" style="color:#5b21b6">{items}</ul></div>')

    # Stale items warning
    stale_html = ""
    if stale_items:
        items = "".join(f"<li>{esc(s)}</li>" for s in stale_items)
        stale_html = (f'<div class="sect">'
                      f'<div class="sh" style="color:#b45309">&#9888; Older / Recycled Items</div>'
                      f'<ul class="blist" style="color:#92400e">{items}</ul></div>')

    # Doc date line
    doc_date_html = ""
    if doc_date:
        doc_date_html = f' &middot; Doc date: {esc(fmt_date(doc_date))}'

    body_with_stale = dupe_html + stale_html + body

    return (
        f'<article class="card" style="border-left-color:{card_border}" '
        f'data-category="{esc(category)}" '
        f'data-sentiment="{esc(sentiment)}" '
        f'data-date="{esc(date)}" '
        f'data-docdate="{esc(doc_date)}" '
        f'data-tags="{esc(tags_csv)}" '
        f'data-search="{esc(search_blob)}" '
        f'id="{cid}">\n'
        f'  <div class="card-hd" onclick="toggle(\'{cid}\')">\n'
        f'    <div class="card-meta">\n'
        f'      {source_type_badge(source_type)}\n'
        f'      <span class="cat-badge">{esc(category)}</span>\n'
        f'      {sentiment_badge(sentiment)}\n'
        f'      <time class="date-badge" datetime="{esc(date)}">{esc(fmt_date(date))}</time>\n'
        f'      {freshness_html}\n'
        f'      {wl_badge}\n'
        f'      <span class="tog-ico" id="{cid}-ico">&#8964;</span>\n'
        f'    </div>\n'
        f'    <h2 class="card-title" data-raw="{esc(title)}">{esc(title)}</h2>\n'
        f'    <p class="card-preview" data-raw="{esc(preview)}">{esc(preview)}</p>\n'
        f'    <div class="chip-row">{tag_row}</div>\n'
        f'    <div class="source-line">{esc(source)}{doc_date_html}</div>\n'
        f'  </div>\n'
        f'  <div class="card-bd" id="{cid}-bd" hidden>\n'
        f'    {body_with_stale}\n'
        f'  </div>\n'
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


def render_row(raw_note, idx, watchlist=None):
    note = normalize_note(raw_note)
    title       = note.get("title", "Untitled")
    date        = note.get("date", "")
    doc_date    = note.get("document_date") or ""
    category    = note.get("category", "Other")
    source      = note.get("source_file", "")
    source_type = note.get("source_type", "other")
    sentiment   = note.get("sentiment", "neutral").lower()
    key_takeaways     = note.get("key_takeaways", [])
    entities_impacted = note.get("entities_impacted", [])
    learning          = note.get("learning", [])
    tags              = note.get("tags", [])
    duplicate_stories = note.get("duplicate_stories", [])

    preview = (key_takeaways[0].get("takeaway", "") if key_takeaways
               else (note.get("executive_summary") or [""])[0])

    search_blob = " ".join([
        title, source, category, sentiment,
        " ".join(tags),
        " ".join(kt.get("takeaway","") + " " + kt.get("analyst_lens","")
                 for kt in key_takeaways),
        " ".join(ei.get("entity","") + " " + ei.get("impact","")
                 for ei in entities_impacted),
        " ".join(learning),
    ]).lower().replace('"', "'")

    tags_csv = ",".join(tags)
    cid = f"r{idx}"

    if key_takeaways:
        sigs = [kt.get("credit_signal", "neutral").lower() for kt in key_takeaways]
        dominant_sig = min(sigs, key=lambda s: SIGNAL_PRIORITY.get(s, 3))
    else:
        dominant_sig = "neutral"
    lborder = SIGNAL_BORDER.get(dominant_sig, "#e2e8f0")

    st_meta = SOURCE_TYPE_META.get(source_type, SOURCE_TYPE_META["other"])
    wl_hit  = check_watchlist(note, watchlist or set())

    CS_COLOR = {"positive": "#15803d", "negative": "#dc2626", "neutral": "#6b7280", "watch": "#d97706"}
    kt_rows = ""
    for kt in key_takeaways:
        cs = kt.get("credit_signal", "").lower()
        cs_col   = CS_COLOR.get(cs, "#6b7280")
        cs_badge = (f'<span style="font-size:10px;font-weight:700;color:{cs_col};'
                    f'text-transform:uppercase">&#x25CF; {esc(cs)}</span><br>') if cs else ""
        kt_rows += (f'<tr><td class="kc tw"><div style="margin-bottom:3px">{cs_badge}</div>'
                    f'{esc(kt.get("takeaway",""))}</td>'
                    f'<td class="kc al">{esc(kt.get("analyst_lens",""))}</td></tr>')

    ei_rows = "".join(
        f'<tr><td class="kc tw">{esc(ei.get("entity",""))}</td>'
        f'<td class="kc">{esc(ei.get("impact",""))}</td></tr>'
        for ei in entities_impacted
    )
    learn_items = "".join(f"<li>{esc(l)}</li>" for l in learning)
    tag_chips   = "".join(f'<span class="tc-sm">{esc(t)}</span>' for t in tags[:8])

    exp_parts = []
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

    wl_badge  = ' <span class="wl-badge">&#9733; Watchlist</span>' if wl_hit else ""
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


def generate_html(notes):
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
    jsonld    = build_jsonld(notes)

    # Credit signal summary bar
    sig_counts = Counter()
    for n in notes:
        for kt in n.get("key_takeaways", []):
            s = kt.get("credit_signal", "neutral").lower()
            sig_counts[s] += 1
    sig_bar_parts = []
    for sig, label, color in [
        ("negative", "Negative", "#dc2626"),
        ("watch",    "Watch",    "#d97706"),
        ("positive", "Positive", "#15803d"),
        ("neutral",  "Neutral",  "#6b7280"),
    ]:
        cnt = sig_counts.get(sig, 0)
        if cnt:
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
<title>{esc(SITE_TITLE)}</title>
<meta name="description" content="{esc(SITE_DESC)}">
<link rel="canonical" href="{SITE_URL}/">
<meta property="og:type" content="website">
<meta property="og:url" content="{SITE_URL}/">
<meta property="og:title" content="{esc(SITE_TITLE)}">
<meta property="og:description" content="{esc(SITE_DESC)}">
<script type="application/ld+json">{jsonld}</script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  background:#f3f2f1;color:#323130;font-size:14px;line-height:1.5;min-height:100vh}}

/* ── Suite bar ── */
.suite-bar{{background:#0078d4;min-height:48px;padding:0 20px}}
.suite-inner{{max-width:1400px;margin:0 auto;height:48px;
  display:flex;align-items:center;gap:10px}}
.suite-brand{{color:#fff;font-size:15px;font-weight:700;
  display:flex;align-items:center;gap:8px}}
.suite-sep{{color:rgba(255,255,255,.45);font-size:13px}}
.suite-lib{{color:rgba(255,255,255,.88);font-size:14px;font-weight:400}}
.suite-meta{{font-size:11px;color:rgba(255,255,255,.6);margin-left:6px}}
.suite-actions{{margin-left:auto;display:flex;align-items:center;gap:8px}}
.suite-btn{{color:rgba(255,255,255,.9);background:rgba(255,255,255,.1);
  border:1px solid rgba(255,255,255,.22);padding:6px 14px;border-radius:2px;
  font-size:12px;font-weight:600;cursor:pointer;text-decoration:none;
  display:inline-flex;align-items:center;gap:5px;white-space:nowrap;
  transition:background .15s}}
.suite-btn:hover{{background:rgba(255,255,255,.2)}}
.digest-tab{{background:#fff;color:#0078d4;border-color:#fff;font-weight:700}}
.digest-tab:hover{{background:#e8f4fd}}
.sync-btn{{background:#107c10;color:#fff;border-color:#0e6b0e;font-weight:700}}
.sync-btn:hover{{background:#0e6b0e}}

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
.share-btn{{background:#0078d4;color:#fff;border:none;padding:6px 14px;
  border-radius:2px;font-size:12px;font-weight:600;cursor:pointer;
  display:inline-flex;align-items:center;gap:5px;white-space:nowrap;
  transition:background .15s}}
.share-btn:hover{{background:#106ebe}}

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

/* ── Main / Table ── */
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
.stype-badge{{font-size:11px;font-weight:600;padding:3px 9px;
  border-radius:2px;border:1px solid transparent;white-space:nowrap}}
.cat-badge{{background:#deecf9;color:#0078d4;font-size:11px;font-weight:600;
  padding:3px 9px;border-radius:2px;white-space:nowrap}}
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

/* ── Empty / Highlights / Toast ── */
#empty{{text-align:center;padding:60px 20px;display:none;
  color:#605e5c;background:#fff;border-top:1px solid #edebe9}}
mark{{background:#fff100;color:#323130;border-radius:1px;padding:0 1px}}
.toast{{position:fixed;bottom:24px;right:24px;background:#323130;color:#fff;
  padding:12px 20px;border-radius:2px;font-size:13px;font-weight:600;
  box-shadow:0 4px 16px rgba(0,0,0,.25);z-index:999;opacity:0;
  transform:translateY(8px);transition:all .25s;pointer-events:none}}
.toast.show{{opacity:1;transform:translateY(0)}}
.toast.ok{{border-left:3px solid #107c10}}

/* ── Responsive ── */
@media(max-width:900px){{
  aside{{display:none}}.layout{{padding:12px}}.col-abstract{{display:none}}
}}
@media(max-width:600px){{
  .col-date,.col-status{{display:none}}#search{{width:140px}}
}}
@media print{{
  .suite-bar,.cmd-bar,.signal-bar,aside{{display:none!important}}
  .exp-row{{display:table-row!important}}body{{background:#fff}}
  .doc-table-wrap{{border:none}}
}}
</style>
</head>
<body>

<div class="suite-bar">
  <div class="suite-inner">
    <div class="suite-brand">&#128218; Daily Reads</div>
    <span class="suite-sep">&#8250;</span>
    <span class="suite-lib">Knowledge Depot</span>
    <span class="suite-meta">Updated {now_str} &middot; {total} note{'s' if total != 1 else ''}</span>
    <div class="suite-actions">
      <a href="digest.html" class="suite-btn digest-tab">&#128203; Weekly Digest</a>
      <a href="https://github.com/mjitendrafeb-cmd/jeetz/actions/workflows/daily-reads.yml"
         target="_blank" class="suite-btn sync-btn" title="Opens GitHub Actions — click Run workflow to pull new PDFs from Drive">
        &#8635; Sync from Drive
      </a>
      <button class="suite-btn" onclick="doShare()">&#128279; Share</button>
    </div>
  </div>
</div>

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
    <span id="stats-lbl"></span>
    <button class="share-btn" onclick="doShare()">&#128279; Share</button>
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

  window.expandDupe=function(cid){{
    var c=document.getElementById(cid+'-dupc');var t=document.getElementById(cid+'-dupt');
    if(c)c.hidden=true;if(t)t.removeAttribute('hidden');
  }};

  function showToast(msg,type){{
    var t=document.getElementById('toast');
    t.textContent=msg;t.className='toast '+(type||'ok');t.classList.add('show');
    setTimeout(function(){{t.classList.remove('show');}},3000);
  }}

  window.doShare=function(){{
    var url=window.location.href;
    if(navigator.clipboard){{
      navigator.clipboard.writeText(url).then(function(){{showToast('Link copied to clipboard','ok');}})
        .catch(function(){{prompt('Copy this link:',url);}});
    }}else{{prompt('Copy this link:',url);}}
  }};

  applyInit();
  document.getElementById('search').focus();
}})();
</script>
</body>
</html>"""


def generate_digest(notes, out_path):
    today = datetime.date.today()
    week_ago = (today - datetime.timedelta(days=7)).isoformat()
    week_end = today.strftime("%d %b %Y")
    week_start = (today - datetime.timedelta(days=7)).strftime("%d %b")

    recent = [n for n in notes if (n.get("document_date") or n.get("date","")) >= week_ago]

    PRIORITY = {"negative": 0, "watch": 1, "positive": 2, "neutral": 3}
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
                "source_date": note.get("document_date") or note.get("date", ""),
                "priority": PRIORITY.get(sig, 3),
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

    neg_cnt = len([t for t in all_tws if t["credit_signal"]=="negative"])
    watch_cnt = len([t for t in all_tws if t["credit_signal"]=="watch"])
    pos_cnt = len([t for t in all_tws if t["credit_signal"]=="positive"])

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Weekly Digest — {esc(week_start)}–{esc(week_end)}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f8fafc;color:#1e293b;font-size:14px;line-height:1.6}}
.hdr{{background:#0f172a;color:#f8fafc;padding:20px 28px;display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}}
.hdr h1{{font-size:18px;font-weight:700}}.hdr small{{font-size:12px;color:#64748b;display:block;margin-top:3px}}
.hdr a{{color:#818cf8;font-size:12px;text-decoration:none}}.hdr a:hover{{text-decoration:underline}}
.content{{max-width:800px;margin:0 auto;padding:28px 20px}}
.stat-row{{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:16px 20px;margin-bottom:24px;display:flex;gap:28px;flex-wrap:wrap}}
.stat{{text-align:center}}.stat-n{{font-size:22px;font-weight:700;color:#0f172a}}
.stat-l{{font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:.5px}}
@media print{{.hdr a{{display:none}}body{{background:#fff}}}}
</style>
</head>
<body>
<div class="hdr">
  <div><h1>Weekly Digest</h1><small>{esc(week_start)} – {esc(week_end)} &middot; Top credit signals</small></div>
  <a href="{SITE_URL}/">← Full library</a>
</div>
<div class="content">
  <div class="stat-row">
    <div class="stat"><div class="stat-n">{len(recent)}</div><div class="stat-l">Notes this week</div></div>
    <div class="stat"><div class="stat-n">{len(all_tws)}</div><div class="stat-l">Total takeaways</div></div>
    <div class="stat"><div class="stat-n">{neg_cnt}</div><div class="stat-l">Negative</div></div>
    <div class="stat"><div class="stat-n">{watch_cnt}</div><div class="stat-l">Watch</div></div>
    <div class="stat"><div class="stat-n">{pos_cnt}</div><div class="stat-l">Positive</div></div>
  </div>
  {sections_html or '<p style="color:#94a3b8;text-align:center;padding:40px 0">No notes from the past 7 days.</p>'}
</div>
</body>
</html>"""

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)


def generate_sitemap(notes, out_path):
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
             f'  <url><loc>{SITE_URL}/</loc><changefreq>weekly</changefreq><priority>1.0</priority></url>']
    for note in notes:
        d = note.get("date", "")
        if d:
            lines.append(f'  <url><loc>{SITE_URL}/</loc>'
                         f'<lastmod>{d}</lastmod>'
                         f'<changefreq>weekly</changefreq><priority>0.8</priority></url>')
            break  # one entry with most-recent lastmod is enough for a single-page site
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
    p = argparse.ArgumentParser(description="Generate GitHub Pages viewer from knowledge notes")
    p.add_argument("--notes-dir", default=DEFAULT_NOTES_DIR)
    p.add_argument("--out", default=DEFAULT_OUT)
    p.add_argument("--no-open", action="store_true", help="Don't open browser")
    args = p.parse_args()

    notes_dir = os.path.expanduser(args.notes_dir)
    notes = load_notes(notes_dir)

    if not notes:
        print(f"No notes found in: {notes_dir}")
        sys.exit(0)

    html = generate_html(notes)
    docs_dir = os.path.dirname(args.out)
    os.makedirs(docs_dir, exist_ok=True)

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Generated: {args.out}  ({len(notes)} notes)")

    sitemap_path = os.path.join(docs_dir, "sitemap.xml")
    generate_sitemap(notes, sitemap_path)
    print(f"Generated: {sitemap_path}")

    digest_path = os.path.join(docs_dir, "digest.html")
    generate_digest(notes, digest_path)
    print(f"Generated: {digest_path}")

    robots_path = write_robots(docs_dir)
    print(f"Generated: {robots_path}")

    if not args.no_open:
        webbrowser.open(f"file:///{args.out.replace(os.sep, '/')}")


if __name__ == "__main__":
    main()
