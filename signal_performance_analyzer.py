#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Signal Performance Analyzer
messages/ klasöründeki analiz edilmiş sinyalleri XAUUSD fiyat verisi ile karşılaştırır,
her sinyalin önce TP'ye mi yoksa SL'ye mi ulaştığını kontrol eder,
chat_id bazında rapor hazırlar.

Zaman Dönüşümü:
  - Mesaj timestamp: UTC+8 (Asia/Shanghai, datetime.now().isoformat())
  - XAUUSD CSV timestamp: UTC (MT5'ten gelen)
  - Karşılaştırma için mesaj zamanından 8 saat çıkarılır

Önemli:
  - messages/ ve data/ klasörlerine YAZMAZ, sadece OKUR
  - Raporu reports/ klasörüne yazar
"""

import json
import csv
import os
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

# === KONFİGÜRASYON ===
MESSAGES_DIR = Path("messages")
DATA_DIR = Path("data")
REPORTS_DIR = Path("reports")
CSV_FILE = DATA_DIR / "xauusd_1m.csv"

# XAUUSD pip değeri: 1 pip = 0.1 fiyat hareketi
PIP_VALUE = 0.1


def load_messages() -> list[dict]:
    """Load all analyzed + signal=true messages from all JSON files."""
    if not MESSAGES_DIR.exists():
        print(f"❌ {MESSAGES_DIR}/ klasörü bulunamadı!")
        return []

    all_files = sorted(MESSAGES_DIR.glob("messages_*.json"))
    if not all_files:
        print("❌ Hiç JSON dosyası bulunamadı!")
        return []

    signals = []
    for file_path in all_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                msgs = json.load(f)
        except Exception as e:
            print(f"  ⚠️  {file_path.name} okunamadı: {e}")
            continue

        for msg in msgs:
            if msg.get("analyzed") is True and msg.get("signal") is True:
                signals.append(msg)

    return signals


def load_price_data() -> list[dict]:
    """Load XAUUSD 1-minute OHLCV data from CSV (UTC timestamps)."""
    if not CSV_FILE.exists():
        print(f"❌ {CSV_FILE} bulunamadı! Önce fetch_xauusd_data.py çalıştırın.")
        return []

    rows = []
    try:
        with open(CSV_FILE, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
    except Exception as e:
        print(f"❌ CSV okuma hatası: {e}")
        return []

    return rows


def msg_timestamp_to_utc(ts_str: str):
    """
    Mesaj timestamp'ini (UTC+8) UTC'ye çevirir.
    Örn: "2026-07-30T01:53:41.089947" UTC+8 → 2026-07-29T17:53:41 UTC
    """
    try:
        if "." in ts_str:
            dt_local = datetime.strptime(ts_str.split(".")[0], "%Y-%m-%dT%H:%M:%S")
        else:
            dt_local = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S")
        dt_utc = dt_local - timedelta(hours=8)
        return dt_utc
    except (ValueError, TypeError):
        return None


def check_tp_sl_result(direction: str, actual_entry: float, sl: float, tp_levels: list, price_rows: list[dict], start_idx: int) -> dict:
    """
    Sinyal sonrası fiyat hareketini kontrol et.
    
    Mantık:
      1. TP/SL kontrolüne sinyalden sonraki mumlarda devam edilir (tüm veri).
      2. SL hit olursa DURULMAZ — max zarar takibi ve TP dönüşü izlenir.
      3. SL sonrası TP vurulursa analiz DURUR (durma koşulu TP).
      4. SL hit olmadıysa ilk TP vurulunca normal durur.
      5. max_adverse_price: Girişten en aleyhte gidilen nokta (en büyük anlık zarar).
    
    Parametreler:
      - direction: "SELL" veya "BUY"
      - actual_entry: Gerçek girilen fiyat (market_price - orijinal entry'ye göre adjust edilmiş)
      - sl: Adjust edilmiş SL seviyesi (actual_entry'e göre kaydırılmış)
      - tp_levels: Adjust edilmiş TP seviyeleri
      - price_rows: XAUUSD mum verisi
      - start_idx: Kontrolün başlayacağı mum indeksi
    """
    result = {
        "first_hit": None,  # "tp" veya "sl" veya "none"
        "tp_hit": False,
        "sl_hit": False,
        "tp_hit_count": 0,
        "last_tp_hit": None,  # En son vurulan TP seviyesi (adjust edilmiş)
        # SL sonrası analiz
        "sl_hit_price": None,          # SL'nin vurulduğu fiyat noktası
        "sl_hit_at": None,             # SL'nin vurulduğu mum indeksi (start_idx'den itibaren)
        "tp_hit_after_sl": False,      # SL aşıldıktan SONRA TP'ye dönüldü mü
        "tp_hit_after_sl_count": 0,    # SL sonrası vurulan TP seviyesi sayısı
        "last_tp_after_sl": None,      # SL sonrası vurulan son TP seviyesi
        "candles_sl_to_tp": None,      # SL aşımından TP dönüşüne kadar geçen mum
        "max_adverse_price": actual_entry,  # Girişten en aleyhte gidilen fiyat (maks zarar noktası)
        # Geçmiş alanlar
        "max_favorable": actual_entry,  # En lehte gidilen fiyat
        "min_favorable": actual_entry,  # En aleyhte gidilen fiyat
        "checked_candles": 0,
    }

    if not price_rows:
        return result

    # Her TP için ayrı hit bayrağı (aynı TP birden fazla mumda sayılmasın)
    tp_hit_flags = [False] * len(tp_levels)

    # Sinyal sonrası TÜM veriye kadar kontrol (MAX_CHECK_MINUTES yok)
    for i in range(start_idx, len(price_rows)):
        try:
            candle_high = float(price_rows[i]["high"])
            candle_low = float(price_rows[i]["low"])
        except (ValueError, KeyError):
            continue

        result["checked_candles"] += 1

        # Her mumda en aleyhte noktayı güncelle (maks zarar takibi)
        if direction == "SELL":
            # SELL'de zarar = fiyatın yukarı gitmesi
            result["max_adverse_price"] = max(result["max_adverse_price"], candle_high)
        else:
            # BUY'da zarar = fiyatın aşağı gitmesi
            result["max_adverse_price"] = min(result["max_adverse_price"], candle_low)

        if direction == "SELL":
            # SELL: fiyatın düşmesi beklenir
            # SL yukarıda: fiyat SL'yi yukarı kırarsa zarar
            # TP aşağıda: fiyat TP'yi aşağı kırarsa kar

            # SL kontrolü (fiyat yükseliyor)
            if sl is not None and candle_high >= sl:
                if not result["sl_hit"]:
                    result["sl_hit"] = True
                    result["sl_hit_price"] = sl
                    result["sl_hit_at"] = result["checked_candles"]
                    if result["first_hit"] is None:
                        result["first_hit"] = "sl"

            # TP kontrolü (fiyat düşüyor)
            for tp_idx, tp in enumerate(tp_levels):
                if tp is not None and not tp_hit_flags[tp_idx] and candle_low <= tp:
                    tp_hit_flags[tp_idx] = True
                    result["tp_hit"] = True
                    result["tp_hit_count"] += 1
                    result["last_tp_hit"] = tp
                    if result["first_hit"] is None:
                        result["first_hit"] = "tp"
                    # SL sonrası TP vurulduysa kaydet
                    if result["sl_hit"]:
                        result["tp_hit_after_sl"] = True
                        result["tp_hit_after_sl_count"] += 1
                        result["last_tp_after_sl"] = tp
                        if result["candles_sl_to_tp"] is None:
                            result["candles_sl_to_tp"] = result["checked_candles"] - result["sl_hit_at"]

            # Durma koşulu:
            # - SL hit olduysa: TP dönüşü olana kadar devam et, TP vurulunca dur
            # - SL hit olmadıysa: TP vurulunca dur
            if result["sl_hit"]:
                if result["tp_hit_after_sl"]:
                    break
            elif result["tp_hit"]:
                break

        else:  # BUY
            # BUY: fiyatın yükselmesi beklenir
            # SL aşağıda: fiyat SL'yi aşağı kırarsa zarar
            # TP yukarıda: fiyat TP'yi yukarı kırarsa kar

            # SL kontrolü (fiyat düşüyor)
            if sl is not None and candle_low <= sl:
                if not result["sl_hit"]:
                    result["sl_hit"] = True
                    result["sl_hit_price"] = sl
                    result["sl_hit_at"] = result["checked_candles"]
                    if result["first_hit"] is None:
                        result["first_hit"] = "sl"

            # TP kontrolü (fiyat yükseliyor)
            for tp_idx, tp in enumerate(tp_levels):
                if tp is not None and not tp_hit_flags[tp_idx] and candle_high >= tp:
                    tp_hit_flags[tp_idx] = True
                    result["tp_hit"] = True
                    result["tp_hit_count"] += 1
                    result["last_tp_hit"] = tp
                    if result["first_hit"] is None:
                        result["first_hit"] = "tp"
                    # SL sonrası TP vurulduysa kaydet
                    if result["sl_hit"]:
                        result["tp_hit_after_sl"] = True
                        result["tp_hit_after_sl_count"] += 1
                        result["last_tp_after_sl"] = tp
                        if result["candles_sl_to_tp"] is None:
                            result["candles_sl_to_tp"] = result["checked_candles"] - result["sl_hit_at"]

            # Durma koşulu:
            if result["sl_hit"]:
                if result["tp_hit_after_sl"]:
                    break
            elif result["tp_hit"]:
                break

        # En lehte/aleyhte fiyat takibi (genel)
        result["min_favorable"] = min(result["min_favorable"], candle_low)
        result["max_favorable"] = max(result["max_favorable"], candle_high)

    return result


def analyze_signals(signals: list[dict], price_rows: list[dict]) -> dict:
    """
    Tüm sinyalleri analiz et, chat_id bazında rapor oluştur.
    """
    chat_groups = defaultdict(lambda: {
        "chat_title": "",
        "total_signals": 0,
        "tp_first": 0,
        "sl_first": 0,
        "no_result": 0,
        "trades": [],
    })

    for msg in signals:
        chat_id = str(msg.get("chat_id", "unknown"))
        chat_title = msg.get("chat_title", "Bilinmeyen Chat")

        # Sinyal bilgileri
        entry = msg.get("entry_point")
        sl = msg.get("sl")

        if entry is None or sl is None:
            continue

        try:
            entry = float(entry) if isinstance(entry, str) else entry
            sl = float(sl) if isinstance(sl, str) else sl
        except (ValueError, TypeError):
            continue

        # Sadece XAUUSD sinyalleri (entry 1000-10000 arası)
        if not (1000 <= entry <= 10000):
            continue

        # Yön tespiti
        if sl > entry:
            direction = "SELL"
        else:
            direction = "BUY"

        chat_groups[chat_id]["chat_title"] = chat_title

        # Mesaj zamanını UTC'ye çevir
        msg_ts = msg.get("timestamp", "")
        utc_dt = msg_timestamp_to_utc(msg_ts)
        if utc_dt is None:
            continue

        # Sinyal anındaki mum indeksini bul
        target_ts = utc_dt.replace(second=0, microsecond=0)
        start_idx = -1

        for idx, row in enumerate(price_rows):
            try:
                row_ts = datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S")
            except (ValueError, KeyError):
                continue

            if row_ts >= target_ts:
                start_idx = idx
                break

        if start_idx < 0 or start_idx >= len(price_rows) - 1:
            continue

        # Sinyal anındaki fiyat (ilk mum)
        try:
            first_candle = price_rows[start_idx]
            open_price = float(first_candle["open"])
            close_price = float(first_candle["close"])
        except (ValueError, KeyError):
            continue

        market_price = round((open_price + close_price) / 2, 2)

        # TP seviyelerini topla
        tp_n = msg.get("tp_n", 0)
        tp_levels = []
        if tp_n and isinstance(tp_n, int) and tp_n > 0:
            for i in range(1, tp_n + 1):
                tp_val = msg.get(f"tp{i}")
                if tp_val is not None and isinstance(tp_val, (int, float)):
                    tp_levels.append(float(tp_val))
                else:
                    tp_levels.append(None)

        # Entry ile market_price arasındaki fark
        price_diff = round(market_price - entry, 2)

        # Adjust edilmiş SL ve TP seviyeleri:
        # Orijinal entry'den farkı koru, market_price'a göre kaydır
        # Örn: entry=4048, sl=4067 (fark=+19), market_price=4045.89
        #   adjusted_sl = 4045.89 + 19 = 4064.89
        adjusted_sl = round(sl + price_diff, 2)
        adjusted_tp_levels = []
        for tp in tp_levels:
            if tp is not None:
                adjusted_tp_levels.append(round(tp + price_diff, 2))
            else:
                adjusted_tp_levels.append(None)

        # TP/SL kontrolü (sinyalden 1 mum sonrasından başla)
        # Adjust edilmiş seviyeleri ve actual_entry=market_price olarak kullan
        result = check_tp_sl_result(direction, market_price, adjusted_sl, adjusted_tp_levels, price_rows, start_idx + 1)

        # Sonucu kaydet ve pip hesabı yap
        if result["first_hit"] == "tp":
            chat_groups[chat_id]["tp_first"] += 1
        elif result["first_hit"] == "sl":
            chat_groups[chat_id]["sl_first"] += 1
        else:
            chat_groups[chat_id]["no_result"] += 1

        # Pip hesabı:
        # TP hit -> vurulan son TP ile market_price arasındaki lehte fark
        # SL hit -> market_price ile SL arasındaki aleyhte fark (negatif)
        # Sonuçsuz -> 0 pip (açık pozisyon kabul edilir)
        tp_hit_count = result["tp_hit_count"]
        win_pips = 0.0
        loss_pips = 0.0

        if result["first_hit"] == "tp" and result["last_tp_hit"] is not None:
            # Vurulan son TP ile giriş fiyatı arasındaki fark = kazanç
            win_pips = abs(result["last_tp_hit"] - market_price) / PIP_VALUE  # XAUUSD: 1 pip = 0.1
        elif result["first_hit"] == "sl":
            # SL ile giriş fiyatı arasındaki fark = kayıp
            loss_pips = abs(adjusted_sl - market_price) / PIP_VALUE
        elif result["first_hit"] == "none" and result["tp_hit"]:
            # TP'lerden bazıları vuruldu ama hepsi değil, en son vurulan TP'yi kazanç say
            if result["last_tp_hit"] is not None:
                win_pips = abs(result["last_tp_hit"] - market_price) / PIP_VALUE

        # Trade detayı
        first_tp = tp_levels[0] if tp_levels else None

        # SL sonrası TP dönüşü ve maks zarar (pip)
        max_adverse_pips = 0.0
        if result["max_adverse_price"] is not None:
            max_adverse_pips = abs(result["max_adverse_price"] - market_price) / PIP_VALUE

        trade = {
            "timestamp": msg_ts,
            "timestamp_utc": utc_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "direction": direction,
            "entry": entry,
            "sl": sl,
            "first_tp": first_tp,
            "tp_count": tp_n if tp_n else 0,
            "market_price_at_signal": market_price,
            "first_hit": result["first_hit"],
            "tp_hit": result["tp_hit"],
            "sl_hit": result["sl_hit"],
            "tp_hit_count": tp_hit_count,
            "checked_candles": result["checked_candles"],
            "max_price_reached": result["max_favorable"],
            "min_price_reached": result["min_favorable"],
            # Yeni: SL sonrası analiz
            "sl_hit_price": result.get("sl_hit_price"),
            "sl_hit_at": result.get("sl_hit_at"),
            "tp_hit_after_sl": result.get("tp_hit_after_sl", False),
            "tp_hit_after_sl_count": result.get("tp_hit_after_sl_count", 0),
            "last_tp_after_sl": result.get("last_tp_after_sl"),
            "candles_sl_to_tp": result.get("candles_sl_to_tp"),
            "max_adverse_price": result.get("max_adverse_price"),
            "max_adverse_pips": round(max_adverse_pips, 2),
            "win_pips": round(win_pips, 2),
            "loss_pips": round(loss_pips, 2),
        }

        chat_groups[chat_id]["trades"].append(trade)
        chat_groups[chat_id]["total_signals"] += 1

    # Chat bazında kazanç/kayıp özetlerini hesapla
    for chat_id, data in chat_groups.items():
        trades = data["trades"]
        total_win_pips = sum(t["win_pips"] for t in trades)
        total_loss_pips = sum(t["loss_pips"] for t in trades)
        net_pips = round(total_win_pips - total_loss_pips, 2)
        data["total_win_pips"] = round(total_win_pips, 2)
        data["total_loss_pips"] = round(total_loss_pips, 2)
        data["net_pips"] = net_pips
        data["win_rate_pct"] = round(data["tp_first"] / data["total_signals"] * 100, 1) if data["total_signals"] > 0 else 0

        # SL sonrası analiz istatistikleri
        sl_trades = [t for t in trades if t["sl_hit"]]
        data["sl_hit_count"] = len(sl_trades)
        sl_to_tp_trades = [t for t in sl_trades if t["tp_hit_after_sl"]]
        data["sl_to_tp_count"] = len(sl_to_tp_trades)
        # SL→TP dönen trade'lerde ortalama max zarar (pip)
        # (SL aşılıp TP dönene kadar görülen en büyük anlık zarar)
        sl_to_tp_adverse = [t["max_adverse_pips"] for t in sl_to_tp_trades if t["max_adverse_pips"]]
        data["avg_max_adverse_pips"] = round(
            sum(sl_to_tp_adverse) / len(sl_to_tp_adverse), 2
        ) if sl_to_tp_adverse else 0.0

    # Her chat için özet sırala: en çok sinyali olan önce
    return dict(sorted(chat_groups.items(), key=lambda x: x[1]["total_signals"], reverse=True))


def print_report(report: dict):
    """Raporu konsola yazdır: chat listesi + kazanç/kayıp oranları + pip."""
    print("\n" + "=" * 78)
    print("  🤖 SIGNAL PERFORMANCE REPORT")
    print("  Kazanç/Kayıp & Pip Analizi")
    print("=" * 78)

    # Chat bazında özet tablosu (net pip'e göre azalan sırala)
    chat_summary = []
    for chat_id, data in report.items():
        # Sinyali olmayan (fiyat verisi eşleşmeyen) chat'leri dahil etme
        if data["total_signals"] <= 0:
            continue
        chat_summary.append({
            "chat_id": chat_id,
            "chat_title": data["chat_title"],
            "total": data["total_signals"],
            "wins": data["tp_first"],
            "losses": data["sl_first"],
            "no_result": data["no_result"],
            "win_rate": data.get("win_rate_pct", 0),
            "win_pips": data.get("total_win_pips", 0),
            "loss_pips": data.get("total_loss_pips", 0),
            "net_pips": data.get("net_pips", 0),
            # Yeni: SL sonrası analiz
            "sl_to_tp": data.get("sl_to_tp_count", 0),
            "avg_adverse": data.get("avg_max_adverse_pips", 0),
        })

    # Net pip'e göre azalan sırala
    chat_summary.sort(key=lambda x: x["net_pips"], reverse=True)

    print(f"\n{'─' * 78}")
    print(f"  {'Chat':<26} {'Sinyal':>6} {'Kazanç':>6} {'Kayıp':>5} {'SL→TP':>5} {'Ort.Zarar':>9} {'Br. Oranı':>8} {'Net Pip':>9}")
    print(f"{'─' * 78}")

    for c in chat_summary:
        # Emoji kısaltmaları + satır
        title = c["chat_title"]
        if len(title) > 24:
            title = title[:24] + "…"
        print(f"  {title:<26} {c['total']:>6} {c['wins']:>6} {c['losses']:>5} {c['sl_to_tp']:>5} "
              f"{c['avg_adverse']:>8.1f} {c['win_rate']:>7.1f}% {c['net_pips']:>+9.1f}")

    # Genel toplamlar
    total_signals = sum(c["total"] for c in chat_summary)
    total_wins = sum(c["wins"] for c in chat_summary)
    total_losses = sum(c["losses"] for c in chat_summary)
    total_no_result = sum(c["no_result"] for c in chat_summary)
    total_win_pips = sum(c["win_pips"] for c in chat_summary)
    total_loss_pips = sum(c["loss_pips"] for c in chat_summary)
    total_net_pips = round(total_win_pips - total_loss_pips, 2)
    total_sl_to_tp = sum(c["sl_to_tp"] for c in chat_summary)
    avg_win_rate = (total_wins / total_signals * 100) if total_signals > 0 else 0

    # En iyi/kötü chat'ler
    best = chat_summary[0] if chat_summary else None
    worst = chat_summary[-1] if chat_summary else None

    print(f"{'─' * 78}")
    print(f"  {'TOPLAM':<26} {total_signals:>6} {total_wins:>6} {total_losses:>5} {total_sl_to_tp:>5} "
          f"{'':>8} {avg_win_rate:>7.1f}% {total_net_pips:>+9.1f}")
    print(f"{'=' * 78}")

    print("\n  📊 GENEL ÖZET")
    print(f"  {'─' * 40}")
    print(f"  Toplam Chat:          {len(chat_summary)}")
    print(f"  Toplam Sinyal:        {total_signals}")
    print(f"  ✅ Kazanç (TP ilk):     {total_wins} ({avg_win_rate:.1f}%)")
    print(f"  ❌ Kayıp (SL ilk):      {total_losses}")
    print(f"  ⏳ Sonuçsuz (açık):     {total_no_result}")
    print(f"  💰 Kazanç Pip:         {total_win_pips:+.1f}")
    print(f"  💸 Kayıp Pip:          {total_loss_pips:.1f}")
    print(f"  📈 Net Pip:            {total_net_pips:+.1f}")
    print(f"  🔄 SL'den TP dönen:     {total_sl_to_tp} (SL aşılıp TP'ye dönen trade)")

    # En iyi 3 / en kötü 3 chat
    if best:
        print(f"\n  🏆 EN İYİ: {best['chat_title']}  "
              f"({best['total']} sinyal, %{best['win_rate']:.1f} başarı, {best['net_pips']:+.1f} net pip)")
    if worst and len(chat_summary) > 1:
        print(f"  📉 EN KÖTÜ: {worst['chat_title']}  "
              f"({worst['total']} sinyal, %{worst['win_rate']:.1f} başarı, {worst['net_pips']:+.1f} net pip)")

    print(f"\n{'=' * 78}")
    print()


def save_report(report: dict):
    """Raporu JSON dosyasına kaydet."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    report_file = REPORTS_DIR / f"signal_performance_report_{today}.json"

    # Özet ekle
    total_signals = sum(d["total_signals"] for d in report.values())
    total_tp = sum(d["tp_first"] for d in report.values())
    total_sl = sum(d["sl_first"] for d in report.values())
    total_none = sum(d["no_result"] for d in report.values())
    total_win_pips = sum(d.get("total_win_pips", 0) for d in report.values())
    total_loss_pips = sum(d.get("total_loss_pips", 0) for d in report.values())
    total_net_pips = round(total_win_pips - total_loss_pips, 2)

    output = {
        "report_timestamp": datetime.now().isoformat(),
        "summary": {
            "total_chats": len(report),
            "total_signals": total_signals,
            "wins_tp_first": total_tp,
            "losses_sl_first": total_sl,
            "no_result": total_none,
            "win_rate_pct": round(total_tp / total_signals * 100, 1) if total_signals > 0 else 0,
            "total_win_pips": round(total_win_pips, 2),
            "total_loss_pips": round(total_loss_pips, 2),
            "net_pips": total_net_pips,
        },
        "chats": report,
    }

    try:
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"  💾 Rapor kaydedildi: {report_file}")
    except Exception as e:
        print(f"  ❌ Rapor kaydedilemedi: {e}")


def main():
    print("=" * 70)
    print("  🤖 SIGNAL PERFORMANCE ANALYZER")
    print("  TP/SL Öncelik Kontrolü - XAUUSD")
    print("=" * 70)

    # Script dizinine git
    script_dir = Path(__file__).parent
    if script_dir != Path.cwd():
        os.chdir(script_dir)
        print(f"  📁 Çalışma dizini: {script_dir}")

    # Verileri yükle
    print("\n  📥 Mesajlar yükleniyor...")
    signals = load_messages()
    print(f"     Toplam sinyal (analyzed=true, signal=true): {len(signals)}")

    if not signals:
        print("\n  ❌ Analiz edilecek sinyal bulunamadı!")
        return

    print("\n  📥 XAUUSD fiyat verisi yükleniyor...")
    price_rows = load_price_data()
    print(f"     Toplam mum: {len(price_rows)}")

    if not price_rows:
        print("\n  ❌ Fiyat verisi bulunamadı!")
        return

    # Analiz
    print("\n  🔍 Sinyaller analiz ediliyor (TP/SL öncelik)...")
    report = analyze_signals(signals, price_rows)

    # Rapor
    print_report(report)
    save_report(report)

    print("\n  ✅ Analiz tamamlandı!\n")


if __name__ == "__main__":
    main()