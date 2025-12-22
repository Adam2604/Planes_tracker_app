from rtlsdr import RtlSdr
import numpy as np
import pyModeS as pms #biblioteka do wyciągania danych samolotu
import time
import threading
import math
from flask import Flask, jsonify

#Moje współrzędne
MY_LAT = 51.978
MY_LON = 17.498

#Baza danych
planes = {} #aktualny stan samolotów
cpr_buffer = {} #bufor do obliczania pozycji
planes_lock = threading.Lock() #zabezpieczenie przed konfiktem wątków

app = Flask(__name__)

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
        callsing = pms.adsb.callsign(hex_msg)
        print(f"Nazwa lotu: {callsing}")
    
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
            planes[icao] = {"icao": icao, "first_seen": time.time()}
        planes[icao].update(dane)
        planes[icao]["last_seen"] = time.time()

def radio_loop():
    #Konfiguracja
    sdr = RtlSdr()
    sdr.sample_rate = 2000000
    sdr.center_freq = 1090000000
    sdr.freq_correction = 1

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
def get_planes():
    with planes_lock:
        return jsonify(list(planes.values()))
    
@app.route('/')
def index():
    return f"Radar działa. Slędzę {len(planes)} samolotów.</h1> <a href='/data'>Pokaż JSON</a>"

if __name__ == "__main__":
    #uruchomienie wątków
    threading.Thread(target=radio_loop, daemon=True).start()

    app.run(host='0.0.0.0', port=5000, debug = False)
