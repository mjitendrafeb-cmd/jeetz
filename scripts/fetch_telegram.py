#!/usr/bin/env python3
"""
fetch_telegram.py — Reads recent messages from Telegram channels using Telethon.

Works for ANY channel the user's account is a member of — public or private.
No bot needed. Uses a pre-generated session string stored as a GitHub secret.

Required env vars:
  TELEGRAM_API_ID      — from https://my.telegram.org/apps
  TELEGRAM_API_HASH    — from https://my.telegram.org/apps
  TELEGRAM_SESSION     — base64 session string (generated once via generate_session.py)

Config (config.json):
  "telegram_channels": ["@economictimes", "@cnbctv18", "@bloombergquint"]
"""

import os
import re
import datetime
import asyncio


def _clean(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split())


def fetch_telegram_channels(channels: list[str]) -> list[str]:
    """Synchronous wrapper around the async fetcher."""
    api_id = os.environ.get("TELEGRAM_API_ID", "")
    api_hash = os.environ.get("TELEGRAM_API_HASH", "")
    session_str = os.environ.get("TELEGRAM_SESSION", "")

    if not api_id or not api_hash or not session_str:
        print("[fetch_telegram] Skipping: TELEGRAM_API_ID / TELEGRAM_API_HASH / TELEGRAM_SESSION not set")
        return []

    if not channels:
        return []

    try:
        return asyncio.run(_fetch_async(api_id, api_hash, session_str, channels))
    except Exception as exc:
        print(f"[fetch_telegram] Fatal error: {exc}")
        return []


async def _fetch_async(api_id: str, api_hash: str, session_str: str, channels: list[str]) -> list[str]:
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
    except ImportError:
        print("[fetch_telegram] telethon not installed — run: pip install telethon")
        return []

    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)
    items: list[str] = []

    client = TelegramClient(StringSession(session_str), int(api_id), api_hash)
    await client.connect()

    try:
        for channel in channels:
            channel = channel.strip()
            if not channel:
                continue
            # Handle full URLs like https://t.me/username or @https://t.me/username
            if "t.me/" in channel:
                channel = "@" + channel.split("t.me/")[-1].split("/")[0].strip("@")
            elif not channel.startswith("@"):
                channel = "@" + channel
            try:
                entity = await client.get_entity(channel)
                async for msg in client.iter_messages(entity, limit=20):
                    if not msg.date:
                        continue
                    msg_date = msg.date
                    if msg_date.tzinfo is None:
                        msg_date = msg_date.replace(tzinfo=datetime.timezone.utc)
                    if msg_date < cutoff:
                        break
                    text = _clean(msg.text or msg.message or "")
                    if not text or len(text) < 30:
                        continue
                    snippet = text[:300]
                    items.append(f"[TELEGRAM — {channel}] {snippet}")
                    if len(items) >= 5:  # max 5 per channel
                        break
            except Exception as exc:
                print(f"[fetch_telegram] Could not read {channel}: {exc}")
    finally:
        await client.disconnect()

    return items
