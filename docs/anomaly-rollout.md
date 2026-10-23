# Analiza anomalii — pierwsze wdrożenie

## Uruchomienie

1. Zatrzymaj poprzednią instancję odbiornika i wykonaj kopię `radar.db`.
2. W środowisku Pythona używanym przez odbiornik zainstaluj `requirements.txt`.
   Sterownik RTL-SDR/libusb pozostaje wymagany. Testy nie wymagają urządzenia.
3. Uruchom aplikację dotychczasowym sposobem (`python main.py`).
   Nowe tabele SQLite powstaną automatycznie i idempotentnie. Istniejące loty,
   archiwa i ich historyczne oznaczenia pozostaną zachowane.
4. Otwórz `/anomalies` (odnośnik „Anomalie” na mapie). Sprawdź „Zapis działa”,
   brak utraconych obserwacji i stopniowy przyrost profili.
5. Po kliknięciu samolotu sprawdź ocenę, powody oraz przerywane pomarańczowe
   odcinki podejrzanych obserwacji. Niebieska linia to zaakceptowana trasa.

Nowy detektor zawsze działa w trybie obserwacyjnym: `is_spoofed=False` dla nowych
ocen, niezależnie od statusu. Punktów odrzuconych przez filtr ruchu nie łączy
z zaakceptowaną trasą, lecz zachowuje je w osobnej tabeli. Nowe alarmy nie
wykluczają całych lotów ze statystyk. Stare etykiety nie są przeliczane wstecz.
Licznik na mapie dotyczy aktywnych anomalii; archiwalny licznik spoofingu na
stronie statystyk nadal dotyczy dawnych oznaczeń.

## Profil zasięgu

- 36 sektorów po 10° × 5 przedziałów wysokości barometrycznej: poniżej 3 km,
  3–6, 6–9, 9–12 i co najmniej 12 km. Brak wysokości nie uczy profilu.
- Ruchome 30 dni, wyłącznie zakończone dni UTC. Odświeżanie co godzinę.
- Jeden głos na sesję śledzenia w danym sektorze i paśmie: maksimum odległości
  kwalifikujących się punktów. To percentyle maksimów przelotów, nie wszystkich ramek.
- Minimum 30 sesji z co najmniej 3 dni. Sesja kończy się po usunięciu nieaktywnego
  samolotu (60 sekund bez wiadomości); nie jest to gwarancja niezależnego lotu.
- Uczenie zaczyna się po 15 sekundach śledzenia. Punkty z niespójnością ruchu
  i kolejne 30 sekund nie uczą profilu. Sama anomalia zasięgu nie blokuje uczenia,
  aby model nie utrwalał własnego ograniczenia. To nie chroni przed wszystkimi
  spójnymi fałszywymi trasami; nie jest to zbiór potwierdzonych pozycji.
- Historyczne maksima z `daily_stats` nie są materiałem treningowym: nie mają
  wysokości, czasu każdego punktu i są obciążone dawnym filtrem 400 km.
- Zmiana anteny, jej położenia lub wzmocnienia wymaga nowej wartości zmiennej
  `PLANES_STATION_PROFILE`, np. `antenna-roof-v2`. Lokalizacja stacji też jest
  częścią klucza profilu. Nie mieszaj danych z różnych konfiguracji.

## Reguły startowe (do kalibracji)

Parametry są zebrane w `anomaly.Settings`; wersja reguł: `sector-motion-v1`.

- Nietypowy zasięg: odległość > P99 + większa z wartości 30 km i 15% P99.
- Skok: przemieszczenie > max(2 km, 0,4 km/s × czas od ostatniej pozycji).
- Prędkość: przemieszczenie w oknie 5–15 sekund przekracza dystans wynikający
  z aktualnej GS o więcej niż max(2 km, 60% tego dystansu). IAS/TAS, brak danych
  i prędkość starsza niż 10 sekund nie są używane. Zakręt skracający odcinek
  między pozycjami nie jest traktowany jako błąd prędkości.
- „Podejrzenie spoofingu”: zasięg + ruch, przynajmniej 3 anomalne obserwacje
  obejmujące co najmniej 5 sekund w ostatnich 30 sekundach. Skok i prędkość
  liczą się jako jedna rodzina dowodów, ponieważ są ze sobą powiązane.
