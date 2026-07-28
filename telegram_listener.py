#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Telegram Message Listener
Real-time Telegram message listener using Telethon.
Saves messages to a JSON file with timestamp, chat, sender, and content.
"""

import os
import json
import asyncio
import logging
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError

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
MESSAGES_FILE = "telegram_messages.json"


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
    """Append a message to the JSON messages file."""
    messages = []
    if Path(MESSAGES_FILE).exists():
        try:
            with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
                messages = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            messages = []

    messages.append(message_data)

    with open(MESSAGES_FILE, "w", encoding="utf-8") as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)

    logger.info(f"💾 Message saved to {MESSAGES_FILE}")


async def main():
    """Main entry point for the Telegram listener."""
    # Load credentials
    credentials = load_environment()
    if credentials is None:
        return

    api_id, api_hash, phone_number = credentials

    # Ensure API_ID is an integer
    try:
        api_id = int(api_id)
    except ValueError:
        logger.error("API_ID must be a valid integer!")
        return

    # Create the Telegram client
    client = TelegramClient(SESSION_FILE, api_id, api_hash)

    try:
        # Start the client
        await client.start(phone=phone_number)

        # Check if authorized
        if not await client.is_user_authorized():
            logger.info("🔐 Session not found or expired. Requesting login code...")
            await client.send_code_request(phone_number)
            code = input("📱 Enter the code you received on Telegram: ").strip()

            try:
                await client.sign_in(phone_number, code)
            except SessionPasswordNeededError:
                password = input("🔑 Two-factor authentication enabled. Enter your password: ").strip()
                await client.sign_in(password=password)

        logger.info("✅ Successfully connected to Telegram!")
        me = await client.get_me()
        logger.info(f"👤 Logged in as: {me.first_name} (@{me.username or 'no username'})")
        logger.info(f"👂 Listening for messages... (saving to {MESSAGES_FILE})")
        print("\n" + "=" * 50)
        print("🟢 LISTENER IS RUNNING")
        print("   Press Ctrl+C to stop")
        print("=" * 50 + "\n")

        @client.on(events.NewMessage)
        async def handle_new_message(event):
            """Handle incoming new messages."""
            try:
                chat = await event.get_chat()
                sender = await event.get_sender()

                # Get chat name
                chat_title = getattr(chat, "title", None) or getattr(chat, "username", None) or str(chat.id)
                # Get sender name
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
                print(
                    f"\n[{message_data['timestamp']}]"
                    f"\n   💬 Chat:    {chat_title}"
                    f"\n   👤 From:    {sender_name}"
                    f"\n   📝 Message: {message_text}"
                    f"\n   {'─' * 40}"
                )

                # Save to file
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

                print(
                    f"\n✏️ [EDITED] [{message_data['timestamp']}]"
                    f"\n   💬 Chat:    {chat_title}"
                    f"\n   👤 From:    {sender_name}"
                    f"\n   📝 Message: {message_text}"
                    f"\n   {'─' * 40}"
                )

                save_message(message_data)

            except Exception as e:
                logger.error(f"Error processing edited message: {e}")

        # Keep the script running
        await client.run_until_disconnected()

    except KeyboardInterrupt:
        logger.info("\n🛑 Stopping listener...")
    except Exception as e:
        logger.error(f"❌ An error occurred: {e}")
    finally:
        await client.disconnect()
        logger.info("👋 Disconnected from Telegram.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass