# Virtualo.pl Audiobook Scraper

Scraper audiobooków z serwisu virtualo.pl z zapisem do bazy SQLite.

## Instalacja

```bash
pip install -r requirements.txt
```

## Użycie

### Pełny scraping (sitemap → odkrywanie → scraping)

```bash
python main.py
```

### Tylko odkrywanie URL-i (bez scrapingu stron szczegółowych)

```bash
python main.py --discover-only
```

### Tylko scraping już zakolejkowanych URL-i

```bash
python main.py --scrape-only
```

### Odkrywanie z listing pages (kategorie)

```bash
python main.py --use-listings --listing-url "https://virtualo.pl/audiobooki/kryminal-i-sensacja-c216/"
```

### Verbose mode

```bash
python main.py -v
```

### Statystyki bazy

```bash
python stats.py
```

## Struktura projektu

```
├── main.py           # CLI entry point
├── scraper.py        # Orkiestrator (discovery + scraping)
├── parsers.py        # Parsery HTML (strona audiobooka, listing, sitemap)
├── storage.py        # Warstwa persystencji (zapis do DB)
├── models.py         # Modele SQLAlchemy
├── db.py             # Sesja i inicjalizacja bazy
├── http_client.py    # Klient HTTP z rate limiting i retries
├── config.py         # Konfiguracja
├── stats.py          # Szybki podgląd statystyk bazy
├── requirements.txt  # Zależności Python
├── covers/           # Pobrane okładki
└── virtualo.db       # Baza SQLite (tworzona automatycznie)
```

## Co jest scrapowane

Dla każdego audiobooka wyciągane są:
- Tytuł, opis
- Autorzy (wielu)
- Lektorzy/narratorzy (wielu)
- Tłumacze (wielu)
- Wydawnictwo
- Kategoria + breadcrumb
- Format (MP3)
- Data wydania
- ISBN
- Czas trwania (string + minuty)
- Ocena średnia + liczba ocen
- Cena aktualna i oryginalna
- URL okładki + lokalna kopia
- URL fragmentu do odsłuchu
- Recenzje (użytkownik, ocena, data, tekst)

## Konfiguracja

Edytuj `config.py`:
- `REQUEST_DELAY_MIN/MAX` – opóźnienie między requestami (domyślnie 1–3s)
- `MAX_RETRIES` – liczba ponownych prób
- `MAX_CONCURRENT_REQUESTS` – maksymalna równoległość
- `COVERS_DIR` – folder na okładki

## Pipeline

1. **Discovery** – pobieranie sitemapy i/lub przeglądanie stron listingowych w celu zebrania URL-i audiobooków
2. **Scraping** – odwiedzanie stron szczegółowych i parsowanie danych
3. **Storage** – zapis do SQLite z deduplicacją (upsert po URL)

Kolejka (`ScrapeQueue`) zapewnia wznawianie po przerwaniu.
