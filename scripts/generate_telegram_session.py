#!/usr/bin/env python3
"""
Run this ONCE on your local machine to generate a Telegram session string.
Save the output as a GitHub secret named TELEGRAM_SESSION.

Usage:
  pip install telethon
  python scripts/generate_telegram_session.py
"""

from telethon.sync import TelegramClient
from telethon.sessions import StringSession

print("=== Telegram Session Generator ===")
print("Get your API ID and Hash from: https://my.telegram.org/apps\n")

api_id   = input("Enter your API ID: ").strip()
api_hash = input("Enter your API Hash: ").strip()

with TelegramClient(StringSession(), int(api_id), api_hash) as client:
    session_string = client.session.save()

print("\n✅ Your session string (save this as GitHub secret TELEGRAM_SESSION):\n")
print(session_string)
print("\nAlso save TELEGRAM_API_ID and TELEGRAM_API_HASH as GitHub secrets.")
