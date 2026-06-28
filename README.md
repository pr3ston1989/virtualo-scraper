# Virtualo.pl Audiobook Scraper

Scraper audiobooków z serwisu virtualo.pl z zapisem do bazy SQLite.

---

## Szybki start

```bash
# 1. Zainstaluj zależności
pip install -r requirements.txt

# 2. Usuń starą bazę (jeśli była z nieudanego runu)
rm -f virtualo.db

# 3. Uruchom pełny skan
python3 main.py
```

---

## Instalacja

```bash
cd virtualo-scraper
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Wymagany Python 3.9+.

---

## Użycie

### Pełny skan (pierwszy raz)

```bash
python3 main.py
```

Przechodzi przez wszystkie 38 kategorii audiobooków + nowości/bestsellery/promocje,
zbiera URL-e wszystkich audiobooków, a następnie scrapuje strony szczegółowe.
Na koniec automatycznie ponawia pozycje które wcześniej się nie udały.

**Czas:** Przy 1-3s delay między requestami — kilka godzin dla pełnej bazy.

### Szybka aktualizacja (codzienne)

```bash
python3 main.py --incremental
```

Crawluje kategorie ale **przerywa gdy nie znajduje nic nowego** — zazwyczaj
przechodzi tylko kilka pierwszych stron każdej kategorii. Idealne do codziennego
uruchamiania (np. z cron).

**Czas:** Kilka-kilkanaście minut.

### Tylko scraping zakolejkowanych URL-i

```bash
python3 main.py --scrape-only
```

Nie szuka nowych URL-i — tylko przetwarza to co już jest w kolejce jako "pending".
Przydatne po przerwaniu (`Ctrl+C`) żeby dokończyć scraping bez ponownego crawla.

### Ponowienie nieudanych

```bash
python3 main.py --retry-only
```

Resetuje pozycje ze statusem "failed" (które nie przekroczyły 5 prób) i ponawia.
Przydatne po problemach sieciowych, timeoutach, chwilowej niedostępności serwera.

### Konkretna kategoria

```bash
python3 main.py --no-categories --listing-url "https://virtualo.pl/audiobooki/kryminal-i-sensacja-c216/"
```

Crawluje tylko podaną kategorię z pełną paginacją.

### Z sitemapy (wolne, niski yield)

```bash
python3 main.py --use-sitemap
```

Dodatkowo skanuje sitemap.xml. Uwaga: sitemapy virtualo.pl nie zawierają
bezpośrednich linków do audiobooków — metoda mało skuteczna, zostawiona
jako opcja "na wszelki wypadek".

### Tylko odkrywanie (bez scrapingu)

```bash
python3 main.py --discover-only
python3 main.py --discover-only --incremental
```

Zbiera URL-e do kolejki ale nie odwiedza stron szczegółowych. Przydatne do
sprawdzenia ile pozycji jest do zebrania.

### Verbose (debug)

```bash
python3 main.py -v
```

Więcej logów — przydatne do diagnozowania problemów.

---

## Sprawdzanie stanu

```bash
python3 stats.py
```

Wyświetla:
- Ile audiobooków w bazie
- Ile autorów, lektorów, wydawnictw
- Stan kolejki (pending/done/failed)
- Próbki błędów z failed items

---

## Przerywanie i wznawianie

Scraper jest odporny na przerwanie:

- **Ctrl+C** → graceful stop (dokańcza bieżący element, commituje, drukuje podsumowanie)
- **Kill / crash** → stan jest w SQLite, nic się nie gubi
- **Wznowienie** → `python3 main.py --scrape-only` kontynuuje od miejsca przerwania

Każdy URL jest w kolejce (`ScrapeQueue`) ze statusem:
- `pending` — czeka na przetworzenie
- `done` — przetworzony pomyślnie
- `failed` — nie udało się (po 5 próbach)

---

## Cron / automatyzacja

Dodaj do crontab dla codziennych aktualizacji:

```bash
# Codziennie o 3:00 — szybka aktualizacja
0 3 * * * cd /home7/pr3ston/downloads/virtualo-scraper && .venv/bin/python3 main.py --incremental >> cron.log 2>&1

# Co tydzień w niedzielę — pełny re-scan (łapie usunięte kategorie itp.)
0 4 * * 0 cd /home7/pr3ston/downloads/virtualo-scraper && .venv/bin/python3 main.py >> cron.log 2>&1
```

---

## Logi

- **Konsola** — bieżący postęp
- **scraper.log** — pełna historia (append mode, zachowuje się między runami)

Na koniec każdego uruchomienia drukowane jest podsumowanie:
```
============================================================
  SCRAPING SUMMARY
============================================================
  Duration: 45m 12s
  HTTP requests: 2341
  New URLs discovered: 1523
  Books scraped: 1420
  Books failed: 12
  Status: COMPLETED
------------------------------------------------------------
  Queue state:
        book: 14230 total (done=14218, failed=12)
