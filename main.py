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
from datetime import date, datetime

#Moje współrzędne
MY_LAT = 51.978
MY_LON = 17.498

#Bazy danych
planes = {} #aktualny stan samolotów
cpr_buffer = {} #bufor do obliczania pozycji
planes_lock = threading.Lock() #zabezpieczenie przed konfiktem wątków
planes_data = {}

app = Flask(__name__)

last_packet_time = time.time() #czas ostatniego pakietu do sprawdzania czy program się nie zawiesił

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
        if icao not in cpr_buffer:
            cpr_buffer[icao] = [None, None] #Even, Odd
        cpr_buffer[icao][oe] = (hex_msg, now)

        even, odd = cpr_buffer[icao]
        if even and odd and abs(even[1] - odd[1]) < 10:
            pos = pms.adsb.position(even[0], odd[0], even[1], odd[1], MY_LAT, MY_LON)
            if pos:
                dist = calculate_distance(MY_LAT, MY_LON, pos[0], pos[1])
                print(f"Samolot znajduje się {dist:.1f} km ode mnie")
                actualize_plane(icao,{
                    "lat": pos[0],
                    "lon": pos[1],
                    "dist": round(dist, 1)
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

def actualize_plane(icao, dane):
    #Aktualizuje lub tworzy samolot w bazie danych
    with planes_lock:
        if icao not in planes:
            #Gdy odebrano sygnał samolotu po raz pierwszy to szukamy go w bazie
            model_info = planes_data.get(icao, "Nieznany model")
            planes[icao] = {
                "icao": icao,
                "first_seen": time.time(),
                "model": model_info,
                "dist": 9999,  #domyślna wartość dystansu
                "min_dist": 9999,
                "speed": 0,
                "max_speed": 0,
                "category": 0
            }
        planes[icao].update(dane)
        planes[icao]["last_seen"] = time.time()

        if "dist" in dane:
            if dane["dist"] < planes[icao]["min_dist"]:
                planes[icao]["min_dist"] = dane["dist"]

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
            sys.exit(1)
        
        #Sprawdzanie czy minęła północ
        current_date = date.today()
        if current_date > last_archived_date:
            print("Minęła północ, archiwizowanie danych.")
            try:
                data_base.archive_past_days()
                last_archived_date = current_date
                print("Archiwizacja zakończona.")
            except Exception as e:
                print(f"Błąd podczas archiwizacji: {e}")
        

def radio_loop():
    #Konfiguracja
    sdr = RtlSdr()
    sdr.sample_rate = 2000000
    sdr.center_freq = 1090000000
    sdr.freq_correction = 1

    global last_packet_time

    print("Czekam na sygnał")
    try:
        while True:
            samples = sdr.read_samples(256 * 1024)
            mag = np.abs(samples) #amplituda

            #Wykrywanie preambuły
            p0 = mag[: -16] #Sygnał w chwili T
            p2 = mag[2: -14] #Sygnał w chwili T + 2 próbki
            p7 = mag[7 : -9] #Sygnał w chwili T +7 próbek
            p9 = mag[9 : -7] #Sygnał w chwili T + 9 próbek

            noise = np.mean(mag)
            threshold = noise * 3.5
            hits = (p0 > threshold) & (p2 > threshold) & \
                   (p7 > threshold) & (p9 > threshold)
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

                #Filtrowanie - sprawdzanie tylko ramek zaczynających się od "8D"
                #Dodatkowo za pomocą biblioteki pyModeS sprawdzamy sumę kontrolną
                #żeby nie brac pod uwagę błędnych ramek
                if hex_msg.startswith("8D"):
                    try:
                        if pms.crc(hex_msg) == 0:
                            last_packet_time = time.time()  #aktualizacja czasu ostatniego pakietu
                            icao = pms.icao(hex_msg)
                            tc = pms.typecode(hex_msg)
                            print(f"Odebrano wiadomość od samolotu ICAO: {icao}, \nType Code: {tc}, HEX: {hex_msg}")
                            decode_details(hex_msg)
                            print("-"*40)
                    except:
                        pass
    except KeyboardInterrupt:
        print("Zakończono odbiór sygnału.")
    finally:
        sdr.close()

@app.route('/data')
def get_data():
    with planes_lock:
        return jsonify(list(planes.values()))

@app.route('/stats')
def get_stats():
    stats = data_base.get_stat_today()
    return jsonify(stats)

@app.route('/list')
def list_page():
    flights = data_base.get_flights_list()
    return render_template('list.html', flights=flights)

@app.route('/statystyki')
def stats_page():
    date_param = request.args.get('date', date.today().strftime("%Y-%m-%d"))
    mode_param = request.args.get('mode', 'day')
    stats = data_base.get_history_stats(date_param, mode_param)

    return render_template('stats.html', s=stats, current_date=date_param, current_mode=mode_param)

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == "__main__":
    load_csv_data()
    data_base.init_db()
    data_base.archive_past_days()
    #uruchomienie wątków
    threading.Thread(target=radio_loop, daemon=True).start()
    threading.Thread(target=cleaner, daemon=True).start()
    threading.Thread(target=watchdog, daemon=True).start()

    app.run(host='0.0.0.0', port=5000, debug = False)
