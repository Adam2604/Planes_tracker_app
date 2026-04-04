from rtlsdr import RtlSdr
import numpy as np
import pyModeS as pms #biblioteka do wyciągania danych samolotu
import time
import threading
import math
from flask import Flask, jsonify, render_template, request
import csv
import data_base
import os
import sys
from datetime import date, datetime, timedelta
import logging
import signal
import atexit

#Współrzędne anteny
MY_LAT = 51.978
MY_LON = 17.498

#Bazy danych
planes = {} #aktualny stan samolotów
cpr_buffer = {} #bufor do obliczania pozycji
planes_lock = threading.Lock() #zabezpieczenie przed konfiktem wątków
planes_data = {}

app = Flask(__name__)
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

last_packet_time = time.time() #czas ostatniego pakietu do sprawdzania czy program się nie zawiesił
last_archived_date = date.today() - timedelta(days=1) #watchdog po starcie od razu sprawdza stan archiwum

def load_csv_data():
    print("Ładowanie bazy samolotów...")
    try:
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(BASE_DIR, 'samoloty.csv')
        with open(file_path, mode='r', encoding = 'utf-8') as file:
            reader = csv.DictReader(file, quotechar="'")
            count = 0
            for row in reader:
                icao = row.get('icao24', '').upper()

                #W poniższych zmiennych opisany dokładny model samolotu
                producer = row.get('manufacturerName', '')
                model = row.get('model', '')
                operator = row.get('operator', '')
                all = f"{producer} {model}"
                if operator:
                    all += f"[{operator}]"

                planes_data[icao] = all
                count += 1

        print(f"Wczytano dane {count} samolotów.")
    except FileNotFoundError:
        print("Brak pliku samoloty.csv, dane o modelach samolotów nie będą dostępne.")
    except Exception as e:
        print(f"Błąd podczas wczytywania bazy: {e}")

def text_from_bits(bits):
    try:
        n = int(bits, 2)
        return "{:028X}".format(n) #zamiana na HEX, wymuszenie 28 znaków
    except ValueError:
        return ""
    
