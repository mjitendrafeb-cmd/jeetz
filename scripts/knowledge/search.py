#!/usr/bin/env python3
"""
search.py — Query your distilled knowledge notes.

Usage:
  python search.py "NBFC liquidity crisis"          # semantic search
  python search.py "RBI regulation" --date 2026-06-14  # search on a specific date
  python search.py --date 2026-06-14                # all notes from a date
  python search.py --tag regulatory                 # filter by relevance/tag
  python search.py --tag regulatory --top 20        # more results
  python search.py --list                           # list all notes (newest first)

Optional env var:
  KNOWLEDGE_CHROMA_DIR   override ChromaDB path (~/.jeetz-knowledge/chroma)
"""

import argparse
import os
import sys
import textwrap


def fmt_result(r: dict, idx: int) -> str:
    score = f"  score={r['_score']:.3f}" if r.get("_score") is not None else ""
    lines = [
        f"\n── {idx}. {r.get('source_file', '?')}  [{r.get('date', '?')}]{score}",
        f"   {r.get('summary', '')}",
    ]

    takeaways = r.get("takeaways", "")
    if takeaways:
        lines.append("   Takeaways:")
        for t in takeaways.split(" | "):
            lines.append(f"     • {t.strip()}")

    data_points = r.get("key_data_points", "")
    if data_points:
        lines.append(f"   Data: {data_points}")

    tags = r.get("tags", "")
    rel = r.get("relevance", "")
    entities = r.get("entities", "")
    meta_parts = []
    if tags:
        meta_parts.append(f"tags:[{tags}]")
    if rel:
        meta_parts.append(f"relevance:[{rel}]")
    if entities:
        meta_parts.append(f"entities:[{entities}]")
    if meta_parts:
        lines.append(f"   {' | '.join(meta_parts)}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Search your distilled knowledge notes")
    parser.add_argument("query", nargs="?", help="Semantic search query")
    parser.add_argument("--date", help="Filter by date (YYYY-MM-DD)")
    parser.add_argument("--tag", help="Filter by tag or relevance category")
    parser.add_argument("--top", type=int, default=5, help="Number of results (default: 5)")
    parser.add_argument("--list", action="store_true", help="List all notes")
    parser.add_argument("--chroma-dir", default=os.environ.get("KNOWLEDGE_CHROMA_DIR"))
    args = parser.parse_args()

    if not args.query and not args.date and not args.tag and not args.list:
        parser.print_help()
        sys.exit(0)

    sys.path.insert(0, os.path.dirname(__file__))
    try:
        from store import query_notes, _get_collection
    except ImportError as e:
        print(f"[search] Import error: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        col = _get_collection(args.chroma_dir)
        total = col.count()
    except Exception as e:
        print(f"[search] Could not connect to ChromaDB: {e}", file=sys.stderr)
        sys.exit(1)

    if total == 0:
        print("[search] No notes stored yet. Run ingest.py --batch to populate.")
        sys.exit(0)

    print(f"[search] {total} note(s) in store", end="")
    if args.query:
        print(f"  |  query: \"{args.query}\"", end="")
    if args.date:
        print(f"  |  date: {args.date}", end="")
    if args.tag:
        print(f"  |  tag: {args.tag}", end="")
    print()

    try:
        results = query_notes(
            query=args.query,
            date=args.date,
            tag=args.tag,
            n_results=args.top,
            chroma_dir=args.chroma_dir,
        )
    except Exception as e:
        print(f"[search] Query error: {e}", file=sys.stderr)
        sys.exit(1)

    if not results:
        print("[search] No matching notes found.")
        sys.exit(0)

    print(f"[search] {len(results)} result(s):")
    for i, r in enumerate(results, 1):
        print(fmt_result(r, i))
    print()


if __name__ == "__main__":
    main()
