# Analiza anomalii — pierwsze wdrożenie

## Przegląd zdarzeń, profil zasięgu i odtwarzanie

Nowy pakiet dodaje trzy widoki/funkcje:

- `/anomalies`: filtr ocen użytkownika i odnośniki do szczegółów. Filtr obejmuje
  100 najnowszych zdarzeń, a nie całe archiwum.
- `/coverage`: mapa P95/P99 oraz dokładnego progu używanego przez detektor,
  z wyborem pięciu przedziałów wysokości. Tabela pokazuje wszystkie 36 sektorów,
  liczbę sesji i dni. Niegotowe sektory nie są rysowane jako rzeczywisty zasięg;
  ich szare znaczniki kierunku mają stałą długość 20 km. Dane są migawką tego
  samego profilu, z którego korzysta detektor (odświeżanego co godzinę).
- `/anomalies/<id>`: mapa i odtwarzanie obserwacji w oknie ±2 minuty wokół
  zdarzenia, tempo 1×/5×/20×, wykresy wysokości i zgłoszonej prędkości. Typ
  prędkości GS/IAS/TAS jest pokazany przy wybranej obserwacji. Luki w danych
  nie są interpolowane, a zmiana typu prędkości przerywa linię wykresu.
  Punkty odrzucone są pomarańczowe. Limit odpowiedzi wynosi 5000 punktów;
  przy przekroczeniu strona informuje o przycięciu. Starsze niż 7 dni zdarzenia
  mogą nie mieć już szczegółowej trasy, ale zachowują opis i ocenę do 30 dni.

Oceny użytkownika („do sprawdzenia”, „wyjaśnione”, „podejrzane”) i notatki są
przechowywane osobno w `anomaly_reviews`. Nowa tabela powstaje przy starcie,
bez przebudowy istniejących tras. Oceny nie zmieniają punktacji, treningu ani
wykluczania lotów. Raport `scripts/anomaly_report.py` pokazuje także liczbę
zapisanych ocen zdarzeń (okno do 30 dni); statystyki obserwacji dotyczą do 7 dni.
Ocena „wyjaśnione” nie jest automatycznie etykietą fałszywego alarmu.

### Włączenie ocen i notatek

Ustaw zmienną `PLANES_REVIEW_TOKEN` w środowisku procesu/usługi odbiornika na
długi, losowy klucz i zrestartuj aplikację. Klucz wpisujesz w polu „Klucz dostępu
do ocen” w szczegółach zdarzenia, następnie wybierasz „Wczytaj ocenę”.
Bez skonfigurowanego klucza podgląd nadal działa, lecz edycja jest wyłączona.
Do dostępu zdalnego używaj HTTPS. Aplikacja wysyła klucz w nagłówku Authorization,
nie w URL, i nie zapisuje go w localStorage ani w bazie.

Status oceny jest widoczny publicznie obok alarmu. Treść notatki jest dostępna
wyłącznie przez endpoint wymagający klucza, z wyłączonym buforowaniem odpowiedzi.
Notatka ma limit 2000 znaków. Równoczesne zmiany są chronione numerem rewizji:
konflikt nie nadpisuje nowszej oceny. Ponowne „Wczytaj ocenę” zastępuje pola
aktualnym zapisem — przed wczytaniem zachowaj własną niezapisaną notatkę.
Ocena i notatka wygasają wraz ze zdarzeniem po 30 dniach.

Testy API: `python -m pytest -q`. Testy logiki interfejsu bez przeglądarki:
`node --test tests/test_analysis_ui.cjs` (Node.js 22). Nie zastępują oględzin
map i układu na urządzeniu użytkownika.

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

### Jakość nawigacji i kondycja odbiornika

- Po aktualizacji uruchom ponownie aplikację. Inicjalizacja SQLite dodaje tabele
  `navigation_updates` i `receiver_samples` bez przebudowy istniejących rekordów.
  Obie mają retencję 7 dni. Nowe zdarzenia zachowują również migawkę jakości
  i odbiornika we własnym opisie przez 30 dni; starym zdarzeniom nie dopisuje się danych.
