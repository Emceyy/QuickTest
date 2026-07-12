# KPSS Güncel Bilgiler Çalışma Uygulaması

Bu proje bilgisayarda yerel çalışan bir web uygulamasıdır. PDF'ler bir kez okunur, sorular `data/kpss.db` SQLite veritabanına aktarılır, sonra tarayıcı arayüzü bu veritabanından çalışır.

## Çalıştırma

Kısa yol:

```bash
cd /Users/emreceylanuysal/Documents/GuncelBilgiler
make dev
```

Alternatif kısa yol:

```bash
cd /Users/emreceylanuysal/Documents/GuncelBilgiler
./dev.sh
```

Uzun komut:

```bash
cd /Users/emreceylanuysal/Documents/GuncelBilgiler
/Users/emreceylanuysal/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 app.py
```

Terminalde şu satırı gördüğünde tarayıcıdan aç:

```text
KPSS uygulamasi hazir: http://127.0.0.1:8765
```

Adres:

```text
http://127.0.0.1:8765
```

## Kapatma

Uygulamanın çalıştığı terminalde:

```text
Ctrl + C
```

## Veriyi Yeniden Aktarma

PDF'lerden veritabanını yeniden oluşturmak için:

```bash
cd /Users/emreceylanuysal/Documents/GuncelBilgiler
make import
```

Uzun komut:

```bash
cd /Users/emreceylanuysal/Documents/GuncelBilgiler
/Users/emreceylanuysal/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 importer.py
```

## Mimari

- `importer.py`: PDF'leri okur, soru/şık/cevap/çözüm verisini çıkarır, SQLite veritabanını oluşturur.
- `app.py`: Yerel web sunucusu ve API katmanıdır.
- `static/app.js`: Tarayıcıdaki çalışma mantığıdır.
- `static/styles.css`: Arayüz tasarımıdır.
- `data/kpss.db`: Sorular, cevaplar, deneme geçmişi ve kalıcı yanlışlar burada tutulur.

## Yanlışlar Mantığı

- Soru bankasından yanlış yapılanlar `Test Yanlışları` listesine düşer.
- Deneme PDF'inden yanlış yapılanlar `Deneme Yanlışları` listesine düşer.
- `Karma Yanlışları`, iki listenin birleşimidir.
- Yanlış listesindeki bir soru doğru çözülürse listeden otomatik çıkar.
- Daha önce doğru yapılan bir soru sonradan yanlış yapılırsa tekrar yanlış listesine eklenir.