============================================================
```

---

## Struktura plików

```
├── main.py           # CLI — punkty wejścia, argumenty, graceful shutdown
├── scraper.py        # Orkiestrator — discovery + scraping + retry
├── parsers.py        # Parsery HTML (audiobook, listing, sitemap, pagination)
├── storage.py        # Zapis do DB, kolejka, retry logic
├── models.py         # Modele SQLAlchemy (Book, Author, Narrator, etc.)
├── db.py             # Sesja i inicjalizacja bazy
├── http_client.py    # HTTP z rate limiting, retry, 429 handling
├── config.py         # Konfiguracja (delays, timeouty, ścieżki)
├── stats.py          # Podgląd statystyk bazy
├── requirements.txt  # Zależności Python
├── scraper.log       # Logi (tworzony automatycznie)
├── covers/           # Pobrane okładki (tworzony automatycznie)
└── virtualo.db       # Baza SQLite (tworzona automatycznie)
```

---

## Co jest scrapowane

Dla każdego audiobooka:

| Pole | Przykład |
|------|----------|
| Tytuł | "Plagiat" |
| Opis | pełny opis ze strony |
| Autorzy | Paulina Świst |
| Lektorzy | Jan Kowalski, Anna Nowak |
| Tłumacze | Marek Wiśniewski |
| Wydawnictwo | Czwarta Strona |
| Kategoria | Kryminał i sensacja |
| Breadcrumb | audiobooki > Kryminał i sensacja |
| Format | MP3 |
| Data wydania | 2026-05-15 |
| ISBN | 978-83-1234-567-8 |
| Seria/cykl | Komisarz Nowak. Tom 3 |
| Czas trwania | 8h 23min (503 min) |
| Ocena | 4.5 / 5 (123 oceny) |
| Cena | 31.43 zł (oryg. 44.90 zł) |
| Okładka | URL + lokalna kopia |
| Fragment | URL do sample audio |
| Recenzje | użytkownik, ocena, data, tekst |

---

## Konfiguracja

Edytuj `config.py`:

```python
# Opóźnienie między requestami (szanuj serwer)
REQUEST_DELAY_MIN = 1.0   # sekundy (minimum)
REQUEST_DELAY_MAX = 3.0   # sekundy (maximum)

# Retry
MAX_RETRIES = 3           # próby na request
RETRY_WAIT_MIN = 5        # backoff min (sekundy)
RETRY_WAIT_MAX = 30       # backoff max (sekundy)

# Timeout na request
TIMEOUT = 30              # sekundy
```

Żeby być mniej agresywnym (np. na wolnym łączu):
```python
REQUEST_DELAY_MIN = 2.0
REQUEST_DELAY_MAX = 5.0
TIMEOUT = 60
```

---

## Rozwiązywanie problemów

### "No more audiobooks in queue" od razu po starcie

Stara baza ze złym stanem kolejki. Rozwiązanie:
```bash
rm virtualo.db
python3 main.py
```

### Dużo "failed" itemów

Sprawdź błędy:
```bash
python3 stats.py
```

Jeśli to timeouty/problemy sieciowe — ponów:
```bash
python3 main.py --retry-only
```

Jeśli to 403 — serwer mógł zablokować. Zwiększ delay w `config.py`.

### ImportError: h2 package not installed

```bash
pip install httpx[http2]
```

### Scraper nie znajduje nowych audiobooków w --incremental

To znaczy że nie ma nic nowego od ostatniego runu. Normalne.
Raz na tydzień uruchom bez `--incremental` żeby mieć pewność.

### Chcę wyeksportować dane

Baza to zwykły SQLite — otwórz przez `sqlite3 virtualo.db` lub dowolny
klient SQL (DBeaver, DB Browser for SQLite, etc.):

```sql
-- Wszystkie audiobooki z autorami
SELECT b.title, b.price, GROUP_CONCAT(a.name, ', ') as authors
FROM books b
JOIN book_authors ba ON b.id = ba.book_id
JOIN authors a ON ba.author_id = a.id
GROUP BY b.id
ORDER BY b.release_date DESC;

-- Statystyki po kategorii
SELECT c.name, COUNT(*) as count, AVG(b.avg_rating) as avg_rating
FROM books b
JOIN categories c ON b.category_id = c.id
GROUP BY c.id
ORDER BY count DESC;
```

---

## Przed uruchomieniem na serwerze — checklist

1. ✅ `pip install -r requirements.txt` (w venv)
2. ✅ Upewnij się że `httpx[http2]` jest zainstalowany: `pip install httpx[http2]`
3. ✅ Usuń starą bazę jeśli była: `rm -f virtualo.db`
4. ✅ Uruchom: `python3 main.py`
5. ✅ Opcjonalnie w tmux/screen żeby nie zginął po rozłączeniu:
   ```bash
   tmux new -s scraper
   python3 main.py
   # Ctrl+B, D — detach
   # tmux attach -t scraper — powrót
   ```
