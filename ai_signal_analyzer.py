#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AI Destekli Telegram Sinyal Analiz Aracı
messages/ klasöründeki mesajları DeepSeek API ile analiz eder,
sinyal bilgilerini çıkarır ve mesajları günceller.
"""

import os
import json
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

ENV_FILE = ".env"
MESSAGES_DIR = Path("messages")
API_URL = "https://api.deepseek.com/v1/chat/completions"
MODEL = "deepseek-v4-flash"
CHUNK_SIZE = 10
MAX_CONCURRENT = 10
MAX_RETRIES = 3

SYSTEM_PROMPT = """For each message in the input array, output EXACTLY ONE object with the SAME timestamp and chat_id.

Return ONLY a JSON array, nothing else. Format for each:
{"timestamp":"same","chat_id":same,"signal":bool,"entry_point":str or null,"sl":number or null,"tp_n":int,"tp1":number or null,"tp2":number or null,"tp3":number or null,...}

Rules:
- signal=true ONLY if the message ITSELF contains a NEW trade setup with explicit entry, SL, and TP levels
- CRITICAL: Messages reporting RESULTS or UPDATES of a previous trade are NOT signals. These often contain words like:
  "HIT", "TP 1 HIT", "TP2HIT", "SL HIT", "profit", "Running", "BOOM", "BOOM BOOM",
  "delivered", "target reached", "target hit", "first target", "pips", "REACHED",
  "ENJOY PROFIT", "DONE", "settle", "settled", "success", "sweet"
  Such messages MUST have signal=false, even if they mention BUY/SELL/gold/XAUUSD.
- If a message only says something like "GOLD BUY Running 40+ pips Profit" without explicit entry+SL+TP levels -> signal=false
- entry_point: "4124" or "4124-4116" format, null if none
- sl: single number, null if none
- tp_n: total count of ALL TP levels (0 if none)
- ALL TP levels MUST be listed individually as tp1, tp2, tp3, ... tpN
- If a message has "TP: 4040, 4046, 4051" then output tp1=4040, tp2=4046, tp3=4051, tp_n=3
- Do NOT combine multiple TPs into a single tp field
- You MUST output exactly as many objects as there were input messages"""


def load_api_key() -> Optional[str]:
    """Load DeepSeek API key from .env file."""
    env_path = Path(ENV_FILE)
    if not env_path.exists():
        logger.error(f"{ENV_FILE} file not found!")
        return None

    load_dotenv(env_path)
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        logger.error("DEEPSEEK_API_KEY not found in .env file!")
        return None

    return api_key


def get_unanalyzed_files() -> list[Path]:
    """Get message files that are NOT fully analyzed (no _analyzed suffix).
    The latest (newest) file is always kept unanalyzed to allow new messages to be added."""
    if not MESSAGES_DIR.exists():
        logger.error(f"Directory {MESSAGES_DIR}/ does not exist!")
        return []

    all_files = sorted(MESSAGES_DIR.glob("messages_*.json"))
    unanalyzed = [f for f in all_files if not f.stem.endswith("_analyzed")]

    # If the newest file exists and is not analyzed, keep it unanalyzed
    # to allow new messages to be added later
    return unanalyzed


def load_messages_from_file(file_path: Path) -> list[dict]:
    """Load messages from a JSON file."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            messages = json.load(f)
        if isinstance(messages, list):
            return messages
        else:
            logger.warning(f"{file_path.name}: Not a list, skipping.")
            return []
    except (json.JSONDecodeError, FileNotFoundError) as e:
        logger.error(f"{file_path.name}: Read error - {e}")
        return []


def save_messages_to_file(file_path: Path, messages: list[dict]):
    """Save messages to a JSON file."""
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(messages, f, ensure_ascii=False, indent=2)
        logger.info(f"💾 Saved {len(messages)} messages to {file_path.name}")
    except Exception as e:
        logger.error(f"Failed to save {file_path.name}: {e}")


