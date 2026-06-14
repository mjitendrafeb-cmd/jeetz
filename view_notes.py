#!/usr/bin/env python3
"""
view_notes.py — Generate an HTML report of all distilled notes and open in browser.

Usage:
  python view_notes.py
  python view_notes.py --notes-dir "C:\Users\User\daily-reads\notes"
  python view_notes.py --out notes.html   # save to specific file (don't auto-open)
"""
import argparse
import json
import os
import sys
import webbrowser
import datetime

DEFAULT_NOTES_DIR = os.path.join(os.path.expanduser("~"), "daily-reads", "notes")

SENTIMENT_COLOR = {
    "positive": "#16a34a",
    "negative": "#dc2626",
    "neutral": "#6b7280",
    "mixed": "#d97706",
}

TAG_COLORS = [
    "#3b82f6", "#8b5cf6", "#ec4899", "#f97316",
    "#14b8a6", "#64748b", "#a16207", "#0891b2",
]


def load_notes(notes_dir):
    notes = []
    if not os.path.isdir(notes_dir):
        return notes
    for name in sorted(os.listdir(notes_dir), reverse=True):
        if not name.endswith("_note.json"):
            continue
        try:
            with open(os.path.join(notes_dir, name), encoding="utf-8") as f:
                n = json.load(f)
                n["_filename"] = name
                notes.append(n)
        except Exception:
            pass
    notes.sort(key=lambda n: n.get("ingested_at", ""), reverse=True)
    return notes


def tag_badge(tag, i=0):
    color = TAG_COLORS[hash(tag) % len(TAG_COLORS)]
    return f'<span class="badge" style="background:{color}22;color:{color};border:1px solid {color}44">{tag}</span>'


def render_list(items, cls=""):
    if not items:
        return ""
    lis = "".join(f"<li>{i}</li>" for i in items)
    return f'<ul class="note-list {cls}">{lis}</ul>'


def render_note(note, idx):
    sentiment = note.get("sentiment", "neutral").lower()
    sent_color = SENTIMENT_COLOR.get(sentiment, "#6b7280")
    date = note.get("date", "")
    source = note.get("source_file", "")
    summary = note.get("summary", "")
    tags = note.get("tags", [])
    relevance = note.get("relevance", [])
    entities = note.get("entities", [])

    takeaways = note.get("takeaways", [])
    risk_analysis = note.get("risk_analysis", [])
    key_implications = note.get("key_implications", [])
    data_points = note.get("key_data_points", [])

    tag_html = " ".join(tag_badge(t) for t in tags)
    rel_html = " ".join(f'<span class="rel-badge">{r}</span>' for r in relevance)
    ent_html = " ".join(f'<span class="ent-badge">{e}</span>' for e in entities)

    sections = ""

    if takeaways:
        sections += f"""
        <div class="section">
          <div class="section-title">📋 Key Takeaways</div>
          {render_list(takeaways)}
        </div>"""

    if risk_analysis:
        sections += f"""
        <div class="section">
          <div class="section-title risk-title">⚠️ Risk Analysis</div>
          {render_list(risk_analysis, "risk-list")}
        </div>"""

    if key_implications:
        sections += f"""
        <div class="section">
          <div class="section-title impl-title">💡 Analyst Implications</div>
          {render_list(key_implications, "impl-list")}
        </div>"""

    if data_points:
        dp_html = "".join(f'<span class="datapoint">{d}</span>' for d in data_points)
        sections += f"""
        <div class="section">
          <div class="section-title">📊 Key Data Points</div>
          <div class="datapoints">{dp_html}</div>
        </div>"""

    meta = ""
    if entities:
        meta += f'<div class="meta-row"><span class="meta-label">Entities</span> {ent_html}</div>'
    if relevance:
        meta += f'<div class="meta-row"><span class="meta-label">Relevance</span> {rel_html}</div>'

    return f"""
    <div class="note-card" data-search="{source} {summary} {' '.join(tags)} {' '.join(entities)} {' '.join(relevance)}">
      <div class="card-header">
        <div class="card-meta">
          <span class="date-badge">{date}</span>
          <span class="sentiment-dot" style="background:{sent_color}" title="Sentiment: {sentiment}"></span>
          <span class="sentiment-label" style="color:{sent_color}">{sentiment}</span>
        </div>
        <div class="filename">{source}</div>
        <div class="summary">{summary}</div>
        <div class="tags-row">{tag_html}</div>
      </div>
      <div class="card-body">
        {sections}
        {meta}
      </div>
    </div>"""


