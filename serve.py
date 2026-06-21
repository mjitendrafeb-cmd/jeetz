#!/usr/bin/env python3
"""
serve.py — Local knowledge assistant. Opens a browser where you can ask
questions and get synthesised answers from all your notes via Claude.

Usage:
  python serve.py
  python serve.py --api-key YOUR_KEY --port 8080
"""
import argparse
import json
import os
import re
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
NOTES_DIR = os.path.join(REPO_ROOT, "docs", "notes")

ASK_PROMPT = """\
You are a senior credit and financial analyst mentoring a junior analyst.
The junior analyst has been reading research and has a question.
Answer using ONLY the knowledge captured in the notes below — be specific,
cite which document you are drawing from, and give a practical analyst-level answer.
If the notes don't cover the topic, say so clearly.

Format your answer with these sections (use plain text, no markdown):

ANSWER
<2-4 sentence direct answer. Cite sources inline as [1], [2] etc.>

KEY POINTS
• <specific point from notes> [N]
• <specific point from notes> [N]
• (3-5 bullets maximum)

ANALYST LENS
<1-2 sentences on risks or rating implications>

SOURCES
<[N] Document title — one line per source you cited>

Question: {question}

--- YOUR NOTES ---
{context}
--- END OF NOTES ---"""


def load_notes():
    notes = []
    if not os.path.isdir(NOTES_DIR):
        return notes
    for name in sorted(os.listdir(NOTES_DIR)):
        if name.endswith("_note.json"):
            try:
                with open(os.path.join(NOTES_DIR, name), encoding="utf-8") as f:
                    notes.append(json.load(f))
            except Exception:
                pass
    return notes


def score_note(note, query_words):
    """Simple relevance score: count query word hits across all text fields."""
    blob = " ".join([
        str(note.get("title", "")),
        str(note.get("category", "")),
        " ".join(note.get("tags", [])),
        " ".join(note.get("executive_summary", [])),
        " ".join(kt.get("takeaway", "") + " " + kt.get("analyst_lens", "")
                 for kt in note.get("key_takeaways", [])),
        " ".join(note.get("learning", [])),
        " ".join(note.get("monitoring_points", [])),
        " ".join(ei.get("entity", "") + " " + ei.get("impact", "")
                 for ei in note.get("entities_impacted", [])),
        " ".join(note.get("related_topics", [])),
    ]).lower()
    return sum(blob.count(w) for w in query_words)


def build_context(notes, question, max_notes=30, max_chars=55000):
    """Select most relevant notes and format them as compact context."""
    query_words = re.findall(r'\w+', question.lower())
    scored = sorted(notes, key=lambda n: score_note(n, query_words), reverse=True)
    selected = scored[:max_notes]

    parts = []
    total = 0
    for i, note in enumerate(selected):
        title = note.get("title") or note.get("source_file", "Unknown")
        date = note.get("date", "")
        category = note.get("category", "")
        takeaways = "\n".join(
            f"  - {kt.get('takeaway','')} | {kt.get('analyst_lens','')}"
            for kt in note.get("key_takeaways", [])
        )
        entities = "; ".join(
            f"{ei.get('entity','')}: {ei.get('impact','')}"
            for ei in note.get("entities_impacted", [])
        )
        learning = "; ".join(note.get("learning", []))

        chunk = (f"[{i+1}] {title} ({date}, {category})\n"
                 f"Key takeaways:\n{takeaways}\n"
                 f"Entities: {entities}\n"
                 f"Lessons: {learning}\n")
        if total + len(chunk) > max_chars:
            break
        parts.append(chunk)
        total += len(chunk)

    return "\n---\n".join(parts)


def call_claude(question, notes, api_key):
    import anthropic
    context = build_context(notes, question)
    if not context:
        return "No notes found. Run publish.bat first to process your documents."

    client = anthropic.Anthropic(api_key=api_key)
    prompt = ASK_PROMPT.format(question=question, context=context)
    msg = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=2048,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    )
    for block in reversed(msg.content):
        if hasattr(block, "text"):
            return block.text.strip()
    return "No response."


