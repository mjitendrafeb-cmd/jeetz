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
import io
import datetime
import asyncio


def _clean(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split())


def _extract_pdf_text(data: bytes, max_chars: int = 400) -> str:
    """Extract text from PDF bytes using pdfplumber. Returns first max_chars chars."""
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            parts = []
            for page in pdf.pages[:4]:  # read first 4 pages max
                t = page.extract_text() or ""
                parts.append(t)
                if sum(len(p) for p in parts) >= max_chars:
                    break
            text = " ".join(" ".join(p.split()) for p in parts if p)
            return text[:max_chars]
    except Exception as exc:
        print(f"[fetch_telegram] PDF extract error: {exc}")
        return ""


def fetch_telegram_channels(channels: list[str], days_back: int = 1) -> list[str]:
    """Synchronous wrapper around the async fetcher.

    days_back: how far back to read. Default 1 (24h) is the long-standing
    behaviour. Telegram was the only source still on a 24h window while
    every other source in the pipeline used 48h — and 4 days for the
    Monday Weekend Edition — so a channel posting on Friday evening was
    invisible to Monday's mail even though no run happens over the
    weekend to pick it up."""
    api_id = os.environ.get("TELEGRAM_API_ID", "")
    api_hash = os.environ.get("TELEGRAM_API_HASH", "")
    session_str = os.environ.get("TELEGRAM_SESSION", "")

    if not api_id or not api_hash or not session_str:
        print("[fetch_telegram] Skipping: TELEGRAM_API_ID / TELEGRAM_API_HASH / TELEGRAM_SESSION not set")
        return []

    if not channels:
        return []

    try:
        return asyncio.run(asyncio.wait_for(
            _fetch_async(api_id, api_hash, session_str, channels, days_back),
            # A wider window means more messages to walk per channel, so the
            # overall budget scales with it rather than staying at 180s.
            timeout=180 + 60 * max(0, days_back - 1),
        ))
    except asyncio.TimeoutError:
        print("[fetch_telegram] Timed out after 180s — session may be expired or network blocked")
        return []
    except Exception as exc:
        print(f"[fetch_telegram] Fatal error: {exc}")
        return []


async def _fetch_async(api_id: str, api_hash: str, session_str: str,
                       channels: list[str], days_back: int = 1) -> list[str]:
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        from telethon.errors import AuthKeyUnregisteredError, SessionExpiredError, UserDeactivatedError
        from telethon.tl.types import DocumentAttributeFilename, MessageMediaDocument
    except ImportError:
        print("[fetch_telegram] telethon not installed — run: pip install telethon")
        return []

    days_back = max(1, int(days_back or 1))
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days_back)
    # Both the scan depth and the per-channel keep-cap scale with the
    # window. Leaving them at 30/8 would have silently truncated a 4-day
    # Weekend Edition read back down to roughly one day's worth.
    scan_limit = 30 * days_back
    per_channel_cap = 8 * days_back
    items: list[str] = []

    client = TelegramClient(StringSession(session_str), int(api_id), api_hash)

    try:
        await asyncio.wait_for(client.connect(), timeout=30)
    except Exception as exc:
        print(f"[fetch_telegram] Connect failed: {exc}")
        return []

    try:
        if not await client.is_user_authorized():
            print("[fetch_telegram] Session is NOT authorised — TELEGRAM_SESSION secret needs to be regenerated")
            print("[fetch_telegram] Run: python scripts/generate_telegram_session.py  then update the GitHub secret")
            return []

        me = await client.get_me()
        print(f"[fetch_telegram] Connected as: {me.first_name} (@{me.username}), "
              f"fetching {len(channels)} channels over the last {days_back}d "
              f"(cap {per_channel_cap}/channel)")

        for channel in channels:
            channel = channel.strip()
            if not channel:
                continue
            if "t.me/" in channel:
                channel = "@" + channel.split("t.me/")[-1].split("/")[0].strip("@")
            elif not channel.startswith("@"):
                channel = "@" + channel
            try:
                entity = await client.get_entity(channel)
                count = 0
                async for msg in client.iter_messages(entity, limit=scan_limit):
                    if not msg.date:
                        continue
                    msg_date = msg.date
                    if msg_date.tzinfo is None:
                        msg_date = msg_date.replace(tzinfo=datetime.timezone.utc)
                    if msg_date < cutoff:
                        break

                    text = _clean(msg.text or msg.message or "")

                    # Try to extract text from PDF attachments
                    pdf_text = ""
                    if isinstance(msg.media, MessageMediaDocument) and msg.media.document:
                        doc = msg.media.document
                        mime = getattr(doc, "mime_type", "") or ""
                        # Get filename from attributes
                        filename = ""
                        for attr in getattr(doc, "attributes", []):
                            if isinstance(attr, DocumentAttributeFilename):
                                filename = attr.file_name or ""
                                break
                        is_pdf = mime == "application/pdf" or filename.lower().endswith(".pdf")
                        # Only download if size < 5 MB
                        size = getattr(doc, "size", 0) or 0
                        if is_pdf and size < 5 * 1024 * 1024:
                            try:
                                print(f"[fetch_telegram] Downloading PDF from {channel}: {filename or 'unknown'} ({size//1024}KB)")
                                data = await client.download_media(msg, file=bytes)
                                if data:
                                    pdf_text = _extract_pdf_text(data)
                                    print(f"[fetch_telegram] Extracted {len(pdf_text)} chars from PDF")
                            except Exception as exc:
                                print(f"[fetch_telegram] PDF download failed: {exc}")

                    # Combine message text + PDF text
                    combined = " | ".join(filter(None, [text, pdf_text]))
                    if not combined or len(combined) < 30:
                        continue

                    label = f"[TELEGRAM — {channel}]"
                    if pdf_text:
                        label = f"[TELEGRAM-PDF — {channel}]"
                    items.append(f"{label} {combined[:500]}")
                    count += 1
                    if count >= per_channel_cap:
                        break
                print(f"[fetch_telegram] {channel}: {count} items")
            except Exception as exc:
                print(f"[fetch_telegram] Could not read {channel}: {exc}")
    except (AuthKeyUnregisteredError, SessionExpiredError, UserDeactivatedError) as exc:
        print(f"[fetch_telegram] Session invalid ({type(exc).__name__}) — regenerate TELEGRAM_SESSION secret")
    finally:
        await client.disconnect()

    print(f"[fetch_telegram] Total Telegram items: {len(items)}")
    return items
