#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Telegram Message Listener
Real-time Telegram message listener using Telethon.
Saves messages to daily JSON files.
Auto-reconnects on connection loss.
"""

import os
import json
import asyncio
import logging
import traceback
from datetime import datetime, date
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.errors import (
    SessionPasswordNeededError,
    FloodWaitError,
    RPCError,
    ConnectionError,
    TimeoutError,
)
from telethon.network import ConnectionTcpFull

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# File paths
ENV_FILE = ".env"
SESSION_FILE = "telegram_session.session"
MESSAGES_DIR = "messages"

# Reconnection settings
RECONNECT_DELAY_SECONDS = 5   # Initial delay before reconnect
RECONNECT_DELAY_MAX = 300      # Max delay (5 minutes)
RECONNECT_BACKOFF = 2          # Exponential backoff multiplier


def get_today_file() -> Path:
    """Return the daily messages file path based on today's date."""
    today_str = date.today().isoformat()  # e.g. 2026-07-29
    return Path(MESSAGES_DIR) / f"messages_{today_str}.json"


def load_environment():
    """Load environment variables from .env file."""
    if not Path(ENV_FILE).exists():
        logger.error(
            f"{ENV_FILE} file not found! "
            "Please create it with your Telegram API credentials."
        )
        print(
            f"\n❌ {ENV_FILE} file not found!"
            f"\n   Create a {ENV_FILE} file with the following content:"
            f"\n   API_ID=your_api_id"
            f"\n   API_HASH=your_api_hash"
            f"\n   PHONE_NUMBER=+901234567890"
        )
        return None

    load_dotenv(ENV_FILE)

    api_id = os.getenv("API_ID")
    api_hash = os.getenv("API_HASH")
    phone_number = os.getenv("PHONE_NUMBER")

    if not all([api_id, api_hash, phone_number]):
        logger.error(
            "Missing required environment variables! "
            "Please ensure API_ID, API_HASH, and PHONE_NUMBER are set in .env"
        )
        return None

    return api_id, api_hash, phone_number


def save_message(message_data: dict):
    """Append a message to the daily JSON file."""
    file_path = get_today_file()
    file_path.parent.mkdir(parents=True, exist_ok=True)

    messages = []
    if file_path.exists():
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                messages = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            messages = []

    messages.append(message_data)

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)

    logger.info(f"💾 Message saved to {file_path.name}")


