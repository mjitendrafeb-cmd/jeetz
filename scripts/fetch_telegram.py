#!/usr/bin/env python3
"""
fetch_telegram.py — Telegram channel news fetcher for Daily Credit Intelligence Report.

Uses Telegram Bot API to read recent messages from public channels.
The bot must be added as a member (or admin) of each channel to read its messages.

Env var: TELEGRAM_BOT_TOKEN
Config: config.json → "telegram_channels": ["@channelname", ...]
"""

import os
import re
import datetime
import requests


def _clean(text: str) -> str:
    """Strip markdown/HTML formatting and normalise whitespace."""
    if not text:
        return ""
    # Remove Telegram markdown links [text](url)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Collapse whitespace
    return " ".join(text.split())


def fetch_telegram_channels(bot_token: str, channels: list[str]) -> list[str]:
    """
    Fetch recent messages (last 24 h) from the given Telegram channel usernames.
    Returns formatted strings tagged [TELEGRAM — @channel].

    Requirements:
    - The bot must be added as a member/admin to each private channel.
    - Public channels can be read by any bot that knows the channel username.
    """
    if not bot_token or not channels:
        return []

    cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
    cutoff_ts = int(cutoff.timestamp())

    items: list[str] = []
    base_url = f"https://api.telegram.org/bot{bot_token}"

    for channel in channels:
        channel = channel.strip()
        if not channel:
            continue
        # Ensure @ prefix
        if not channel.startswith("@"):
            channel = "@" + channel
        try:
            # getUpdates doesn't work for channels; use getChat + getChatHistory workaround:
            # We use forwardMessages from the channel via getUpdates with allowed_updates=["channel_post"]
            # The most reliable approach for a bot added to a channel is to use
            # the channel_post updates; but since we're doing a one-shot fetch,
            # we call getUpdates with a large limit and filter by chat username.
            resp = requests.get(
                f"{base_url}/getUpdates",
                params={"limit": 100, "allowed_updates": '["channel_post"]'},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            if not data.get("ok"):
                print(f"[fetch_telegram] getUpdates error for {channel}: {data.get('description')}")
                continue

            for update in data.get("result", []):
                post = update.get("channel_post", {})
                if not post:
                    continue
                chat = post.get("chat", {})
                # Match by username or title
                post_username = "@" + chat.get("username", "") if chat.get("username") else ""
                if post_username.lower() != channel.lower():
                    continue
                date_ts = post.get("date", 0)
                if date_ts < cutoff_ts:
                    continue
                text = post.get("text") or post.get("caption") or ""
                text = _clean(text)
                if not text or len(text) < 20:
                    continue
                # Take first 300 chars as headline
                snippet = text[:300]
                items.append(f"[TELEGRAM — {channel}] {snippet}")

        except Exception as exc:
            print(f"[fetch_telegram] Error fetching {channel}: {exc}")

    return items