def decode_details(hex_msg):
    tc = pms.typecode(hex_msg)
    icao = pms.icao(hex_msg)
    now = time.time()

    #1. Nazwa lotu
    if 1 <= tc <= 4:
        callsing = pms.adsb.callsign(hex_msg).strip()
        category = pms.adsb.category(hex_msg)
        print(f"Nazwa lotu: {callsing.strip()}")
        actualize_plane(icao, {"callsign": callsing, "category": category})
    
    #2. Wysokość
    elif 9 <= tc <= 18:
        altitude = pms.adsb.altitude(hex_msg)
        altitude_meters = round(altitude * 0.3048)
        actualize_plane(icao, {"altitude": altitude_meters})
        print(f"Wysokość: {altitude_meters} m")

        #Logika pozycji - Odd/Even
        oe = pms.adsb.oe_flag(hex_msg)
        
        with planes_lock: # Zabezpieczamy dostęp do cpr_buffer na wypadek usuwania przez wątek cleaner
            if icao not in cpr_buffer:
                cpr_buffer[icao] = [None, None] #Even, Odd
            cpr_buffer[icao][oe] = (hex_msg, now)
            even, odd = cpr_buffer[icao]

        if even and odd and abs(even[1] - odd[1]) < 10:  # Standard ADS-B pozwala do 10s dla local decoding
            pos = pms.adsb.position(even[0], odd[0], even[1], odd[1], MY_LAT, MY_LON)
            if pos:
                dist = calculate_distance(MY_LAT, MY_LON, pos[0], pos[1])
                if dist < 800:  # Zwiększony zasięg — CRC i tak filtruje błędne pozycje
                    # Filtrowanie skoków pozycji
                    accept = True
                    with planes_lock:
                        if icao in planes and "lat" in planes[icao] and "lon" in planes[icao]:
                            prev_lat = planes[icao]["lat"]
                            prev_lon = planes[icao]["lon"]
                            prev_time = planes[icao].get("last_pos_time", 0)
                            jump = calculate_distance(prev_lat, prev_lon, pos[0], pos[1])
                            dt = now - prev_time if prev_time else 10

                            # Filtr 1: Max prędkość ~1200 km/h = 0.333 km/s
                            max_dist = max(0.4 * dt, 2)
                            if jump > max_dist:
                                accept = False
                                print(f"Odrzucono skok pozycji {jump:.1f} km (max {max_dist:.1f} km) dla {icao}")


                            if accept and jump > 0.3:
                                route = planes[icao].get("route", [])
                                if len(route) >= 2:
                                    # Kierunek z dwóch ostatnich znanych pozycji
                                    p1 = route[-2]
                                    p2 = route[-1]
                                    # Kierunek dotychczasowy (p1 → p2)
                                    bearing_old = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
                                    # Kierunek nowy (p2 → nowa pozycja)
                                    bearing_new = math.atan2(pos[1] - prev_lon, pos[0] - prev_lat)
                                    # Różnica kątów w stopniach
                                    angle_diff = abs(math.degrees(bearing_new - bearing_old)) % 360
                                    if angle_diff > 180:
                                        angle_diff = 360 - angle_diff
                                    # Odrzuć jeśli zmiana kierunku > 70°
                                    # ale tylko gdy skok jest wystarczająco duży żeby to miało sens
                                    if angle_diff > 70 and jump > 1.0:
                                        accept = False
                                        print(f"Odrzucono zmianę kierunku {angle_diff:.0f}° (skok {jump:.1f} km) dla {icao}")

                    if accept:
                        print(f"Samolot znajduje się {dist:.1f} km ode mnie")
                        actualize_plane(icao,{
                            "lat": pos[0],
                            "lon": pos[1],
                            "dist": round(dist, 1),
                            "last_pos_time": now
                        })

    #3. Prędkość i kurs
    elif tc == 19:
        velocity = pms.adsb.velocity(hex_msg)
        if velocity:
            speed, heading, rate, v_type = velocity
            speed_kmh = round(speed * 1.852)
            if v_type == "GS":
                print(f"Prędkość względem ziemi: {speed_kmh} km/h, Kurs: {heading:.2f}°")
            elif v_type == "IAS" or v_type == "TAS":
                print(f"Prędkość powietrzna (IAS/TAS): {speed_kmh} km/h")
            actualize_plane(icao, {
                "speed": speed_kmh,
                "heading": heading,
                "v_type": v_type
            })

def calculate_distance(lat1, lon1, lat2, lon2):
    #Obliczanie odległości do samolotu za pomocą wzoru Haversine'a
    R = 6371 # Promień Ziemi w km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2)**2
    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))

def actualize_plane(icao, dane, update_last_seen=True):
    #Aktualizuje lub tworzy samolot w bazie danych
    with planes_lock:
        if icao not in planes:
            #Gdy odebrano sygnał samolotu po raz pierwszy to szukamy go w bazie
            model_info = planes_data.get(icao, "Nieznany model")
            planes[icao] = {
                "icao": icao,
                "first_seen": time.time(),
                "model": model_info,
                "dist": None,  #domyślna wartość dystansu
                "min_dist": None,
                "max_dist": None,
                "speed": 0,
                "max_speed": 0,
                "category": 0,
                "route": []
            }
            planes[icao]["last_seen"] = time.time()  # Nowy samolot — zawsze ustaw
        planes[icao].update(dane)
        if update_last_seen:
            planes[icao]["last_seen"] = time.time()

        if "lat" in dane and "lon" in dane:
            planes[icao]["route"].append([dane["lat"], dane["lon"]])

        if "dist" in dane:
            if planes[icao]["min_dist"] is None or dane["dist"] < planes[icao]["min_dist"]:
                planes[icao]["min_dist"] = dane["dist"]
            if planes[icao]["max_dist"] is None or dane["dist"] > planes[icao]["max_dist"]:
                planes[icao]["max_dist"] = dane["dist"]

        if "speed" in dane:
            if dane["speed"] > planes[icao]["max_speed"]:
                planes[icao]["max_speed"] = dane["speed"]