async def run_listener(api_id: int, api_hash: str, phone_number: str):
    """
    Connect to Telegram and listen for messages.
    Returns when disconnected (for reconnection loop).
    """
    client = TelegramClient(
        SESSION_FILE,
        api_id,
        api_hash,
        connection=ConnectionTcpFull,
        connection_retries=None,        # Infinite retries on connection level
        request_retries=10,             # Retry failed requests 10 times
    )

    @client.on(events.NewMessage)
    async def handle_new_message(event):
        """Handle incoming new messages."""
        try:
            chat = await event.get_chat()
            sender = await event.get_sender()

            chat_title = getattr(chat, "title", None) or getattr(chat, "username", None) or str(chat.id)
            sender_name = (
                getattr(sender, "first_name", "")
                + (
                    " " + getattr(sender, "last_name", "")
                    if getattr(sender, "last_name", None)
                    else ""
                )
            ).strip() or getattr(sender, "username", None) or str(sender.id)

            message_text = event.text or "[Non-text message]"

            message_data = {
                "timestamp": datetime.now().isoformat(),
                "chat_id": chat.id,
                "chat_title": chat_title,
                "sender_id": sender.id,
                "sender_name": sender_name,
                "message": message_text,
            }

            # Print to console
            today_str = date.today().isoformat()
            print(
                f"\n[{message_data['timestamp']}]"
                f"\n   💬 Chat:    {chat_title}"
                f"\n   👤 From:    {sender_name}"
                f"\n   📝 Message: {message_text}"
                f"\n   📁 File:    messages_{today_str}.json"
                f"\n   {'─' * 40}"
            )

            # Save to daily file
            save_message(message_data)

        except Exception as e:
            logger.error(f"Error processing message: {e}")

    @client.on(events.MessageEdited)
    async def handle_edited_message(event):
        """Handle edited messages."""
        try:
            chat = await event.get_chat()
            sender = await event.get_sender()

            chat_title = getattr(chat, "title", None) or getattr(chat, "username", None) or str(chat.id)
            sender_name = (
                getattr(sender, "first_name", "")
                + (
                    " " + getattr(sender, "last_name", "")
                    if getattr(sender, "last_name", None)
                    else ""
                )
            ).strip() or getattr(sender, "username", None) or str(sender.id)

            message_text = event.text or "[Non-text message]"

            message_data = {
                "timestamp": datetime.now().isoformat(),
                "chat_id": chat.id,
                "chat_title": chat_title,
                "sender_id": sender.id,
                "sender_name": sender_name,
                "message": message_text,
                "edited": True,
            }

            today_str = date.today().isoformat()
            print(
                f"\n✏️ [EDITED] [{message_data['timestamp']}]"
                f"\n   💬 Chat:    {chat_title}"
                f"\n   👤 From:    {sender_name}"
                f"\n   📝 Message: {message_text}"
                f"\n   📁 File:    messages_{today_str}.json"
                f"\n   {'─' * 40}"
            )

            save_message(message_data)

        except Exception as e:
            logger.error(f"Error processing edited message: {e}")

    # Connect and authorize
    await client.start(phone=phone_number)

    if not await client.is_user_authorized():
        logger.info("🔐 Session not found or expired. Requesting login code...")
        await client.send_code_request(phone_number)
        code = input("📱 Enter the code you received on Telegram: ").strip()

        try:
            await client.sign_in(phone_number, code)
        except SessionPasswordNeededError:
            password = input("🔑 Two-factor authentication enabled. Enter your password: ").strip()
            await client.sign_in(password=password)

    me = await client.get_me()
    logger.info(f"✅ Logged in as: {me.first_name} (@{me.username or 'no username'})")

    today_str = date.today().isoformat()
    logger.info(f"👂 Listening... saving to messages_{today_str}.json")
    print("\n" + "=" * 50)
    print("🟢 LISTENER IS RUNNING")
    print("   Press Ctrl+C to stop")
    print("=" * 50 + "\n")

    # Run until disconnected
    await client.run_until_disconnected()


async def main():
    """Main entry point with auto-reconnect loop."""
    credentials = load_environment()
    if credentials is None:
        return

    api_id_str, api_hash, phone_number = credentials

    try:
        api_id = int(api_id_str)
    except ValueError:
        logger.error("API_ID must be a valid integer!")
        return

    delay = RECONNECT_DELAY_SECONDS
    attempt = 0

    while True:
        attempt += 1
        logger.info(f"🔄 Connection attempt #{attempt}")

        try:
            await run_listener(api_id, api_hash, phone_number)

            # If we get here without exception, disconnected cleanly
            logger.warning("⚠️ Disconnected unexpectedly. Reconnecting...")

        except KeyboardInterrupt:
            logger.info("\n🛑 Stopping listener.")
            break

        except (ConnectionError, TimeoutError, OSError, RPCError) as e:
            logger.error(f"❌ Connection error: {type(e).__name__}: {e}")

        except FloodWaitError as e:
            # Telegram rate limiting - wait the required time
            wait_seconds = e.seconds
            logger.warning(f"⏳ Flood wait required: {wait_seconds} seconds. Waiting...")
            await asyncio.sleep(wait_seconds)
            delay = RECONNECT_DELAY_SECONDS  # Reset delay after flood wait
            continue

        except Exception as e:
            logger.error(f"❌ Unexpected error: {type(e).__name__}: {e}")
            traceback.print_exc()

        # Exponential backoff before reconnect
        logger.info(f"⏳ Waiting {delay} seconds before reconnecting...")
        await asyncio.sleep(delay)
        delay = min(delay * RECONNECT_BACKOFF, RECONNECT_DELAY_MAX)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass