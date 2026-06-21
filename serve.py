#!/usr/bin/env python3
"""
serve.py — Local knowledge assistant with upload, refresh, and Q&A.

Usage:
  python serve.py --api-key YOUR_KEY
  python serve.py --port 8080
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
NOTES_DIR = os.path.join(REPO_ROOT, "docs", "notes")

ASK_PROMPT = """\
You are a senior credit and financial analyst mentoring a junior analyst.
Answer using ONLY the knowledge captured in the notes below.
Be specific, cite sources inline as [N], and give a practical analyst-level answer.
If the notes don't cover the topic, say so clearly.

Format your answer with these exact section headers (plain text, no markdown):

ANSWER
<2-4 sentence direct answer with inline citations like [1], [2]>

KEY POINTS
• <specific point> [N]
• <specific point> [N]
(3-5 bullets)

ANALYST LENS
<1-2 sentences on risks, opportunities, or rating implications>

SOURCES
[N] Document title

Question: {question}

--- YOUR NOTES ---
{context}
--- END OF NOTES ---"""


def load_notes(notes_dir=NOTES_DIR):
    notes = []
    if not os.path.isdir(notes_dir):
        return notes
    for name in sorted(os.listdir(notes_dir)):
        if name.endswith("_note.json"):
            try:
                with open(os.path.join(notes_dir, name), encoding="utf-8") as f:
                    notes.append(json.load(f))
            except Exception:
                pass
    return notes


def score_note(note, query_words):
    blob = " ".join([
        str(note.get("title", "")),
        str(note.get("category", "")),
        " ".join(note.get("tags", [])),
        " ".join(kt.get("takeaway", "") + " " + kt.get("analyst_lens", "")
                 for kt in note.get("key_takeaways", [])),
        " ".join(note.get("learning", [])),
        " ".join(ei.get("entity", "") + " " + ei.get("impact", "")
                 for ei in note.get("entities_impacted", [])),
    ]).lower()
    return sum(blob.count(w) for w in query_words)


def build_context(notes, question, max_notes=30, max_chars=55000):
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
                 f"Takeaways:\n{takeaways}\n"
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
        return "No notes found. Upload a document first."
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
    cards_js = json.dumps([
        {
            "title": n.get("title") or os.path.splitext(n.get("source_file",""))[0].replace("_"," "),
            "category": n.get("category", "Other"),
            "source_type": n.get("source_type", "other"),
            "sentiment": n.get("sentiment", "neutral"),
            "date": n.get("date", ""),
            "doc_date": n.get("document_date", ""),
            "freshness": n.get("freshness", ""),
            "tags": n.get("tags", []),
            "source": n.get("source_file", ""),
            "has_dupes": bool(n.get("duplicate_stories", [])),
            "preview": (n.get("key_takeaways") or [{}])[0].get("takeaway","") or
                       (n.get("executive_summary") or [""])[0],
            "takeaways": [{"tw": kt.get("takeaway",""), "al": kt.get("analyst_lens",""),
                           "cs": kt.get("credit_signal","neutral")}
                          for kt in n.get("key_takeaways", [])],
            "entities": [{"e": ei.get("entity",""), "i": ei.get("impact","")}
                         for ei in n.get("entities_impacted", [])],
            "learning": n.get("learning", []),
            "search": " ".join([
                n.get("title",""), n.get("category",""), n.get("sentiment",""),
                " ".join(n.get("tags",[])),
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
  background:#f1f5f9;color:#1e293b;font-size:14px;line-height:1.6;min-height:100vh}}

/* ══ Header ══ */
header{{background:linear-gradient(135deg,#0f172a 0%,#1e3a5f 100%);
  color:#f8fafc;padding:0 28px;box-shadow:0 2px 12px #00000030}}
.hdr-inner{{display:flex;align-items:center;justify-content:space-between;
  max-width:1240px;margin:0 auto;height:64px;gap:16px}}
.brand{{display:flex;align-items:center;gap:12px}}
.brand-icon{{width:36px;height:36px;background:#6366f1;border-radius:10px;
  display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0}}
.brand-text h1{{font-size:16px;font-weight:700;letter-spacing:-.2px}}
.brand-text small{{font-size:11px;color:#94a3b8}}
.hdr-actions{{display:flex;align-items:center;gap:8px}}
.hdr-btn{{display:flex;align-items:center;gap:6px;padding:7px 14px;border-radius:8px;
  font-size:12px;font-weight:600;cursor:pointer;border:1.5px solid transparent;
  transition:all .15s;white-space:nowrap}}
.hdr-btn-ghost{{background:rgba(255,255,255,.08);color:#e2e8f0;border-color:rgba(255,255,255,.12)}}
.hdr-btn-ghost:hover{{background:rgba(255,255,255,.15);border-color:rgba(255,255,255,.2)}}
.hdr-btn-primary{{background:#6366f1;color:#fff;border-color:#6366f1}}
.hdr-btn-primary:hover{{background:#4f46e5}}
.hdr-btn:disabled{{opacity:.5;cursor:not-allowed}}
.spin{{display:inline-block;animation:spin 1s linear infinite}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}

/* ══ Ask hero ══ */
.ask-hero{{background:linear-gradient(180deg,#1e3a5f 0%,#f1f5f9 100%);
  padding:28px 28px 0}}
.ask-hero-inner{{max-width:820px;margin:0 auto}}
.ask-label{{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;
  color:#a5b4fc;margin-bottom:10px}}
.ask-box{{background:#fff;border-radius:16px;box-shadow:0 8px 32px #00000020;
  overflow:hidden;border:1.5px solid #e2e8f0}}
.ask-row{{display:flex;align-items:stretch}}
#ask-input{{flex:1;border:none;padding:16px 20px;font-size:15px;outline:none;
  color:#0f172a;background:transparent}}
#ask-input::placeholder{{color:#94a3b8}}
#ask-btn{{background:#6366f1;color:#fff;border:none;padding:0 28px;
  font-size:14px;font-weight:700;cursor:pointer;transition:background .15s;
  display:flex;align-items:center;gap:8px}}
#ask-btn:hover{{background:#4f46e5}}
#ask-btn:disabled{{background:#a5b4fc;cursor:not-allowed}}
.ask-hints{{display:flex;gap:8px;padding:10px 16px;flex-wrap:wrap;
  border-top:1px solid #f1f5f9}}
.hint{{font-size:11px;color:#94a3b8;background:#f8fafc;border:1px solid #e2e8f0;
  padding:3px 10px;border-radius:20px;cursor:pointer;transition:all .15s}}
.hint:hover{{background:#eff6ff;color:#2563eb;border-color:#bfdbfe}}

/* ══ Answer panel ══ */
.ans-wrap{{max-width:820px;margin:16px auto 0;padding-bottom:4px}}
#answer-panel{{display:none;background:#fff;border-radius:14px;
  box-shadow:0 4px 24px #00000012;border:1.5px solid #e2e8f0;overflow:hidden}}
.ans-hd{{background:#f8fafc;border-bottom:1px solid #e2e8f0;
  padding:12px 20px;display:flex;align-items:center;gap:10px}}
.ans-hd-dot{{width:8px;height:8px;background:#6366f1;border-radius:50%}}
.ans-hd-label{{font-size:11px;font-weight:700;text-transform:uppercase;
  letter-spacing:.6px;color:#6366f1}}
.ans-hd-source{{margin-left:auto;font-size:11px;color:#94a3b8}}
#answer-body{{padding:20px 24px}}
#answer-text{{font-size:13.5px;color:#0f172a;line-height:1.9;white-space:pre-wrap}}
.cite{{background:#eff6ff;color:#2563eb;border-radius:4px;padding:1px 5px;
  font-size:11px;font-weight:700;vertical-align:middle}}
.sec-hd{{display:block;font-size:10px;font-weight:700;text-transform:uppercase;
  letter-spacing:.8px;color:#6366f1;margin-top:16px;margin-bottom:6px;
  padding-bottom:4px;border-bottom:1px solid #e2e8f0}}
.ans-close{{margin-top:16px;text-align:right}}
.ans-close a{{font-size:11px;color:#94a3b8;cursor:pointer;text-decoration:none}}
.ans-close a:hover{{color:#6366f1}}

/* ══ Upload drawer ══ */
#upload-drawer{{background:#fff;border-top:1px solid #e2e8f0;
  padding:0;max-height:0;overflow:hidden;transition:max-height .3s,padding .3s}}
#upload-drawer.open{{max-height:280px;padding:20px 28px}}
.upload-inner{{max-width:820px;margin:0 auto}}
.drop-zone{{border:2px dashed #c7d2fe;border-radius:12px;padding:32px 20px;
  text-align:center;cursor:pointer;transition:all .2s;background:#fafbff;
  position:relative}}
.drop-zone.drag-over{{border-color:#6366f1;background:#eff6ff}}
.drop-zone input[type=file]{{position:absolute;inset:0;opacity:0;cursor:pointer;width:100%;height:100%}}
.drop-icon{{font-size:32px;color:#c7d2fe;margin-bottom:8px}}
.drop-text{{font-size:14px;color:#475569;font-weight:600}}
.drop-sub{{font-size:12px;color:#94a3b8;margin-top:4px}}
#upload-status{{margin-top:12px;font-size:13px;color:#475569;min-height:20px;text-align:center}}
.prog-bar{{height:4px;background:#e2e8f0;border-radius:2px;margin-top:8px;overflow:hidden;display:none}}
.prog-fill{{height:100%;background:#6366f1;border-radius:2px;width:0;transition:width .3s}}

/* ══ Filter toolbar ══ */
.toolbar{{background:#fff;border-bottom:1px solid #e2e8f0;padding:0 28px;
  position:sticky;top:0;z-index:50;box-shadow:0 1px 4px #0000000a}}
.toolbar-inner{{max-width:1240px;margin:0 auto;display:flex;align-items:center;
  gap:10px;height:52px;flex-wrap:nowrap}}
#search{{flex:1;min-width:0;max-width:280px;border:1.5px solid #e2e8f0;
  background:#f8fafc;color:#0f172a;padding:8px 14px;border-radius:8px;
  font-size:13px;outline:none;transition:border-color .15s}}
#search:focus{{border-color:#6366f1;background:#fff;box-shadow:0 0 0 3px #6366f122}}
#search::placeholder{{color:#94a3b8}}
.sf{{border:1.5px solid #e2e8f0;background:#f8fafc;color:#64748b;
  padding:5px 12px;border-radius:20px;font-size:11px;font-weight:600;
  cursor:pointer;transition:all .15s;white-space:nowrap}}
.sf:hover{{border-color:#6366f1;color:#6366f1}}
.sf.active{{background:#6366f1;border-color:#6366f1;color:#fff}}
#sort-sel{{border:1.5px solid #e2e8f0;background:#f8fafc;color:#475569;
  padding:7px 10px;border-radius:8px;font-size:12px;outline:none;
  margin-left:auto;cursor:pointer}}
#stats-bar{{font-size:12px;color:#94a3b8;white-space:nowrap}}

/* ══ Layout ══ */
.layout{{display:flex;max-width:1240px;margin:20px auto;padding:0 20px;gap:22px}}
aside{{width:196px;flex-shrink:0;position:sticky;top:72px;
  align-self:flex-start;max-height:calc(100vh - 92px);overflow-y:auto}}
.aside-sec{{background:#fff;border-radius:12px;border:1.5px solid #e2e8f0;
  padding:14px;margin-bottom:12px}}
.aside-title{{font-size:10px;font-weight:700;text-transform:uppercase;
  letter-spacing:.8px;color:#94a3b8;margin-bottom:10px}}
.cat-item{{list-style:none;padding:6px 10px;border-radius:8px;cursor:pointer;
  font-size:13px;display:flex;justify-content:space-between;align-items:center;
  color:#475569;margin-bottom:2px;transition:background .1s,color .1s}}
.cat-item:hover{{background:#f1f5f9;color:#0f172a}}
.cat-item.active{{background:#0f172a;color:#f8fafc;font-weight:600}}
.cnt{{font-size:11px;padding:1px 7px;border-radius:20px;background:#f1f5f9;color:#64748b}}
.cat-item.active .cnt{{background:#334155;color:#94a3b8}}
main{{flex:1;min-width:0}}

/* ══ Cards ══ */
.card{{background:#fff;border-radius:14px;margin-bottom:12px;
  border:1.5px solid #e2e8f0;overflow:hidden;
  transition:box-shadow .2s,transform .15s,border-color .2s;
  border-left-width:4px}}
.card:hover{{box-shadow:0 6px 24px #00000012;transform:translateY(-1px);border-color:#c7d2fe}}
.card-hd{{padding:16px 18px 12px;cursor:pointer;user-select:none}}
.card-hd:hover{{background:#fafbff}}
.card-meta{{display:flex;align-items:center;gap:6px;margin-bottom:8px;flex-wrap:wrap}}
.cat-badge{{background:#eff6ff;color:#2563eb;border:1px solid #bfdbfe;
  font-size:10px;font-weight:700;padding:2px 8px;border-radius:20px;
  text-transform:uppercase;letter-spacing:.3px}}
.stype-badge{{font-size:10px;font-weight:600;padding:2px 8px;border-radius:20px;
  border:1px solid transparent}}
.sent-badge{{font-size:10px;font-weight:700;padding:2px 8px;border-radius:20px}}
.date-badge{{font-size:11px;color:#94a3b8;margin-left:auto}}
.tog-ico{{color:#cbd5e1;font-size:15px;transition:transform .2s;margin-left:6px}}
.tog-ico.open{{transform:rotate(180deg)}}
.card-title{{font-size:16px;font-weight:700;color:#0f172a;
  line-height:1.35;margin-bottom:6px;letter-spacing:-.2px}}
.card-preview{{font-size:13px;color:#475569;line-height:1.65;
  margin-bottom:10px;max-width:90ch}}
.chip-row{{display:flex;flex-wrap:wrap;gap:4px;margin-bottom:4px}}
.chip{{font-size:11px;padding:2px 8px;border-radius:20px;background:#f1f5f9;
  color:#64748b;border:1px solid #e2e8f0}}
.source-line{{font-size:11px;color:#cbd5e1;font-family:monospace;
  margin-top:6px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.card-bd{{padding:0 18px 16px;border-top:1.5px solid #f8fafc}}
.sect{{margin-top:16px}}
.sh{{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;
  color:#94a3b8;margin-bottom:8px;padding-bottom:4px;border-bottom:1px solid #f1f5f9}}
.tbl-wrap{{overflow-x:auto}}
.dt{{width:100%;border-collapse:collapse;font-size:13px}}
.dt thead th{{padding:8px 12px;text-align:left;font-size:10px;font-weight:700;
  text-transform:uppercase;letter-spacing:.4px;color:#64748b;
  background:#f8fafc;border-bottom:2px solid #e2e8f0}}
.kc{{padding:9px 12px;vertical-align:top;border-bottom:1px solid #f8fafc;
  line-height:1.6;font-size:13px;color:#334155}}
.tw{{font-weight:600;color:#0f172a;width:42%}}
.blist{{padding-left:18px}}
.blist li{{margin-bottom:6px;line-height:1.65;color:#075985;font-size:13px}}
.rel-row{{margin-top:12px;font-size:11px;color:#94a3b8;display:flex;
  align-items:center;gap:5px;flex-wrap:wrap}}
.rel-chip{{background:#f1f5f9;color:#64748b;border:1px solid #e2e8f0;
  padding:2px 7px;border-radius:10px;font-size:10px;font-weight:600}}
mark{{background:#fef9c3;color:#713f12;border-radius:2px;padding:0 2px}}
#empty{{text-align:center;padding:60px 20px;display:none;color:#94a3b8}}
.toast{{position:fixed;bottom:24px;right:24px;background:#0f172a;color:#f8fafc;
  padding:12px 20px;border-radius:10px;font-size:13px;font-weight:600;
  box-shadow:0 4px 16px #00000030;z-index:999;opacity:0;transform:translateY(10px);
  transition:all .25s;pointer-events:none}}
.toast.show{{opacity:1;transform:translateY(0)}}
.toast.ok{{border-left:3px solid #22c55e}}
.toast.err{{border-left:3px solid #ef4444}}
@media(max-width:768px){{
  aside{{display:none}}.layout{{padding:12px}}.toolbar-inner{{flex-wrap:wrap;height:auto;padding:8px 0}}
  .sf{{display:none}}#search{{max-width:100%;width:100%}}
  .hdr-actions .hdr-btn span{{display:none}}
}}
</style>
</head>
<body>

<!-- ══ Header ══ -->
<header>
  <div class="hdr-inner">
    <div class="brand">
      <div class="brand-icon">📚</div>
      <div class="brand-text">
        <h1>Daily Reads</h1>
        <small id="note-count-hdr">{note_count} note{'s' if note_count != 1 else ''} in library</small>
      </div>
    </div>
    <div class="hdr-actions">
      <button class="hdr-btn hdr-btn-ghost" id="refresh-btn" onclick="doRefresh()">
        <span id="refresh-ico">↻</span> <span>Refresh</span>
      </button>
      <button class="hdr-btn hdr-btn-ghost" onclick="toggleUpload()">
        <span>⬆</span> <span>Upload PDF</span>
      </button>
    </div>
  </div>
</header>

<!-- ══ Ask Hero ══ -->
<div class="ask-hero">
  <div class="ask-hero-inner">
    <div class="ask-label">✦ Ask your library</div>
    <div class="ask-box">
      <div class="ask-row">
        <input id="ask-input" type="text" placeholder="What did I learn about liquidity risk? / Explain FCNR-B leverage mechanics…"
               autocomplete="off" onkeydown="if(event.key==='Enter')askLibrary()">
        <button id="ask-btn" onclick="askLibrary()">
          <span id="ask-ico">→</span> Ask
        </button>
      </div>
      <div class="ask-hints">
        <span class="hint" onclick="setQ('credit signal negative')">Credit risk notes</span>
        <span class="hint" onclick="setQ('banking regulation')">Banking regulation</span>
        <span class="hint" onclick="setQ('FCNR forex')">FCNR &amp; forex</span>
        <span class="hint" onclick="setQ('IMF systemic banking')">Banking crises</span>
      </div>
    </div>
    <div class="ans-wrap">
      <div id="answer-panel">
        <div class="ans-hd">
          <div class="ans-hd-dot"></div>
          <div class="ans-hd-label">Answer from your notes</div>
          <div class="ans-hd-source" id="ans-src"></div>
        </div>
        <div id="answer-body">
          <div id="answer-text"></div>
          <div class="ans-close"><a onclick="document.getElementById('answer-panel').style.display='none'">✕ Close</a></div>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- ══ Upload Drawer ══ -->
<div id="upload-drawer">
  <div class="upload-inner">
    <div class="drop-zone" id="drop-zone">
      <input type="file" id="file-input" accept=".pdf,.txt,.md" onchange="handleFiles(this.files)">
      <div class="drop-icon">📄</div>
      <div class="drop-text">Drop a PDF here or click to browse</div>
      <div class="drop-sub">Supports PDF, TXT, MD — will be processed by Claude automatically</div>
    </div>
    <div class="prog-bar" id="prog-bar"><div class="prog-fill" id="prog-fill"></div></div>
    <div id="upload-status"></div>
  </div>
</div>

<!-- ══ Filter Toolbar ══ -->
<div class="toolbar">
  <div class="toolbar-inner">
    <input id="search" type="search" placeholder="Filter notes…" oninput="setQf(this.value)" autocomplete="off">
    <button class="sf active" data-sent="all" onclick="setSent(this,'all')">All</button>
    <button class="sf" data-sent="positive" onclick="setSent(this,'positive')">● Positive</button>
    <button class="sf" data-sent="negative" onclick="setSent(this,'negative')">● Negative</button>
    <button class="sf" data-sent="mixed" onclick="setSent(this,'mixed')">◑ Mixed</button>
    <button class="sf" data-sent="neutral" onclick="setSent(this,'neutral')">· Neutral</button>
    <select id="sort-sel" onchange="setSort(this.value)">
      <option value="newest">Newest first</option>
      <option value="oldest">Oldest first</option>
    </select>
    <span id="stats-bar"></span>
  </div>
</div>

<!-- ══ Main layout ══ -->
<div class="layout">
  <aside>
    <div class="aside-sec">
      <div class="aside-title">Categories</div>
      <ul id="cat-list"></ul>
    </div>
  </aside>
  <main>
    <div id="cards-container"></div>
    <div id="empty">No notes match your filter.</div>
  </main>
</div>

<!-- Toast -->
<div class="toast" id="toast"></div>

<script>
var NOTES = {cards_js};
var state = {{q:'',cat:'all',sent:'all',sort:'newest'}};

// ── Hint click: sets search
function setQ(q) {{
  document.getElementById('ask-input').value = q;
  document.getElementById('ask-input').focus();
}}

// ── Ask library ──
function askLibrary() {{
  var q = document.getElementById('ask-input').value.trim();
  if (!q) return;
  var btn = document.getElementById('ask-btn');
  var ico = document.getElementById('ask-ico');
  var panel = document.getElementById('answer-panel');
  var txt = document.getElementById('answer-text');
  var src = document.getElementById('ans-src');
  btn.disabled = true; ico.textContent = '…';
  panel.style.display = 'block';
  txt.innerHTML = '<span style="color:#94a3b8">Thinking…</span>';
  src.textContent = '';
  fetch('/ask', {{method:'POST',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{question:q}})}})
  .then(function(r){{return r.json();}})
  .then(function(d){{
    var ans = d.answer || d.error || 'No answer.';
    function escH(t){{return String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}
    var styled = escH(ans)
      .replace(/\\[(\\d+)\\]/g,'<span class="cite">[$1]</span>')
      .replace(/^(ANSWER|KEY POINTS|ANALYST LENS|SOURCES)$/gm,'<span class="sec-hd">$1</span>');
    txt.innerHTML = styled;
    var srcMatch = ans.match(/SOURCES\\n([\\s\\S]+)$/);
    src.textContent = srcMatch ? (srcMatch[1].split('\\n').filter(Boolean).length + ' source(s)') : '';
    btn.disabled = false; ico.textContent = '→';
  }})
  .catch(function(e){{
    txt.textContent = 'Error: '+e.message;
    btn.disabled = false; ico.textContent = '→';
  }});
}}

// ── Refresh ──
function doRefresh() {{
  var btn = document.getElementById('refresh-btn');
  var ico = document.getElementById('refresh-ico');
  btn.disabled = true; ico.className = 'spin'; ico.textContent = '↻';
  fetch('/refresh', {{method:'POST'}})
  .then(function(r){{return r.json();}})
  .then(function(d){{
    showToast('✓ Refreshed — '+d.count+' note'+(d.count===1?'':'s')+' loaded', 'ok');
    btn.disabled = false; ico.className = ''; ico.textContent = '↻';
    if (d.notes) {{ NOTES = d.notes; apply(); }}
  }})
  .catch(function(e){{
    showToast('Refresh failed: '+e.message, 'err');
    btn.disabled = false; ico.className = ''; ico.textContent = '↻';
  }});
}}

// ── Upload ──
function toggleUpload() {{
  var drawer = document.getElementById('upload-drawer');
  drawer.classList.toggle('open');
}}
var dropZone = document.getElementById('drop-zone');
dropZone.addEventListener('dragover',function(e){{e.preventDefault();dropZone.classList.add('drag-over');}});
dropZone.addEventListener('dragleave',function(){{dropZone.classList.remove('drag-over');}});
dropZone.addEventListener('drop',function(e){{
  e.preventDefault(); dropZone.classList.remove('drag-over');
  handleFiles(e.dataTransfer.files);
}});
function handleFiles(files) {{
  if (!files || !files[0]) return;
  var file = files[0];
  var status = document.getElementById('upload-status');
  var prog = document.getElementById('prog-bar');
  var fill = document.getElementById('prog-fill');
  status.textContent = 'Uploading ' + file.name + '…';
  prog.style.display = 'block'; fill.style.width = '20%';
  var reader = new FileReader();
  reader.onload = function(e) {{
    fill.style.width = '50%';
    status.textContent = 'Processing with Claude… (may take ~30s for large PDFs)';
    fetch('/upload', {{
      method: 'POST',
      headers: {{'Content-Type':'application/octet-stream','X-Filename':encodeURIComponent(file.name)}},
      body: e.target.result
    }})
    .then(function(r){{return r.json();}})
    .then(function(d){{
      fill.style.width = '100%';
      if (d.error) {{
        status.textContent = '✗ ' + d.error;
        showToast('Upload failed: '+d.error, 'err');
      }} else {{
        status.textContent = '✓ Processed: ' + (d.title || file.name);
        showToast('✓ Note added: '+d.title, 'ok');
        if (d.notes) {{ NOTES = d.notes; apply(); }}
        document.getElementById('note-count-hdr').textContent = NOTES.length + ' note' + (NOTES.length===1?'':'s') + ' in library';
      }}
      setTimeout(function(){{prog.style.display='none';fill.style.width='0';}},2000);
    }})
    .catch(function(err){{
      status.textContent = '✗ Error: '+err.message;
      showToast('Upload error: '+err.message,'err');
      prog.style.display='none';
    }});
  }};
  reader.readAsArrayBuffer(file);
}}

// ── Toast ──
function showToast(msg, type) {{
  var t = document.getElementById('toast');
  t.textContent = msg; t.className = 'toast '+(type||'ok');
  t.classList.add('show');
  setTimeout(function(){{t.classList.remove('show');}}, 3500);
}}

// ── Cards ──
var SENT_BORDER = {{positive:'#22c55e',negative:'#ef4444',mixed:'#f59e0b',neutral:'#cbd5e1',watch:'#f59e0b'}};
var SENT_BG = {{positive:'#f0fdf4',negative:'#fef2f2',mixed:'#fffbeb',neutral:'#f9fafb'}};
var SENT_FG = {{positive:'#15803d',negative:'#dc2626',mixed:'#b45309',neutral:'#6b7280'}};
var SENT_BD = {{positive:'#bbf7d0',negative:'#fecaca',mixed:'#fde68a',neutral:'#e5e7eb'}};
var STYPE = {{broker_research:['Broker Research','#2563eb','#eff6ff','#bfdbfe'],
  regulatory:['Regulatory','#15803d','#f0fdf4','#bbf7d0'],
  academic:['Academic','#7c3aed','#faf5ff','#ddd6fe'],
  news:['News','#c2410c','#fff7ed','#fed7aa'],
  other:['Other','#64748b','#f8fafc','#e2e8f0']}};
var CS_COLOR = {{positive:'#15803d',negative:'#dc2626',neutral:'#6b7280',watch:'#d97706'}};

function esc(t){{return String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}
function hlText(txt,q){{
  if(!q)return esc(txt);
  var re=new RegExp('('+q.replace(/[.*+?^${{}}()|[\\]\\\\]/g,'\\\\$&')+')','gi');
  return esc(txt).replace(re,'<mark>$1</mark>');
}}

function renderCard(n,idx) {{
  var cid='c'+idx;
  var bord=SENT_BORDER[n.sentiment]||'#cbd5e1';
  var sbg=SENT_BG[n.sentiment]||'#f9fafb';
  var sfg=SENT_FG[n.sentiment]||'#6b7280';
  var sbd=SENT_BD[n.sentiment]||'#e5e7eb';
  var q=state.q.toLowerCase().trim();
  var st=STYPE[n.source_type]||STYPE.other;

  var chips=n.tags.map(function(t){{return '<span class="chip">'+esc(t)+'</span>';}}).join('');

  var twRows=n.takeaways.map(function(kt){{
    var csc=CS_COLOR[kt.cs]||'#6b7280';
    var csBadge=kt.cs?'<span style="font-size:10px;font-weight:700;color:'+csc+';text-transform:uppercase">&#x25CF; '+esc(kt.cs)+'</span><br>':'';
    return '<tr><td class="kc tw">'+csBadge+esc(kt.tw)+'</td><td class="kc">'+esc(kt.al)+'</td></tr>';
  }}).join('');
  var ktSection=twRows?'<div class="sect"><div class="sh">Key Takeaways &amp; Analyst Lens</div>'
    +'<div class="tbl-wrap"><table class="dt"><thead><tr>'
    +'<th style="width:44%">Takeaway</th><th>Analyst Lens</th>'
    +'</tr></thead><tbody>'+twRows+'</tbody></table></div></div>':'';

  if(n.has_dupes&&twRows){{
    ktSection='<div class="sect"><div class="sh">Key Takeaways &amp; Analyst Lens</div>'
      +'<div id="'+cid+'-dupc" style="padding:8px 0;color:#6d28d9;font-size:13px">'
      +n.takeaways.length+' takeaway(s) — overlaps with earlier notes. '
      +'<a href="#" onclick="expandDupe(\''+cid+'\');return false" style="color:#6366f1;font-size:12px;text-decoration:none">Show anyway →</a>'
      +'</div><div id="'+cid+'-dupt" hidden>'
      +'<div class="tbl-wrap"><table class="dt"><thead><tr>'
      +'<th style="width:44%">Takeaway</th><th>Analyst Lens</th>'
      +'</tr></thead><tbody>'+twRows+'</tbody></table></div></div></div>';
  }}

  var eiRows=n.entities.map(function(ei){{
    return '<tr><td class="kc tw">'+esc(ei.e)+'</td><td class="kc">'+esc(ei.i)+'</td></tr>';
  }}).join('');
  var eiSection=eiRows?'<div class="sect"><div class="sh">Companies &amp; Sectors Impacted</div>'
    +'<div class="tbl-wrap"><table class="dt"><thead><tr>'
    +'<th style="width:30%">Entity</th><th>Impact</th>'
    +'</tr></thead><tbody>'+eiRows+'</tbody></table></div></div>':'';

  var learnItems=n.learning.map(function(l){{return '<li>'+esc(l)+'</li>';}}).join('');
  var learnSection=learnItems?'<div class="sect"><div class="sh">What Can I Learn?</div><ul class="blist">'+learnItems+'</ul></div>':'';

  return '<article class="card" style="border-left-color:'+bord+'" '
    +'data-cat="'+esc(n.category)+'" data-sent="'+esc(n.sentiment)+'" '
    +'data-date="'+esc(n.date)+'" data-search="'+esc(n.search)+'" id="'+cid+'">'
    +'<div class="card-hd" onclick="toggle(\''+cid+\')">'
    +'<div class="card-meta">'
    +'<span class="stype-badge" style="color:'+st[1]+';background:'+st[2]+';border-color:'+st[3]+'">'+esc(st[0])+'</span>'
    +'<span class="cat-badge">'+esc(n.category)+'</span>'
    +'<span class="sent-badge" style="color:'+sfg+';background:'+sbg+';border:1px solid '+sbd+'">'+esc(n.sentiment)+'</span>'
    +'<span class="date-badge">'+esc(n.date)+'</span>'
    +'<span class="tog-ico" id="'+cid+'-ico">&#8964;</span>'
    +'</div>'
    +'<h2 class="card-title">'+hlText(n.title,q)+'</h2>'
    +'<p class="card-preview">'+hlText(n.preview,q)+'</p>'
    +'<div class="chip-row">'+chips+'</div>'
    +'<div class="source-line">'+esc(n.source)+(n.doc_date?' &middot; Doc: '+esc(n.doc_date):'')+'</div>'
    +'</div>'
    +'<div class="card-bd" id="'+cid+'-bd" hidden>'
    +ktSection+eiSection+learnSection
    +'</div></article>';
}}

function toggle(id) {{
  var bd=document.getElementById(id+'-bd');
  var ico=document.getElementById(id+'-ico');
  if(bd.hasAttribute('hidden')){{bd.removeAttribute('hidden');ico.classList.add('open');}}
  else{{bd.setAttribute('hidden','');ico.classList.remove('open');}}
}}
window.toggle=toggle;
function expandDupe(cid){{
  var c=document.getElementById(cid+'-dupc');var t=document.getElementById(cid+'-dupt');
  if(c)c.hidden=true;if(t)t.removeAttribute('hidden');
}}
window.expandDupe=expandDupe;

function apply() {{
  var q=state.q.toLowerCase().trim();
  var notes=NOTES.slice();
  if(state.sort==='oldest')notes.sort(function(a,b){{return a.date.localeCompare(b.date)}});

  var catMap={{}};
  notes.forEach(function(n){{catMap[n.category]=(catMap[n.category]||0)+1;}});

  var container=document.getElementById('cards-container');
  container.innerHTML='';
  var vis=0;
  notes.forEach(function(n,idx){{
    var catOk=state.cat==='all'||n.category===state.cat;
    var sentOk=state.sent==='all'||n.sentiment===state.sent;
    var searchOk=!q||n.search.includes(q);
    if(catOk&&sentOk&&searchOk){{
      container.insertAdjacentHTML('beforeend',renderCard(n,idx));
      vis++;
    }}
  }});

  var bar=document.getElementById('stats-bar');
  var filtered=q||state.cat!=='all'||state.sent!=='all';
  bar.textContent=filtered?('Showing '+vis+' of '+NOTES.length):(NOTES.length+' note'+(NOTES.length===1?'':'s'));

  document.getElementById('empty').style.display=vis?'none':'block';

  var catList=document.getElementById('cat-list');
  var cats=Object.keys(catMap).sort(function(a,b){{return catMap[b]-catMap[a]}});
  var html='<li class="cat-item'+(state.cat==='all'?' active':'')+'" onclick="setCat(this,\'all\')">'
    +'All <span class="cnt">'+NOTES.length+'</span></li>';
  cats.forEach(function(c){{
    html+='<li class="cat-item'+(state.cat===c?' active':'')+'" onclick="setCat(this,'+JSON.stringify(c)+')">'
      +esc(c)+' <span class="cnt">'+catMap[c]+'</span></li>';
  }});
  catList.innerHTML=html;
}}

window.setCat=function(el,cat){{state.cat=cat;apply();}};
window.setSent=function(el,sent){{
  state.sent=sent;
  document.querySelectorAll('.sf').forEach(function(b){{b.classList.toggle('active',b.dataset.sent===sent)}});
  apply();
}};
window.setSort=function(v){{state.sort=v;apply();}};
window.setQf=function(v){{state.q=v;apply();}};
apply();
document.getElementById('search').focus();
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    api_key = ""
    notes = []
    notes_dir = NOTES_DIR

    def log_message(self, fmt, *args):
        pass

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        html = make_html(self.notes).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        if self.path == "/ask":
            try:
                data = json.loads(body)
                question = data.get("question", "").strip()
                if not question:
                    raise ValueError("empty question")
                answer = call_claude(question, self.notes, self.api_key)
                self.send_json({"answer": answer})
            except Exception as e:
                self.send_json({"error": str(e)})

        elif self.path == "/refresh":
            try:
                # Reload notes from disk
                Handler.notes = load_notes(self.notes_dir)
                # Regenerate index.html
                subprocess.run(
                    [sys.executable, os.path.join(REPO_ROOT, "view_notes.py"), "--no-open"],
                    cwd=REPO_ROOT, capture_output=True
                )
                # Build fresh card data for the client
                import re as _re
                cards = [
                    {
                        "title": n.get("title") or os.path.splitext(n.get("source_file",""))[0].replace("_"," "),
                        "category": n.get("category","Other"), "source_type": n.get("source_type","other"),
                        "sentiment": n.get("sentiment","neutral"), "date": n.get("date",""),
                        "doc_date": n.get("document_date",""), "freshness": n.get("freshness",""),
                        "tags": n.get("tags",[]), "source": n.get("source_file",""),
                        "has_dupes": bool(n.get("duplicate_stories",[])),
                        "preview": (n.get("key_takeaways") or [{}])[0].get("takeaway",""),
                        "takeaways": [{"tw": kt.get("takeaway",""), "al": kt.get("analyst_lens",""),
                                       "cs": kt.get("credit_signal","neutral")}
                                      for kt in n.get("key_takeaways",[])],
                        "entities": [{"e": ei.get("entity",""), "i": ei.get("impact","")}
                                     for ei in n.get("entities_impacted",[])],
                        "learning": n.get("learning",[]),
                        "search": " ".join([n.get("title",""), n.get("category",""),
                                            " ".join(n.get("tags",[])),
                                            " ".join(kt.get("takeaway","") for kt in n.get("key_takeaways",[])),
                                            " ".join(ei.get("entity","") for ei in n.get("entities_impacted",[]))]).lower(),
                    }
                    for n in sorted(Handler.notes, key=lambda x: x.get("ingested_at",""), reverse=True)
                ]
                self.send_json({"count": len(Handler.notes), "notes": cards})
            except Exception as e:
                self.send_json({"error": str(e)})

        elif self.path == "/upload":
            try:
                filename = urllib.parse.unquote(self.headers.get("X-Filename", "upload.pdf"))
                ext = os.path.splitext(filename)[1].lower()
                if ext not in {".pdf", ".txt", ".md"}:
                    self.send_json({"error": f"Unsupported type: {ext}"})
                    return

                # Save to temp file
                with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                    tmp.write(body)
                    tmp_path = tmp.name

                # Rename so note stem matches original filename
                dest = os.path.join(tempfile.gettempdir(), filename)
                os.replace(tmp_path, dest)

                # Process with run_ingest.process()
                sys.path.insert(0, REPO_ROOT)
                from run_ingest import process
                ok = process(dest, self.notes_dir, self.api_key)
                os.unlink(dest)

                if not ok:
                    self.send_json({"error": "Processing failed — check server logs."})
                    return

                # Reload and regenerate
                Handler.notes = load_notes(self.notes_dir)
                subprocess.run(
                    [sys.executable, os.path.join(REPO_ROOT, "view_notes.py"), "--no-open"],
                    cwd=REPO_ROOT, capture_output=True
                )

                # Find the new note to get its title
                stem = os.path.splitext(filename)[0]
                note_file = os.path.join(self.notes_dir, f"{stem}_note.json")
                title = filename
                if os.path.isfile(note_file):
                    with open(note_file, encoding="utf-8") as f:
                        ndata = json.load(f)
                    title = ndata.get("title", filename)

                cards = [
                    {
                        "title": n.get("title") or os.path.splitext(n.get("source_file",""))[0].replace("_"," "),
                        "category": n.get("category","Other"), "source_type": n.get("source_type","other"),
                        "sentiment": n.get("sentiment","neutral"), "date": n.get("date",""),
                        "doc_date": n.get("document_date",""), "freshness": n.get("freshness",""),
                        "tags": n.get("tags",[]), "source": n.get("source_file",""),
                        "has_dupes": bool(n.get("duplicate_stories",[])),
                        "preview": (n.get("key_takeaways") or [{}])[0].get("takeaway",""),
                        "takeaways": [{"tw": kt.get("takeaway",""), "al": kt.get("analyst_lens",""),
                                       "cs": kt.get("credit_signal","neutral")}
                                      for kt in n.get("key_takeaways",[])],
                        "entities": [{"e": ei.get("entity",""), "i": ei.get("impact","")}
                                     for ei in n.get("entities_impacted",[])],
                        "learning": n.get("learning",[]),
                        "search": " ".join([n.get("title",""), n.get("category",""),
                                            " ".join(n.get("tags",[])),
                                            " ".join(kt.get("takeaway","") for kt in n.get("key_takeaways",[])),
                                            " ".join(ei.get("entity","") for ei in n.get("entities_impacted",[]))]).lower(),
                    }
                    for n in sorted(Handler.notes, key=lambda x: x.get("ingested_at",""), reverse=True)
                ]
                self.send_json({"title": title, "count": len(Handler.notes), "notes": cards})

            except Exception as e:
                self.send_json({"error": str(e)})

        else:
            self.send_response(404)
            self.end_headers()


def main():
    p = argparse.ArgumentParser(description="Local knowledge assistant")
    p.add_argument("--api-key", help="Anthropic API key (or set ANTHROPIC_API_KEY)")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--notes-dir", default=NOTES_DIR)
    args = p.parse_args()

    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("Set ANTHROPIC_API_KEY or pass --api-key")
        sys.exit(1)

    notes = load_notes(args.notes_dir)
    if not notes:
        print(f"No notes found in {args.notes_dir}. Process some documents first.")
        sys.exit(1)
    print(f"Loaded {len(notes)} note(s).")

    Handler.api_key = api_key
    Handler.notes = notes
    Handler.notes_dir = args.notes_dir

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
