#!/usr/bin/env python3
"""
view_notes.py — Generate docs/index.html from all distilled notes in docs/notes/.

Usage:
  python view_notes.py
  python view_notes.py --notes-dir path/to/notes --out docs/index.html
"""
import argparse
import datetime
import json
import os
import sys
import webbrowser

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_NOTES_DIR = os.path.join(REPO_ROOT, "docs", "notes")
DEFAULT_OUT = os.path.join(REPO_ROOT, "docs", "index.html")

SENTIMENT_COLOR = {
    "positive": "#16a34a", "negative": "#dc2626",
    "neutral": "#6b7280", "mixed": "#d97706",
}
TAG_COLORS = ["#3b82f6","#8b5cf6","#ec4899","#f97316","#14b8a6","#64748b","#a16207","#0891b2"]


def load_notes(notes_dir):
    notes = []
    if not os.path.isdir(notes_dir):
        return notes
    for name in sorted(os.listdir(notes_dir)):
        if not name.endswith("_note.json"):
            continue
        try:
            with open(os.path.join(notes_dir, name), encoding="utf-8") as f:
                n = json.load(f)
                notes.append(n)
        except Exception:
            pass
    notes.sort(key=lambda n: n.get("ingested_at", ""), reverse=True)
    return notes


def esc(s):
    """Escape HTML special characters."""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def badge(text, color):
    return (f'<span style="background:{color}22;color:{color};border:1px solid {color}44;'
            f'font-size:11px;font-weight:500;padding:2px 9px;border-radius:20px;'
            f'display:inline-block;margin:2px 2px 2px 0">{esc(text)}</span>')


def normalize_note(note):
    """
    Normalize a note to the new schema. Handles backward compatibility with
    old-schema notes that have takeaways/risk_analysis/key_implications fields.
    Returns a dict guaranteed to have new-schema keys.
    """
    out = dict(note)

    # executive_summary: old schema had "summary" (string)
    if "executive_summary" not in out:
        old_summary = out.get("summary", "")
        if old_summary:
            out["executive_summary"] = [old_summary]
        else:
            out["executive_summary"] = []

    # key_takeaways: old schema had separate "takeaways", "risk_analysis", "key_implications"
    if "key_takeaways" not in out:
        old_takeaways = out.get("takeaways", [])
        old_risks = out.get("risk_analysis", [])
        old_implications = out.get("key_implications", [])
        kt = []
        for t in old_takeaways:
            kt.append({"takeaway": t, "analyst_lens": ""})
        # Append risks and implications as extra rows
        for r in old_risks:
            kt.append({"takeaway": r, "analyst_lens": "(risk)"})
        for i in old_implications:
            kt.append({"takeaway": i, "analyst_lens": "(implication)"})
        out["key_takeaways"] = kt

    # entities_impacted: old schema had "entities" (list of strings)
    if "entities_impacted" not in out:
        old_entities = out.get("entities", [])
        out["entities_impacted"] = [{"entity": e, "impact": ""} for e in old_entities]

    # monitoring_points, learning, related_topics — default to empty lists
    for field in ("monitoring_points", "learning", "related_topics"):
        if field not in out:
            out[field] = []

    return out


