#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
messages/ klasöründeki tüm JSON dosyalarını doğruluk kontrolünden geçirir.
Her mesajın kurallara uygun olup olmadığını kontrol eder ve raporlar.
"""

import os
import json
import sys
from pathlib import Path
from datetime import datetime

MESSAGES_DIR = Path("messages")

# Global counters
total_errors = 0
total_warnings = 0
error_list = []


def reset():
    global total_errors, total_warnings, error_list
    total_errors = 0
    total_warnings = 0
    error_list = []


def err(msg: str, file: str, idx: int):
    global total_errors, error_list
    total_errors += 1
    entry = f"  ❌ [{file}#{idx}] {msg}"
    error_list.append(entry)
    print(entry)


def warn(msg: str, file: str, idx: int):
    global total_warnings
    total_warnings += 1
    print(f"  ⚠️  [{file}#{idx}] {msg}")


def validate_field_type(msg: dict, field: str, expected_type, file: str, idx: int) -> bool:
    """Validate that a field exists and has the expected type. Returns True if valid."""
    if field not in msg:
        err(f"Missing required field: '{field}'", file, idx)
        return False
    val = msg[field]
    if not isinstance(val, expected_type):
        err(f"Field '{field}' should be {expected_type.__name__}, got {type(val).__name__}: {val}", file, idx)
        return False
    return True


def check_no_field(msg: dict, field: str, file: str, idx: int) -> bool:
    """Check that a field does NOT exist. Returns True if absent (valid)."""
    if field in msg:
        err(f"Field '{field}' should NOT exist (found: {msg[field]})", file, idx)
        return False
    return True


def validate_messages(messages: list[dict], file_name: str):
    """Validate all messages in a file against the rules."""
    for idx, msg in enumerate(messages):
        # --- Rule 0: Every message must have timestamp and chat_id ---
        validate_field_type(msg, "timestamp", str, file_name, idx)
        has_chat_id = "chat_id" in msg
        if not has_chat_id:
            err("Missing 'chat_id' field", file_name, idx)
        elif not isinstance(msg["chat_id"], int):
            # chat_id can be int or possibly missing from fetched messages
            if not isinstance(msg["chat_id"], (int, str)):
                err(f"chat_id should be int/str, got {type(msg['chat_id']).__name__}: {msg['chat_id']}", file_name, idx)

        analyzed = msg.get("analyzed", False)

        if not analyzed:
            # --- Rule: Not analyzed messages should NOT have signal fields ---
            if "signal" in msg:
                warn(f"Not analyzed but has 'signal' field (will be ignored)", file_name, idx)
            if "entry_point" in msg:
                warn(f"Not analyzed but has 'entry_point' field", file_name, idx)
            if "sl" in msg:
                warn(f"Not analyzed but has 'sl' field", file_name, idx)
            if "tp_n" in msg:
                warn(f"Not analyzed but has 'tp_n' field", file_name, idx)
            continue  # Skip further checks for non-analyzed messages

        # ============================================================
        # RULES FOR analyzed: true messages
        # ============================================================

        # --- Rule 1: analyzed=true MUST have 'signal' field ---
        if "signal" not in msg:
            err("analyzed=true but missing 'signal' field", file_name, idx)
            continue

        signal_val = msg["signal"]
        is_true = signal_val is True or signal_val == "True"
        is_false = signal_val is False or signal_val == "False"

        if not is_true and not is_false:
            err(f"Invalid 'signal' value: {signal_val} (expected true/false)", file_name, idx)
            continue

        # Ensure Boolean type
        if isinstance(signal_val, str):
            warn(f"'signal' is string '{signal_val}' instead of bool", file_name, idx)

        signal = is_true

        # --- Rule 2: Check for forbidden 'tp' field (should be tp1, tp2...) ---
        if "tp" in msg:
            err("Deprecated 'tp' field found (use tp1, tp2, ... instead)", file_name, idx)

        if signal:
            # ============================================================
            # RULES FOR signal: true
            # ============================================================

            # --- entry_point should exist and be a non-empty string ---
            if "entry_point" not in msg:
                warn("signal=true but missing 'entry_point' (model limitation)", file_name, idx)
            else:
                ep = msg["entry_point"]
                if ep is None or (isinstance(ep, str) and not ep.strip()):
                    warn("signal=true but 'entry_point' is null/empty (model limitation)", file_name, idx)
                elif not isinstance(ep, str):
                    warn(f"signal=true but 'entry_point' is not string: {type(ep).__name__}: {ep}", file_name, idx)

            # --- sl must be a number ---
            if "sl" not in msg:
                err("signal=true but missing 'sl'", file_name, idx)
            else:
                sl = msg["sl"]
                if sl is None:
                    err("signal=true but 'sl' is null", file_name, idx)
                elif not isinstance(sl, (int, float)):
                    err(f"signal=true but 'sl' is not number: {type(sl).__name__}: {sl}", file_name, idx)

            # --- tp_n must be int >= 1 ---
            if "tp_n" not in msg:
                err("signal=true but missing 'tp_n'", file_name, idx)
            else:
                tp_n = msg["tp_n"]
                if not isinstance(tp_n, int):
                    err(f"signal=true but 'tp_n' is not int: {type(tp_n).__name__}: {tp_n}", file_name, idx)
                elif tp_n < 1:
                    err(f"signal=true but 'tp_n' is {tp_n} (should be >= 1)", file_name, idx)
                else:
                    # Check that tp1...tpN fields exist (model sometimes returns only tp1)
                    for i in range(1, tp_n + 1):
                        tp_key = f"tp{i}"
                        if tp_key not in msg:
                            warn(f"signal=true, tp_n={tp_n} but missing '{tp_key}' (model limitation - will be skipped for tp_n>1 without individual levels)", file_name, idx)
                            break  # Don't check further, model likely only returned tp1
                        else:
                            tp_val = msg[tp_key]
                            if tp_val is None:
                                warn(f"signal=true but '{tp_key}' is null", file_name, idx)
                            elif not isinstance(tp_val, (int, float)):
                                warn(f"signal=true but '{tp_key}' is not number: {type(tp_val).__name__}: {tp_val}", file_name, idx)

            # --- Check no extra signal-related null fields ---
            # (analysis_timestamp is allowed for both true and false)

        else:
            # ============================================================
            # RULES FOR signal: false
            # ============================================================

            # These fields MUST NOT exist
            forbidden = ["entry_point", "sl", "tp_n", "tp"]
            forbidden += [f"tp{i}" for i in range(1, 15)]  # tp1..tp14
            for field in forbidden:
                check_no_field(msg, field, file_name, idx)

        # --- Check analysis_timestamp format if present ---
        if "analysis_timestamp" in msg:
            ts = msg["analysis_timestamp"]
            if not isinstance(ts, str):
                err(f"'analysis_timestamp' is not string: {type(ts).__name__}", file_name, idx)
            else:
                try:
                    datetime.fromisoformat(ts)
                except ValueError:
                    warn(f"'analysis_timestamp' has invalid format: {ts}", file_name, idx)


def check_file(file_path: Path):
    """Validate a single JSON file."""
    global total_errors, total_warnings
    print(f"\n📂 {file_path.name}")

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            messages = json.load(f)
    except Exception as e:
        err(f"Cannot read file: {e}", file_path.name, -1)
        return

    if not isinstance(messages, list):
        err(f"File content is not a JSON array: {type(messages).__name__}", file_path.name, -1)
        return

    print(f"   Total messages: {len(messages)}")
    analyzed_count = sum(1 for m in messages if m.get("analyzed"))

    print(f"   Analyzed: {analyzed_count}, Unanalyzed: {len(messages) - analyzed_count}")

    # Run validation
    validate_messages(messages, file_path.name)


def check_summary(file_path: Path):
    """Print a summary without full validation details."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            messages = json.load(f)
    except Exception:
        return

    if not isinstance(messages, list):
        return

    # Stats
    total = len(messages)
    analyzed = sum(1 for m in messages if m.get("analyzed"))
    signals = sum(1 for m in messages if m.get("analyzed") and m.get("signal") is True)
    no_signals = sum(1 for m in messages if m.get("analyzed") and m.get("signal") is False)
    no_signal_field = sum(1 for m in messages if m.get("analyzed") and "signal" not in m)
    has_tp_field = sum(1 for m in messages if m.get("analyzed") and "tp" in m)
    has_dangling = sum(1 for m in messages if not m.get("analyzed") and "signal" in m)

    issues = []
    if no_signal_field > 0:
        issues.append(f"{no_signal_field} missing signal")
    if has_tp_field > 0:
        issues.append(f"{has_tp_field} with deprecated 'tp'")
    if has_dangling > 0:
        issues.append(f"{has_dangling} unanalyzed with signal field")

    extra = f" ⚠️  Issues: {', '.join(issues)}" if issues else " ✅ Clean"
    print(f"   {total} msgs | {analyzed} analyzed | {signals} signals | {no_signals} no-signal{extra}")