def cleaner():
    #Usuwanie samolotów, które nie były widziane przez minutę
    while True:
        time.sleep(5)
        limit = time.time() - 60
        data_base.delete_old_data()
        with planes_lock:
            old = [k for k, v in planes.items() if v["last_seen"] < limit]
            for k in old:
                #Najpiew zapisz do bazy a potem usuń
                data_base.save_flight(planes[k])
                del planes[k]
                if k in cpr_buffer:
                    del cpr_buffer[k]

def watchdog():
    global last_packet_time
    global last_archived_date
    #Sprawdza czy program się nie zawiesił i w razie co go resetuje
    #Dodatkowo sprawdza czy nie minęła północ i archiwizuje dane
    print("Watchdog uruchomiony.")
    while True:
        time.sleep(60) #sprawdzanie co minutę
        if time.time() - last_packet_time > 3600: #brak pakietów przez godzinę
            print("Brak sygnału przez godzinę, restart programu.")
            os.system("sudo reboot")
        
        #Sprawdzanie czy minęła północ
        current_date = date.today()

        #logowanie diagnostyczne raz na godzinę aby sprawdzić czy watchdog działa
        if time.localtime().tm_min == 0:
            print(f"[{time.strftime('%H:%M')}] Watchdog działa. Dziś: {current_date}, Ostatnia archiwizacja: {last_archived_date}")
        if current_date > last_archived_date:
            print("Minęła północ, archiwizowanie danych.")
            try:
                data_base.archive_past_days()
                last_archived_date = current_date
                print("Archiwizacja zakończona.")
            except Exception as e:
                print(f"[{time.strftime('%H:%M:%S')}] BŁĄD podczas archiwizacji: {e}")
        

def radio_loop():
    #Konfiguracja
    sdr = RtlSdr()
    sdr.sample_rate = 2000000
    sdr.center_freq = 1090000000
    sdr.freq_correction = 1
    sdr.gain = 49.6

    global last_packet_time

    print("Czekam na sygnał")
    try:
        while True:
            samples = sdr.read_samples(512 * 1024)  # Większy bufor = mniej luk w odczycie
            mag = np.abs(samples) #amplituda

            #Wykrywanie preambuły
            p0 = mag[: -16] #Sygnał w chwili T
            p2 = mag[2: -14] #Sygnał w chwili T + 2 próbki
            p7 = mag[7 : -9] #Sygnał w chwili T +7 próbek
            p9 = mag[9 : -7] #Sygnał w chwili T + 9 próbek

            # Dołki (szum/brak sygnału w preambule) - poprawia skuteczność detekcji względem zniekształceń
            p1 = mag[1: -15]
            p3 = mag[3: -13]
            p4 = mag[4: -12]
            p5 = mag[5: -11]
            p6 = mag[6: -10]
            p8 = mag[8: -8]

            noise = np.median(mag)  # Mediana — odporna na outliery od bliskich samolotów
            threshold = noise * 3.0
            
            # Detekcja: górki muszą być ponad progiem ORAZ dołki muszą obrysowywać kształt impulsów
            # To drastycznie zmniejsza wystąpienie 'False Positives' przy szumach.
            hits = (p0 > threshold) & (p2 > threshold) & \
                   (p7 > threshold) & (p9 > threshold) & \
                   (p1 < p0) & (p1 < p2) & (p3 < p2) & (p4 < p2) & \
                   (p5 < p7) & (p6 < p7) & (p8 < p7) & (p8 < p9)
            hit_indices = np.where(hits)[0]
            #Hits = True -> wiadomość od samolotu się zaczyna

            for idx in hit_indices:
                data_start = idx + 16 #dane zaczynają się 16 próbek po preambule
                if data_start + 224 >= len(mag): continue
                #Dekodowanie bitów
                signal_slice = mag[data_start: data_start + 224]
                try:
                    bit_pairs = signal_slice.reshape(112, 2)
                    #Jeżeli pierwsza połówka pary jest wyższa -> bit "1"
                    bits_list = bit_pairs[:, 0] > bit_pairs[:, 1]
                    bits = "".join(["1" if b else "0" for b in bits_list])

                    hex_msg = text_from_bits(bits)
                except ValueError:
                    continue

                #Filtrowanie - standardowy ADS-B (DF17 = "8D") 
                #oraz sygnały zależne/TIS-B/ADS-R (DF18 = "90", "91", "92") dla większej ilości detekcji
                #Dodatkowo za pomocą biblioteki pyModeS sprawdzamy sumę kontrolną
                #żeby nie brac pod uwagę błędnych ramek
                first_two = hex_msg[:2]
                first_byte = int(first_two, 16) if len(hex_msg) >= 2 else 0

                # DF17 (ADS-B) i DF18 (TIS-B/ADS-R) — pełne dane
                if first_two in ("8D", "90", "91", "92"):
                    try:
                        if pms.crc(hex_msg) == 0:
                            last_packet_time = time.time()
                            icao = pms.icao(hex_msg)
                            tc = pms.typecode(hex_msg)
                            print(f"Odebrano wiadomość od samolotu ICAO: {icao}, \nType Code: {tc}, HEX: {hex_msg}")
                            decode_details(hex_msg)
                            print("-"*40)
                    except:
                        pass

                # DF11 (Mode S All-Call Reply)
                elif first_two == "5D":
                    try:
                        if pms.crc(hex_msg) == 0:
                            last_packet_time = time.time()
                            icao = pms.icao(hex_msg)
                            actualize_plane(icao, {}, update_last_seen=False)
                            print(f"DF11 All-Call od ICAO: {icao}")
                    except:
                        pass

                # DF20/DF21 (Comm-B)
                elif 0xA0 <= first_byte <= 0xBF:
                    try:
                        if pms.crc(hex_msg) == 0:
                            last_packet_time = time.time()
                            icao = pms.icao(hex_msg)
                            alt = pms.common.altcode(hex_msg)
                            if alt:
                                alt_m = round(alt * 0.3048)
                                actualize_plane(icao, {"altitude": alt_m}, update_last_seen=False)
                                print(f"Comm-B altitude od ICAO: {icao}, wysokość: {alt_m} m")
                            else:
                                actualize_plane(icao, {}, update_last_seen=False)
                    except:
                        pass
    except KeyboardInterrupt:
        print("Zakończono odbiór sygnału.")
    finally:
        sdr.close()