def generate_html(notes, notes_dir):
    now = datetime.datetime.now().strftime("%d %b %Y, %H:%M")
    count = len(notes)
    cards = "\n".join(render_note(n, i) for i, n in enumerate(notes))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Daily Reads — Knowledge Notes</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #f1f5f9; color: #1e293b; font-size: 14px; }}
  .topbar {{ background: #0f172a; color: #f8fafc; padding: 16px 24px;
             display: flex; align-items: center; justify-content: space-between;
             position: sticky; top: 0; z-index: 100; box-shadow: 0 2px 8px #0002; }}
  .topbar h1 {{ font-size: 18px; font-weight: 700; letter-spacing: -0.3px; }}
  .topbar small {{ color: #94a3b8; font-size: 12px; }}
  .search-wrap {{ display: flex; align-items: center; gap: 8px; }}
  #search {{ background: #1e293b; border: 1px solid #334155; color: #f1f5f9;
             padding: 7px 14px; border-radius: 8px; font-size: 13px; width: 260px;
             outline: none; }}
  #search::placeholder {{ color: #64748b; }}
  #search:focus {{ border-color: #3b82f6; }}
  .count-badge {{ background: #334155; color: #94a3b8; font-size: 11px;
                  padding: 3px 10px; border-radius: 20px; white-space: nowrap; }}
  .container {{ max-width: 900px; margin: 0 auto; padding: 24px 16px; }}
  .note-card {{ background: #fff; border-radius: 12px; margin-bottom: 20px;
                box-shadow: 0 1px 4px #0001; border: 1px solid #e2e8f0;
                overflow: hidden; transition: box-shadow .15s; }}
  .note-card:hover {{ box-shadow: 0 4px 16px #0002; }}
  .card-header {{ padding: 16px 20px 12px; border-bottom: 1px solid #f1f5f9; }}
  .card-meta {{ display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }}
  .date-badge {{ background: #f1f5f9; color: #475569; font-size: 11px; font-weight: 600;
                 padding: 3px 10px; border-radius: 20px; }}
  .sentiment-dot {{ width: 8px; height: 8px; border-radius: 50%; }}
  .sentiment-label {{ font-size: 11px; font-weight: 600; text-transform: uppercase;
                      letter-spacing: .4px; }}
  .filename {{ font-size: 12px; color: #94a3b8; margin-bottom: 6px;
               font-family: monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .summary {{ font-size: 14px; font-weight: 600; color: #0f172a; line-height: 1.5;
              margin-bottom: 10px; }}
  .tags-row {{ display: flex; flex-wrap: wrap; gap: 5px; }}
  .badge {{ font-size: 11px; font-weight: 500; padding: 2px 9px; border-radius: 20px; }}
  .rel-badge {{ font-size: 11px; font-weight: 500; padding: 2px 9px; border-radius: 20px;
                background: #eff6ff; color: #1d4ed8; border: 1px solid #bfdbfe; }}
  .ent-badge {{ font-size: 11px; font-weight: 500; padding: 2px 9px; border-radius: 20px;
                background: #f5f3ff; color: #6d28d9; border: 1px solid #ddd6fe; }}
  .card-body {{ padding: 0 20px 16px; }}
  .section {{ padding-top: 14px; }}
  .section-title {{ font-size: 12px; font-weight: 700; text-transform: uppercase;
                    letter-spacing: .6px; color: #64748b; margin-bottom: 6px; }}
  .risk-title {{ color: #b45309; }}
  .impl-title {{ color: #0369a1; }}
  .note-list {{ padding-left: 18px; }}
  .note-list li {{ font-size: 13px; line-height: 1.55; color: #334155;
                   margin-bottom: 5px; }}
  .risk-list li {{ color: #92400e; }}
  .impl-list li {{ color: #075985; }}
  .datapoints {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; }}
  .datapoint {{ background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0;
                font-size: 12px; font-weight: 500; padding: 3px 10px; border-radius: 6px;
                font-family: monospace; }}
  .meta-row {{ display: flex; align-items: flex-start; gap: 8px; margin-top: 10px;
               flex-wrap: wrap; }}
  .meta-label {{ font-size: 11px; font-weight: 700; color: #94a3b8; padding-top: 4px;
                 min-width: 60px; text-transform: uppercase; letter-spacing: .4px; }}
  .hidden {{ display: none !important; }}
  .no-results {{ text-align: center; color: #94a3b8; padding: 60px 0; font-size: 15px; }}
  footer {{ text-align: center; color: #94a3b8; font-size: 11px; padding: 24px 0 40px; }}
</style>
</head>
<body>
<div class="topbar">
  <div>
    <h1>📚 Daily Reads</h1>
    <small>Generated {now}</small>
  </div>
  <div class="search-wrap">
    <input id="search" type="text" placeholder="Search notes…" oninput="filterNotes(this.value)">
    <span class="count-badge" id="count-label">{count} note{'s' if count != 1 else ''}</span>
  </div>
</div>

<div class="container">
  <div id="cards">
{cards}
  </div>
  <div id="no-results" class="no-results hidden">No notes match your search.</div>
</div>
<footer>Notes saved in {notes_dir}</footer>

<script>
function filterNotes(q) {{
  q = q.toLowerCase().trim();
  var cards = document.querySelectorAll('.note-card');
  var visible = 0;
  cards.forEach(function(c) {{
    var match = !q || c.dataset.search.toLowerCase().includes(q);
    c.classList.toggle('hidden', !match);
    if (match) visible++;
  }});
  document.getElementById('no-results').classList.toggle('hidden', visible > 0);
  document.getElementById('count-label').textContent = visible + ' note' + (visible !== 1 ? 's' : '');
}}
document.getElementById('search').focus();
</script>
</body>
</html>"""


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--notes-dir", default=DEFAULT_NOTES_DIR)
    p.add_argument("--out", default=None, help="Output HTML file path (default: temp file, auto-opens)")
    args = p.parse_args()

    notes_dir = os.path.expanduser(args.notes_dir)
    notes = load_notes(notes_dir)

    if not notes:
        print(f"No notes found in: {notes_dir}")
        print("Run: python run_ingest.py --batch --watch-dir \"H:\\My Drive\\daily reads\"")
        sys.exit(0)

    html = generate_html(notes, notes_dir)

    if args.out:
        out_path = args.out
    else:
        out_path = os.path.join(os.path.expanduser("~"), "daily-reads", "notes_viewer.html")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Generated: {out_path}")
    print(f"Opening in browser...")
    webbrowser.open(f"file:///{out_path.replace(os.sep, '/')}")


if __name__ == "__main__":
    main()
