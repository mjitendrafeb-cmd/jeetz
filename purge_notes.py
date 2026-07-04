#!/usr/bin/env python3
"""
purge_notes.py — Permanently delete distilled notes from docs/notes/.

Usage:
  python purge_notes.py "kpmg"                 # deletes notes matching 'kpmg'
  python purge_notes.py "kpmg, wef outlook"    # comma-separated, multiple

A note matches if the fragment (case-insensitive) appears in its file name
or in its title. Prints what it deletes; exits 0 even when nothing matches
so the workflow continues.
"""
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
NOTES_DIR = os.path.join(REPO_ROOT, "docs", "notes")


def main():
    raw = sys.argv[1] if len(sys.argv) > 1 else ""
    frags = [f.strip().lower() for f in raw.split(",") if f.strip()]
    if not frags:
        print("No purge fragments given — nothing to do.")
        return

    if not os.path.isdir(NOTES_DIR):
        print(f"Notes dir not found: {NOTES_DIR}")
        return

    deleted = 0
    for name in sorted(os.listdir(NOTES_DIR)):
        if not name.endswith("_note.json"):
            continue
        path = os.path.join(NOTES_DIR, name)
        title = ""
        try:
            with open(path, encoding="utf-8") as f:
                title = (json.load(f).get("title") or "")
        except Exception:
            pass
        blob = (name + " " + title).lower()
        if any(f in blob for f in frags):
            os.remove(path)
            deleted += 1
            print(f"PURGED: {name}  ({title})")

    if not deleted:
        print(f"No notes matched: {raw!r}")
    else:
        print(f"\n{deleted} note(s) permanently deleted.")


if __name__ == "__main__":
    main()