def make_html(notes):
    note_count = len(notes)
    # Build a compact JS array of note data for client-side card rendering
    cards_js = json.dumps([
        {
            "title": n.get("title") or os.path.splitext(n.get("source_file",""))[0].replace("_"," "),
            "category": n.get("category", "Other"),
            "sentiment": n.get("sentiment", "neutral"),
            "date": n.get("date", ""),
            "tags": n.get("tags", []),
            "source": n.get("source_file", ""),
            "preview": (n.get("key_takeaways") or [{}])[0].get("takeaway","") or
                       (n.get("executive_summary") or [""])[0],
            "takeaways": [{"tw": kt.get("takeaway",""), "al": kt.get("analyst_lens","")}
                          for kt in n.get("key_takeaways", [])],
            "entities": [{"e": ei.get("entity",""), "i": ei.get("impact","")}
                         for ei in n.get("entities_impacted", [])],
            "learning": n.get("learning", []),
            "relevance": n.get("relevance", []),
            "search": " ".join([
                n.get("title",""), n.get("category",""), n.get("sentiment",""),
                " ".join(n.get("tags",[])),
                " ".join(n.get("executive_summary",[])),
                " ".join(kt.get("takeaway","") for kt in n.get("key_takeaways",[])),
                " ".join(kt.get("analyst_lens","") for kt in n.get("key_takeaways",[])),
                " ".join(ei.get("entity","") for ei in n.get("entities_impacted",[])),
                " ".join(n.get("learning",[])),
            ]).lower(),
        }
        for n in sorted(notes, key=lambda x: x.get("ingested_at",""), reverse=True)
    ], ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Daily Reads — Knowledge Assistant</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  background:#f8fafc;color:#1e293b;font-size:14px;line-height:1.6}}
header{{background:#0f172a;color:#f8fafc;padding:16px 28px;
  display:flex;align-items:center;justify-content:space-between}}
header h1{{font-size:17px;font-weight:700}}
header small{{font-size:11px;color:#64748b;margin-top:2px;display:block}}

/* ── Ask box ── */
.ask-wrap{{background:#fff;border-bottom:1px solid #e2e8f0;padding:20px 28px}}
.ask-inner{{max-width:860px;margin:0 auto}}
.ask-label{{font-size:11px;font-weight:700;text-transform:uppercase;
  letter-spacing:.6px;color:#6366f1;margin-bottom:8px}}
.ask-row{{display:flex;gap:10px}}
#ask-input{{flex:1;border:1.5px solid #e2e8f0;border-radius:10px;
  padding:11px 16px;font-size:14px;outline:none;background:#f8fafc;color:#0f172a;
  transition:border-color .15s,box-shadow .15s}}
#ask-input:focus{{border-color:#6366f1;box-shadow:0 0 0 3px #6366f122;background:#fff}}
#ask-input::placeholder{{color:#94a3b8}}
#ask-btn{{background:#6366f1;color:#fff;border:none;border-radius:10px;
  padding:11px 22px;font-size:13px;font-weight:600;cursor:pointer;
  white-space:nowrap;transition:background .15s}}
#ask-btn:hover{{background:#4f46e5}}
#ask-btn:disabled{{background:#a5b4fc;cursor:not-allowed}}

/* ── Answer panel ── */
#answer-panel{{max-width:860px;margin:16px auto 0;display:none}}
.ans-card{{background:#f0f9ff;border:1.5px solid #bae6fd;border-radius:12px;
  padding:20px 24px}}
.ans-hd{{font-size:11px;font-weight:700;text-transform:uppercase;
  letter-spacing:.6px;color:#0284c7;margin-bottom:12px}}
#answer-text{{font-size:13px;color:#0f172a;line-height:1.8;white-space:pre-wrap}}
.ans-spinner{{color:#0284c7;font-size:13px;margin-top:4px}}

/* ── Search / filter bar ── */
.filter-bar{{max-width:1200px;margin:0 auto;padding:18px 20px 0;
  display:flex;gap:10px;flex-wrap:wrap;align-items:center}}
#search{{border:1.5px solid #e2e8f0;background:#fff;color:#0f172a;
  padding:8px 14px;border-radius:8px;font-size:13px;width:240px;outline:none;
  transition:border-color .15s}}
#search:focus{{border-color:#6366f1;box-shadow:0 0 0 3px #6366f122}}
#search::placeholder{{color:#94a3b8}}
.sf{{border:1.5px solid #e2e8f0;background:#fff;color:#64748b;
  padding:5px 12px;border-radius:20px;font-size:11px;font-weight:600;
  cursor:pointer;transition:all .15s;white-space:nowrap}}
.sf.active{{background:#6366f1;border-color:#6366f1;color:#fff}}
#sort-sel{{border:1.5px solid #e2e8f0;background:#fff;color:#475569;
  padding:7px 10px;border-radius:8px;font-size:12px;outline:none;margin-left:auto}}

/* ── Layout ── */
.layout{{display:flex;max-width:1200px;margin:0 auto;padding:20px;gap:22px}}
aside{{width:190px;flex-shrink:0;position:sticky;top:20px;
  align-self:flex-start;max-height:calc(100vh - 40px);overflow-y:auto}}
.aside-title{{font-size:10px;font-weight:700;text-transform:uppercase;
  letter-spacing:.8px;color:#94a3b8;margin-bottom:8px;padding-left:4px}}
.cat-item{{list-style:none;padding:6px 10px;border-radius:8px;cursor:pointer;
  font-size:13px;display:flex;justify-content:space-between;align-items:center;
  color:#475569;margin-bottom:2px;transition:background .1s}}
.cat-item:hover{{background:#e2e8f0}}
.cat-item.active{{background:#0f172a;color:#f8fafc;font-weight:600}}
.cnt{{font-size:11px;padding:1px 7px;border-radius:20px;background:#e2e8f0;color:#64748b}}
.cat-item.active .cnt{{background:#334155;color:#94a3b8}}
main{{flex:1;min-width:0}}
#stats-bar{{font-size:12px;color:#64748b;margin-bottom:12px;min-height:18px}}

/* ── Cards ── */
.card{{background:#fff;border-radius:12px;margin-bottom:12px;
  border:1.5px solid #e2e8f0;overflow:hidden;transition:box-shadow .2s,border-color .2s}}
.card:hover{{box-shadow:0 4px 18px #0000000f;border-color:#c7d2fe}}
.card-hd{{padding:16px 18px 12px;cursor:pointer;user-select:none}}
.card-hd:hover{{background:#fafbff}}
.card-meta{{display:flex;align-items:center;gap:6px;margin-bottom:8px;flex-wrap:wrap}}
.cat-badge{{background:#eff6ff;color:#2563eb;border:1px solid #bfdbfe;
  font-size:11px;font-weight:600;padding:2px 9px;border-radius:20px}}
.sent-pos{{background:#f0fdf4;color:#15803d;border:1px solid #bbf7d0}}
.sent-neg{{background:#fef2f2;color:#dc2626;border:1px solid #fecaca}}
.sent-neu{{background:#f9fafb;color:#6b7280;border:1px solid #e5e7eb}}
.sent-mix{{background:#fffbeb;color:#b45309;border:1px solid #fde68a}}
.sent-badge{{font-size:11px;font-weight:600;padding:2px 9px;border-radius:20px}}
.date-badge{{font-size:11px;color:#94a3b8;font-weight:500;margin-left:auto}}
.tog-ico{{color:#cbd5e1;font-size:16px;transition:transform .2s;line-height:1;margin-left:6px}}
.tog-ico.open{{transform:rotate(180deg)}}
.card-title{{font-size:15px;font-weight:700;color:#0f172a;line-height:1.4;margin-bottom:5px}}
.card-preview{{font-size:13px;color:#475569;line-height:1.6;margin-bottom:8px;max-width:80ch}}
.chip-row{{display:flex;flex-wrap:wrap;gap:4px;margin-bottom:4px}}
.chip{{font-size:11px;padding:2px 9px;border-radius:20px;
  background:#f1f5f9;color:#475569;border:1px solid #e2e8f0}}
.source-line{{font-size:11px;color:#cbd5e1;font-family:monospace;margin-top:5px;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.card-bd{{padding:0 18px 16px;border-top:1.5px solid #f1f5f9}}
.sect{{margin-top:16px}}
.sh{{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;
  color:#94a3b8;margin-bottom:7px;padding-bottom:4px;border-bottom:1px solid #f1f5f9}}
.tbl-wrap{{overflow-x:auto}}
.dt{{width:100%;border-collapse:collapse;font-size:13px}}
.dt thead th{{padding:7px 10px;text-align:left;font-size:10px;font-weight:700;
  text-transform:uppercase;letter-spacing:.4px;color:#64748b;
  background:#f8fafc;border-bottom:2px solid #e2e8f0}}
.kc{{padding:8px 10px;vertical-align:top;border-bottom:1px solid #f8fafc;
  line-height:1.6;font-size:13px;color:#334155}}
.tw{{font-weight:600;color:#0f172a;width:40%}}
.blist{{padding-left:18px}}
.blist li{{margin-bottom:5px;line-height:1.6;color:#075985;font-size:13px}}
.rel-row{{margin-top:12px;font-size:11px;color:#94a3b8;display:flex;
  align-items:center;gap:5px;flex-wrap:wrap}}
.rel-chip{{background:#f1f5f9;color:#64748b;border:1px solid #e2e8f0;
  padding:2px 7px;border-radius:10px;font-size:10px;font-weight:600}}
mark{{background:#fef9c3;color:#713f12;border-radius:2px;padding:0 1px}}
#empty{{text-align:center;padding:60px 20px;display:none;color:#94a3b8}}
.cite {{ background:#eff6ff; color:#2563eb; border-radius:3px; padding:1px 4px; font-size:11px; font-weight:700; }}
.sec-hd {{ display:block; font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:.6px; color:#6366f1; margin-top:14px; margin-bottom:4px; }}
#answer-text {{ white-space: pre-wrap; }}
@media(max-width:700px){{
  aside{{display:none}}
  .ask-wrap{{padding:14px}}
  .layout{{padding:12px}}
  #search{{width:100%}}
}}
</style>
</head>
<body>
<header>
  <div>
    <h1>Daily Reads</h1>
    <small>{note_count} note{'s' if note_count != 1 else ''} in your library</small>
  </div>
</header>

<!-- ── Ask Your Library ── -->
<div class="ask-wrap">
  <div class="ask-inner">
    <div class="ask-label">&#x2728; Ask your library</div>
    <div class="ask-row">
      <input id="ask-input" type="text" placeholder="e.g. What did I learn about liquidity risk?" autocomplete="off">
      <button id="ask-btn" onclick="askLibrary()">Ask</button>
    </div>
    <div id="answer-panel">
      <div class="ans-card">
        <div class="ans-hd">Answer from your notes</div>
        <div id="answer-text"></div>
      </div>
    </div>
  </div>
</div>

<!-- ── Filter bar ── -->
<div class="filter-bar">
  <input id="search" type="search" placeholder="Filter cards&#8230;" oninput="setQ(this.value)" autocomplete="off">
  <button class="sf active" data-sent="all" onclick="setSent(this,'all')">All</button>
  <button class="sf" data-sent="positive" onclick="setSent(this,'positive')">Positive</button>
  <button class="sf" data-sent="negative" onclick="setSent(this,'negative')">Negative</button>
  <button class="sf" data-sent="mixed" onclick="setSent(this,'mixed')">Mixed</button>
  <button class="sf" data-sent="neutral" onclick="setSent(this,'neutral')">Neutral</button>
  <select id="sort-sel" onchange="setSort(this.value)">
    <option value="newest">Newest first</option>
    <option value="oldest">Oldest first</option>
  </select>
</div>

<div class="layout">
  <aside>
    <div class="aside-title">Categories</div>
    <ul id="cat-list"></ul>
  </aside>
  <main>
    <div id="stats-bar"></div>
    <div id="cards-container"></div>
    <div id="empty">No notes match your filter.</div>
  </main>
</div>

<script>
var NOTES = {cards_js};

// ── Ask your library ──
function askLibrary() {{
  var q = document.getElementById('ask-input').value.trim();
  if (!q) return;
  var btn = document.getElementById('ask-btn');
  var panel = document.getElementById('answer-panel');
  var txt = document.getElementById('answer-text');
  btn.disabled = true;
  btn.textContent = 'Thinking…';
  panel.style.display = 'block';
  txt.textContent = 'Searching your notes and asking Claude…';
  fetch('/ask', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{question: q}})
  }})
  .then(function(r) {{ return r.json(); }})
  .then(function(d) {{
    var ans = d.answer || d.error || 'No answer.';
    // Style citation numbers [N]
    function escH(t) {{ return String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }}
    var styled = escH(ans)
        .replace(/\[(\d+)\]/g, '<span class="cite">[$1]</span>')
        .replace(/^(ANSWER|KEY POINTS|ANALYST LENS|SOURCES)$/gm, '<span class="sec-hd">$1</span>');
    txt.innerHTML = styled;
    btn.disabled = false;
    btn.textContent = 'Ask';
  }})
  .catch(function(e) {{
    txt.textContent = 'Error: ' + e.message;
    btn.disabled = false;
    btn.textContent = 'Ask';
  }});
}}
document.getElementById('ask-input').addEventListener('keydown', function(e) {{
  if (e.key === 'Enter') askLibrary();
}});

// ── Cards rendering ──
var state = {{q:'', cat:'all', sent:'all', sort:'newest'}};

function sentClass(s) {{
  return {{positive:'sent-pos',negative:'sent-neg',mixed:'sent-mix',neutral:'sent-neu'}}[s]||'sent-neu';
}}
function esc(t) {{
  return String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}}
function hlText(txt, q) {{
  if (!q) return esc(txt);
  var re = new RegExp('(' + q.replace(/[.*+?^${{}}()|[\\]\\\\]/g,'\\\\$&') + ')','gi');
  return esc(txt).replace(re,'<mark>$1</mark>');
}}

function renderCard(n, idx) {{
  var cid = 'c' + idx;
  var chips = n.tags.map(function(t) {{ return '<span class="chip">' + esc(t) + '</span>'; }}).join('');
  var q = state.q.toLowerCase().trim();

  var twRows = n.takeaways.map(function(kt) {{
    return '<tr><td class="kc tw">' + esc(kt.tw) + '</td><td class="kc">' + esc(kt.al) + '</td></tr>';
  }}).join('');
  var ktSection = twRows ? '<div class="sect"><div class="sh">Key Takeaways &amp; Analyst Lens</div>'
    + '<div class="tbl-wrap"><table class="dt"><thead><tr>'
    + '<th style="width:42%">Key Takeaway</th><th>Analyst Lens</th>'
    + '</tr></thead><tbody>' + twRows + '</tbody></table></div></div>' : '';

  var eiRows = n.entities.map(function(ei) {{
    return '<tr><td class="kc tw">' + esc(ei.e) + '</td><td class="kc">' + esc(ei.i) + '</td></tr>';
  }}).join('');
  var eiSection = eiRows ? '<div class="sect"><div class="sh">Companies &amp; Sectors Impacted</div>'
    + '<div class="tbl-wrap"><table class="dt"><thead><tr>'
    + '<th style="width:30%">Entity</th><th>Impact</th>'
    + '</tr></thead><tbody>' + eiRows + '</tbody></table></div></div>' : '';

  var learnItems = n.learning.map(function(l) {{ return '<li>' + esc(l) + '</li>'; }}).join('');
  var learnSection = learnItems ? '<div class="sect"><div class="sh">What Can I Learn?</div>'
    + '<ul class="blist">' + learnItems + '</ul></div>' : '';

  var relChips = n.relevance.map(function(r) {{ return '<span class="rel-chip">' + esc(r) + '</span>'; }}).join('');
  var relSection = relChips ? '<div class="rel-row">Relevance: ' + relChips + '</div>' : '';

  return '<article class="card" data-cat="' + esc(n.category) + '" data-sent="' + esc(n.sentiment)
    + '" data-date="' + esc(n.date) + '" data-search="' + esc(n.search) + '" id="' + cid + '">'
    + '<div class="card-hd" onclick="toggle(\'' + cid + '\')">'
    + '<div class="card-meta">'
    + '<span class="cat-badge">' + esc(n.category) + '</span>'
    + '<span class="sent-badge ' + sentClass(n.sentiment) + '">' + esc(n.sentiment) + '</span>'
    + '<span class="date-badge">' + esc(n.date) + '</span>'
    + '<span class="tog-ico" id="' + cid + '-ico">&#8964;</span>'
    + '</div>'
    + '<h2 class="card-title">' + hlText(n.title, q) + '</h2>'
    + '<p class="card-preview">' + hlText(n.preview, q) + '</p>'
    + '<div class="chip-row">' + chips + '</div>'
    + '<div class="source-line">' + esc(n.source) + '</div>'
    + '</div>'
    + '<div class="card-bd" id="' + cid + '-bd" hidden>'
    + ktSection + eiSection + learnSection + relSection
    + '</div></article>';
}}

function toggle(id) {{
  var bd = document.getElementById(id + '-bd');
  var ico = document.getElementById(id + '-ico');
  if (bd.hasAttribute('hidden')) {{ bd.removeAttribute('hidden'); ico.classList.add('open'); }}
  else {{ bd.setAttribute('hidden',''); ico.classList.remove('open'); }}
}}
window.toggle = toggle;

function apply() {{
  var q = state.q.toLowerCase().trim();
  var notes = NOTES.slice();
  if (state.sort === 'oldest') notes.sort(function(a,b){{return a.date.localeCompare(b.date)}});

  // Build category counts from all notes (unfiltered by cat)
  var catMap = {{}};
  notes.forEach(function(n) {{ catMap[n.category] = (catMap[n.category]||0)+1; }});

  var container = document.getElementById('cards-container');
  container.innerHTML = '';
  var vis = 0;
  notes.forEach(function(n, idx) {{
    var catOk = state.cat === 'all' || n.category === state.cat;
    var sentOk = state.sent === 'all' || n.sentiment === state.sent;
    var searchOk = !q || n.search.includes(q);
    if (catOk && sentOk && searchOk) {{
      container.insertAdjacentHTML('beforeend', renderCard(n, idx));
      vis++;
    }}
  }});

  // Stats
  var bar = document.getElementById('stats-bar');
  if (q || state.cat !== 'all' || state.sent !== 'all') {{
    bar.textContent = 'Showing ' + vis + ' of ' + NOTES.length + ' note' + (NOTES.length===1?'':'s');
  }} else {{
    bar.textContent = NOTES.length + ' note' + (NOTES.length===1?'':'s');
  }}
  document.getElementById('empty').style.display = vis ? 'none' : 'block';

  // Rebuild sidebar
  var catList = document.getElementById('cat-list');
  var cats = Object.keys(catMap).sort(function(a,b){{return catMap[b]-catMap[a]}});
  var html = '<li class="cat-item' + (state.cat==='all'?' active':'') + '" onclick="setCat(this,\'all\')">'
    + 'All <span class="cnt">' + NOTES.length + '</span></li>';
  cats.forEach(function(c) {{
    html += '<li class="cat-item' + (state.cat===c?' active':'') + '" onclick="setCat(this,' + JSON.stringify(c) + ')">'
      + esc(c) + ' <span class="cnt">' + catMap[c] + '</span></li>';
  }});
  catList.innerHTML = html;
}}

window.setCat = function(el, cat) {{ state.cat = cat; apply(); }};
window.setSent = function(el, sent) {{
  state.sent = sent;
  document.querySelectorAll('.sf').forEach(function(b){{b.classList.toggle('active', b.dataset.sent===sent)}});
  apply();
}};
window.setSort = function(v) {{ state.sort = v; apply(); }};
window.setQ = function(v) {{ state.q = v; apply(); }};

apply();
document.getElementById('search').focus();
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    api_key = ""
    notes = []

    def log_message(self, fmt, *args):
        pass  # silence default access log

    def do_GET(self):
        html = make_html(self.notes).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    def do_POST(self):
        if self.path != "/ask":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
            question = data.get("question", "").strip()
            if not question:
                raise ValueError("empty question")
            answer = call_claude(question, self.notes, self.api_key)
            resp = json.dumps({"answer": answer}).encode("utf-8")
        except Exception as e:
            resp = json.dumps({"error": str(e)}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)


def main():
    p = argparse.ArgumentParser(description="Local knowledge assistant server")
    p.add_argument("--api-key", help="Anthropic API key (or set ANTHROPIC_API_KEY)")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--notes-dir", default=NOTES_DIR)
    args = p.parse_args()

    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("Set ANTHROPIC_API_KEY or pass --api-key")
        sys.exit(1)

    notes = load_notes()
    if not notes:
        print(f"No notes found in {args.notes_dir}. Run publish.bat first.")
        sys.exit(1)
    print(f"Loaded {len(notes)} note(s).")

    Handler.api_key = api_key
    Handler.notes = notes

    server = HTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://localhost:{args.port}"
    print(f"Serving at {url}  (Ctrl-C to stop)")

    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
