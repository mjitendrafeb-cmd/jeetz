#!/usr/bin/env python3
"""
run_ingest.py — Drop-in runner: distils PDFs/text files in a folder, saves JSON notes.
No ChromaDB. No extra dependencies beyond: anthropic, pdfplumber, watchdog.

Usage:
  python run_ingest.py --batch --watch-dir "H:\My Drive\daily reads"
  python run_ingest.py --batch --watch --watch-dir "H:\My Drive\daily reads"
"""
import argparse
import base64
import datetime
import json
import os
import re
import sys
import time

SUPPORTED = {".pdf", ".txt", ".md", ".html", ".htm"}
MAX_CHARS = 150_000
PDF_MAX_BYTES = 30 * 1024 * 1024  # above this, fall back to text extraction
SEEN_DAYS = 60    # dedup context: only look back this far
SEEN_MAX = 40     # dedup context: at most this many recent notes
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_NOTES_DIR = os.path.join(REPO_ROOT, "docs", "notes")

PROMPT = """\
You are a senior credit and financial analyst mentoring junior analysts. Deeply analyse the document below and return ONLY valid JSON (no markdown, no preamble).

Return this exact structure:

{
  "title": "<concise human-readable title, e.g. 'Motilal Oswal: Nuvama Wealth BUY — FY26-28 Outlook' or 'Credit Intel Daily — 15 Jun 2026'>",
  "document_date": "<date printed on the document in YYYY-MM-DD format. Look for newsletter date, report date, issue date. null if not found.>",
  "source_type": "<broker_research|regulatory|academic|news|other>",
  "freshness": "<fresh|stale|mixed>",
  "stale_items": ["<specific story that appears old or recycled>"],
  "duplicate_stories": ["<story already covered in a previously processed note — match by company, deal, or event>"],
  "executive_summary": ["<4 to 8 crisp bullets that together form the CRUX of the ENTIRE document — a reader should get 80% of the document's value from these alone. Cover every major section and theme, include the key numbers. This is the substitute for reading the full report.>"],
  "key_takeaways": [
    {
      "takeaway": "<one precise insight — lead with the credit or business implication, not the event description. Answer 'so what for credit?' not 'what happened'.>",
      "credit_signal": "<positive|negative|neutral|watch — effect on credit quality of the most affected issuer or sector>",
      "analyst_lens": "<why it matters for credit + risks/opportunities + what single metric to track going forward. Be specific, name numbers where possible.>"
    }
  ],
  "entities_impacted": [
    {
      "entity": "<name as written in the document>",
      "canonical": "<short canonical name, used consistently across all documents, e.g. 'RBI' not 'Reserve Bank of India (RBI)', 'HDFC Bank' not 'HDFC Bank Ltd.', 'L&T' not 'Larsen & Toubro'>",
      "type": "<company|sector|regulator|macro>",
      "impact": "<specific mechanism of impact on their credit profile, funding, operations, or market position>"
    }
  ],
  "learning": ["<sharp, non-obvious lesson for credit or rating work — something a senior analyst would tell a junior that they cannot find in a textbook. Tie it directly to what this document shows.>"],
  "category": "<Banking Regulation|Credit Research|Macro & Economy|Rating Action|Sector Report|Wealth Management|Equities|NBFC & FI|Real Estate|Infrastructure|Other>",
  "sentiment": "<positive|negative|neutral|mixed>",
  "tags": ["<short lowercase keyword>"],
  "relevance": ["<one or more of: regulatory|sector_analysis|pr_review|training|market_data|macro|credit_event|other>"]
}

Rules:
- title: max 80 chars. Capture document type and key subject. No generic titles.
- document_date: from the document itself, not today's date. null if genuinely absent.
- source_type: classify the document publisher — broker_research (sell-side bank/broker equity or credit analysis), regulatory (RBI/SEBI/IRDAI/MoF circular or notification), academic (working paper, research paper), news (newsletter, news article), other.
- executive_summary: this is the crux. Walk through the document section by section — no major section, entity, data table, chart or exhibit may go unrepresented. Name specific numbers, dates and companies.
- key_takeaways: 3 to 10 takeaways — scale with the document's density. A multi-sector conference note or long report warrants 8-10; a short newsletter 3-4. NEVER drop a material credit-relevant point to stay within a count. Each must answer "so what for credit?" — not just summarise the event. Consolidate takeaways pointing to the same risk.
- Coverage check: before finalising, re-scan the document and verify nothing material is missing from executive_summary + key_takeaways combined.
- credit_signal: from the perspective of the most affected issuer or sector.
- analyst_lens: be specific. "Leverage will increase" is bad. "Net debt/EBITDA likely rises above 3x post-acquisition, breaching typical investment-grade thresholds" is good. Always name a metric to track.
- learning: 2 to 4 lessons, specific to this document, not generic credit advice.
- canonical: the same real-world entity must always get the same canonical name — use the most common short market name. type=sector for industries ('Indian Banking Sector' → canonical 'Banking Sector'), type=macro for economy-wide themes (rates, inflation, currency, fiscal policy), type=regulator for RBI/SEBI/IRDAI/ministries.
- tags: 5 to 12 lowercase keywords.
- Return ONLY the JSON object, nothing else."""