def rename_to_analyzed(file_path: Path) -> bool:
    """Rename a file from messages_YYYY-MM-DD.json to messages_YYYY-MM-DD_analyzed.json."""
    analyzed_path = file_path.with_name(
        file_path.stem + "_analyzed" + file_path.suffix
    )
    try:
        if analyzed_path.exists():
            analyzed_path.unlink()
        file_path.rename(analyzed_path)
        logger.info(f"📦 Renamed {file_path.name} -> {analyzed_path.name}")
        return True
    except Exception as e:
        logger.error(f"Failed to rename {file_path.name}: {e}")
        return False


def get_unanalyzed_messages(messages: list[dict]) -> list[dict]:
    """Get messages that haven't been analyzed yet."""
    return [msg for msg in messages if not msg.get("analyzed", False)]


def build_chunks(messages: list[dict]) -> list[list[dict]]:
    """Split messages into chunks of CHUNK_SIZE."""
    return [messages[i:i + CHUNK_SIZE] for i in range(0, len(messages), CHUNK_SIZE)]


def prepare_api_messages(chunk: list[dict]) -> list[dict]:
    """Prepare the API request body for a chunk."""
    simplified = [{
        "timestamp": msg.get("timestamp", ""),
        "chat_id": msg.get("chat_id", 0),
        "message": msg.get("message", ""),
    } for msg in chunk]

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(simplified, ensure_ascii=False)},
    ]


async def analyze_chunk(
    client: httpx.AsyncClient,
    chunk: list[dict],
    api_key: str,
    sem: asyncio.Semaphore,
) -> Optional[list[dict]]:
    """Send a chunk to DeepSeek API for analysis."""
    async with sem:
        for attempt in range(MAX_RETRIES):
            try:
                payload = {
                    "model": MODEL,
                    "messages": prepare_api_messages(chunk),
                    "temperature": 0.01,
                    "max_tokens": 16384,
                }

                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }

                logger.info(
                    f"📤 Sending {len(chunk)} msgs (attempt {attempt + 1})..."
                )

                response = await client.post(
                    API_URL, json=payload, headers=headers, timeout=120.0
                )
                response.raise_for_status()

                result = response.json()
                choice = result["choices"][0]["message"]

                content = (choice.get("content") or choice.get("reasoning_content") or "").strip()
                if not content:
                    logger.warning(f"⚠️ Empty response, retrying (attempt {attempt + 1})...")
                    await asyncio.sleep(2 ** attempt)
                    continue

                # Strip markdown if present
                if content.startswith("```"):
                    lines = [l for l in content.splitlines() if not l.strip().startswith("```")]
                    content = "\n".join(lines).strip()

                analyzed_data = json.loads(content)
                if not isinstance(analyzed_data, list):
                    logger.error(f"Response not a list: {type(analyzed_data)}")
                    continue

                logger.info(f"✅ Got {len(analyzed_data)} results")
                return analyzed_data

            except httpx.TimeoutException:
                logger.warning(f"⏱️  Timeout attempt {attempt + 1}")
                await asyncio.sleep(2 ** attempt)
            except httpx.HTTPStatusError as e:
                logger.error(f"❌ HTTP {e.response.status_code}")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    return None
            except (json.JSONDecodeError, ValueError, KeyError, IndexError) as e:
                logger.error(f"❌ Parse error: {e} (attempt {attempt + 1})")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    return None

        return None


def merge_analysis_results(
    original_messages: list[dict],
    analyzed_results: list[dict],
) -> int:
    """Merge AI analysis results back into original messages."""
    lookup = {}
    for result in analyzed_results:
        ts = result.get("timestamp", "")
        cid = result.get("chat_id", 0)
        lookup[(ts, cid)] = result

    now = datetime.now().isoformat()
    updated = 0

    for msg in original_messages:
        if msg.get("analyzed", False):
            continue

        key = (msg.get("timestamp", ""), msg.get("chat_id", 0))
        if key not in lookup:
            continue

        result = lookup[key]
        msg["analyzed"] = True
        msg["analysis_timestamp"] = now
        is_signal = result.get("signal", False)

        if is_signal:
            msg["signal"] = True
            msg["entry_point"] = result.get("entry_point")
            msg["sl"] = result.get("sl")
            # Collect all individual TP levels (tp1, tp2, tp3, ...)
            tp_n = 0
            for key, value in result.items():
                if key.startswith("tp") and key[2:].isdigit() and isinstance(value, (int, float)):
                    idx = int(key[2:])
                    msg[key] = value
                    tp_n = max(tp_n, idx)
            msg["tp_n"] = tp_n
        else:
            msg["signal"] = False

        updated += 1

    return updated