cleanup_done = False

def cleanup_on_exit():
    global cleanup_done
    if cleanup_done:
        return
    cleanup_done = True
    print("\n" + "="*50)
    print("Zabezpieczenie: Zapisywanie aktywnych samolotów do bazy przed zamknięciem...")
    saved_count = 0
    with planes_lock:
        for icao, plane in list(planes.items()):
            try:
                data_base.save_flight(plane)
                saved_count += 1
            except Exception as e:
                print(f"Błąd zapisu {icao}: {e}")
    print(f"Zapisano {saved_count} samolotów. Zamknięto bezpiecznie.")
    print("="*50 + "\n")

def handle_exit(signum, frame):
    cleanup_on_exit()
    sys.exit(0)

@app.route('/data')
def get_data():
    with planes_lock:
        planes_for_map = []
        for plane in planes.values():
            map_plane = {k: v for k, v in plane.items() if k != "route"}
            planes_for_map.append(map_plane)
        return jsonify(planes_for_map)

@app.route('/route/<icao>')
def get_route(icao):
    normalized_icao = icao.upper()
    with planes_lock:
        plane = planes.get(normalized_icao)
        if plane:
            route = plane.get("route", [])
            return jsonify({"icao": normalized_icao, "active": True, "route": route})

    # Fallback — samolot nie jest aktywny, szukaj trasy w bazie danych
    import sqlite3 as _sqlite3
    import json as _json
    conn = _sqlite3.connect(data_base.DB_NAME, timeout=10)
    c = conn.cursor()
    today_midnight = datetime.combine(date.today(), datetime.min.time()).timestamp()
    c.execute("SELECT route FROM historia WHERE icao = ? AND last_seen > ? ORDER BY last_seen DESC LIMIT 1", (normalized_icao, today_midnight))
    row = c.fetchone()
    conn.close()
    if row and row[0]:
        try:
            db_route = _json.loads(row[0])
        except:
            db_route = []
        return jsonify({"icao": normalized_icao, "active": False, "route": db_route})
    return jsonify({"icao": normalized_icao, "active": False, "route": []})