def render_card(raw_note, card_index):
    note = normalize_note(raw_note)

    sentiment = note.get("sentiment", "neutral").lower()
    sc = SENTIMENT_COLOR.get(sentiment, "#6b7280")
    source = note.get("source_file", "")
    date = note.get("date", "")
    category = note.get("category", "Other")
    tags = note.get("tags", [])
    relevance = note.get("relevance", [])

    exec_summary = note.get("executive_summary", [])
    key_takeaways = note.get("key_takeaways", [])
    entities_impacted = note.get("entities_impacted", [])
    monitoring_points = note.get("monitoring_points", [])
    learning = note.get("learning", [])
    related_topics = note.get("related_topics", [])

    # Headline: first bullet of executive_summary
    headline = esc(exec_summary[0]) if exec_summary else esc(source)

    tag_html = "".join(badge(t, TAG_COLORS[hash(t) % len(TAG_COLORS)]) for t in tags)
    rel_html = "".join(badge(r, "#1d4ed8") for r in relevance)

    # Build search text for JS filtering
    all_text_parts = (
        [source, category, sentiment]
        + list(tags)
        + list(relevance)
        + exec_summary
        + [kt.get("takeaway", "") + " " + kt.get("analyst_lens", "") for kt in key_takeaways]
        + [ei.get("entity", "") + " " + ei.get("impact", "") for ei in entities_impacted]
        + monitoring_points
        + learning
        + related_topics
    )
    search_text = " ".join(str(x) for x in all_text_parts).lower().replace('"', "'")

    # ---- Section 1: Executive Summary ----
    exec_html = ""
    if exec_summary:
        items = "".join(
            f'<li style="margin-bottom:6px;line-height:1.6;color:#334155">{esc(b)}</li>'
            for b in exec_summary
        )
        exec_html = f"""
        <div class="section">
          <div class="section-title">Executive Summary</div>
          <ul style="padding-left:20px">{items}</ul>
        </div>"""

    # ---- Section 2: Key Takeaways & Analyst Lens ----
    kt_html = ""
    if key_takeaways:
        rows = ""
        for kt in key_takeaways:
            tw = esc(kt.get("takeaway", ""))
            al = esc(kt.get("analyst_lens", ""))
            rows += f"""<tr>
              <td style="padding:9px 12px;vertical-align:top;border-bottom:1px solid #f1f5f9;width:40%;font-weight:500;color:#0f172a;line-height:1.55">{tw}</td>
              <td style="padding:9px 12px;vertical-align:top;border-bottom:1px solid #f1f5f9;color:#334155;line-height:1.6">{al}</td>
            </tr>"""
        kt_html = f"""
        <div class="section">
          <div class="section-title">Key Takeaways &amp; Analyst Lens</div>
          <div style="overflow-x:auto">
            <table style="width:100%;border-collapse:collapse;font-size:13px">
              <thead>
                <tr style="background:#f8fafc">
                  <th style="padding:8px 12px;text-align:left;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:#64748b;border-bottom:2px solid #e2e8f0;width:40%">Key Takeaway</th>
                  <th style="padding:8px 12px;text-align:left;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:#64748b;border-bottom:2px solid #e2e8f0">Analyst Lens</th>
                </tr>
              </thead>
              <tbody>{rows}</tbody>
            </table>
          </div>
        </div>"""

    # ---- Section 3: Companies & Sectors Impacted ----
    ei_html = ""
    if entities_impacted:
        rows = ""
        for ei in entities_impacted:
            entity = esc(ei.get("entity", ""))
            impact = esc(ei.get("impact", ""))
            rows += f"""<tr>
              <td style="padding:8px 12px;vertical-align:top;border-bottom:1px solid #f1f5f9;width:35%;font-weight:500;color:#0f172a">{entity}</td>
              <td style="padding:8px 12px;vertical-align:top;border-bottom:1px solid #f1f5f9;color:#334155;line-height:1.55">{impact}</td>
            </tr>"""
        ei_html = f"""
        <div class="section">
          <div class="section-title">Companies &amp; Sectors Impacted</div>
          <div style="overflow-x:auto">
            <table style="width:100%;border-collapse:collapse;font-size:13px">
              <thead>
                <tr style="background:#f8fafc">
                  <th style="padding:8px 12px;text-align:left;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:#64748b;border-bottom:2px solid #e2e8f0;width:35%">Entity</th>
                  <th style="padding:8px 12px;text-align:left;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:#64748b;border-bottom:2px solid #e2e8f0">Impact</th>
                </tr>
              </thead>
              <tbody>{rows}</tbody>
            </table>
          </div>
        </div>"""

    # ---- Section 4: What Analysts Should Monitor ----
    mon_html = ""
    if monitoring_points:
        items = "".join(
            f'<li style="margin-bottom:6px;line-height:1.6;color:#92400e">{esc(m)}</li>'
            for m in monitoring_points
        )
        mon_html = f"""
        <div class="section">
          <div class="section-title">What Analysts Should Monitor</div>
          <ol style="padding-left:20px">{items}</ol>
        </div>"""

    # ---- Section 5: What Can I Learn? ----
    learn_html = ""
    if learning:
        items = "".join(
            f'<li style="margin-bottom:6px;line-height:1.6;color:#075985">{esc(l)}</li>'
            for l in learning
        )
        learn_html = f"""
        <div class="section">
          <div class="section-title">What Can I Learn?</div>
          <ul style="padding-left:20px">{items}</ul>
        </div>"""

    # ---- Section 6: Related Topics ----
    rt_html = ""
    if related_topics:
        chips = "".join(badge(t, "#7c3aed") for t in related_topics)
        rt_html = f"""
        <div class="section">
          <div class="section-title">Related Topics</div>
          <div>{chips}</div>
        </div>"""

    # Relevance tags footer
    rel_footer = ""
    if relevance:
        rel_footer = f'<div style="margin-top:8px"><span style="font-size:11px;font-weight:600;color:#94a3b8;text-transform:uppercase;letter-spacing:.4px">Relevance: </span>{rel_html}</div>'

    body_html = exec_html + kt_html + ei_html + mon_html + learn_html + rt_html + rel_footer

    card_id = f"card-{card_index}"

    return f"""<div class="card" data-category="{esc(category)}" data-search="{search_text}" id="{card_id}">
  <div class="card-header" onclick="toggleCard('{card_id}')">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap">
      <span class="badge-date">{esc(date)}</span>
      <span style="background:{sc}22;color:{sc};border:1px solid {sc}44;font-size:11px;font-weight:600;padding:3px 10px;border-radius:20px">{esc(sentiment)}</span>
      <span class="badge-cat">{esc(category)}</span>
      <span class="expand-icon" id="{card_id}-icon">&#9660;</span>
    </div>
    <div class="source-name">{esc(source)}</div>
    <div class="headline">{headline}</div>
    <div style="margin-top:8px">{tag_html}</div>
  </div>
  <div class="card-body" id="{card_id}-body" style="display:none">
    {body_html}
  </div>
</div>"""


