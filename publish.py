#!/usr/bin/env python3
"""
publish.py — One command: ingest new files → generate HTML → push to GitHub.

Usage:
  python publish.py --watch-dir "H:\\My Drive\\daily reads"

What it does:
  1. Processes any new PDFs/text files in watch-dir with Claude
  2. Saves JSON notes to docs/notes/
  3. Regenerates docs/index.html
  4. git add + commit + push  →  GitHub Pages updates within ~1 minute
"""
import argparse
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))


def run(cmd, check=True):
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip())
    if check and result.returncode != 0:
        print(f"Command failed (exit {result.returncode})")
        sys.exit(1)
    return result


def main():
    p = argparse.ArgumentParser(description="Ingest, build, and publish knowledge notes")
    p.add_argument("--watch-dir", required=True, help='Folder with PDFs, e.g. "H:\\My Drive\\daily reads"')
    p.add_argument("--api-key", help="Anthropic API key (or set ANTHROPIC_API_KEY env var)")
    p.add_argument("--no-push", action="store_true", help="Skip git push (just generate locally)")
    args = p.parse_args()

    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("Set ANTHROPIC_API_KEY or pass --api-key")
        sys.exit(1)

    watch_dir = os.path.expanduser(args.watch_dir)
    notes_dir = os.path.join(REPO_ROOT, "docs", "notes")

    # Step 1: ingest
    print("\n[1/3] Processing new files...")
    env = {**os.environ, "ANTHROPIC_API_KEY": api_key}
    result = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "run_ingest.py"),
         "--batch", "--watch-dir", watch_dir, "--notes-dir", notes_dir],
        cwd=REPO_ROOT, env=env
    )

    # Step 2: generate HTML
    print("\n[2/3] Generating HTML viewer...")
    subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "view_notes.py"), "--no-open"],
        cwd=REPO_ROOT, check=True
    )

    # Step 3: git push
    if args.no_push:
        print("\n[3/3] Skipped git push (--no-push)")
        print("\nDone. Open docs/index.html in your browser to preview.")
        return

    print("\n[3/3] Pushing to GitHub...")
    status = run(["git", "status", "--porcelain"], check=False)
    if not status.stdout.strip():
        print("Nothing new to commit.")
        return

    from datetime import datetime
    date_str = datetime.now().strftime("%Y-%m-%d")
    run(["git", "add", "docs/"])
    run(["git", "commit", "-m", f"Update knowledge notes {date_str}"])
    run(["git", "push", "-u", "origin", "HEAD:claude/knowledge-mgmt-daily-reads-cj7wbf"])

    print(f"\n✓ Published! GitHub Pages will update in ~1 minute.")
    print(f"  View at: https://mjitendrafeb-cmd.github.io/jeetz/")


if __name__ == "__main__":
    main()
