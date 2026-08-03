#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
XAUUSD Fiyat Verisi Çekme Aracı
messages/ klasöründeki mesajların zaman aralığına göre
MT5'ten XAUUSD 1-dakikalık OHLCV verilerini çeker,
data/ klasörüne CSV olarak kaydeder.
Maksimum +1 gün güncel tutar.
"""

import os
import csv
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import MetaTrader5 as mt5
import pandas as pd
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

ENV_FILE = ".env"
MESSAGES_DIR = Path("messages")
DATA_DIR = Path("data")
CSV_FILE = DATA_DIR / "xauusd_1m.csv"

SYMBOL = "XAUUSD"
TIMEFRAME = mt5.TIMEFRAME_M1


def load_env_mt5() -> Optional[dict]:
    """Load MT5 credentials from .env file."""
    env_path = Path(ENV_FILE)
    if not env_path.exists():
        logger.error(f"{ENV_FILE} not found!")
        return None

    load_dotenv(env_path)

    login = os.getenv("MT5_LOGIN")
    password = os.getenv("MT5_PASSWORD")
    server = os.getenv("MT5_SERVER")

    if not all([login, password, server]):
        logger.error("MT5_LOGIN, MT5_PASSWORD, MT5_SERVER not found in .env!")
        return None

    return {
        "login": int(login),
        "password": password,
        "server": server,
    }


def get_message_time_range() -> Optional[tuple]:
    """Scan messages/ folder and find earliest and latest timestamps.
    Returns (earliest_datetime, latest_datetime, latest_plus_1day)."""
    if not MESSAGES_DIR.exists():
        logger.error(f"Directory {MESSAGES_DIR}/ does not exist!")
        return None

    json_files = sorted(MESSAGES_DIR.glob("messages_*.json"))
    if not json_files:
        logger.error(f"No JSON files found in {MESSAGES_DIR}/!")
        return None

    earliest = None
    latest = None

    for file_path in json_files:
        # Skip _analyzed files for latest check (they're historical)
        pass

    for file_path in json_files:
        try:
            import json
            with open(file_path, "r", encoding="utf-8") as f:
                messages = json.load(f)
            if not isinstance(messages, list):
                continue
            for msg in messages:
                ts = msg.get("timestamp", "")
                if not ts:
                    continue
                try:
                    dt = datetime.fromisoformat(ts)
                    # Convert to timezone-naive for pandas
                    if dt.tzinfo is not None:
                        dt = dt.replace(tzinfo=None)
                    if earliest is None or dt < earliest:
                        earliest = dt
                    if latest is None or dt > latest:
                        latest = dt
                except (ValueError, TypeError):
                    continue
        except Exception:
            continue

    if earliest is None or latest is None:
        logger.error("Could not determine time range from messages!")
        return None

    logger.info(f"📅 Message time range: {earliest}  →  {latest}")

    return earliest, latest


def get_csv_last_time() -> Optional[datetime]:
    """Get the last timestamp from existing CSV file."""
    if not CSV_FILE.exists():
        return None

    try:
        df = pd.read_csv(CSV_FILE)
        if df.empty:
            return None
        # Parse timestamp column (ISO format)
        last_row = df.iloc[-1]
        last_ts = last_row["timestamp"]
        return datetime.fromisoformat(last_ts)
    except Exception as e:
        logger.warning(f"Could not read CSV: {e}")
        return None


def connect_mt5(creds: dict):
    """Connect to MetaTrader 5 terminal and return terminal info."""
    mt5_paths = [
        "C:\\Program Files\\MetaTrader 5\\terminal64.exe",
        "C:\\Program Files (x86)\\MetaTrader 5\\terminal64.exe",
    ]
    mt5_path = None
    for p in mt5_paths:
        if Path(p).exists():
            mt5_path = p
            break

    if mt5_path:
        logger.info(f"🖥️  MT5 found at: {mt5_path}")
        if not mt5.initialize(path=mt5_path):
            logger.error(f"MT5 initialize failed: {mt5.last_error()}")
            return None
    else:
        logger.info("🖥️  Trying MT5 without path...")
        if not mt5.initialize():
            logger.error(f"MT5 initialize failed: {mt5.last_error()}")
            return None

    authorized = mt5.login(creds["login"], password=creds["password"], server=creds["server"])
    if not authorized:
        logger.error(f"MT5 login failed: {mt5.last_error()}")
        mt5.shutdown()
        return None

    account_info = mt5.account_info()
    if account_info:
        logger.info(f"✅ MT5 connected: {account_info.name} (Server: {account_info.server})")
        # UTC offset sabit: XBTFX sunucusu UTC kullanıyor (yerel saat UTC+8)
        return {
            "account": account_info,
            "utc_offset": 0,  # MT5 data returns in UTC
        }
    return None


def fetch_xauusd_rates(from_dt: datetime, to_dt: datetime) -> Optional[pd.DataFrame]:
    """Fetch XAUUSD 1-minute rates from MT5 for the given date range.
    Fetches day by day to avoid MT5 limits on copy_rates_range."""
    logger.info(f"📥 Fetching XAUUSD from {from_dt} to {to_dt}...")

    mt5.symbol_select(SYMBOL, True)
    all_dfs = []

    current = from_dt
    while current < to_dt:
        chunk_end = min(current + timedelta(days=1), to_dt)
        
        logger.info(f"   📦 Chunk: {current} → {chunk_end}")
        rates = mt5.copy_rates_range(SYMBOL, TIMEFRAME, current, chunk_end)

        if rates is not None and len(rates) > 0:
            df = pd.DataFrame(rates)
            df["timestamp"] = pd.to_datetime(df["time"], unit="s")
            df = df[["timestamp", "open", "high", "low", "close", "tick_volume"]]
            df["timestamp"] = df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
            all_dfs.append(df)
            logger.info(f"      ✅ {len(df)} candles")
        elif rates is not None:
            logger.info(f"      ⏳ No data (weekend?)")
        else:
            logger.info(f"      ⚠️  Error: {mt5.last_error()}")

        current = chunk_end

    if not all_dfs:
        logger.warning("No data returned for any chunk!")
        return None

    combined = pd.concat(all_dfs)
    combined = combined.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

    logger.info(f"✅ Total: {len(combined)} candles")
    return combined


def save_to_csv(df: pd.DataFrame):
    """Save DataFrame to CSV, appending if file exists and handling duplicates."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if CSV_FILE.exists():
        # Read existing data
        existing = pd.read_csv(CSV_FILE, parse_dates=["timestamp"])

        # Convert new data timestamp for comparison
        df_parse = df.copy()
        df_parse["timestamp"] = pd.to_datetime(df_parse["timestamp"])

        # Combine and remove duplicates
        combined = pd.concat([existing, df_parse])
        combined = combined.drop_duplicates(subset=["timestamp"], keep="last")
        combined = combined.sort_values("timestamp").reset_index(drop=True)

        # Convert back to string for saving
        combined["timestamp"] = combined["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
        combined.to_csv(CSV_FILE, index=False)

        logger.info(f"💾 Appended: {len(df)} new rows (total: {len(combined)})")
    else:
        # First time: save directly
        df.to_csv(CSV_FILE, index=False)
        logger.info(f"💾 Created: {len(df)} rows")


def main():
    print("=" * 60)
    print("  📥 XAUUSD Fiyat Verisi Çekme")
    print("  MT5 → data/xauusd_1m.csv")
    print("=" * 60)

    # Change to script directory
    script_dir = Path(__file__).parent
    if script_dir != Path.cwd():
        os.chdir(script_dir)

    # Load MT5 credentials
    creds = load_env_mt5()
    if not creds:
        return

    # Get message time range
    time_range = get_message_time_range()
    if not time_range:
        return

    earliest_msg, latest_msg = time_range

    # Calculate fetch range (MT5 returns data in UTC)
    # Start: earliest message time converted to UTC (minus 1 hour buffer)
    # Messages are recorded in UTC+8 (Asia/Shanghai local time)
    fetch_from = (earliest_msg - timedelta(hours=8)) - timedelta(hours=1)
    # End: min(now_utc, latest_message_UTC + 1 day)
    # Son mesaja 1 gün ekleyerek çeker, ama maksimum şu an ile sınırlar.
    now_utc = datetime.utcnow()
    latest_msg_utc = latest_msg - timedelta(hours=8)  # UTC+8 -> UTC
    fetch_to = min(now_utc, latest_msg_utc + timedelta(days=1))

    # Check if we already have data
    csv_last = get_csv_last_time()
    if csv_last is not None:
        logger.info(f"📂 Existing CSV last entry: {csv_last}")
        # Only fetch what's missing
        if csv_last >= fetch_to:
            logger.info("✅ Data is already up to date!")
            return
        fetch_from = max(fetch_from, csv_last)
    else:
        logger.info("📂 No existing CSV, will create new")

    logger.info(f"🔍 Fetch range: {fetch_from}  →  {fetch_to}")

    # Connect to MT5
    mt5_info = connect_mt5(creds)
    if not mt5_info:
        return

    # MT5 server is UTC. The from/to datetimes are naive UTC values.
    # Make them timezone-aware (UTC) so MetaTrader5 converts them with
    # .timestamp() correctly. Without this, Python would interpret the
    # naive datetimes in local time (UTC+8), causing an 8-hour shift.
    fetch_from_aware = fetch_from.replace(tzinfo=timezone.utc)
    fetch_to_aware = fetch_to.replace(tzinfo=timezone.utc)

    try:
        # Fetch data
        df = fetch_xauusd_rates(fetch_from_aware, fetch_to_aware)

        if df is not None and not df.empty:
            save_to_csv(df)
            # Print stats
            print(f"\n  📊 XAUUSD Data Summary:")
            print(f"     Rows: {len(df)}")
            print(f"     From: {df['timestamp'].iloc[0]}")
            print(f"     To:   {df['timestamp'].iloc[-1]}")
            print(f"     File: {CSV_FILE}")
        else:
            logger.warning("No data fetched (weekend/market closed?)")

    finally:
        mt5.shutdown()
        logger.info("🔌 MT5 disconnected")

    print("\n✅ Done!")


if __name__ == "__main__":
    main()