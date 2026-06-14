#!/usr/bin/env python3
"""
run_ingest.py — Drop-in runner: distils PDFs/text files in a folder, saves JSON notes.
No ChromaDB. No extra dependencies beyond: anthropic, pdfplumber, watchdog.

Usage:
  python run_ingest.py --batch --watch-dir "H:\My Drive\daily reads"
  python run_ingest.py --batch --watch --watch-dir "H:\My Drive\daily reads"
"""
import argparse
import datetime
import json
import os
import re
import sys
import time

SUPPORTED = {".pdf", ".txt", ".md"}
MAX_CHARS = 60_000
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_NOTES_DIR = os.path.join(REPO_ROOT, "docs", "notes")

PROMPT = """\
You are a senior credit and financial analyst mentoring junior analysts. Deeply analyse the document below and return ONLY valid JSON (no markdown, no preamble).

Return this exact structure:

{
  "title": "<concise human-readable title for this document, e.g. 'Motilal Oswal: Nuvama Wealth BUY — FY26-28 Outlook' or 'IMF Systemic Banking Crises Database Update 2025'>",
  "executive_summary": ["<concise bullet 1>", "..."],
  "key_takeaways": [
    {
      "takeaway": "<one clear insight — what happened, no fluff>",
      "analyst_lens": "<why it matters + risks/opportunities + rating implications + what to monitor — consolidated, no repetition>"
    }
  ],
  "entities_impacted": [
    {
      "entity": "<company, sector, regulator or country>",
      "impact": "<how they are specifically affected>"
    }
  ],
  "monitoring_points": ["<actionable monitoring point>"],
  "learning": ["<practical lesson applicable to credit/rating work>"],
  "related_topics": ["<connected concept>"],
  "category": "<one category Claude freely assigns, e.g. Banking Regulation, Credit Research, Macro & Economy, Rating Action, Sector Report, Wealth Management, Equities>",
  "sentiment": "<positive|negative|neutral|mixed>",
  "tags": ["<short lowercase keyword>"],
  "relevance": ["<one or more of: regulatory|sector_analysis|pr_review|training|market_data|macro|credit_event|other>"]
}

Rules:
- title: concise (max 80 chars), professional, human-readable. Capture the document type + key subject. No generic titles.
- executive_summary: max 5 bullets — cover "what happened" and "why it matters". Be concise.
- key_takeaways: every takeaway must answer "So what?" — give insight, not summary. If multiple takeaways point to the same risk, consolidate them. analyst_lens consolidates risks, opportunities, rating implications, monitoring points — no repetition.
- entities_impacted: name every company, sector, regulator, or country specifically affected, explain the mechanism.
- monitoring_points: 3 to 5 actionable items in the format "Monitor X at Y because Z".
- learning: 3 to 5 practical lessons directly applicable in day-to-day credit or rating work.
- related_topics: connected concepts, instruments, regulations, or frameworks (e.g. co-lending, LCR, GNPA).
- tags: 5 to 12 short lowercase keywords.
- Return ONLY the JSON object, nothing else.

Document:
\"\"\"
%s
\"\"\""""


def extract_pdf(path):
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


def extract_text(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return extract_pdf(path), "pdf"
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read(), "txt"


def call_claude(text, api_key):
    import anthropic
    truncated = text[:MAX_CHARS]
    if len(text) > MAX_CHARS:
        print(f"  [truncated {len(text):,} → {MAX_CHARS:,} chars]")
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=8192,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": PROMPT % truncated}],
    )
    # Get the text block (last content block, skipping thinking blocks)
    raw = ""
    for block in reversed(msg.content):
        if hasattr(block, "text"):
            raw = block.text.strip()
            break
    # Strip markdown fences
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    # Extract JSON object between first { and last }
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start != -1 and end > start:
        raw = raw[start:end]
    return json.loads(raw)


def note_path(notes_dir, source_path):
    stem = os.path.splitext(os.path.basename(source_path))[0]
    return os.path.join(notes_dir, f"{stem}_note.json")


def already_done(notes_dir, path):
    return os.path.isfile(note_path(notes_dir, path))


def process(path, notes_dir, api_key):
    print(f"\nProcessing: {os.path.basename(path)}")
    try:
        text, ftype = extract_text(path)
    except Exception as e:
        print(f"  Extract failed: {e}")
        return False

    if len(text.strip()) < 50:
        print("  Skipping — too little text")
        return False

    print(f"  Extracted {len(text):,} chars ({ftype}), calling Claude...")
    try:
        result = call_claude(text, api_key)
    except json.JSONDecodeError as e:
        print(f"  Claude returned bad JSON: {e}")
        return False
    except Exception as e:
        print(f"  Claude call failed: {e}")
        return False

    now = datetime.datetime.now(datetime.timezone.utc)
    note = {
        "date": now.strftime("%Y-%m-%d"),
        "ingested_at": now.isoformat(),
        "source_file": os.path.basename(path),
        "source_path": os.path.abspath(path),
        "file_type": ftype,
        **result,
    }

    os.makedirs(notes_dir, exist_ok=True)
    out = note_path(notes_dir, path)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(note, f, indent=2, ensure_ascii=False)

    print(f"  Saved: {out}")
    print(f"  Summary: {note.get('summary','')}")
    for t in note.get("takeaways", []):
        print(f"    • {t}")
    return True


def batch(watch_dir, notes_dir, api_key):
    files = [
        os.path.join(watch_dir, n)
        for n in sorted(os.listdir(watch_dir))
        if os.path.splitext(n)[1].lower() in SUPPORTED
        and os.path.isfile(os.path.join(watch_dir, n))
        and not already_done(notes_dir, os.path.join(watch_dir, n))
    ]
    if not files:
        print("No new files to process.")
        return
    print(f"Found {len(files)} file(s).")
    ok = sum(1 for p in files if process(p, notes_dir, api_key))
    print(f"\nDone: {ok}/{len(files)} processed.")


def watch(watch_dir, notes_dir, api_key):
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler

    class H(FileSystemEventHandler):
        def _handle(self, path):
            if os.path.splitext(path)[1].lower() not in SUPPORTED:
                return
            time.sleep(1)
            if not already_done(notes_dir, path):
                process(path, notes_dir, api_key)

        def on_created(self, e):
            if not e.is_directory:
                self._handle(e.src_path)

        def on_moved(self, e):
            if not e.is_directory:
                self._handle(e.dest_path)

    obs = Observer()
    obs.schedule(H(), watch_dir, recursive=False)
    obs.start()
    print(f"\nWatching: {watch_dir}  (Ctrl-C to stop)")
    try:
        while True:
            time.sleep(2)
    except KeyboardInterrupt:
        obs.stop()
    obs.join()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--watch-dir", default=os.path.join(os.path.expanduser("~"), "daily-reads"))
    p.add_argument("--notes-dir", default=DEFAULT_NOTES_DIR)
    p.add_argument("--batch", action="store_true")
    p.add_argument("--watch", action="store_true")
    p.add_argument("--api-key")
    args = p.parse_args()

    if not args.batch and not args.watch:
        p.print_help()
        sys.exit(1)

    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("Set ANTHROPIC_API_KEY or pass --api-key")
        sys.exit(1)

    watch_dir = os.path.expanduser(args.watch_dir)
    if not os.path.isdir(watch_dir):
        print(f"Watch dir not found: {watch_dir}")
        sys.exit(1)

    if args.batch:
        batch(watch_dir, args.notes_dir, api_key)
    if args.watch:
        watch(watch_dir, args.notes_dir, api_key)


if __name__ == "__main__":
    main()