def generate_html(notes):
    now = datetime.datetime.now().strftime("%d %b %Y, %H:%M")
    from collections import Counter
    cat_counts = Counter(n.get("category", "Other") for n in notes)
    cats = sorted(cat_counts.items(), key=lambda x: -x[1])

    cat_items = (
        '<li class="cat-item active" data-cat="all" onclick="filterCat(this)">'
        f'All Notes <span class="cat-count">{len(notes)}</span></li>\n'
    )
    for cat, cnt in cats:
        cat_items += (
            f'<li class="cat-item" data-cat="{esc(cat)}" onclick="filterCat(this)">'
            f'{esc(cat)} <span class="cat-count">{cnt}</span></li>\n'
        )

    cards_html = "\n".join(render_card(n, i) for i, n in enumerate(notes))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Daily Reads — Knowledge Notes</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f1f5f9;color:#1e293b;font-size:14px;line-height:1.5}}
.topbar{{background:#0f172a;color:#f8fafc;padding:14px 28px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100;box-shadow:0 2px 12px #0005}}
.topbar-brand{{display:flex;flex-direction:column}}
.topbar-brand h1{{font-size:18px;font-weight:700;letter-spacing:-.3px}}
.topbar-brand small{{color:#64748b;font-size:11px;margin-top:1px}}
#search{{background:#1e293b;border:1px solid #334155;color:#f1f5f9;padding:9px 16px;border-radius:8px;font-size:13px;width:300px;outline:none;transition:border-color .15s}}
#search::placeholder{{color:#64748b}}
#search:focus{{border-color:#3b82f6;box-shadow:0 0 0 3px #3b82f611}}
.layout{{display:flex;max-width:1180px;margin:0 auto;padding:28px 20px;gap:24px}}
.sidebar{{width:210px;flex-shrink:0}}
.sidebar-title{{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;color:#94a3b8;margin-bottom:12px;padding-left:4px}}
.cat-item{{list-style:none;padding:7px 12px;border-radius:8px;cursor:pointer;font-size:13px;display:flex;justify-content:space-between;align-items:center;color:#475569;margin-bottom:2px;transition:background .1s,color .1s}}
.cat-item:hover{{background:#e2e8f0;color:#0f172a}}
.cat-item.active{{background:#1e293b;color:#f8fafc;font-weight:600}}
.cat-count{{font-size:11px;background:#334155;color:#94a3b8;padding:1px 8px;border-radius:20px;font-weight:500}}
.cat-item.active .cat-count{{background:#3b82f6;color:#fff}}
.cards{{flex:1;min-width:0}}
.card{{background:#fff;border-radius:14px;margin-bottom:16px;box-shadow:0 1px 4px #0001,0 0 0 1px #e2e8f020;border:1px solid #e2e8f0;overflow:hidden;transition:box-shadow .2s,border-color .2s}}
.card:hover{{box-shadow:0 4px 20px #0002;border-color:#cbd5e1}}
.card-header{{padding:18px 22px 14px;cursor:pointer;user-select:none;position:relative}}
.card-header:hover{{background:#fafbfc}}
.card-body{{padding:0 22px 18px;border-top:1px solid #f1f5f9}}
.section{{margin-top:18px}}
.section-title{{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.7px;color:#94a3b8;margin-bottom:10px;padding-bottom:4px;border-bottom:1px solid #f1f5f9}}
.badge-date{{background:#f1f5f9;color:#475569;font-size:11px;font-weight:600;padding:3px 10px;border-radius:20px}}
.badge-cat{{background:#fff7ed;color:#c2410c;border:1px solid #fed7aa;font-size:11px;font-weight:600;padding:3px 10px;border-radius:20px}}
.source-name{{font-size:11px;color:#94a3b8;font-family:'SF Mono',Consolas,monospace;margin-bottom:8px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:calc(100% - 32px)}}
.headline{{font-size:15px;font-weight:600;color:#0f172a;line-height:1.5}}
.expand-icon{{position:absolute;right:18px;top:18px;font-size:12px;color:#94a3b8;transition:transform .2s}}
.expand-icon.open{{transform:rotate(180deg)}}
#no-results{{text-align:center;color:#94a3b8;padding:80px 0;font-size:15px;display:none}}
#stats-bar{{font-size:12px;color:#64748b;margin-bottom:16px;padding:0 2px}}
@media(max-width:640px){{
  .layout{{flex-direction:column;padding:16px 12px}}
  .sidebar{{width:100%}}
  #search{{width:180px}}
}}
</style>
</head>
<body>
<div class="topbar">
  <div class="topbar-brand">
    <h1>Daily Reads</h1>
    <small>Updated {now} &nbsp;&middot;&nbsp; {len(notes)} note{'s' if len(notes) != 1 else ''}</small>
  </div>
  <input id="search" type="text" placeholder="Search notes..." oninput="filterSearch(this.value)" autocomplete="off">
</div>
<div class="layout">
  <div class="sidebar">
    <div class="sidebar-title">Categories</div>
    <ul id="cat-list">{cat_items}</ul>
  </div>
  <div class="cards">
    <div id="stats-bar"></div>
    <div id="cards-container">{cards_html}</div>
    <div id="no-results">No notes match your filter.</div>
  </div>
</div>
<script>
var activecat='all', searchq='';
function toggleCard(id){{
  var body=document.getElementById(id+'-body');
  var icon=document.getElementById(id+'-icon');
  if(body.style.display==='none'){{
    body.style.display='block';
    icon.classList.add('open');
  }}else{{
    body.style.display='none';
    icon.classList.remove('open');
  }}
}}
function filterCat(el){{
  document.querySelectorAll('.cat-item').forEach(function(i){{i.classList.remove('active')}});
  el.classList.add('active');
  activecat=el.dataset.cat;
  apply();
}}
function filterSearch(q){{searchq=q.toLowerCase().trim();apply();}}
function apply(){{
  var cards=document.querySelectorAll('.card'), vis=0;
  cards.forEach(function(c){{
    var catOk=activecat==='all'||c.dataset.category===activecat;
    var searchOk=!searchq||c.dataset.search.includes(searchq);
    var show=catOk&&searchOk;
    c.style.display=show?'':'none';
    if(show)vis++;
  }});
  document.getElementById('no-results').style.display=vis?'none':'block';
  var bar=document.getElementById('stats-bar');
  if(searchq||activecat!=='all'){{
    bar.textContent='Showing '+vis+' of {len(notes)} note'+('{len(notes)}'!=='1'?'s':'');
  }}else{{
    bar.textContent='';
  }}
}}
document.getElementById('search').focus();
</script>
</body>
</html>"""


def main():
    p = argparse.ArgumentParser()
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
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Generated: {args.out}  ({len(notes)} notes)")

    if not args.no_open:
        webbrowser.open(f"file:///{args.out.replace(os.sep, '/')}")


if __name__ == "__main__":
    main()
