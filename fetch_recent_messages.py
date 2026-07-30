#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Telegram Recent Messages Fetcher
Fetches messages from the last 10 days across all dialogs.
Saves to a single JSON file with only timestamp, message, and chat info.
"""

import os
import json
import asyncio
import logging
from datetime import datetime, timedelta, date
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError,
    FloodWaitError,
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
OUTPUT_DIR = "fetched_messages"


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


async def fetch_all_messages(client, days: int = 10):
    """Fetch messages from all dialogs within the last N days."""
    cutoff_date = datetime.now() - timedelta(days=days)
    all_messages = []

    logger.info(f"📡 Fetching messages from last {days} days (since {cutoff_date.date()})...")

    async for dialog in client.iter_dialogs():
        chat_id = dialog.id
        chat_title = dialog.name or f"Chat {chat_id}"
        chat_type = ""

        if dialog.is_user:
            chat_type = "private"
        elif dialog.is_group:
            chat_type = "group"
        elif dialog.is_channel:
            chat_type = "channel"

        logger.info(f"   📂 Checking: {chat_title} ({chat_type})")

        message_count = 0
        try:
            async for msg in client.iter_messages(
                dialog.entity,
                offset_date=cutoff_date,
                reverse=True,  # oldest first to newest
            ):
                if msg.date.replace(tzinfo=None) < cutoff_date:
                    continue

                message_text = msg.text or "[Non-text message]"

                message_data = {
                    "timestamp": msg.date.isoformat(),
                    "chat": {
                        "id": chat_id,
                        "title": chat_title,
                        "type": chat_type,
                    },
                    "message": message_text,
                }

                all_messages.append(message_data)
                message_count += 1

        except FloodWaitError as e:
            wait_seconds = e.seconds
            logger.warning(f"      ⏳ Flood wait: {wait_seconds}s. Waiting...")
            await asyncio.sleep(wait_seconds)
            # Retry this dialog after wait
            try:
                async for msg in client.iter_messages(
                    dialog.entity,
                    offset_date=cutoff_date,
                    reverse=True,
                ):
                    if msg.date.replace(tzinfo=None) < cutoff_date:
                        continue

                    message_text = msg.text or "[Non-text message]"

                    message_data = {
                        "timestamp": msg.date.isoformat(),
                        "chat": {
                            "id": chat_id,
                            "title": chat_title,
                            "type": chat_type,
                        },
                        "message": message_text,
                    }

                    all_messages.append(message_data)
                    message_count += 1
            except Exception as retry_err:
                logger.error(f"      ❌ Retry failed for {chat_title}: {retry_err}")

        except Exception as e:
            logger.error(f"      ❌ Error fetching from {chat_title}: {e}")
            continue

        if message_count > 0:
            logger.info(f"      ✅ {message_count} messages fetched")

    return all_messages


def save_messages(messages: list):
    """Save all fetched messages to a JSON file."""
    output_path = Path(OUTPUT_DIR)
    output_path.mkdir(parents=True, exist_ok=True)

    today_str = date.today().isoformat()
    file_path = output_path / f"fetched_{today_str}.json"

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)

    return file_path


async def main():
    """Main entry point."""
    credentials = load_environment()
    if credentials is None:
        return

    api_id_str, api_hash, phone_number = credentials

    try:
        api_id = int(api_id_str)
    except ValueError:
        logger.error("API_ID must be a valid integer!")
        return

    client = TelegramClient(
        SESSION_FILE,
        api_id,
        api_hash,
        connection=ConnectionTcpFull,
        connection_retries=5,
        request_retries=5,
    )

    try:
        await client.start(phone=phone_number)

        if not await client.is_user_authorized():
            logger.info("🔐 Session not found or expired. Requesting login code...")
            await client.send_code_request(phone_number)
            code = input("📱 Enter the code you received on Telegram: ").strip()

            try:
                await client.sign_in(phone_number, code)
            except SessionPasswordNeededError:
                password = input("🔑 Two-factor auth enabled. Enter your password: ").strip()
                await client.sign_in(password=password)

        me = await client.get_me()
        logger.info(f"✅ Logged in as: {me.first_name} (@{me.username or 'no username'})")

        # Fetch messages from last 10 days
        messages = await fetch_all_messages(client, days=10)

        # Save to file
        file_path = save_messages(messages)

        # Summary
        total = len(messages)
        print("\n" + "=" * 50)
        print(f"📊 FETCH COMPLETE")
        print(f"   Total messages: {total}")
        print(f"   Saved to:       {file_path}")
        print("=" * 50 + "\n")

        # Quick preview
        if messages:
            print("📋 First 3 messages preview:")
            for i, msg in enumerate(messages[:3], 1):
                ts = msg["timestamp"][:19]  # YYYY-MM-DDTHH:MM:SS
                chat = msg["chat"]["title"]
                text = msg["message"][:80]
                print(f"   {i}. [{ts}] [{chat}] {text}")
            if total > 3:
                print(f"   ... and {total - 3} more messages")

    except KeyboardInterrupt:
        logger.info("\n🛑 Stopped by user.")
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass