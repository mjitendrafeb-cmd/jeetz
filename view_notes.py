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


def esc(s):
    return (str(s)
            .replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;")
            .replace("'", "&#39;"))


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

    return out


def tag_chip(text, color):
    return f'<span class="chip" style="--cc:{color}">{esc(text)}</span>'


def sentiment_badge(sentiment):
    s = sentiment.lower()
    c = SENTIMENT_COLORS.get(s, SENTIMENT_COLORS["neutral"])
    return (f'<span class="sent-badge" '
            f'style="color:{c["fg"]};background:{c["bg"]};border-color:{c["bd"]}">'
            f'{esc(s)}</span>')


def fmt_date(date_str):
    try:
        return datetime.date.fromisoformat(date_str).strftime("%d %b %Y")
    except Exception:
        return date_str


def render_card(raw_note, idx):
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
        " ".join(dp.get("metric","") + " " + dp.get("value","") + " " + dp.get("entity","") for dp in data_points),
        " ".join(learning),
    ]).lower().replace('"', "'")

    # Tags
    tag_row = "".join(tag_chip(t, TAG_COLORS[hash(t) % len(TAG_COLORS)]) for t in tags)

    CS_COLOR = {"positive": "#15803d", "negative": "#dc2626", "neutral": "#6b7280", "watch": "#d97706"}

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
        kt_html = (f'<div class="sect"><div class="sh">Key Takeaways &amp; Analyst Lens</div>'
                   f'<div class="tbl-wrap"><table class="dt">'
                   f'<thead><tr><th style="width:44%">Takeaway</th><th>Analyst Lens</th></tr></thead>'
                   f'<tbody>{rows}</tbody></table></div></div>')

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
    cid = f"c{idx}"

    # Freshness / duplicate badge
    has_dupes = bool(duplicate_stories)
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
        f'<article class="card" '
        f'data-category="{esc(category)}" '
        f'data-sentiment="{esc(sentiment)}" '
        f'data-date="{esc(date)}" '
        f'data-search="{esc(search_blob)}" '
        f'id="{cid}">\n'
        f'  <div class="card-hd" onclick="toggle(\'{cid}\')">\n'
        f'    <div class="card-meta">\n'
        f'      <span class="cat-badge">{esc(category)}</span>\n'
        f'      {sentiment_badge(sentiment)}\n'
        f'      <time class="date-badge" datetime="{esc(date)}">{esc(fmt_date(date))}</time>\n'
        f'      {freshness_html}\n'
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

    cards_html = "\n".join(render_card(n, i) for i, n in enumerate(notes))
    jsonld = build_jsonld(notes)
    total_js = total  # used inside JS

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
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="{esc(SITE_TITLE)}">
<meta name="twitter:description" content="{esc(SITE_DESC)}">
<script type="application/ld+json">{jsonld}</script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  background:#f8fafc;color:#1e293b;font-size:14px;line-height:1.6}}

