# Telegram Message Analyzer

Telegram mesajlarını gerçek zamanlı olarak dinleyen, kaydeden ve DeepSeek AI ile sinyal analizi yapan araç seti.

## 📁 Proje Yapısı

```
telegram_listener/
├── telegram_listener.py      # Gerçek zamanlı Telegram dinleyici
├── fetch_recent_messages.py  # Geçmiş mesajları çekme
├── analyze_messages.py       # İstatistiksel analiz aracı
├── ai_signal_analyzer.py     # DeepSeek AI ile sinyal analizi
├── messages/                 # Dinlenen mesajların kaydedildiği klasör
├── fetched_messages/         # Çekilen geçmiş mesajların klasörü
├── .env                      # API anahtarları
├── requirements.txt          # Python bağımlılıkları
└── README.md
```

---

## 🚀 Kurulum

```bash
pip install -r requirements.txt
```

`.env` dosyasını oluşturun:
```
API_ID=your_api_id
API_HASH=your_api_hash
PHONE_NUMBER=+901234567890
DEEPSEEK_API_KEY=sk-your_deepseek_api_key
```

---

## 📡 1. Telegram Listener (`telegram_listener.py`)

Gerçek zamanlı olarak Telegram mesajlarını dinler ve günlük JSON dosyalarına kaydeder.

**Kullanım:**
```bash
python telegram_listener.py
```

- Mesajlar `messages/messages_YYYY-MM-DD.json` formatında kaydedilir
- Otomatik yeniden bağlanma özelliği
- Reply, forward, edit bilgilerini de kaydeder

---

## 📥 2. Geçmiş Mesajları Çekme (`fetch_recent_messages.py`)

Belirtilen chat'lerden geçmiş mesajları çeker.

**Kullanım:**
```bash
python fetch_recent_messages.py
```

- Çekilen mesajlar `fetched_messages/fetched_YYYY-MM-DD.json` olarak kaydedilir

---

## 📊 3. İstatistiksel Analiz (`analyze_messages.py`)

`messages/` klasöründeki JSON dosyalarını okuyarak detaylı istatistikler çıkarır.

**Kullanım:**
```bash
python analyze_messages.py
```

**Gösterilen Bilgiler:**
| Bölüm | Detaylar |
|-------|----------|
| 📈 Genel İstatistikler | Toplam mesaj, tarih aralığı, metin/medya dağılımı, reply/forward/edit sayıları, ortalama mesaj uzunluğu |
| 💬 Chat'lere Göre Dağılım | Her chat'teki mesaj sayısı, yüzdesi, bar grafiği ve kullanıcı sayısı (chat_id bazlı) |
| 👤 En Aktif Kullanıcılar | İlk 10 kullanıcı (kullanıcı_id bazlı) |
| 📅 Günlük Dağılım | Her gündeki mesaj sayısı |
| 🕐 En Aktif Saatler | En yoğun 5 saat dilimi |

**Notlar:**
- Sadece `messages/` klasöründeki dosyaları analiz eder (fetched_messages hariç)
- Chat/kullanıcı adı yoksa ID bazlı gösterim yapar
- Reply mesajları istatistiklere dahil edilir (reply_to bilgisi gösterilmez)

---

## 🤖 4. AI Sinyal Analizi (`ai_signal_analyzer.py`)

DeepSeek AI API kullanarak mesajlardaki forex/gold sinyallerini otomatik olarak analiz eder.

**Kullanım:**
```bash
python ai_signal_analyzer.py
```

### Nasıl Çalışır:
1. `messages/` klasöründeki tüm JSON dosyalarını tarar
2. `analyzed: true` olmayan mesajları bulur
3. 10'ar mesajlık chunk'lara böler
4. Chunk'ları DeepSeek API'ye paralel olarak gönderir (max 5 eşzamanlı)
5. Gelen yanıtları orijinal mesajlara ekler
6. 3 pass'a kadar başarısız chunk'ları tekrar dener

### Mesajlara Eklenen Alanlar:
```json
{
  "analyzed": true,
  "analysis_timestamp": "2026-07-31T04:30:00.123456",
  "signal": true,
  "entry_point": "4124-4116",
  "sl": 4128,
  "tp_n": 7,
  "tp": 4114,
  "tp1": 4114,
  "tp2": 4112,
  "tp3": 4110,
  "tp4": 4107,
  "tp5": 4104,
  "tp6": 4099,
  "tp7": 4093
}
```

### Analiz Kuralları:
- **signal=true** → Sadece SL ve TP birlikte belirlenebiliyorsa
- **signal=false** → SL veya TP belirlenemiyorsa
- **SL/TP "open" ise** → Diğer mesajlardaki context'e göre model kendi karar verir
- **entry_point** → Tek fiyat `"4124"` veya range `"4124-4116"` formatında