async def process_file(file_path: Path, api_key: str, sem: asyncio.Semaphore) -> bool:
    """Process a single message file."""
    logger.info(f"\n{'='*60}")
    logger.info(f"📂 Processing: {file_path.name}")

    messages = load_messages_from_file(file_path)
    if not messages:
        return False

    total = len(messages)
    unanalyzed = get_unanalyzed_messages(messages)

    if not unanalyzed:
        logger.info(f"✅ All {total} already analyzed. Renaming...")
        rename_to_analyzed(file_path)
        return True

    logger.info(f"🔍 {len(unanalyzed)}/{total} unanalyzed")

    chunks = build_chunks(unanalyzed)
    logger.info(f"📦 {len(chunks)} chunks of {CHUNK_SIZE}")

    async with httpx.AsyncClient(timeout=120.0) as client:
        tasks = [analyze_chunk(client, c, api_key, sem) for c in chunks]
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            logger.error(f"❌ Gather error: {e}")
            results = [None] * len(tasks)

    total_updated = 0
    failed = 0

    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"❌ Chunk {i + 1} exception: {result}")
            failed += 1
        elif result is not None:
            updated = merge_analysis_results(messages, result)
            total_updated += updated
        else:
            logger.error(f"❌ Chunk {i + 1} failed")
            failed += 1

    save_messages_to_file(file_path, messages)
    logger.info(f"📈 Updated {total_updated} msgs")

    if failed > 0:
        logger.warning(f"⚠️  {failed}/{len(chunks)} chunks failed")
        return False

    remaining = get_unanalyzed_messages(messages)
    if not remaining:
        # Check if this is the latest (newest) file - if so, don't rename
        all_files = sorted(Path(MESSAGES_DIR).glob("messages_*.json"))
        unanalyzed_files = [f for f in all_files if not f.stem.endswith("_analyzed")]
        is_latest_file = len(unanalyzed_files) == 1 and unanalyzed_files[0] == file_path

        if is_latest_file:
            logger.info(f"📌 Latest file '{file_path.name}' kept unanalyzed for future messages")
        else:
            logger.info(f"🎉 All done! Renaming...")
            rename_to_analyzed(file_path)
    else:
        logger.info(f"⏳ {len(remaining)} remaining for next run")
        logger.info(f"   (expected: model sometimes returns fewer results than input)")

    return True


async def main():
    """Main entry point with retry loop for failed chunks."""
    script_dir = Path(__file__).parent
    os.chdir(script_dir)
    print(f"\n📁 Working: {script_dir}")

    print("=" * 60)
    print("  🤖 AI SIGNAL ANALYZER")
    print("=" * 60)

    api_key = load_api_key()
    if not api_key:
        return

    max_passes = 3
    for pass_num in range(1, max_passes + 1):
        files = get_unanalyzed_files()
        if not files:
            logger.info("✅ All files analyzed!")
            break

        logger.info(f"\n{'='*60}")
        logger.info(f"📁 Pass {pass_num}/{max_passes}: {len(files)} file(s): {[f.name for f in files]}")
        sem = asyncio.Semaphore(MAX_CONCURRENT)

        for f in files:
            await process_file(f, api_key, sem)

        if pass_num < max_passes:
            remaining = sum(len(get_unanalyzed_messages(load_messages_from_file(f))) for f in get_unanalyzed_files())
            if remaining == 0:
                break
            logger.info(f"⏳ {remaining} messages remaining across all files, retrying...")

    logger.info("\n✅ Done!")


if __name__ == "__main__":
    asyncio.run(main())