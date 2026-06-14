#!/usr/bin/env python3
"""
search.py — Query your distilled knowledge notes (reads JSON files directly).

Usage:
  python search.py "NBFC liquidity crisis"          # keyword search
  python search.py "RBI regulation" --date 2026-06-14
  python search.py --date 2026-06-14                # all notes from a date
  python search.py --tag regulatory                 # filter by tag/relevance
  python search.py --list                           # list all notes (newest first)
  python search.py --top 20 "banking"               # more results

Optional env var:
  KNOWLEDGE_NOTES_DIR   override notes directory (default: ~/daily-reads/notes)
"""

import argparse
import json
import os
import re
import sys

DEFAULT_NOTES_DIR = os.path.expanduser("~/daily-reads/notes")


def load_notes(notes_dir: str) -> list[dict]:
    notes = []
    if not os.path.isdir(notes_dir):
        return notes
    for name in os.listdir(notes_dir):
        if not name.endswith("_note.json"):
            continue
        try:
            with open(os.path.join(notes_dir, name), encoding="utf-8") as f:
                notes.append(json.load(f))
        except Exception:
            pass
    notes.sort(key=lambda n: n.get("ingested_at", ""), reverse=True)
    return notes


def _matches_query(note: dict, query: str) -> bool:
    text = " ".join([
        note.get("summary", ""),
        " ".join(note.get("takeaways", [])),
        " ".join(note.get("key_data_points", [])),
        " ".join(note.get("tags", [])),
        " ".join(note.get("entities", [])),
        note.get("source_file", ""),
    ]).lower()
    return all(word.lower() in text for word in query.split())


def search_notes(
    notes: list[dict],
    query: str | None = None,
    date: str | None = None,
    tag: str | None = None,
    n: int = 10,
) -> list[dict]:
    results = notes
    if date:
        results = [r for r in results if r.get("date") == date]
    if tag:
        results = [
            r for r in results
            if tag.lower() in ",".join(r.get("tags", [])).lower()
            or tag.lower() in ",".join(r.get("relevance", [])).lower()
        ]
    if query:
        results = [r for r in results if _matches_query(r, query)]
    return results[:n]


def fmt_note(note: dict, idx: int) -> str:
    lines = [
        f"\n── {idx}. {note.get('source_file', '?')}  [{note.get('date', '?')}]",
        f"   {note.get('summary', '')}",
    ]
    takeaways = note.get("takeaways", [])
    if takeaways:
        lines.append("   Takeaways:")
        for t in takeaways:
            lines.append(f"     • {t}")
    data = note.get("key_data_points", [])
    if data:
        lines.append(f"   Data: {' | '.join(data)}")
    meta = []
    if note.get("tags"):
        meta.append(f"tags:[{','.join(note['tags'])}]")
    if note.get("relevance"):
        meta.append(f"relevance:[{','.join(note['relevance'])}]")
    if note.get("entities"):
        meta.append(f"entities:[{','.join(note['entities'])}]")
    if meta:
        lines.append(f"   {' | '.join(meta)}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Search your distilled knowledge notes")
    parser.add_argument("query", nargs="?", help="Keyword search query")
    parser.add_argument("--date", help="Filter by date (YYYY-MM-DD)")
    parser.add_argument("--tag", help="Filter by tag or relevance category")
    parser.add_argument("--top", type=int, default=5, help="Max results (default: 5)")
    parser.add_argument("--list", action="store_true", help="List all notes")
    parser.add_argument(
        "--notes-dir",
        default=os.environ.get("KNOWLEDGE_NOTES_DIR", DEFAULT_NOTES_DIR),
        help="Directory containing _note.json files",
    )
    args = parser.parse_args()

    if not args.query and not args.date and not args.tag and not args.list:
        parser.print_help()
        sys.exit(0)

    notes_dir = os.path.expanduser(args.notes_dir)
    notes = load_notes(notes_dir)

    if not notes:
        print(f"[search] No notes found in: {notes_dir}")
        print("[search] Run: python scripts\\knowledge\\ingest.py --batch --watch-dir \"H:\\My Drive\\daily reads\"")
        sys.exit(0)

    results = search_notes(
        notes,
        query=args.query,
        date=args.date,
        tag=args.tag,
        n=args.top,
    )

    label_parts = [f"{len(notes)} note(s) in store"]
    if args.query:
        label_parts.append(f'query: "{args.query}"')
    if args.date:
        label_parts.append(f"date: {args.date}")
    if args.tag:
        label_parts.append(f"tag: {args.tag}")
    print(f"[search] {' | '.join(label_parts)}")

    if not results:
        print("[search] No matching notes found.")
        sys.exit(0)

    print(f"[search] {len(results)} result(s):")
    for i, note in enumerate(results, 1):
        print(fmt_note(note, i))
    print()


if __name__ == "__main__":
    main()