def main():
    print("=" * 60)
    print("  🔍 MESSAGE VALIDATION TOOL")
    print("  Tüm kurallara uygunluk kontrolü")
    print("=" * 60)

    # Change to script directory
    script_dir = Path(__file__).parent
    if script_dir != Path.cwd():
        os.chdir(script_dir)

    if not MESSAGES_DIR.exists():
        print(f"❌ Directory {MESSAGES_DIR}/ not found!")
        return

    all_files = sorted(MESSAGES_DIR.glob("messages_*.json"))
    if not all_files:
        print("❌ No JSON files found!")
        return

    print(f"\n📁 Found {len(all_files)} file(s):")
    print("-" * 60)

    # Quick summary first
    for f in all_files:
        check_summary(f)

    print("\n" + "=" * 60)
    print("  🔍 DETAILED VALIDATION")
    print("=" * 60)

    reset()

    run_detailed = len(sys.argv) > 1 and sys.argv[1] == "--all"
    if not run_detailed:
        print("\n💡 Use --all flag for detailed per-message validation")
        print("   (Skipping detailed check, showing summary only)\n")
        return

    for f in all_files:
        check_file(f)

    # Final summary
    print("\n" + "=" * 60)
    print("  📊 VALIDATION RESULTS")
    print("=" * 60)
    print(f"  ❌ Errors:   {total_errors}")
    print(f"  ⚠️  Warnings: {total_warnings}")

    if total_errors == 0:
        print("\n  ✅ ALL CHECKS PASSED! All files are valid.")
    else:
        print(f"\n  🔧 Fix required. Run: python fix_analyzed_messages.py --yes")

    print()


if __name__ == "__main__":
    main()