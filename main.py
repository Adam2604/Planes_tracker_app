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
import hmac
import sqlite3
from anomaly import TrackDetector, Settings, calculate_distance, bearing, altitude_band
from aircraft_state import update_plane
from observation_store import ObservationStore, ReviewConflict
from radio_decoder import FrameValidator, extract_message, text_from_bits
from navigation_quality import NavigationQuality
from receiver_health import ReceiverHealth

#Współrzędne anteny
MY_LAT = 51.978
MY_LON = 17.498

# Change the profile name after moving/replacing the antenna or changing gain.
STATION_PROFILE = os.environ.get("PLANES_STATION_PROFILE", "default")
STATION_ID = f"{MY_LAT:.6f},{MY_LON:.6f}:{STATION_PROFILE}"
DETECTOR_SETTINGS = Settings()
detectors = {}
navigation_states = {}
receiver_health = ReceiverHealth()
observation_store = None
receiver_stop = threading.Event()
receiver_thread = None

#Bazy danych
planes = {} #aktualny stan samolotów
cpr_buffer = {} #bufor do obliczania pozycji
planes_lock = threading.Lock() #zabezpieczenie przed konfiktem wątków
planes_data = {}

app = Flask(__name__)
app.config['ANOMALY_REVIEW_TOKEN'] = os.environ.get('PLANES_REVIEW_TOKEN', '')
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

def decode_details(hex_msg):
    import pyModeS as pms
    tc = pms.typecode(hex_msg)
    icao = pms.icao(hex_msg).upper()
    now = time.time()
    if tc is None:
        return
    if tc == 31 or tc == 19 or 9 <= tc <= 18:
        update_navigation(icao, hex_msg, now, pms.adsb)
    if 1 <= tc <= 4:
        actualize_plane(icao, {"callsign": pms.adsb.callsign(hex_msg).strip(),
                               "category": pms.adsb.category(hex_msg)})
    elif 9 <= tc <= 18:
        altitude = pms.adsb.altitude(hex_msg)
        altitude_meters = round(altitude * .3048) if altitude is not None else None
        actualize_plane(icao, {"altitude": altitude_meters})
        oe = pms.adsb.oe_flag(hex_msg)
        with planes_lock:
            pair = cpr_buffer.setdefault(icao, [None, None])
            pair[oe] = (hex_msg, now)
            even, odd = pair
        if even and odd and abs(even[1] - odd[1]) < 10:
            pos = pms.adsb.position(even[0], odd[0], even[1], odd[1], MY_LAT, MY_LON)
            if pos:
                process_position(icao, pos[0], pos[1], now, hex_msg)
    elif tc == 19:
        velocity = pms.adsb.velocity(hex_msg)
        if velocity:
            speed, heading, rate, v_type = velocity
            actualize_plane(icao, {
                "speed": round(speed * 1.852) if speed is not None else None,
                "heading": heading, "v_type": v_type,
                "vertical_rate": round(rate * .3048 / 60, 2) if rate is not None else None,
                "velocity_time": now,
            })


def update_navigation(icao, message, now, adsb):
    row = None
    with planes_lock:
        state = navigation_states.get(icao) or NavigationQuality()
        if not state.update(message, now, adsb):
            return
        navigation_states[icao] = state
        plane = update_plane(planes, planes_data, icao, {}, now)
        quality = state.snapshot(now, adsb)
        plane['navigation'] = quality
        if observation_store and state.should_save(quality, now):
            row = dict(kind='navigation', track_id=plane['track_id'], icao=icao,
                       time=now, quality=quality, raw_message=message)
    if row is not None:
        observation_store.submit(row)


def navigation_snapshot(icao, now):
    state = navigation_states.get(icao)
    if state is None:
        return None
    import pyModeS as pms
    return state.snapshot(now, pms.adsb)