### Dosya Yönetimi:
- Tüm mesajları analiz edilen dosyalar `_analyzed` son eki alır (örn: `messages_2026-07-30_analyzed.json`)
- **En güncel (bugünün) dosyası asla yeniden adlandırılmaz** → yeni mesajlar geldikçe tekrar çalıştırıldığında sadece analiz edilmemiş mesajlar işlenir

### Örnek Çıktı:
```
📦 Created 7 chunks of 10
📤 Sending 10 msgs (attempt 1)...
✅ Got 10 results
💾 Saved 68 messages
📈 Updated 68 msgs
🎉 All done! Renaming...
📦 Renamed -> messages_2026-07-29_analyzed.json
📌 Latest file 'messages_2026-07-31.json' kept unanalyzed for future messages
```

---

## 📦 Dosya Formatı

### Kaydedilen Mesaj (ham):
```json
{
  "timestamp": "2026-07-31T00:04:07.616653",
  "chat_id": 2108856565,
  "chat_title": "Sinyal Kanali",
  "sender_id": 123456789,
  "sender_name": "Trader",
  "message": "Sell Gold 4124 - 4116\n\nStop Loss 4128\n\nTP1 4114\nTP2 4112\nTP3 4110"
}
```

### AI Analiz Sonrası:
```json
{
  "timestamp": "2026-07-31T00:04:07.616653",
  "chat_id": 2108856565,
  "chat_title": "Sinyal Kanali",
  "sender_id": 123456789,
  "sender_name": "Trader",
  "message": "Sell Gold 4124 - 4116\n\nStop Loss 4128\n\nTP1 4114...",
  "analyzed": true,
  "analysis_timestamp": "2026-07-31T04:30:00.123456",
  "signal": true,
  "entry_point": "4124-4116",
  "sl": 4128,
  "tp_n": 3,
  "tp": 4114,
  "tp1": 4114,
  "tp2": 4112,
  "tp3": 4110
}
```

---

## 📊 5. DayOutcome MT5 İndikatörü (`DayOutcome.mq5`)

Ayrı pencerede çalışan MQL5 indikatörü. Her bar için: o barın açılış fiyatı ile **gün sonundan 1 saat önceki** kapanış fiyatını karşılaştırır. Ayrıca belirtilen hesap bakiyesi ve lot büyüklüğüne göre **%0 equity margin call** kontrolü yapar.

**Renkler:**
- **Yeşil** → Buy karlı + margin call yememiş
- **Kırmızı** → Buy zararlı VEYA margin call olmuş

**Kurulum:**
1. MT5 → `Dosya → Veri Klasörünü Aç`
2. `MQL5/Indicators/` klasörüne `DayOutcome.mq5` dosyasını kopyalayın
3. MT5'te `Navigator → Indicators → DayOutcome` üzerine çift tıklayın veya derleyin
4. Grafiğe ekleyin (H1, M30, M15 gibi saatten küçük periyotlarda çalışır)

**Ayarlar:**
| Parametre | Varsayılan | Açıklama |
|-----------|-----------|----------|
| `InpCloseHourOffset` | 1 | Gün sonundan kaç saat önceki kapanış baz alınsın |
| `InpBalance` | 1000 | Hesap bakiyesi (USD) |
| `InpLot` | 0.10 | Lot büyüklüğü |
| `InpLeverage` | 100 | Kaldıraç (1:100) |
| `InpSkipIncompleteDay` | true | Tamamlanmamış (henüz bitmemiş) günü atla |

> **Not:** Günün sonu henüz gelmediyse, o gün hesaplanamaz. `InpSkipIncompleteDay=true` olduğunda tamamlanmamış son gün boş bırakılır.
>
> **Margin Call formülü:** Margin call (0% equity), fiyat giriş seviyesinden `Bakiye / (KontratBüyüklüğü × Lot)` kadar ters yönde hareket ettiğinde oluşur. Kaldıraç, marjini etkiler ancak %0 equity seviyesinde doğrudan hesaba katılmaz (equity zaten 0'a düştüğünde MC tetiklenir).

---

## ⚙️ Gereksinimler

```
telethon>=1.34.0
python-dotenv>=1.0.0
httpx>=0.27.0
```

---

## 🔧 Yapılandırma

`.env` dosyasındaki parametreler:
- `API_ID` - Telegram API ID (my.telegram.org)
- `API_HASH` - Telegram API Hash
- `PHONE_NUMBER` - Telefon numarası (+90... formatında)
- `DEEPSEEK_API_KEY` - DeepSeek API anahtarı

`ai_signal_analyzer.py` içinde değiştirilebilir sabitler:
- `CHUNK_SIZE = 10` - API'ye gönderilecek mesaj sayısı
- `MAX_CONCURRENT = 5` - Eşzamanlı API istek sayısı
- `MAX_RETRIES = 3` - Başarısız chunk için maksimum deneme