@app.route('/route/history/<int:rowid>')
def get_route_history(rowid):
    source = request.args.get('source', 'historia')
    icao, route = data_base.get_flight_route(rowid, source)
    if not icao:
        return jsonify({"icao": None, "route": []})
    return jsonify({"icao": icao, "route": route})

@app.route('/stats')
def get_stats():
    stats = data_base.get_stat_today()
    return jsonify(stats)

@app.route('/list')
def list_page():
    date_from = request.args.get('date_from', date.today().strftime('%Y-%m-%d'))
    date_to = request.args.get('date_to', date_from)
    flights = data_base.get_flights_list(date_from, date_to)
    return render_template('list.html', flights=flights, date_from=date_from, date_to=date_to)

@app.route('/statystyki')
def stats_page():
    mode_param = request.args.get('mode', 'day')
    if mode_param == 'month':
        default_date = date.today().strftime("%Y-%m")
    else:
        default_date = date.today().strftime("%Y-%m-%d")

    date_param = request.args.get('date', default_date)

    if mode_param == "month" and len(date_param) > 7:
        date_param = date_param[:7]
    stats = data_base.get_history_stats(date_param, mode_param)

    return render_template('stats.html', s=stats, current_date=date_param, current_mode=mode_param)

@app.route('/api/list')
def api_list():
    date_from = request.args.get('date_from', date.today().strftime('%Y-%m-%d'))
    date_to = request.args.get('date_to', date_from)
    flights = data_base.get_flights_list(date_from, date_to)
    return jsonify(flights)

@app.route('/api/stats')
def api_stats():
    mode_param = request.args.get('mode', 'day')
    if mode_param == 'month':
        default_date = date.today().strftime("%Y-%m")
    else:
        default_date = date.today().strftime("%Y-%m-%d")
    date_param = request.args.get('date', default_date)
    if mode_param == "month" and len(date_param) > 7:
        date_param = date_param[:7]
    stats = data_base.get_history_stats(date_param, mode_param)
    return jsonify(stats) if stats else jsonify({})

@app.route('/api/range_map')
def api_range_map():
    mode_param = request.args.get('mode', 'day')
    if mode_param == 'month':
        default_date = date.today().strftime("%Y-%m")
    else:
        default_date = date.today().strftime("%Y-%m-%d")
    date_param = request.args.get('date', default_date)
    if mode_param == "month" and len(date_param) > 7:
        date_param = date_param[:7]

    # Przekaż aktywne samoloty jeśli dzisiejszy dzień zawiera się w przedziale
    active = None
    today_str = date.today().strftime("%Y-%m-%d")
    include_active = False
    
    if mode_param == 'day' and date_param == today_str:
        include_active = True
    elif mode_param == 'week':
        try:
            dt = datetime.strptime(date_param, "%Y-%m-%d")
            start_week = dt - timedelta(days=dt.weekday())
            end_week = start_week + timedelta(days=6)
            if start_week.strftime("%Y-%m-%d") <= today_str <= end_week.strftime("%Y-%m-%d"):
                include_active = True
        except: pass
    elif mode_param == 'month' and date_param == today_str[:7]:
        include_active = True

    if include_active:
        with planes_lock:
            active = [dict(p) for p in planes.values()]

    sectors = data_base.get_range_data(date_param, mode_param, active)
    return jsonify({"sectors": sectors, "antenna": {"lat": MY_LAT, "lon": MY_LON}})

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == "__main__":
    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)
    atexit.register(cleanup_on_exit)

    load_csv_data()
    data_base.init_db()
    data_base.archive_past_days()
    #uruchomienie wątków
    threading.Thread(target=radio_loop, daemon=True).start()
    threading.Thread(target=cleaner, daemon=True).start()
    threading.Thread(target=watchdog, daemon=True).start()

    app.run(host='0.0.0.0', port=5000, debug = False)