def extract_pdf(path):
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


def extract_html(path):
    from html.parser import HTMLParser

    class _Strip(HTMLParser):
        def __init__(self):
            super().__init__()
            self._parts = []
            self._skip = False

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style"):
                self._skip = True
            if tag in ("p", "br", "div", "h1", "h2", "h3", "h4", "h5", "li", "tr"):
                self._parts.append("\n")

        def handle_endtag(self, tag):
            if tag in ("script", "style"):
                self._skip = False

        def handle_data(self, data):
            if not self._skip:
                self._parts.append(data)

        def text(self):
            raw = "".join(self._parts)
            return re.sub(r"\n{3,}", "\n\n", raw).strip()

    with open(path, encoding="utf-8", errors="replace") as f:
        content = f.read()
    p = _Strip()
    p.feed(content)
    return p.text()


def extract_text(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return extract_pdf(path), "pdf"
    if ext in (".html", ".htm"):
        return extract_html(path), "html"
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read(), "txt"


def build_seen_context(notes_dir):
    """Compact summary of recently processed notes for deduplication.

    Capped to the last SEEN_DAYS days and SEEN_MAX notes so the prompt
    stays small as the library grows — dedup only matters for recent stories.
    """
    if not os.path.isdir(notes_dir):
        return ""
    cutoff = (datetime.date.today() - datetime.timedelta(days=SEEN_DAYS)).isoformat()
    seen = []
    for name in sorted(os.listdir(notes_dir)):
        if not name.endswith("_note.json"):
            continue
        try:
            with open(os.path.join(notes_dir, name), encoding="utf-8") as f:
                n = json.load(f)
            date = n.get("document_date") or n.get("date", "")
            if date and date < cutoff:
                continue
            title = n.get("title") or n.get("source_file", "")
            entities = ", ".join(e.get("canonical") or e.get("entity", "")
                                 for e in n.get("entities_impacted", []))
            tags = ", ".join(n.get("tags", []))
            seen.append((date, f"- [{date}] {title} | entities: {entities} | tags: {tags}"))
        except Exception:
            pass
    if not seen:
        return ""
    seen.sort(key=lambda x: x[0])
    return "\n".join(line for _, line in seen[-SEEN_MAX:])


def call_claude(path, api_key, seen_context=""):
    """Distil one document. PDFs are sent natively (tables/charts included);
    HTML/text files are sent as extracted text. Returns (result_dict, ftype)."""
    import anthropic

    seen_block = ""
    if seen_context:
        seen_block = (f"\n\nALREADY PROCESSED (do not repeat these in key_takeaways — "
                      f"flag them in duplicate_stories instead):\n{seen_context}\n")

    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf" and os.path.getsize(path) <= PDF_MAX_BYTES:
        with open(path, "rb") as f:
            pdf_b64 = base64.standard_b64encode(f.read()).decode("ascii")
        content = [
            {"type": "document",
             "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_b64}},
            {"type": "text",
             "text": PROMPT + seen_block +
                     "\n\nAnalyse the attached PDF document, including its tables, charts and exhibits."},
        ]
        ftype = "pdf"
        print("  Sending PDF natively to Claude (tables/charts included)...")
    else:
        text, ftype = extract_text(path)
        if len(text.strip()) < 50:
            raise ValueError("too little text extracted")
        truncated = text[:MAX_CHARS]
        if len(text) > MAX_CHARS:
            print(f"  [truncated {len(text):,} → {MAX_CHARS:,} chars]")
        content = (PROMPT + seen_block +
                   '\n\nDocument:\n"""\n' + truncated + '\n"""')
        print(f"  Extracted {len(text):,} chars ({ftype}), calling Claude...")

    client = anthropic.Anthropic(api_key=api_key)
    with client.messages.stream(
        model="claude-opus-4-8",
        max_tokens=16384,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": content}],
    ) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason == "max_tokens":
        print("  Claude hit the output token limit — response was truncated, retrying is unlikely to help without raising max_tokens further")
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
    return json.loads(raw), ftype


def note_path(notes_dir, source_path):
    stem = os.path.splitext(os.path.basename(source_path))[0]
    return os.path.join(notes_dir, f"{stem}_note.json")


def already_done(notes_dir, path):
    return os.path.isfile(note_path(notes_dir, path))


def process(path, notes_dir, api_key):
    print(f"\nProcessing: {os.path.basename(path)}")
    seen_context = build_seen_context(notes_dir)
    if seen_context:
        print(f"  (passing {seen_context.count(chr(10))+1} recent note(s) for deduplication)")
    try:
        result, ftype = call_claude(path, api_key, seen_context)
    except json.JSONDecodeError as e:
        print(f"  Claude returned bad JSON: {e}")
        return False
    except ValueError as e:
        print(f"  Skipping — {e}")
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
    print(f"  Title: {note.get('title','')}")
    print(f"  {len(note.get('key_takeaways', []))} takeaway(s), "
          f"{len(note.get('entities_impacted', []))} entity(ies)")
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
