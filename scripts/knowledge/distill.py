#!/usr/bin/env python3
"""
distill.py — Extract and distill key insights from PDF or text files.

Usage:
  python distill.py <file_path> [--out-dir <dir>] [--api-key <key>]

Extracts text, sends to Claude API, and saves structured JSON with:
  - 3-5 key takeaways for a credit/financial analyst
  - Key numbers and data points
  - Relevance tags (regulatory, sector_analysis, pr_review, training, market_data, other)
  - Named entities (companies, regulators, instruments)
  - Topic tags
  - One-line summary

Required env var:
  ANTHROPIC_API_KEY  — your Anthropic API key

Output file: <out-dir>/<source_stem>_note.json
"""

import argparse
import datetime
import json
import os
import sys
import re
import io

MAX_TEXT_CHARS = 60_000  # ~15k tokens — leaves room for prompt and response


def extract_text_pdf(path: str) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            parts = []
            for page in pdf.pages:
                t = page.extract_text() or ""
                parts.append(t)
        return "\n".join(parts)
    except ImportError:
        print("[distill] pdfplumber not installed — run: pip install pdfplumber", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"[distill] PDF extraction error: {exc}", file=sys.stderr)
        sys.exit(1)


def extract_text_txt(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def extract_text(path: str) -> tuple[str, str]:
    """Return (text, file_type)."""
    lower = path.lower()
    if lower.endswith(".pdf"):
        return extract_text_pdf(path), "pdf"
    elif lower.endswith(".txt") or lower.endswith(".md"):
        return extract_text_txt(path), "txt"
    else:
        # Try as plain text
        try:
            return extract_text_txt(path), "txt"
        except Exception:
            print(f"[distill] Unsupported file type: {path}", file=sys.stderr)
            sys.exit(1)


PROMPT_TEMPLATE = """\
You are a senior credit and financial analyst. Carefully read the following document and extract structured insights.

Document:
\"\"\"
{text}
\"\"\"

Return ONLY valid JSON (no markdown fences, no preamble) matching this exact schema:

{{
  "summary": "<one sentence summarising the document's main point>",
  "takeaways": [
    "<key takeaway 1 relevant to a credit analyst>",
    "<key takeaway 2>",
    "<key takeaway 3>"
  ],
  "key_data_points": [
    "<specific number, ratio, date, or threshold mentioned in the document>",
    "<another data point>"
  ],
  "relevance": [
    "<one or more of: regulatory, sector_analysis, pr_review, training, market_data, macro, other>"
  ],
  "entities": [
    "<company name, regulator, rating agency, financial instrument, or sector mentioned>"
  ],
  "tags": [
    "<short topic keyword>"
  ]
}}

Rules:
- takeaways: 3 to 5 items; focus on credit risk, regulatory change, rating implications, or market impact
- key_data_points: extract exact figures (percentages, amounts, dates, ratios) — omit if none
- relevance: pick all that apply from the allowed values
- entities: named organisations, regulators, instruments, and sectors only
- tags: 3 to 8 short lowercase keywords (e.g. "nbfc", "liquidity", "rbi", "credit_rating")
- Return ONLY the JSON object — nothing else
"""


def call_claude(text: str, api_key: str) -> dict:
    try:
        import anthropic
    except ImportError:
        print("[distill] anthropic not installed — run: pip install anthropic", file=sys.stderr)
        sys.exit(1)

    truncated = text[:MAX_TEXT_CHARS]
    if len(text) > MAX_TEXT_CHARS:
        print(f"[distill] Text truncated from {len(text):,} to {MAX_TEXT_CHARS:,} chars")

    prompt = PROMPT_TEMPLATE.format(text=truncated)

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=2048,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[-1].text if message.content else ""

    # Strip markdown fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw.strip())

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"[distill] Claude returned invalid JSON: {exc}", file=sys.stderr)
        print(f"[distill] Raw response:\n{raw}", file=sys.stderr)
        sys.exit(1)


def build_note(source_path: str, file_type: str, claude_output: dict) -> dict:
    now = datetime.datetime.now(datetime.timezone.utc)
    return {
        "date": now.strftime("%Y-%m-%d"),
        "ingested_at": now.isoformat(),
        "source_file": os.path.basename(source_path),
        "source_path": os.path.abspath(source_path),
        "file_type": file_type,
        "summary": claude_output.get("summary", ""),
        "takeaways": claude_output.get("takeaways", []),
        "key_data_points": claude_output.get("key_data_points", []),
        "relevance": claude_output.get("relevance", []),
        "entities": claude_output.get("entities", []),
        "tags": claude_output.get("tags", []),
    }


def main():
    parser = argparse.ArgumentParser(description="Distill a PDF or text file into structured analyst notes")
    parser.add_argument("file", help="Path to the PDF or text file to distill")
    parser.add_argument("--out-dir", default=".", help="Directory to save the output JSON (default: current dir)")
    parser.add_argument("--api-key", help="Anthropic API key (overrides ANTHROPIC_API_KEY env var)")
    args = parser.parse_args()

    if not os.path.isfile(args.file):
        print(f"[distill] File not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("[distill] No API key — set ANTHROPIC_API_KEY or pass --api-key", file=sys.stderr)
        sys.exit(1)

    os.makedirs(args.out_dir, exist_ok=True)

    print(f"[distill] Extracting text from: {args.file}")
    text, file_type = extract_text(args.file)
    print(f"[distill] Extracted {len(text):,} chars ({file_type})")

    if len(text.strip()) < 50:
        print("[distill] File appears empty or unreadable", file=sys.stderr)
        sys.exit(1)

    print("[distill] Calling Claude API...")
    claude_output = call_claude(text, api_key)

    note = build_note(args.file, file_type, claude_output)

    stem = os.path.splitext(os.path.basename(args.file))[0]
    out_path = os.path.join(args.out_dir, f"{stem}_note.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(note, f, indent=2, ensure_ascii=False)

    print(f"\n[distill] Saved: {out_path}")
    print(f"\nSummary: {note['summary']}")
    print(f"\nTakeaways:")
    for i, t in enumerate(note["takeaways"], 1):
        print(f"  {i}. {t}")
    if note["key_data_points"]:
        print(f"\nKey data points:")
        for dp in note["key_data_points"]:
            print(f"  • {dp}")
    print(f"\nRelevance: {', '.join(note['relevance'])}")
    print(f"Tags: {', '.join(note['tags'])}")


if __name__ == "__main__":
    main()
