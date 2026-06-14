#!/usr/bin/env python3
"""
ingest.py — Watch a folder for new PDFs/text files and distill + store them.

Usage:
  # Batch: process all files in the folder that haven't been stored yet
  python ingest.py --batch [--watch-dir ~/daily-reads] [--notes-dir ~/daily-reads/notes]

  # Watch: run continuously (Ctrl-C to stop)
  python ingest.py --watch [--watch-dir ~/daily-reads] [--notes-dir ~/daily-reads/notes]

  # Both: batch-process existing files, then keep watching
  python ingest.py --batch --watch ...

Required env var:
  ANTHROPIC_API_KEY

Optional env vars:
  KNOWLEDGE_WATCH_DIR    override default watch directory
  KNOWLEDGE_NOTES_DIR    override default notes directory
  KNOWLEDGE_CHROMA_DIR   override ChromaDB path (~/.jeetz-knowledge/chroma)
"""

import argparse
import json
import os
import sys
import time

SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md"}

DEFAULT_WATCH_DIR = os.path.expanduser("~/daily-reads")
DEFAULT_NOTES_DIR = os.path.expanduser("~/daily-reads/notes")


def _note_path(notes_dir: str, source_path: str) -> str:
    stem = os.path.splitext(os.path.basename(source_path))[0]
    return os.path.join(notes_dir, f"{stem}_note.json")


def _already_processed(notes_dir: str, source_path: str) -> bool:
    return os.path.isfile(_note_path(notes_dir, source_path))


def process_file(source_path: str, notes_dir: str, api_key: str, chroma_dir: str | None = None) -> bool:
    """Distill a file and save the note as JSON. Returns True on success."""
    from distill import extract_text, call_claude, build_note

    print(f"[ingest] Processing: {source_path}")

    try:
        text, file_type = extract_text(source_path)
    except SystemExit:
        return False

    if len(text.strip()) < 50:
        print(f"[ingest] Skipping (too little text): {source_path}")
        return False

    print(f"[ingest]   Extracted {len(text):,} chars ({file_type}), calling Claude...")
    try:
        claude_output = call_claude(text, api_key)
    except SystemExit:
        return False

    note = build_note(source_path, file_type, claude_output)

    os.makedirs(notes_dir, exist_ok=True)
    note_path = _note_path(notes_dir, source_path)
    with open(note_path, "w", encoding="utf-8") as f:
        json.dump(note, f, indent=2, ensure_ascii=False)
    print(f"[ingest]   Saved: {note_path}")
    print(f"[ingest]   Summary: {note['summary']}")
    if note.get("takeaways"):
        for t in note["takeaways"]:
            print(f"[ingest]     • {t}")
    return True


def batch_ingest(watch_dir: str, notes_dir: str, api_key: str, chroma_dir: str | None = None):
    """Process all unprocessed files in watch_dir."""
    files = []
    for name in sorted(os.listdir(watch_dir)):
        ext = os.path.splitext(name)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            continue
        full = os.path.join(watch_dir, name)
        if not os.path.isfile(full):
            continue
        if _already_processed(notes_dir, full):
            print(f"[ingest] Already processed, skipping: {name}")
            continue
        files.append(full)

    if not files:
        print("[ingest] No new files to process.")
        return

    print(f"[ingest] Found {len(files)} new file(s) to process.")
    ok = 0
    for path in files:
        if process_file(path, notes_dir, api_key, chroma_dir):
            ok += 1
    print(f"[ingest] Batch complete: {ok}/{len(files)} processed successfully.")


def watch_folder(watch_dir: str, notes_dir: str, api_key: str, chroma_dir: str | None = None):
    """Watch watch_dir for new files and process them as they arrive."""
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        print("[ingest] watchdog not installed — run: pip install watchdog", file=sys.stderr)
        sys.exit(1)

    class Handler(FileSystemEventHandler):
        def on_created(self, event):
            if event.is_directory:
                return
            path = event.src_path
            ext = os.path.splitext(path)[1].lower()
            if ext not in SUPPORTED_EXTENSIONS:
                return
            # Wait briefly for the file to finish writing
            time.sleep(1)
            if not _already_processed(notes_dir, path):
                process_file(path, notes_dir, api_key, chroma_dir)

        def on_moved(self, event):
            # Handles files moved/renamed into the watch dir
            if event.is_directory:
                return
            path = event.dest_path
            ext = os.path.splitext(path)[1].lower()
            if ext not in SUPPORTED_EXTENSIONS:
                return
            time.sleep(1)
            if not _already_processed(notes_dir, path):
                process_file(path, notes_dir, api_key, chroma_dir)

    os.makedirs(watch_dir, exist_ok=True)
    observer = Observer()
    observer.schedule(Handler(), watch_dir, recursive=False)
    observer.start()
    print(f"[ingest] Watching: {watch_dir}  (Ctrl-C to stop)")
    try:
        while True:
            time.sleep(2)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
    print("[ingest] Stopped.")


def main():
    parser = argparse.ArgumentParser(description="Ingest PDFs/text files into the knowledge pipeline")
    parser.add_argument("--watch-dir", default=os.environ.get("KNOWLEDGE_WATCH_DIR", DEFAULT_WATCH_DIR))
    parser.add_argument("--notes-dir", default=os.environ.get("KNOWLEDGE_NOTES_DIR", DEFAULT_NOTES_DIR))
    parser.add_argument("--chroma-dir", default=os.environ.get("KNOWLEDGE_CHROMA_DIR"))
    parser.add_argument("--api-key", help="Anthropic API key (overrides ANTHROPIC_API_KEY)")
    parser.add_argument("--batch", action="store_true", help="Process all existing unprocessed files")
    parser.add_argument("--watch", action="store_true", help="Watch folder for new files")
    args = parser.parse_args()

    if not args.batch and not args.watch:
        parser.print_help()
        sys.exit(1)

    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("[ingest] No API key — set ANTHROPIC_API_KEY or pass --api-key", file=sys.stderr)
        sys.exit(1)

    watch_dir = os.path.expanduser(args.watch_dir)
    notes_dir = os.path.expanduser(args.notes_dir)

    if not os.path.isdir(watch_dir):
        print(f"[ingest] Watch directory does not exist: {watch_dir}", file=sys.stderr)
        sys.exit(1)

    # Add scripts/knowledge to path so distill/store imports work
    sys.path.insert(0, os.path.dirname(__file__))

    if args.batch:
        batch_ingest(watch_dir, notes_dir, api_key, args.chroma_dir)

    if args.watch:
        watch_folder(watch_dir, notes_dir, api_key, args.chroma_dir)


if __name__ == "__main__":
    main()
