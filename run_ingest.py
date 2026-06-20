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
  "title": "<concise human-readable title, e.g. 'Motilal Oswal: Nuvama Wealth BUY — FY26-28 Outlook' or 'Credit Intel Daily — 15 Jun 2026'>",
  "document_date": "<date printed on the document in YYYY-MM-DD format. Look for newsletter date, report date, issue date. null if not found.>",
  "freshness": "<fresh|stale|mixed>",
  "stale_items": ["<specific story that appears old or recycled>"],
  "duplicate_stories": ["<story already covered in a previously processed note — match by company, deal, or event>"],
  "data_points": [
    {
      "metric": "<specific ratio or figure name, e.g. 'deal size', 'GNPA ratio', 'NIM', 'AUM growth', 'net debt/EBITDA'>",
      "value": "<the actual number, e.g. '4000 Cr', '13.95%% YoY', '2.3x'>",
      "entity": "<company or sector this belongs to>"
    }
  ],
  "key_takeaways": [
    {
      "takeaway": "<one precise insight — lead with the credit or business implication, not the event description. Answer 'so what for credit?' not 'what happened'.>",
      "materiality": "<high|medium|low — high = could move a rating or trigger a watch; medium = flag in a credit note; low = background context>",
      "credit_signal": "<positive|negative|neutral|watch — effect on credit quality of the most affected issuer or sector>",
      "analyst_lens": "<three things in order: (1) credit implication in one sentence with a number where possible; (2) what specifically could trigger a rating action or watchlist change, or 'no near-term rating trigger'; (3) the single metric to track going forward and why.>"
    }
  ],
  "entities_impacted": [
    {
      "entity": "<company, sector, regulator or country>",
      "credit_view": "<positive|negative|neutral|watch>",
      "impact": "<specific mechanism of impact on their credit profile, funding, operations, or market position>"
    }
  ],
  "rating_trigger": "<yes|no|possible>",
  "rating_trigger_detail": "<if yes or possible: name the entity and the specific factor. Empty string otherwise.>",
  "learning": ["<sharp, non-obvious lesson for credit or rating work — something a senior analyst would tell a junior that they cannot find in a textbook. Tie it directly to what this document shows.>"],
  "category": "<Banking Regulation|Credit Research|Macro & Economy|Rating Action|Sector Report|Wealth Management|Equities|NBFC & FI|Real Estate|Infrastructure|Other>",
  "sentiment": "<positive|negative|neutral|mixed>",
  "tags": ["<short lowercase keyword>"],
  "relevance": ["<one or more of: regulatory|sector_analysis|pr_review|training|market_data|macro|credit_event|other>"]
}

Rules:
- title: max 80 chars. Capture document type and key subject. No generic titles.
- document_date: from the document itself, not today's date. null if genuinely absent.
- data_points: extract every specific number that matters — deal sizes, ratios, growth rates, yields, NPA, CAR, coverage. Skip vague descriptions. Empty array [] if no meaningful numbers.
- key_takeaways: 3 to 6 takeaways, highest materiality first. Each must answer "so what for credit?" — not just summarise the event. Consolidate takeaways pointing to the same risk.
- analyst_lens: be specific. "Leverage will increase" is bad. "Net debt/EBITDA likely rises above 3x post-acquisition, breaching typical investment-grade thresholds" is good.
- rating_trigger: say yes only if the document contains material news that genuinely warrants credit action consideration. Do not overuse.
- learning: 2 to 4 lessons, specific to this document, not generic credit advice.
- tags: 5 to 12 lowercase keywords.
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


def build_seen_context(notes_dir):
    """Build a compact summary of already-processed notes for deduplication."""
    if not os.path.isdir(notes_dir):
        return ""
    seen = []
    for name in sorted(os.listdir(notes_dir)):
        if not name.endswith("_note.json"):
            continue
        try:
            with open(os.path.join(notes_dir, name), encoding="utf-8") as f:
                n = json.load(f)
            title = n.get("title") or n.get("source_file", "")
            date = n.get("document_date") or n.get("date", "")
            entities = ", ".join(e.get("entity", "") for e in n.get("entities_impacted", []))
            tags = ", ".join(n.get("tags", []))
            seen.append(f"- [{date}] {title} | entities: {entities} | tags: {tags}")
        except Exception:
            pass
    if not seen:
        return ""
    return "\n".join(seen)


def call_claude(text, api_key, seen_context=""):
    import anthropic
    truncated = text[:MAX_CHARS]
    if len(text) > MAX_CHARS:
        print(f"  [truncated {len(text):,} → {MAX_CHARS:,} chars]")

    seen_block = ""
    if seen_context:
        seen_block = (f"\n\nALREADY PROCESSED (do not repeat these in key_takeaways — "
                      f"flag them in duplicate_stories instead):\n{seen_context}\n")

    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=8192,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": PROMPT % truncated + seen_block}],
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
    seen_context = build_seen_context(notes_dir)
    if seen_context:
        print(f"  (passing {seen_context.count(chr(10))+1} previously seen note(s) for deduplication)")
    try:
        result = call_claude(text, api_key, seen_context)
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