- Ocena wygasa po 60 sekundach bez nowych anomalii, przy kolejnej poprawnej
  obserwacji. Brak danych nie dowodzi poprawności; po 15 sekundach interfejs
  oznacza ocenę jako nieaktualną.
- Po odrzuceniach 3 kolejne spójne punkty obejmujące minimum 5 sekund pozwalają
  zacząć nowy odcinek. To odzyskanie ciągłości śledzenia, nie potwierdzenie pozycji.
  Długa przerwa również zaczyna osobny odcinek.

Wynik 30/40/70 to wagi heurystyk, nie procentowe prawdopodobieństwo. Pojedynczy
odbiornik nie mierzy kierunku nadejścia sygnału. Profil opisuje typowo obserwowane
pozycje i zależy także od ruchu lotniczego. CRC nie uwierzytelnia nadawcy.

## Dane i diagnostyka

- `observations`: czas odbioru, sesja, pozycja, wysokość, świeże parametry ruchu,
  surowa ramka pozycji, decyzja i pełne uzasadnienie. Retencja: 7 dni.
- `coverage_samples`: maksima kwalifikujących się pozycji per sesja/sektor/pasmo/dzień.
  Retencja: 30 dni.
- `anomaly_events`: zmiany statusu lub uzasadnienia, w tym wygaśnięcie.
  Retencja: 30 dni. `/api/anomalies` zwraca do 100 ostatnich zdarzeń i stan zapisu.
- Zapis odbywa się w osobnym wątku, partiami do 1000 rekordów. Kolejka ma limit
  20 000 obserwacji; przepełnienia są raportowane, błąd SQLite pozostawia partię
  do ponowienia. Ostatnia niezapisana partia może zginąć przy utracie zasilania.
- Kontroluj wielkość bazy na stacji: szczegółowe dane są znacznie obszerniejsze
  niż dotychczasowe trasy. Usuwanie starych rekordów umożliwia ponowne użycie
  stron SQLite, ale samo nie zmniejsza pliku na dysku.

## Dekoder

Rozpoznaje DF z pierwszych 5 bitów, zachowuje długość 56/112 bitów i przenosi
końcówkę próbek między odczytami SDR. DF11 uwzględnia nakładkę identyfikatora
interrogatora. DF20/21 z Address Parity są przyjmowane tylko dla adresu ICAO
potwierdzonego niezależnie w ostatnich 60 sekundach. DF21 nie jest dekodowany
jako wysokość. Data Parity z nieznaną nakładką BDS nie jest zgadywane.
DF18 przyjmowany jest tylko z CF=0 (bezpośredni ADS-B z adresem ICAO);
retransmisje i adresy nie-ICAO nie uczą profilu bezpośredniego odbioru.
Pozycje powierzchniowe i pozycje z wysokością GNSS TC20–22 pozostają poza
zakresem tej wersji detektora. Analizowane są pozycje airborne TC9–18.

Źródła formatu:
[Mode S / parity](https://mode-s.org/1090mhz/content/mode-s/1-basics.html),
[DF11](https://mode-s.org/1090mhz/content/mode-s/2-allcall.html).

## Sprawdzenie i strojenie

Uruchom `python -m pytest -q` po zainstalowaniu `requirements-dev.txt`.
Testy wywołują kod produkcyjny, używają tymczasowych baz i znanych ramek Mode S.

Po zebraniu danych uruchom `python scripts/anomaly_report.py radar.db`.
Raport tylko czyta bazę i podaje liczbę sesji z alarmami oraz rozkład powodów.
Następnie ręcznie przejrzyj zdarzenia na `/anomalies` i reprezentatywne przeloty
bez alarmów. Dopiero oznaczone przypadki pozwalają mierzyć fałszywe alarmy.
Nie nazywaj odsetka sesji z alarmami „skutecznością detekcji”.

Pierwszy przegląd: po co najmniej 3 zakończonych dniach, o ile zebrano dostatecznie
dużo sesji. Porównuj kierunki, pasma wysokości, zakręty, zaniki odbioru i dalekie
stabilne przeloty. Zmiany progów powinny dostać nową wersję reguł. Przed aktywnym
wykluczaniem lotów potrzebna jest osobna decyzja wdrożeniowa i ocena tych danych.