- `/data` i okienko samolotu pokazują NIC, NACp, NACv i SIL. Wersja ADS-B pochodzi
  z TC31 subtype 0. Obsługiwane są wersje 1 i 2; brak TC31, wersja 0 i wersje
  zarezerwowane oznaczają brak obsługiwanych wskaźników, a nie wartości zerowe.
  NACp i SIL pochodzą z TC31, NACv z TC19 subtype 1–4, NIC z TC9–18 oraz
  suplementów odpowiednich dla wersji. TC29, status powierzchniowy i TC20–22
  pozostają poza tym zakresem. Zarezerwowane wartości oznaczają brak danych.
- Status i wersja wygasają po 60 s, NIC i NACv po 10 s bez aktualizacji pozycji
  lub prędkości. Stara wartość pozostaje widoczna jako nieaktualna. Wersja 1 nie
  otrzymuje zgadywanej podstawy SIL; wersja 2 rozróżnia podstawę na godzinę/próbkę.
  Zmiana wersji usuwa zapamiętaną pozycję i prędkość z modułu jakości.
- Zmiany są porównywane tylko między świeżymi wartościami tej samej wersji,
  a SIL dodatkowo tej samej podstawy. Zapisywana jest każda zmiana wartości/stanu
  oraz, przy dalszym odbiorze, migawka co 5 s. Zapis nie wymaga nowej pozycji CPR.
  W pamięci pozostaje maksymalnie 20 ostatnich zmian z 2 minut; szczegóły trafiają
  do historii. Na stronie zdarzenia można przejrzeć spadki/wzrosty i przesuwać
  czas odtwarzania również poza ostatnią dostępną pozycję.
- Te wskaźniki są deklaracjami nadajnika, nie dowodem autentyczności ani przyczyny
  pogorszenia nawigacji. Ten etap nie dodaje za nie punktów spoofingu i nie zmienia
  reguł treningu profilu. Dokumentacja formatu:
  [ADS-B uncertainty indicators](https://mode-s.org/1090mhz/content/ads-b/7-uncertainty.html).
- `/receiver` i `/api/receiver-health` pokazują tempo zaakceptowanych ramek,
  kandydatów z wykrytą preambułą, błędy dekodowania, wiek odczytu i poprawnej ramki,
  przerwy oraz kolejkę zapisu. Okno wynosi 60 s (krótsze po starcie).
  Odsetek poprawnego CRC ma w mianowniku wyłącznie sprawdzone DF17/18;
  brak prób daje brak danych, nie 0%. Akceptacja ramki i CRC to osobne liczniki.
- Tło to `20*log10(mediana(abs(próbki)))`, dB względem amplitudy 1, nie dBm ani
  skalibrowany pomiar zakłóceń. Zero lub nieważny wynik daje brak danych. Wartość
  znika po 5 s bez odczytu. Zmiana wzmocnienia wpływa na tę miarę.
- Przerwa odczytu to odstęp ponad 2 s między odebranymi buforami. Licznik nie
  mierzy utraconych próbek sprzętowych. Po 5 s bez odczytu stan wskazuje przerwę;
  przy świeżym odczycie i 15 s bez zaakceptowanej ramki wskazuje ciszę radiową.
  Błędy uruchomienia/odczytu SDR są widoczne w panelu.
- Wątek zapisu pobiera stan odbiornika co około 5 s niezależnie od ramek, również
  podczas błędu SDR. Panel pokazuje ostatnią godzinę (do 720 próbek), a odtwarzanie
  zdarzenia stan odbiornika z okna ±2 minuty. Awaria całego procesu nie zapisuje próbek.

Po wdrożeniu na stacji sprawdź `/receiver`, obecność nowych rekordów po kilku
sekundach i jakość samolotu nadającego TC31. Testy automatyczne używają symulowanego
SDR; poziom tła i zachowanie rzeczywistego urządzenia wymagają obserwacji na stacji.
Testy interfejsu: `node --test tests/test_analysis_ui.cjs`.

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