def process_position(icao, lat, lon, now=None, raw_message=None):
    now = time.time() if now is None else now
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    distance = calculate_distance(MY_LAT, MY_LON, lat, lon)
    sector = int(bearing(MY_LAT, MY_LON, lat, lon) // 10)
    with planes_lock:
        plane = update_plane(planes, planes_data, icao, {}, now)
        band = altitude_band(plane.get("altitude"))
        fresh_velocity = 0 <= now - plane.get("velocity_time", float("-inf")) <= DETECTOR_SETTINGS.velocity_max_age
        point = {
            "icao": icao, "track_id": plane["track_id"], "time": now,
            "lat": lat, "lon": lon, "altitude": plane.get("altitude"),
            "distance": distance, "sector": sector, "band": band,
            "raw_message": raw_message,
            **{key: plane.get(key) if fresh_velocity else None
               for key in ("speed", "heading", "vertical_rate", "v_type", "velocity_time")},
        }
        profile = observation_store.profiles.get((sector, band)) if observation_store else None
        detector = detectors.setdefault(icao, TrackDetector(DETECTOR_SETTINGS))
        analysis = detector.observe(point, profile)
        analysis['navigation'] = navigation_snapshot(icao, now)
        analysis['receiver'] = receiver_health.snapshot(now)
        previous = plane.get("anomaly", {})
        point["event"] = ((analysis["status"], analysis["reasons"]) !=
                          (previous.get("status", "clear"), previous.get("reasons", [])))
        plane["anomaly"] = analysis
        plane["spoof_score"] = analysis["score"]
        # Observation mode never flags a flight for exclusion by legacy statistics.
        plane["is_spoofed"] = False
        if not analysis["accepted"]:
            plane["rejected_jumps"] += 1
        if analysis["reason_codes"]:
            segments = plane.setdefault("suspect_segments", [])
            anchor = [plane["lat"], plane["lon"]] if "lat" in plane else [lat, lon]
            segments.append([anchor, [lat, lon]])
            del segments[:-200]
        if analysis["accepted"]:
            if analysis["break_route"] and plane["route"]:
                plane["route"].append(None)
            update_plane(planes, planes_data, icao,
                         {"lat": lat, "lon": lon, "dist": round(distance, 1), "last_pos_time": now}, now)
        point["analysis"] = analysis
    if observation_store:
        observation_store.submit(point)
    return analysis


def actualize_plane(icao, dane, update_last_seen=True):
    with planes_lock:
        update_plane(planes, planes_data, icao, dane, time.time(), update_last_seen)


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
                detectors.pop(k, None)
                navigation_states.pop(k, None)
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
    global last_packet_time
    sdr = None
    receiver_health.start()
    try:
        from rtlsdr import RtlSdr
        import numpy as np
        import pyModeS as pms
        validator = FrameValidator()
        tail = np.array([], dtype=float)
        sdr = RtlSdr()
        sdr.sample_rate = 2000000
        sdr.center_freq = 1090000000
        sdr.freq_correction = 1
        sdr.gain = 49.6
        print("Czekam na sygnał")
        while not receiver_stop.is_set():
            samples = sdr.read_samples(512 * 1024)  # Większy bufor = mniej luk w odczycie
            magnitudes = np.abs(samples)
            receiver_health.read(float(np.median(magnitudes)) if len(magnitudes) else 0)
            mag = np.concatenate((tail, magnitudes))
            tail = mag[-239:].copy()  # Preserve frames crossing read boundaries.
            if len(mag) < 17:
                continue

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
                # Defer the final possible preambles to the next read, exactly once.
                if idx >= len(mag) - 239:
                    continue
                hex_msg = extract_message(mag, idx + 16)
                if not hex_msg:
                    continue
                try:
                    frame = validator.validate(hex_msg, pms, time.time())
                    receiver_health.frame(accepted=frame is not None, **validator.last_check)
                    if frame is None:
                        continue
                    df, icao = frame
                    last_packet_time = time.time()
                    if df in (17, 18):
                        decode_details(hex_msg)
                    elif df == 20:
                        alt = pms.common.altcode(hex_msg)
                        actualize_plane(icao, {"altitude": round(alt * .3048) if alt is not None else None})
                    else:
                        # DF21 carries identity, not altitude; DF11 only confirms presence.
                        actualize_plane(icao, {})
                except (ValueError, TypeError, RuntimeError, IndexError):
                    receiver_health.frame(decode_error=True)
                    logging.debug("Rejected undecodable frame %s", hex_msg, exc_info=True)
    except KeyboardInterrupt:
        print("Zakończono odbiór sygnału.")
    except Exception as exc:
        receiver_health.failed(exc)
        logging.exception('Receiver stopped after an error')
    finally:
        try:
            if sdr is not None:
                sdr.close()
        except Exception as exc:
            receiver_health.failed(exc)
            logging.exception('Cannot close receiver')
        finally:
            receiver_health.stop()

cleanup_done = False

def cleanup_on_exit():
    global cleanup_done
    if cleanup_done:
        return
    cleanup_done = True
    receiver_stop.set()
    if receiver_thread and receiver_thread is not threading.current_thread():
        receiver_thread.join(timeout=5)
    if observation_store:
        observation_store.close()
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
            map_plane = {k: v for k, v in plane.items() if k not in ("route", "suspect_segments")}
            map_plane['navigation'] = navigation_snapshot(plane['icao'], time.time())
            if "anomaly" in plane:
                map_plane["anomaly"] = dict(plane["anomaly"],
                    stale=time.time() - plane["anomaly"]["evaluated_at"] > 15)
            planes_for_map.append(map_plane)
        return jsonify(planes_for_map)

@app.route('/route/<icao>')
def get_route(icao):
    normalized_icao = icao.upper()
    with planes_lock:
        plane = planes.get(normalized_icao)
        if plane:
            route = plane.get("route", [])
            return jsonify({"icao": normalized_icao, "active": True, "route": route, "suspect_segments": plane.get("suspect_segments", [])})

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

@app.route('/api/anomalies')
def api_anomalies():
    if observation_store is None:
        return jsonify({"events": [], "health": {"mode": "observe", "storage_ok": False}})
    return jsonify({"events": observation_store.recent_events(), "health": observation_store.health(),
                    "review_enabled": bool(app.config['ANOMALY_REVIEW_TOKEN'])})


@app.route('/api/receiver-health')
def api_receiver_health():
    history = []
    storage = observation_store.health() if observation_store else dict(storage_ok=False, queued=0, dropped=0)
    if observation_store:
        try:
            history = observation_store.receiver_history()
        except sqlite3.Error:
            logging.exception('Cannot read receiver history')
            storage = dict(storage, storage_ok=False)
    return jsonify(receiver=receiver_health.snapshot(), storage=storage, history=history)


@app.route('/receiver')
def receiver_page():
    return render_template('receiver.html')


@app.route('/api/anomalies/<int:event_id>/review', methods=['GET', 'POST'])
def api_anomaly_review(event_id):
    token = app.config['ANOMALY_REVIEW_TOKEN']
    if not token or observation_store is None:
        return jsonify(error='Ocenianie zdarzeń jest wyłączone na tej stacji.'), 503
    expected = ('Bearer ' + token).encode('utf-8')
    supplied = request.headers.get('Authorization', '').encode('utf-8')
    if not hmac.compare_digest(expected, supplied):
        return jsonify(error='Nieprawidłowy klucz dostępu.'), 401
    if request.method == 'GET':
        result = observation_store.get_review(event_id)
    else:
        request.max_content_length = 12000
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error='Oczekiwano danych JSON.'), 400
        try:
            result = observation_store.save_review(event_id, payload.get('status'),
                       payload.get('note'), payload.get('revision'))
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except ReviewConflict:
            return jsonify(error='Ocena została zmieniona w innym oknie. Wczytaj aktualną ocenę przed zapisem.'), 409
    if result is None:
        return jsonify(error='Zdarzenie nie istnieje lub wygasło.'), 404
    response = jsonify(result)
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.route('/api/anomalies/<int:event_id>/replay')
def api_anomaly_replay(event_id):
    result = observation_store.replay(event_id) if observation_store else None
    if result is None:
        return jsonify(error='Zdarzenie nie istnieje lub wygasło.'), 404
    return jsonify(result)


