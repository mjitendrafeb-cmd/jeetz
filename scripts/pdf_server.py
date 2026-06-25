#!/usr/bin/env python3
"""
Flask web server: upload PDFs, download converted Markdown files.
Run: python3 scripts/pdf_server.py
Then open http://localhost:5055
"""

import os
import sys
import uuid
import tempfile
from pathlib import Path

from flask import Flask, request, send_file, jsonify, render_template_string

# Import our converter
sys.path.insert(0, str(Path(__file__).parent))
from pdf_to_markdown import pdf_to_markdown

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB limit

UPLOAD_DIR = Path(tempfile.gettempdir()) / "pdf2md_uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>PDF → Markdown Converter</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#d4d4d4;font-family:'Inter',Arial,sans-serif;color:#1a1a1a;padding:16px 0 60px;min-height:100vh}
.wrap{max-width:820px;margin:0 auto;background:#fff;box-shadow:0 4px 20px rgba(0,0,0,.2)}
.bar{background:#cc0000;height:5px}
.mast{padding:14px 24px 10px;border-bottom:3px solid #1a1a1a}
.mast p{font-size:9px;letter-spacing:2px;text-transform:uppercase;color:#999;margin-bottom:2px}
.mast h1{font-family:'Playfair Display',Georgia,serif;font-size:26px;font-weight:900;letter-spacing:-1px}
.mast h1 span{color:#cc0000}
.mast sub{font-size:11px;color:#777;font-family:'Inter',sans-serif;font-weight:400;letter-spacing:0}
nav{background:#1a1a1a;display:flex}
nav span{padding:9px 18px;font-size:10px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#fff;border-right:1px solid #333}
.body{padding:28px 28px 36px}

/* Drop zone */
.dropzone{border:2.5px dashed #ccc;border-radius:6px;padding:48px 20px;text-align:center;cursor:pointer;transition:.2s;background:#fafafa;position:relative}
.dropzone.drag{border-color:#cc0000;background:#fff5f5}
.dropzone.drag *{pointer-events:none}
.dropzone input[type=file]{position:absolute;inset:0;opacity:0;cursor:pointer;width:100%;height:100%}
.dz-icon{font-size:42px;margin-bottom:10px}
.dz-title{font-size:15px;font-weight:700;color:#333;margin-bottom:4px}
.dz-sub{font-size:12px;color:#888}
.dz-sub em{color:#cc0000;font-style:normal;font-weight:600}

/* File queue */
.queue{margin-top:20px;display:none}
.queue.visible{display:block}
.sec-head{font-size:10px;font-weight:800;letter-spacing:2px;text-transform:uppercase;color:#cc0000;border-bottom:2px solid #f0f0f0;padding-bottom:6px;margin-bottom:12px}
.file-row{display:flex;align-items:center;gap:10px;padding:10px 12px;border:1px solid #eee;border-radius:4px;margin-bottom:8px;background:#fff;transition:.2s}
.file-row.done{background:#f0fdf4;border-color:#86efac}
.file-row.error{background:#fff1f2;border-color:#fca5a5}
.file-name{flex:1;font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.file-size{font-size:11px;color:#999;white-space:nowrap}
.file-status{font-size:11px;white-space:nowrap}
.file-status.converting{color:#d97706}
.file-status.done{color:#16a34a;font-weight:700}
.file-status.error{color:#dc2626}
.dl-btn{background:#15803d;color:#fff;border:none;border-radius:3px;padding:5px 12px;font-size:11px;font-weight:700;letter-spacing:.5px;cursor:pointer;white-space:nowrap;text-decoration:none;display:none}
.dl-btn.visible{display:inline-block}
.remove-btn{background:none;border:none;color:#bbb;cursor:pointer;font-size:16px;padding:0 4px;line-height:1;flex-shrink:0}
.remove-btn:hover{color:#dc2626}

/* Convert button */
.actions{margin-top:20px;display:flex;gap:12px;align-items:center}
.convert-btn{background:#cc0000;color:#fff;border:none;border-radius:3px;padding:11px 28px;font-size:11px;font-weight:800;letter-spacing:1.5px;text-transform:uppercase;cursor:pointer;transition:.2s}
.convert-btn:hover:not(:disabled){background:#aa0000}
.convert-btn:disabled{background:#aaa;cursor:not-allowed}
.dl-all-btn{background:#1a1a1a;color:#fff;border:none;border-radius:3px;padding:11px 22px;font-size:11px;font-weight:700;letter-spacing:1px;text-transform:uppercase;cursor:pointer;transition:.2s;display:none}
.dl-all-btn.visible{display:inline-block}
.dl-all-btn:hover{background:#333}

/* Stats */
.stats{margin-top:24px;display:none;background:#f9f9f9;border:1px solid #eee;border-radius:4px;padding:14px 18px}
.stats.visible{display:block}
.stats-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:8px}
.stat-box{text-align:center}
.stat-num{font-size:22px;font-weight:800;color:#cc0000}
.stat-label{font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:#888;margin-top:2px}

/* Progress bar */
.progress{height:3px;background:#f0f0f0;border-radius:2px;margin-top:8px;overflow:hidden;display:none}
.progress.visible{display:block}
.progress-fill{height:100%;background:#cc0000;transition:width .3s;width:0%}
</style>
</head>
<body>
<div class="wrap">
  <div class="bar"></div>
  <div class="mast">
    <p>Credit Intelligence Tools</p>
    <h1>PDF <span>→</span> Markdown <sub>Token-efficient conversion for Claude Projects</sub></h1>
  </div>
  <nav>
    <span>PDF Converter</span>
  </nav>
  <div class="body">

    <div class="dropzone" id="dropzone">
      <input type="file" id="fileInput" accept=".pdf" multiple>
      <div class="dz-icon">📄</div>
      <div class="dz-title">Drop PDF files here</div>
      <div class="dz-sub">or <em>click to browse</em> — multiple files supported, up to 50 MB each</div>
    </div>

    <div class="progress" id="progress">
      <div class="progress-fill" id="progressFill"></div>
    </div>

    <div class="queue" id="queue">
      <div class="sec-head" style="margin-top:20px">Files</div>
      <div id="fileList"></div>
      <div class="actions">
        <button class="convert-btn" id="convertBtn" onclick="convertAll()">Convert to Markdown</button>
        <button class="dl-all-btn" id="dlAllBtn" onclick="downloadAll()">Download All .md</button>
      </div>
    </div>

    <div class="stats" id="stats">
      <div class="sec-head">Conversion Summary</div>
      <div class="stats-grid">
        <div class="stat-box">
          <div class="stat-num" id="statFiles">0</div>
          <div class="stat-label">Files</div>
        </div>
        <div class="stat-box">
          <div class="stat-num" id="statTokens">0</div>
          <div class="stat-label">Est. Tokens</div>
        </div>
        <div class="stat-box">
          <div class="stat-num" id="statSaved">0%</div>
          <div class="stat-label">Size Reduction</div>
        </div>
      </div>
    </div>

  </div>
</div>

<script>
const fileMap = new Map(); // name -> { file, state, mdContent, tokens, origSize }

const dropzone = document.getElementById('dropzone');
const fileInput = document.getElementById('fileInput');
const queue = document.getElementById('queue');
const fileList = document.getElementById('fileList');
const convertBtn = document.getElementById('convertBtn');
const dlAllBtn = document.getElementById('dlAllBtn');
const stats = document.getElementById('stats');
const progress = document.getElementById('progress');
const progressFill = document.getElementById('progressFill');

dropzone.addEventListener('dragover', e => { e.preventDefault(); dropzone.classList.add('drag'); });
dropzone.addEventListener('dragleave', () => dropzone.classList.remove('drag'));
dropzone.addEventListener('drop', e => {
  e.preventDefault();
  dropzone.classList.remove('drag');
  addFiles(e.dataTransfer.files);
});
fileInput.addEventListener('change', () => addFiles(fileInput.files));

function addFiles(files) {
  for (const f of files) {
    if (!f.name.endsWith('.pdf')) continue;
    if (!fileMap.has(f.name)) {
      fileMap.set(f.name, { file: f, state: 'pending', mdContent: null, tokens: 0, origSize: f.size });
    }
  }
  renderQueue();
}

function renderQueue() {
  if (fileMap.size === 0) { queue.classList.remove('visible'); return; }
  queue.classList.add('visible');
  fileList.innerHTML = '';
  for (const [name, info] of fileMap) {
    const row = document.createElement('div');
    row.className = 'file-row' + (info.state === 'done' ? ' done' : info.state === 'error' ? ' error' : '');
    row.id = 'row-' + CSS.escape(name);

    const statusText = info.state === 'pending' ? 'Pending'
      : info.state === 'converting' ? 'Converting...'
      : info.state === 'done' ? `Done — ~${info.tokens.toLocaleString()} tokens`
      : 'Error';

    const dlBtn = info.state === 'done'
      ? `<a class="dl-btn visible" href="#" onclick="downloadOne('${encodeURIComponent(name)}');return false">Download</a>`
      : `<a class="dl-btn"></a>`;

    row.innerHTML = `
      <div class="file-name" title="${name}">${name}</div>
      <div class="file-size">${(info.origSize/1024).toFixed(0)} KB</div>
      <div class="file-status ${info.state}">${statusText}</div>
      ${dlBtn}
      <button class="remove-btn" onclick="removeFile('${encodeURIComponent(name)}')" title="Remove">×</button>
    `;
    fileList.appendChild(row);
  }

  const allDone = [...fileMap.values()].every(i => i.state === 'done');
  const anyPending = [...fileMap.values()].some(i => i.state === 'pending');
  convertBtn.disabled = !anyPending;
  dlAllBtn.classList.toggle('visible', allDone && fileMap.size > 1);
}

function removeFile(encodedName) {
  fileMap.delete(decodeURIComponent(encodedName));
  renderQueue();
  updateStats();
}

async function convertAll() {
  const pending = [...fileMap.entries()].filter(([,i]) => i.state === 'pending');
  if (!pending.length) return;

  convertBtn.disabled = true;
  progress.classList.add('visible');
  let done = 0;

  for (const [name, info] of pending) {
    info.state = 'converting';
    renderQueue();

    const formData = new FormData();
    formData.append('file', info.file);

    try {
      const resp = await fetch('/convert', { method: 'POST', body: formData });
      const data = await resp.json();
      if (data.error) throw new Error(data.error);
      info.state = 'done';
      info.mdContent = data.markdown;
      info.tokens = data.tokens;
    } catch (e) {
      info.state = 'error';
    }

    done++;
    progressFill.style.width = (done / pending.length * 100) + '%';
    renderQueue();
  }

  updateStats();
  setTimeout(() => { progress.classList.remove('visible'); progressFill.style.width = '0%'; }, 800);
}

function updateStats() {
  const doneItems = [...fileMap.values()].filter(i => i.state === 'done');
  if (!doneItems.length) { stats.classList.remove('visible'); return; }

  const totalTokens = doneItems.reduce((s, i) => s + i.tokens, 0);
  const totalOrig = doneItems.reduce((s, i) => s + i.origSize, 0);
  const totalMd = doneItems.reduce((s, i) => s + (i.mdContent ? i.mdContent.length : 0), 0);
  const saved = totalOrig > 0 ? Math.round((1 - totalMd / totalOrig) * 100) : 0;

  document.getElementById('statFiles').textContent = doneItems.length;
  document.getElementById('statTokens').textContent = totalTokens > 999 ? (totalTokens/1000).toFixed(1)+'k' : totalTokens;
  document.getElementById('statSaved').textContent = saved + '%';
  stats.classList.add('visible');
}

function downloadOne(encodedName) {
  const name = decodeURIComponent(encodedName);
  const info = fileMap.get(name);
  if (!info || !info.mdContent) return;
  const blob = new Blob([info.mdContent], { type: 'text/markdown' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name.replace(/\.pdf$/i, '.md');
  a.click();
  URL.revokeObjectURL(url);
}

function downloadAll() {
  for (const [name, info] of fileMap) {
    if (info.state === 'done') {
      setTimeout(() => downloadOne(encodeURIComponent(name)), 100);
    }
  }
}
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/convert", methods=["POST"])
def convert():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    f = request.files["file"]
    if not f.filename or not f.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are accepted"}), 400

    # Save to temp file
    tmp_path = UPLOAD_DIR / f"{uuid.uuid4().hex}.pdf"
    try:
        f.save(str(tmp_path))
        markdown = pdf_to_markdown(str(tmp_path))
        tokens = len(markdown) // 4
        return jsonify({
            "markdown": markdown,
            "tokens": tokens,
            "chars": len(markdown),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5055))
    print(f"\n  PDF → Markdown Converter")
    print(f"  Open: http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