/* ── Top bar ── */
header{{background:#fff;border-bottom:1px solid #e2e8f0;
  padding:0 28px;position:sticky;top:0;z-index:100;
  box-shadow:0 1px 4px #0000000a}}
.topbar{{display:flex;align-items:center;justify-content:space-between;
  gap:16px;height:60px;max-width:1240px;margin:0 auto}}
.brand h1{{font-size:17px;font-weight:700;color:#0f172a;letter-spacing:-.3px}}
.brand small{{font-size:11px;color:#94a3b8;display:block;margin-top:1px}}
.top-right{{display:flex;align-items:center;gap:10px;flex-shrink:0}}

/* search */
#search{{background:#f1f5f9;border:1.5px solid #e2e8f0;color:#0f172a;
  padding:8px 14px;border-radius:8px;font-size:13px;width:260px;
  outline:none;transition:border-color .15s,box-shadow .15s}}
#search::placeholder{{color:#94a3b8}}
#search:focus{{border-color:#6366f1;box-shadow:0 0 0 3px #6366f122;background:#fff}}

/* sort */
#sort-sel{{border:1.5px solid #e2e8f0;background:#f1f5f9;color:#475569;
  padding:8px 10px;border-radius:8px;font-size:12px;outline:none;cursor:pointer}}
#sort-sel:focus{{border-color:#6366f1}}

/* sentiment filter chips */
.sent-filters{{display:flex;gap:6px;flex-wrap:wrap}}
.sf{{border:1.5px solid #e2e8f0;background:#fff;color:#64748b;
  padding:5px 12px;border-radius:20px;font-size:11px;font-weight:600;
  cursor:pointer;transition:all .15s;white-space:nowrap}}
.sf:hover{{border-color:#6366f1;color:#6366f1}}
.sf.active{{background:#6366f1;border-color:#6366f1;color:#fff}}

/* ── Layout ── */
.layout{{display:flex;max-width:1240px;margin:0 auto;padding:24px 20px;gap:24px}}
aside{{width:200px;flex-shrink:0;position:sticky;top:76px;
  align-self:flex-start;max-height:calc(100vh - 96px);overflow-y:auto}}
.aside-title{{font-size:10px;font-weight:700;text-transform:uppercase;
  letter-spacing:.8px;color:#94a3b8;margin-bottom:10px;padding-left:4px}}
.cat-item{{list-style:none;padding:7px 12px;border-radius:8px;cursor:pointer;
  font-size:13px;display:flex;justify-content:space-between;align-items:center;
  color:#475569;margin-bottom:2px;transition:background .1s,color .1s}}
.cat-item:hover{{background:#e2e8f0;color:#0f172a}}
.cat-item.active{{background:#0f172a;color:#f8fafc;font-weight:600}}
.cnt{{font-size:11px;padding:1px 8px;border-radius:20px;font-weight:500;
  background:#e2e8f0;color:#64748b}}
.cat-item.active .cnt{{background:#334155;color:#94a3b8}}

/* ── Cards area ── */
main{{flex:1;min-width:0}}
#stats-bar{{font-size:12px;color:#64748b;margin-bottom:14px;min-height:18px}}
.card{{background:#fff;border-radius:14px;margin-bottom:14px;
  border:1.5px solid #e2e8f0;overflow:hidden;
  transition:box-shadow .2s,border-color .2s}}
.card:hover{{box-shadow:0 4px 20px #0000000f;border-color:#c7d2fe}}
.card-hd{{padding:18px 20px 14px;cursor:pointer;user-select:none}}
.card-hd:hover{{background:#fafbff}}
.card-meta{{display:flex;align-items:center;gap:7px;margin-bottom:10px;flex-wrap:wrap}}
.cat-badge{{background:#eff6ff;color:#2563eb;border:1px solid #bfdbfe;
  font-size:11px;font-weight:600;padding:3px 10px;border-radius:20px}}
.sent-badge{{font-size:11px;font-weight:600;padding:3px 10px;border-radius:20px;
  border:1px solid transparent}}
.date-badge{{font-size:11px;color:#94a3b8;font-weight:500}}
.tog-ico{{margin-left:auto;color:#cbd5e1;font-size:18px;
  transition:transform .2s;line-height:1}}
.tog-ico.open{{transform:rotate(180deg)}}
.card-title{{font-size:16px;font-weight:700;color:#0f172a;
  line-height:1.4;margin-bottom:6px}}
.card-preview{{font-size:13px;color:#475569;line-height:1.6;
  margin-bottom:10px;max-width:90ch}}
.chip-row{{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:4px}}
.chip{{font-size:11px;font-weight:500;padding:3px 10px;border-radius:20px;
  background:#f1f5f9;color:#475569;border:1px solid #e2e8f0;
  display:inline-block}}
.source-line{{font-size:11px;color:#cbd5e1;font-family:'SF Mono',Consolas,monospace;
  margin-top:6px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.fresh-badge{{font-size:11px;font-weight:600;padding:2px 9px;border-radius:20px;border:1px solid transparent}}
.fresh-badge.stale{{background:#fef3c7;color:#b45309;border-color:#fde68a}}
.fresh-badge.mixed{{background:#f0f9ff;color:#0284c7;border-color:#bae6fd}}

/* ── Card body (expanded) ── */
.card-bd{{padding:0 20px 18px;border-top:1.5px solid #f1f5f9}}
.sect{{margin-top:18px}}
.sh{{font-size:10px;font-weight:700;text-transform:uppercase;
  letter-spacing:.7px;color:#94a3b8;margin-bottom:8px;
  padding-bottom:5px;border-bottom:1px solid #f1f5f9}}
.blist{{padding-left:20px}}
.blist li{{margin-bottom:6px;line-height:1.65;color:#334155;font-size:13px}}
.mon li{{color:#92400e}}
.learn li{{color:#075985}}
.tbl-wrap{{overflow-x:auto}}
.dt{{width:100%;border-collapse:collapse;font-size:13px}}
.dt thead th{{padding:8px 12px;text-align:left;font-size:10px;font-weight:700;
  text-transform:uppercase;letter-spacing:.5px;color:#64748b;
  background:#f8fafc;border-bottom:2px solid #e2e8f0}}
.kc{{padding:9px 12px;vertical-align:top;border-bottom:1px solid #f8fafc;
  line-height:1.6;font-size:13px;color:#334155}}
.tw{{font-weight:600;color:#0f172a;width:40%}}
.al{{color:#475569}}
.rel-row{{margin-top:14px;font-size:11px;color:#94a3b8;display:flex;
  align-items:center;gap:6px;flex-wrap:wrap}}
.rel-chip{{background:#f1f5f9;color:#64748b;border:1px solid #e2e8f0;
  padding:2px 8px;border-radius:12px;font-size:10px;font-weight:600}}

/* ── Highlights ── */
mark{{background:#fef9c3;color:#713f12;border-radius:2px;padding:0 2px}}

/* ── Empty state ── */
#empty{{text-align:center;padding:80px 20px;display:none}}
#empty svg{{color:#e2e8f0;margin-bottom:16px}}
#empty h3{{font-size:16px;color:#94a3b8;margin-bottom:6px}}
#empty p{{font-size:13px;color:#cbd5e1}}

/* ── Responsive ── */
@media(max-width:800px){{
  aside{{display:none}}
  .layout{{padding:16px 12px}}
  .topbar{{flex-wrap:wrap;height:auto;padding:10px 0;gap:8px}}
  #search{{width:100%}}
  .top-right{{flex-wrap:wrap;width:100%}}
  .sent-filters{{display:none}}
}}
@media(max-width:480px){{
  .card-title{{font-size:14px}}
  header{{padding:0 14px}}
}}
</style>
</head>
<body>
<header>
  <div class="topbar">
    <div class="brand">
      <h1>Daily Reads</h1>
      <small>Updated {now_str} &middot; {total} note{'s' if total != 1 else ''}</small>
    </div>
    <div class="top-right">
      <div class="sent-filters" role="group" aria-label="Filter by sentiment">
        <button class="sf active" data-sent="all" onclick="setSent(this,'all')">All</button>
        <button class="sf" data-sent="positive" onclick="setSent(this,'positive')">Positive</button>
        <button class="sf" data-sent="negative" onclick="setSent(this,'negative')">Negative</button>
        <button class="sf" data-sent="mixed" onclick="setSent(this,'mixed')">Mixed</button>
        <button class="sf" data-sent="neutral" onclick="setSent(this,'neutral')">Neutral</button>
      </div>
      <select id="sort-sel" onchange="setSort(this.value)" aria-label="Sort order">
        <option value="newest">Newest first</option>
        <option value="oldest">Oldest first</option>
      </select>
      <input id="search" type="search" placeholder="Search notes&#8230;"
             oninput="setQ(this.value)" autocomplete="off" aria-label="Search notes">
    </div>
  </div>
</header>
<div class="layout">
  <aside>
    <div class="aside-title">Categories</div>
    <ul id="cat-list" role="list">{cat_items}</ul>
  </aside>
  <main>
    <div id="stats-bar" role="status" aria-live="polite"></div>
    <div id="cards-container">{cards_html}</div>
    <div id="empty" role="status">
      <svg width="48" height="48" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
          d="M21 21l-4.35-4.35M17 11A6 6 0 1 1 5 11a6 6 0 0 1 12 0z"/>
      </svg>
      <h3>No notes found</h3>
      <p>Try a different search term or clear the filters.</p>
    </div>
  </main>
</div>
<script>
(function(){{
  var TOTAL={total_js};
  var state={{q:'',cat:'all',sent:'all',sort:'newest'}};

  // ── Read URL params on load ──
  var params=new URLSearchParams(window.location.search);
  if(params.get('q'))state.q=params.get('q');
  if(params.get('category'))state.cat=params.get('category');
  if(params.get('sentiment'))state.sent=params.get('sentiment');
  if(params.get('sort'))state.sort=params.get('sort');

  function applyInit(){{
    if(state.q){{
      var el=document.getElementById('search');
      if(el)el.value=state.q;
    }}
    if(state.sort!=='newest'){{
      var sel=document.getElementById('sort-sel');
      if(sel)sel.value=state.sort;
    }}
    if(state.cat!=='all'){{
      document.querySelectorAll('.cat-item').forEach(function(li){{
        li.classList.toggle('active',li.dataset.cat===state.cat);
      }});
    }}
    if(state.sent!=='all'){{
      document.querySelectorAll('.sf').forEach(function(b){{
        b.classList.toggle('active',b.dataset.sent===state.sent);
      }});
    }}
    apply();
  }}

  // ── Highlight helper ──
  function hlText(txt,q){{
    if(!q)return escH(txt);
    var re=new RegExp('('+q.replace(/[.*+?^${{}}()|[\\]\\\\]/g,'\\\\$&')+')','gi');
    return escH(txt).replace(re,'<mark>$1</mark>');
  }}
  function escH(t){{
    return String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }}

  // ── Apply all filters ──
  function apply(){{
    var cards=Array.from(document.querySelectorAll('.card'));
    var q=state.q.toLowerCase().trim();
    var cat=state.cat, sent=state.sent;

    // Sort cards in DOM
    var container=document.getElementById('cards-container');
    if(state.sort==='oldest'){{
      cards.sort(function(a,b){{return a.dataset.date.localeCompare(b.dataset.date)}});
    }}else{{
      cards.sort(function(a,b){{return b.dataset.date.localeCompare(a.dataset.date)}});
    }}
    cards.forEach(function(c){{container.appendChild(c)}});

    var vis=0;
    cards.forEach(function(c){{
      var catOk=cat==='all'||c.dataset.category===cat;
      var sentOk=sent==='all'||c.dataset.sentiment===sent;
      var searchOk=!q||c.dataset.search.includes(q);
      var show=catOk&&sentOk&&searchOk;
      c.style.display=show?'':'none';
      if(show){{
        vis++;
        // Highlight title and preview
        var titleEl=c.querySelector('.card-title');
        var prevEl=c.querySelector('.card-preview');
        if(titleEl)titleEl.innerHTML=hlText(titleEl.dataset.raw||'',q);
        if(prevEl)prevEl.innerHTML=hlText(prevEl.dataset.raw||'',q);
      }}
    }});

    // Stats bar — always visible
    var bar=document.getElementById('stats-bar');
    if(q||cat!=='all'||sent!=='all'){{
      bar.textContent='Showing '+vis+' of '+TOTAL+' note'+(TOTAL===1?'':'s');
    }}else{{
      bar.textContent=TOTAL+' note'+(TOTAL===1?'':'s');
    }}

    // Empty state
    document.getElementById('empty').style.display=vis?'none':'block';

    // Update URL
    var p=new URLSearchParams();
    if(q)p.set('q',state.q);
    if(cat!=='all')p.set('category',cat);
    if(sent!=='all')p.set('sentiment',sent);
    if(state.sort!=='newest')p.set('sort',state.sort);
    var qs=p.toString();
    history.replaceState(null,'',qs?'?'+qs:window.location.pathname);
  }}

  // ── Public handlers ──
  window.setCat=function(el,cat){{
    state.cat=cat;
    document.querySelectorAll('.cat-item').forEach(function(li){{li.classList.remove('active')}});
    el.classList.add('active');
    apply();
  }};
  window.setSent=function(el,sent){{
    state.sent=sent;
    document.querySelectorAll('.sf').forEach(function(b){{b.classList.remove('active')}});
    el.classList.add('active');
    apply();
  }};
  window.setSort=function(val){{
    state.sort=val;
    apply();
  }};
  window.setQ=function(val){{
    state.q=val;
    apply();
  }};
  window.toggle=function(id){{
    var bd=document.getElementById(id+'-bd');
    var ico=document.getElementById(id+'-ico');
    var hidden=bd.hasAttribute('hidden');
    if(hidden){{bd.removeAttribute('hidden');ico.classList.add('open');}}
    else{{bd.setAttribute('hidden','');ico.classList.remove('open');}}
  }};

  // Run initial filter (applies URL params)
  applyInit();
  document.getElementById('search').focus();
}})();
</script>
</body>
</html>"""


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

    robots_path = write_robots(docs_dir)
    print(f"Generated: {robots_path}")

    if not args.no_open:
        webbrowser.open(f"file:///{args.out.replace(os.sep, '/')}")


if __name__ == "__main__":
    main()
