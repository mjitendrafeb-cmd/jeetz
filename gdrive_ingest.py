#!/usr/bin/env python3
"""
gdrive_ingest.py — Download PDFs from Google Drive folder, distil with Claude, save JSON notes.

Reads from a shared Google Drive folder using a service account.
Skips files already processed (stem_note.json already exists in docs/notes/).

Required environment variables:
  ANTHROPIC_API_KEY            — Anthropic API key
  GOOGLE_SERVICE_ACCOUNT_JSON  — full content of the service account JSON key file
  GDRIVE_FOLDER_ID             — Google Drive folder ID (default below)
"""
import io
import json
import os
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
NOTES_DIR = os.path.join(REPO_ROOT, "docs", "notes")
GDRIVE_FOLDER_ID = os.environ.get("GDRIVE_FOLDER_ID", "1DKkfBndGPDD-UWYWkIuYr8jdWb802BG0")


def _drive_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not sa_json:
        print("ERROR: GOOGLE_SERVICE_ACCOUNT_JSON env var not set.")
        sys.exit(1)

    info = json.loads(sa_json)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def list_pdfs(service, folder_id):
    files, page_token = [], None
    while True:
        resp = service.files().list(
            q=(f"'{folder_id}' in parents"
               " and mimeType='application/pdf'"
               " and trashed=false"),
            fields="nextPageToken, files(id, name, modifiedTime)",
            pageToken=page_token,
            orderBy="name",
        ).execute()
        files.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return files


def download_pdf(service, file_id, dest_path):
    from googleapiclient.http import MediaIoBaseDownload

    req = service.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = dl.next_chunk()
    with open(dest_path, "wb") as f:
        f.write(buf.getvalue())


def already_done(filename):
    stem = os.path.splitext(filename)[0]
    return os.path.isfile(os.path.join(NOTES_DIR, f"{stem}_note.json"))


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY env var not set.")
        sys.exit(1)

    sys.path.insert(0, REPO_ROOT)
    from run_ingest import process  # reuse all extraction + Claude logic

    print(f"Connecting to Google Drive folder: {GDRIVE_FOLDER_ID}")
    service = _drive_service()

    all_files = list_pdfs(service, GDRIVE_FOLDER_ID)
    print(f"Found {len(all_files)} PDF(s) in Drive folder.")

    new_files = [f for f in all_files if not already_done(f["name"])]
    if not new_files:
        print("No new PDFs — library already up to date.")
        return

    print(f"{len(new_files)} new file(s) to process.")
    os.makedirs(NOTES_DIR, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        ok = 0
        for f in new_files:
            dest = os.path.join(tmpdir, f["name"])
            print(f"\nDownloading: {f['name']}")
            try:
                download_pdf(service, f["id"], dest)
            except Exception as e:
                print(f"  Download failed: {e}")
                continue
            if process(dest, NOTES_DIR, api_key):
                ok += 1

    print(f"\nDone: {ok}/{len(new_files)} successfully processed.")


if __name__ == "__main__":
    main()
