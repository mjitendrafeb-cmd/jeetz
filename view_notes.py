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


def badge(text, color):
    return f'<span style="background:{color}22;color:{color};border:1px solid {color}44;font-size:11px;font-weight:500;padding:2px 9px;border-radius:20px;display:inline-block;margin:2px 2px 2px 0">{text}</span>'


def render_card(note):
    sentiment = note.get("sentiment", "neutral").lower()
    sc = SENTIMENT_COLOR.get(sentiment, "#6b7280")
    source = note.get("source_file", "")
    date = note.get("date", "")
    category = note.get("category", "Other")
    summary = note.get("summary", "")
    tags = note.get("tags", [])
    relevance = note.get("relevance", [])
    entities = note.get("entities", [])
    takeaways = note.get("takeaways", [])
    risks = note.get("risk_analysis", [])
    implications = note.get("key_implications", [])
    data_pts = note.get("key_data_points", [])

    tag_html = "".join(badge(t, TAG_COLORS[hash(t) % len(TAG_COLORS)]) for t in tags)
    rel_html = "".join(badge(r, "#1d4ed8") for r in relevance)
    ent_html = "".join(badge(e, "#6d28d9") for e in entities)

    def section(icon, title, items, color="#334155"):
        if not items:
            return ""
        lis = "".join(f'<li style="margin-bottom:5px;line-height:1.55;color:{color}">{i}</li>' for i in items)
        return f"""<div style="margin-top:14px">
          <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:#94a3b8;margin-bottom:6px">{icon} {title}</div>
          <ul style="padding-left:18px">{lis}</ul></div>"""

    dp_html = ""
    if data_pts:
        chips = "".join(f'<span style="background:#f0fdf4;color:#166534;border:1px solid #bbf7d0;font-size:12px;font-weight:500;padding:3px 10px;border-radius:6px;font-family:monospace;display:inline-block;margin:2px">{d}</span>' for d in data_pts)
        dp_html = f"""<div style="margin-top:14px">
          <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:#94a3b8;margin-bottom:6px">📊 Key Data Points</div>
          <div>{chips}</div></div>"""

    search_text = f"{source} {summary} {category} {' '.join(tags)} {' '.join(entities)} {' '.join(relevance)}".lower()

    return f"""<div class="card" data-category="{category}" data-search="{search_text}">
  <div style="padding:16px 20px 12px;border-bottom:1px solid #f1f5f9">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
      <span style="background:#f1f5f9;color:#475569;font-size:11px;font-weight:600;padding:3px 10px;border-radius:20px">{date}</span>
      <span style="background:{sc}22;color:{sc};border:1px solid {sc}44;font-size:11px;font-weight:600;padding:3px 10px;border-radius:20px">{sentiment}</span>
      <span style="background:#fff7ed;color:#c2410c;border:1px solid #fed7aa;font-size:11px;font-weight:600;padding:3px 10px;border-radius:20px">{category}</span>
    </div>
    <div style="font-size:11px;color:#94a3b8;font-family:monospace;margin-bottom:6px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{source}</div>
    <div style="font-size:14px;font-weight:600;color:#0f172a;line-height:1.5;margin-bottom:10px">{summary}</div>
    <div>{tag_html}</div>
  </div>
  <div style="padding:0 20px 16px">
    {section("📋", "Key Takeaways", takeaways)}
    {section("⚠️", "Risk Analysis", risks, "#92400e")}
    {section("💡", "Analyst Implications", implications, "#075985")}
    {dp_html}
    {"<div style='margin-top:10px'><span style='font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.4px;color:#94a3b8'>Entities</span> " + ent_html + "</div>" if entities else ""}
    {"<div style='margin-top:6px'><span style='font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.4px;color:#94a3b8'>Relevance</span> " + rel_html + "</div>" if relevance else ""}
  </div>
</div>"""


def generate_html(notes):
    now = datetime.datetime.now().strftime("%d %b %Y, %H:%M")
    from collections import Counter
    cat_counts = Counter(n.get("category", "Other") for n in notes)
    cats = sorted(cat_counts.items(), key=lambda x: -x[1])

    cat_items = '<li class="cat-item active" data-cat="all" onclick="filterCat(this)">All Notes <span class="cat-count">' + str(len(notes)) + '</span></li>\n'
    for cat, cnt in cats:
        cat_items += f'<li class="cat-item" data-cat="{cat}" onclick="filterCat(this)">{cat} <span class="cat-count">{cnt}</span></li>\n'

    cards_html = "\n".join(render_card(n) for n in notes)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Daily Reads — Knowledge Notes</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f1f5f9;color:#1e293b;font-size:14px}}
.topbar{{background:#0f172a;color:#f8fafc;padding:14px 24px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100;box-shadow:0 2px 8px #0003}}
.topbar h1{{font-size:17px;font-weight:700}}
.topbar small{{color:#94a3b8;font-size:11px;display:block}}
#search{{background:#1e293b;border:1px solid #334155;color:#f1f5f9;padding:8px 14px;border-radius:8px;font-size:13px;width:280px;outline:none}}
#search::placeholder{{color:#64748b}}
#search:focus{{border-color:#3b82f6}}
.layout{{display:flex;max-width:1100px;margin:0 auto;padding:24px 16px;gap:20px}}
.sidebar{{width:200px;flex-shrink:0}}
.sidebar-title{{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:#94a3b8;margin-bottom:10px}}
.cat-item{{list-style:none;padding:7px 12px;border-radius:8px;cursor:pointer;font-size:13px;display:flex;justify-content:space-between;align-items:center;color:#475569;margin-bottom:3px}}
.cat-item:hover{{background:#e2e8f0}}
.cat-item.active{{background:#1e293b;color:#f8fafc;font-weight:600}}
.cat-count{{font-size:11px;background:#334155;color:#94a3b8;padding:1px 7px;border-radius:20px}}
.cat-item.active .cat-count{{background:#3b82f6;color:#fff}}
.cards{{flex:1;min-width:0}}
.card{{background:#fff;border-radius:12px;margin-bottom:18px;box-shadow:0 1px 4px #0001;border:1px solid #e2e8f0;overflow:hidden}}
.card:hover{{box-shadow:0 4px 16px #0002}}
#no-results{{text-align:center;color:#94a3b8;padding:60px 0;font-size:15px;display:none}}
@media(max-width:640px){{.layout{{flex-direction:column}}.sidebar{{width:100%}}}}
</style>
</head>
<body>
<div class="topbar">
  <div><h1>📚 Daily Reads</h1><small>Updated {now} · {len(notes)} note{'s' if len(notes)!=1 else ''}</small></div>
  <input id="search" type="text" placeholder="Search notes…" oninput="filterSearch(this.value)">
</div>
<div class="layout">
  <div class="sidebar">
    <div class="sidebar-title">Categories</div>
    <ul id="cat-list">{cat_items}</ul>
  </div>
  <div class="cards">
    <div id="cards-container">{cards_html}</div>
    <div id="no-results">No notes match your filter.</div>
  </div>
</div>
<script>
var activecat='all', searchq='';
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