@app.route('/api/coverage-profile')
def api_coverage_profile():
    if observation_store is None:
        return jsonify(error='Profil zasięgu nie jest jeszcze dostępny.'), 503
    try:
        band = int(request.args.get('band', '3'))
        profile = observation_store.coverage_profile(band)
    except ValueError:
        return jsonify(error='Wybierz przedział wysokości od 0 do 4.'), 400
    return jsonify(**profile, antenna={'lat': MY_LAT, 'lon': MY_LON})


@app.route('/coverage')
def coverage_page():
    return render_template('coverage.html')


@app.route('/anomalies/<int:event_id>')
def incident_page(event_id):
    return render_template('incident.html', event_id=event_id)


@app.route('/anomalies')
def anomalies_page():
    return render_template('anomalies.html')


@app.route('/stats')
def get_stats():
    stats = data_base.get_stat_today()
    with planes_lock:
        stats["stat_anomalies"] = sum(p.get("anomaly", {}).get("status") in ("anomaly", "suspected") for p in planes.values())
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
    observation_store = ObservationStore(data_base.DB_NAME, STATION_ID, DETECTOR_SETTINGS,
                                         telemetry_provider=receiver_health.snapshot)
    observation_store.initialize()
    observation_store.start()
    data_base.archive_past_days()
    #uruchomienie wątków
    receiver_thread = threading.Thread(target=radio_loop, name="radio-receiver", daemon=True)
    receiver_thread.start()
    threading.Thread(target=cleaner, daemon=True).start()
    threading.Thread(target=watchdog, daemon=True).start()

    app.run(host='0.0.0.0', port=5000, debug = False)
