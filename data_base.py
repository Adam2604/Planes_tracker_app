import sqlite3
import time
from datetime import datetime, date, timedelta
import json
import os
import calendar

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "radar.db")

def init_db():
    conn = sqlite3.connect(DB_NAME, timeout = 10)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS historia (
                    icao TEXT, callsign TEXT, model TEXT, min_dist REAL,
                    max_speed INTEGER, category INTEGER, has_location INTEGER,
                    first_seen INTEGER, last_seen INTEGER,
                    route TEXT, max_dist REAL
                )''')
    # Migracja — dodanie kolumny route jeśli nie istnieje (dla istniejących baz)
    try:
        c.execute("ALTER TABLE historia ADD COLUMN route TEXT")
    except sqlite3.OperationalError:
        pass  # Kolumna już istnieje
    # Migracja — dodanie kolumny max_dist (najdalsza odległość wykrycia)
    try:
        c.execute("ALTER TABLE historia ADD COLUMN max_dist REAL")
    except sqlite3.OperationalError:
        pass  # Kolumna już istnieje
    c.execute("CREATE INDEX IF NOT EXISTS idx_icao_time ON historia (icao, last_seen)")
    
    # Tabela archiwum
    c.execute('''CREATE TABLE IF NOT EXISTS daily_stats (
                    day_date TEXT PRIMARY KEY,
                    total_flights INTEGER,
                    close_flights INTEGER,
                    light_flights INTEGER,
                    military_ghost_found INTEGER,
                    farthest_dist REAL,
                    farthest_model TEXT,
                    rarest_model TEXT, 
                    top_model TEXT,
                    range_map TEXT
                )''')
    # Migracja — dodanie kolumny range_map do daily_stats
    try:
        c.execute("ALTER TABLE daily_stats ADD COLUMN range_map TEXT")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()

def save_flight(plane):
    # Ignorujemy szumy (krótsze niż 5s)
    if plane['last_seen'] - plane['first_seen'] < 5:
        return

    conn = sqlite3.connect(DB_NAME, timeout = 10)
    c = conn.cursor()
    
    # Dane do zapisu
    icao = plane.get('icao')
    current_min_dist = plane.get('min_dist')
    current_max_dist = plane.get('max_dist')
    current_speed = plane.get('speed', 0)
    current_max_speed = plane.get('max_speed', current_speed) 
    current_last_seen = int(plane['last_seen'])
    current_route = plane.get('route', [])
    route_json = json.dumps(current_route) if current_route else None
    
    today_midnight = datetime.combine(date.today(), datetime.min.time()).timestamp()

    # Sprawdzamy, czy ten samolot już był dzisiaj w bazie
    c.execute("""SELECT rowid, min_dist, max_speed, first_seen, last_seen, has_location, route, max_dist 
                 FROM historia 
                 WHERE icao = ? AND last_seen > ?
                 ORDER BY last_seen DESC LIMIT 1""", (icao, today_midnight))
    
    existing_row = c.fetchone()

    # Jeśli przerwa > 10 min — to nowy, oddzielny przelot, nie scalaj
    if existing_row:
        old_last_seen = existing_row[4]
        gap = plane['first_seen'] - old_last_seen
        if gap > 600:
            existing_row = None  # Traktuj jako nowy wpis

    if existing_row:
        # Samolot był niedawno (< 10 min przerwy). Scalamy dane.
        row_id, old_dist, old_speed, old_first, old_last_seen, old_has_loc, old_route_json, old_max_dist = existing_row
        
        # Wybieramy najlepsze wartości z obu przelotów
        if old_dist is None and current_min_dist is None:
            new_best_dist = None
        elif old_dist is None:
            new_best_dist = current_min_dist
        elif current_min_dist is None:
            new_best_dist = old_dist
        else:
            new_best_dist = min(old_dist, current_min_dist)

        # max_dist — najdalsza odległość wykrycia
        if old_max_dist is None and current_max_dist is None:
            new_best_max_dist = None
        elif old_max_dist is None:
            new_best_max_dist = current_max_dist
        elif current_max_dist is None:
            new_best_max_dist = old_max_dist
        else:
            new_best_max_dist = max(old_max_dist, current_max_dist)

        new_best_speed = max(old_speed or 0, current_max_speed or 0)
        new_has_loc = 1 if new_best_dist is not None else 0

        # Scalanie tras — stara trasa + separator null + nowa trasa
        merged_route = []
        if old_route_json:
            try:
                merged_route = json.loads(old_route_json)
            except:
                merged_route = []
        if merged_route and current_route:
            merged_route.append(None)  # separator — przerwa w linii na mapie
        merged_route.extend(current_route)
        merged_route_json = json.dumps(merged_route) if merged_route else None
        
        # Aktualizujemy rekord
        c.execute("""UPDATE historia SET 
                     last_seen = ?, 
                     min_dist = ?, 
                     max_dist = ?,
                     max_speed = ?,
                     has_location = ?,
                     route = ?
                     WHERE rowid = ?""", 
                     (current_last_seen, new_best_dist, new_best_max_dist, new_best_speed, new_has_loc, merged_route_json, row_id))

    else:
        # NOWY WPIS
        has_loc = 1 if current_min_dist is not None else 0
        
        c.execute("INSERT INTO historia (icao, callsign, model, min_dist, max_speed, category, has_location, first_seen, last_seen, route, max_dist) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
            icao,
            plane.get('callsign', 'N/A'),
            plane.get('model', 'Nieznany'),
            current_min_dist,
            current_max_speed,
            plane.get('category', 0),
            has_loc,
            int(plane['first_seen']),
            current_last_seen,
            route_json,
            current_max_dist
        ))

    conn.commit()
    conn.close()

def rarity_check(model_text):
    #zwraca punkty w zależności od rzadkości samolotu
    text = model_text.upper()

    #lista "VIP" -> najrzadsze samoloty 100 pkt
    vip = ["AIR FORCE", "MILITARY", "NATO", "NAVY", "POLICE", "LPR", "ANTONOV", "ROBINSON"]
    if any(x in text for x in vip): return 100
    #Lista rzadkich samolotów -> 50 pkt
    rare = ["A380", "CESSNA", "PIPER", "TECNAM"]
    if any(x in text for x in rare): return 50
    #lista częstych samolotów -> 0 pkt
    common = ["BOEING", "AIRBUS A320", "AIRBUS A321", "EMBRAER", "RYANAIR", "WIZZ AIR", "CRJ", "ATR 72"]
    if any(x in text for x in common): return 0

    #reszta 10 pkt
    return 10

def archive_past_days():
    conn = sqlite3.connect(DB_NAME, timeout = 10)
    c = conn.cursor()
    
    today_str = date.today().strftime("%Y-%m-%d")
    
    import math
    MY_LAT = 51.978
    MY_LON = 17.498
    NUM_SECTORS = 36
    SECTOR_SIZE = 360 / NUM_SECTORS

    def _haversine(lat1, lon1, lat2, lon2):
        R = 6371
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dp = math.radians(lat2 - lat1)
        dl = math.radians(lon2 - lon1)
        a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
        return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))

    def _bearing(lat1, lon1, lat2, lon2):
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dl = math.radians(lon2 - lon1)
        x = math.sin(dl) * math.cos(p2)
        y = math.cos(p1)*math.sin(p2) - math.sin(p1)*math.cos(p2)*math.cos(dl)
        brng = math.degrees(math.atan2(x, y))
        return (brng + 360) % 360

    c.execute("SELECT DISTINCT date(last_seen, 'unixepoch', 'localtime') as d FROM historia WHERE d != ?", (today_str,))
    days_to_archive = [row[0] for row in c.fetchall()]
    
    for day_str in days_to_archive:
        c.execute("SELECT 1 FROM daily_stats WHERE day_date = ?", (day_str,))
        if c.fetchone(): continue 

        print(f"Archiwizuję dzień: {day_str}...")
        
        day_start = datetime.strptime(day_str, "%Y-%m-%d").timestamp()
        day_end = day_start + 86400
        
        # 1. Liczniki
        c.execute("SELECT COUNT(*) FROM historia WHERE last_seen >= ? AND last_seen < ?", (day_start, day_end))
        total = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM historia WHERE last_seen >= ? AND last_seen < ? AND min_dist <= 5.0", (day_start, day_end))
        close = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM historia WHERE last_seen >= ? AND last_seen < ? AND category = 1", (day_start, day_end))
        light = c.fetchone()[0]
        
        # 2. Ghost 
        key_words = ['Military', 'Air Force', 'NATO', 'Army', 'Polish Air Force']
        sql_like = " OR ".join([f"model LIKE '%{slowo}%'" for slowo in key_words])
        c.execute(f"SELECT model FROM historia WHERE last_seen >= ? AND last_seen < ? AND has_location = 0 AND ({sql_like}) LIMIT 1", (day_start, day_end))
        ghost_row = c.fetchone()
        mil_ghost = ghost_row[0] if ghost_row else None 
        
        # 3. Najdalszy
        c.execute("SELECT model, COALESCE(max_dist, min_dist) as best_dist FROM historia WHERE last_seen >= ? AND last_seen < ? AND COALESCE(max_dist, min_dist) IS NOT NULL AND COALESCE(max_dist, min_dist) < 9000 ORDER BY best_dist DESC LIMIT 1", (day_start, day_end))
        f_row = c.fetchone()
        f_model = f_row[0] if f_row else ""
        f_dist = f_row[1] if f_row else 0
        
        # 4. Najczęstsze 5
        c.execute("""
            SELECT model, COUNT(*) as cnt 
            FROM historia 
            WHERE last_seen >= ? AND last_seen < ? 
            AND model IS NOT NULL AND model NOT LIKE 'Nieznany%' AND model != 'None' AND TRIM(model) != ''
            GROUP BY model ORDER BY cnt DESC LIMIT 5
        """, (day_start, day_end))
        top_json = json.dumps(c.fetchall())

        # 5. Najrzadsze 5
        c.execute("""
            SELECT model, COUNT(*) as cnt 
            FROM historia 
            WHERE last_seen >= ? AND last_seen < ? 
            AND model IS NOT NULL AND model NOT LIKE 'Nieznany%' AND model != 'None' AND TRIM(model) != ''
            GROUP BY model 
        """, (day_start, day_end))
        all_models = c.fetchall()
        
        scored = []
        for m, count in all_models:
            pts = rarity_check(m)
            scored.append((m, count, pts))
        scored.sort(key=lambda x: (x[2], -x[1]), reverse=True)
        rare_json = json.dumps([(x[0], x[1]) for x in scored[:5]])

        day_sectors = [0.0] * NUM_SECTORS

        def _process_point(lat, lon):
            dist = _haversine(MY_LAT, MY_LON, lat, lon)
            if dist < 1 or dist > 800:
                return
            brng = _bearing(MY_LAT, MY_LON, lat, lon)
            idx = int(brng / SECTOR_SIZE) % NUM_SECTORS
            if dist > day_sectors[idx]:
                day_sectors[idx] = dist

        c.execute("SELECT route FROM historia WHERE last_seen >= ? AND last_seen < ? AND route IS NOT NULL", (day_start, day_end))
        for r_row in c.fetchall():
            if not r_row[0]: continue
            try:
                route = json.loads(r_row[0])
                for point in route:
                    if point is None: continue
                    if isinstance(point, list) and len(point) == 2:
                        _process_point(point[0], point[1])
            except:
                pass
        
        range_map_json = json.dumps([round(d, 1) for d in day_sectors])

        # Zapis do bazy
        c.execute("INSERT INTO daily_stats (day_date, total_flights, close_flights, light_flights, military_ghost_found, farthest_dist, farthest_model, rarest_model, top_model, range_map) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  (day_str, total, close, light, mil_ghost, f_dist, f_model, rare_json, top_json, range_map_json))
        
    conn.commit()
    conn.close()

def get_history_stats(date_str, mode='day'):
    conn = sqlite3.connect(DB_NAME, timeout = 10)
    c = conn.cursor()
    
    today_str = date.today().strftime("%Y-%m-%d")
    if mode == 'day' and date_str == today_str:
        conn.close()
        return get_detailed_stats_today()

    if mode == 'day':
        c.execute("SELECT * FROM daily_stats WHERE day_date = ?", (date_str,))
        row = c.fetchone()
        conn.close()
        if not row: return None
        
        try:
            raw_top = json.loads(row[8]) if row[8] else []
            raw_rare = json.loads(row[7]) if row[7] else []
        except:
            raw_top = []
            raw_rare = []

        top_list = [item for item in raw_top if item[0] and len(item[0].strip()) > 1]
        rare_list = [item for item in raw_rare if item[0] and len(item[0].strip()) > 1]
        ghost_val = row[4]
        ghost_display = None
        
        if ghost_val:
            if str(ghost_val) == "1": # Stare archiwum
                ghost_display = "Wykryto (Szczegóły nieznane)"
            else:
                ghost_display = str(ghost_val) # Nowe archiwum (nazwa modelu)

        return {
            "total": row[1], "close": row[2], "light": row[3],
            "farthest": {'dist': row[5], 'model': row[6]} if row[5] else None,
            "ghost_model": ghost_display,
            "top_models": top_list,
            "rare_models": rare_list
        }
    
    elif mode == 'week' or mode == "month":
        try:
            if mode == "week":
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                start_week = dt - timedelta(days=dt.weekday())
                end_week = start_week + timedelta(days=6)
                s_str = start_week.strftime("%Y-%m-%d")
                e_str = end_week.strftime("%Y-%m-%d")
            
            elif mode == "month":
                #Format daty: YYYY-MM
                parts = date_str.split('-')
                y = int(parts[0])
                m = int(parts[1])

                last_day = calendar.monthrange(y,m)[1]
                s_str = f"{y}-{m:02d}-01"
                e_str = f"{y}-{m:02d}-{last_day}"
        except Exception as e:
            print(f"Błąd daty {e}")
            conn.close()
            return None
        
        c.execute("""
            SELECT SUM(total_flights), SUM(close_flights), SUM(light_flights), 
                   MAX(military_ghost_found), MAX(farthest_dist)
            FROM daily_stats WHERE day_date >= ? AND day_date <= ?
        """, (s_str, e_str))
        c.execute("""
            SELECT SUM(total_flights), SUM(close_flights), SUM(light_flights), MAX(farthest_dist)
            FROM daily_stats WHERE day_date >= ? AND day_date <= ?
        """, (s_str, e_str))
        sums = c.fetchone()

        if not sums or sums[0] is None:
            conn.close()
            return None
        
        c.execute("""
            SELECT top_model, rarest_model, military_ghost_found, farthest_model, farthest_dist
            FROM daily_stats WHERE day_date >= ? AND day_date <= ?
        """, (s_str, e_str))
        rows = c.fetchall()
        conn.close()
        
        weekly_top = {}
        weekly_rare = {}
        ghost_found = set()
        max_dist_found = 0
        max_dist_model = "Nieznany"
        
        for r in rows:
            # r[0] = top_json, r[1] = rare_json, r[2] = ghost, r[3] = f_model, r[4] = f_dist
            #1. Sumowanie top modeli
            if r[0]:
                try:
                    day_list = json.loads(r[0])
                    for model, count in day_list:
                        if model and len(model.strip()) > 1:
                            weekly_top[model] = weekly_top.get(model, 0) + count
                except: pass

            #2. Sumowanie rzadkich modeli
            if r[1]:
                try:
                    day_list = json.loads(r[1])
                    for model, count in day_list:
                        if model and len(model.strip()) > 1:
                            weekly_rare[model] = weekly_rare.get(model, 0) + count
                except: pass

            #3. Zbieranie nazw duchów
            if r[2]:
                val = str(r[2])
                if val != "1" and val != "0":
                    ghost_found.add(val)

            #4. Najdalszy samolot
            dist = r[4] if r[4] else 0
            if dist > max_dist_found:
                max_dist_found = dist
                max_dist_model = r[3]
            
        #Sortowanie wyników tygodniowych
        sorted_top = sorted(weekly_top.items(), key=lambda x: x[1], reverse=True)[:5]
        scored_rare = []
        for model, count in weekly_rare.items():
            pts = rarity_check(model)
            scored_rare.append((model, count, pts))

        scored_rare.sort(key=lambda x: (x[2], -x[1]), reverse=True)
        final_rare = [(x[0], x[1]) for x in scored_rare[:5]]

        ghost_text = None
        if ghost_found:
            ghost_text = ", ".join(list(ghost_found)[:3])
            if len(ghost_found) > 3:
                ghost_text += ", ..."
        elif sums[0] > 0 and not ghost_found:
            for r in rows:
                if r[2] == 1:
                    ghost_text = "Wykryto (Szczegóły nieznane)"
                    break


        return {
            "total": sums[0], "close": sums[1], "light": sums[2],
            "farthest": {'dist': max_dist_found, 'model': max_dist_model},
            "ghost_model": ghost_text,
            "top_models": sorted_top,
            "rare_models": final_rare
        }

def get_stat_today():
    #Zwraca statystyki od północy do teraz
    conn = sqlite3.connect(DB_NAME, timeout = 10)
    c = conn.cursor()
    today_midnight = datetime.combine(date.today(), datetime.min.time()).timestamp()
    
    # 1. Łączna liczba samolotów dzisiaj
    c.execute("SELECT COUNT(*) FROM historia WHERE last_seen > ?", (today_midnight,))
    total = c.fetchone()[0]
    
    # 2. Łączna liczba w promieniu 5 km
    c.execute("SELECT COUNT(*) FROM historia WHERE last_seen > ? AND min_dist <= 5.0", (today_midnight,))
    near_5km = c.fetchone()[0]
    
    # 3. Najrzadszy model
    c.execute("SELECT model FROM historia WHERE last_seen > ?", (today_midnight,))
    rows = c.fetchall()
    best_model = "Brak danych"
    max_score = -1
    found_any_valid = False
    for row in rows:
        model = row[0]
        if not model or 'NIEZNANY' in model.upper():
            continue
        
        found_any_valid = True
        score = rarity_check(model)
        if score >= max_score:
            max_score = score
            best_model = model

    if total > 0 and not found_any_valid:
        best_model = "Tylko niezidentyfikowane"

    # 4. Samolot wojskowy bez lokalizacji
    key_words = ['Military', 'Air Force', 'NATO', 'Army', 'Polish Air Force']
    sql_like = " OR ".join([f"model LIKE '%{slowo}%'" for slowo in key_words])
    
    query_military = f"""
        SELECT COUNT(*) FROM historia 
        WHERE last_seen > ? 
        AND has_location = 0 
        AND ({sql_like})
    """
    c.execute(query_military, (today_midnight,))
    military_invisible = c.fetchone()[0]
    
    # 5. Samoloty lekkie/prywatne w promieniu 5 km
    c.execute("SELECT COUNT(*) FROM historia WHERE last_seen > ? AND min_dist <= 5.0 AND category = 1", (today_midnight,))
    lekkie_5km = c.fetchone()[0]

    conn.close()
    
    return {
        "stat_total": total,
        "stat_close": near_5km,
        "stat_rarest": best_model,
        "stat_military_ghost": military_invisible > 0, # Zwraca True/False
        "stat_light": lekkie_5km
    }

def get_detailed_stats_today():
    #Zwraca szczegółowe statystyki do podstrony statystyk
    conn = sqlite3.connect(DB_NAME, timeout = 10)
    c = conn.cursor()
    today_midnight = datetime.combine(date.today(), datetime.min.time()).timestamp()
    # 1. Podstawowe liczniki
    c.execute("SELECT COUNT(*) FROM historia WHERE last_seen > ?", (today_midnight,))
    total = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM historia WHERE last_seen > ? AND min_dist <= 5.0", (today_midnight,))
    close_5km = c.fetchone()[0]
    
    # 2. Samoloty lekkie (WSZYSTKIE dzisiaj, nie tylko bliskie)
    c.execute("SELECT COUNT(*) FROM historia WHERE last_seen > ? AND category = 1", (today_midnight,))
    light_total = c.fetchone()[0]
    
    # 3. Wojskowy Ghost - pobieramy NAZWĘ modelu
    key_words = ['Military', 'Air Force', 'NATO', 'Army', 'Polish Air Force']
    sql_like = " OR ".join([f"model LIKE '%{slowo}%'" for slowo in key_words])

    c.execute(f"""
        SELECT model FROM historia 
        WHERE last_seen > ? 
        AND has_location = 0 
        AND ({sql_like})
        LIMIT 1
    """, (today_midnight,))

    ghost_row = c.fetchone()
    ghost_info = ghost_row[0] if ghost_row else None

    #4. Top 3 najczęstszych modeli
    c.execute("""
        SELECT model, COUNT(*) as cnt 
        FROM historia 
        WHERE last_seen > ? 
        AND model IS NOT NULL 
        AND model != '' 
        AND model != 'Nieznany model'
        AND model != 'None'
        AND TRIM(model) != ''
        GROUP BY model 
        ORDER BY cnt DESC 
        LIMIT 5
    """, (today_midnight,))
    top_models = c.fetchall()

    #5. Top 5 najrzadszych samolotów
    c.execute("""
        SELECT model, COUNT(*) as cnt 
        FROM historia 
        WHERE last_seen > ? 
        AND model IS NOT NULL 
        AND model != '' 
        AND model != 'Nieznany model'
        AND model != 'None'
        AND TRIM(model) != ''
        GROUP BY model 
        ORDER BY cnt ASC 
    """, (today_midnight,))
    all_models_rows = c.fetchall()

    #Ocena rzadkości i przypisanie punktów
    scored_models = []
    for model, count in all_models_rows:
        points = rarity_check(model)
        scored_models.append((model, count, points))

    #Sortowanie według punktów i liczby wystąpień
    scored_models.sort(key=lambda x: (x[2], -x[1]), reverse=True)
    rare_models = [(model, count) for model, count, points in scored_models[:5]]

    #Najdalszy odebrany samolot (wg max_dist, fallback na min_dist dla starych danych)
    c.execute("""
        SELECT model, COALESCE(max_dist, min_dist) as best_dist
        FROM historia
        WHERE last_seen > ? 
        AND COALESCE(max_dist, min_dist) IS NOT NULL
        AND COALESCE(max_dist, min_dist) < 9000
        ORDER BY best_dist DESC
        LIMIT 1
    """, (today_midnight,))

    farthest_row = c.fetchone()
    farthest_data = {'model': farthest_row[0], 'dist': farthest_row[1]} if farthest_row else None
    conn.close()

    return {
        "total": total,
        "close": close_5km,
        "light": light_total,
        "ghost_model": ghost_info,
        "top_models": top_models,
        "rare_models": rare_models,
        "farthest": farthest_data
    }

def get_flights_list(date_from=None, date_to=None):
    #Pobiera listę lotów z podanego zakresu dat do wyświetlenia w tabeli
    conn = sqlite3.connect(DB_NAME, timeout = 10)
    c = conn.cursor()

    # Domyślnie: dzisiejszy dzień
    if not date_from:
        date_from = date.today().strftime("%Y-%m-%d")
    if not date_to:
        date_to = date_from

    try:
        start_ts = datetime.strptime(date_from, "%Y-%m-%d").timestamp()
        end_dt = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
        end_ts = end_dt.timestamp()
    except ValueError:
        # Fallback na dzisiaj przy błędnym formacie
        start_ts = datetime.combine(date.today(), datetime.min.time()).timestamp()
        end_ts = start_ts + 86400

    multi_day = (date_from != date_to)
    
    c.execute("""
        SELECT rowid, icao, model, last_seen, min_dist, max_speed, route 
        FROM historia 
        WHERE last_seen >= ? AND last_seen < ?
        ORDER BY last_seen DESC
    """, (start_ts, end_ts))
    
    rows = c.fetchall()
    conn.close()
    
    results = []
    for row in rows:
        # Pokaż datę + godzinę gdy zakres > 1 dzień, w przeciwnym razie tylko godzinę
        if multi_day:
            time_str = datetime.fromtimestamp(row[3]).strftime('%d.%m %H:%M')
        else:
            time_str = datetime.fromtimestamp(row[3]).strftime('%H:%M')
        has_route = bool(row[6] and row[6] != '[]' and row[6] != 'null')
        
        # Bezpieczne ładowanie dystansu, żeby uniknąć exception w jsonach
        raw_dist = row[4]
        safe_dist = 9999.0 if raw_dist is None else round(raw_dist, 1)

        results.append({
            "rowid": row[0],
            "icao": row[1],
            "model": row[2],
            "time": time_str,
            "dist": safe_dist, #Dla frontendów listowych wspierających "9999" jako ukrycie (Android) i list.html
            "speed": row[5],
            "has_route": has_route
        })
        
    return results

def get_flight_route(rowid):
    """Pobiera trasę lotu z bazy danych po rowid"""
    conn = sqlite3.connect(DB_NAME, timeout = 10)
    c = conn.cursor()
    c.execute("SELECT icao, route FROM historia WHERE rowid = ?", (rowid,))
    row = c.fetchone()
    conn.close()
    if not row or not row[1]:
        return None, []
    try:
        route = json.loads(row[1])
    except:
        route = []
    return row[0], route

def get_range_data(date_str, mode='day', active_planes=None):
    """Oblicza zasięg radiowy w 36 sektorach (co 10°).
    Zwraca listę: [{ angle: 0, dist: 123.4 }, ...] dla każdego sektora."""
    import math

    MY_LAT = 51.978
    MY_LON = 17.498
    NUM_SECTORS = 36
    SECTOR_SIZE = 360 / NUM_SECTORS

    def _haversine(lat1, lon1, lat2, lon2):
        R = 6371
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dp = math.radians(lat2 - lat1)
        dl = math.radians(lon2 - lon1)
        a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
        return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))

    def _bearing(lat1, lon1, lat2, lon2):
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dl = math.radians(lon2 - lon1)
        x = math.sin(dl) * math.cos(p2)
        y = math.cos(p1)*math.sin(p2) - math.sin(p1)*math.cos(p2)*math.cos(dl)
        brng = math.degrees(math.atan2(x, y))
        return (brng + 360) % 360

    sectors = [0.0] * NUM_SECTORS

    def _process_point(lat, lon):
        dist = _haversine(MY_LAT, MY_LON, lat, lon)
        if dist < 1 or dist > 800:
            return
        brng = _bearing(MY_LAT, MY_LON, lat, lon)
        idx = int(brng / SECTOR_SIZE) % NUM_SECTORS
        if dist > sectors[idx]:
            sectors[idx] = dist

    # 1. Pobierz trasy z bazy danych
    conn = sqlite3.connect(DB_NAME, timeout=10)
    c = conn.cursor()

    today_str = date.today().strftime("%Y-%m-%d")

    def _merge_sectors(saved_map_json):
        if saved_map_json:
            try:
                saved = json.loads(saved_map_json)
                for i in range(NUM_SECTORS):
                    if i < len(saved) and saved[i] > sectors[i]:
                        sectors[i] = saved[i]
            except:
                pass

    if mode == 'day':
        if date_str == today_str:
            # Dzisiaj — dane z bazy wg aktualnych godzin + aktywne samoloty
            today_midnight = datetime.combine(date.today(), datetime.min.time()).timestamp()
            c.execute("SELECT route FROM historia WHERE last_seen > ? AND route IS NOT NULL", (today_midnight,))
            for row in c.fetchall():
                if not row[0]: continue
                try:
                    route = json.loads(row[0])
                    for point in route:
                        if point is None: continue
                        if isinstance(point, list) and len(point) == 2:
                            _process_point(point[0], point[1])
                except:
                    pass
        else:
            # Wcześniejszy dzień - pobieramy z daily_stats, jeżeli brak to próbujemy z historia (jeśli to wczoraj i jeszcze nie usunięto)
            c.execute("SELECT range_map FROM daily_stats WHERE day_date = ?", (date_str,))
            stats_row = c.fetchone()
            if stats_row and stats_row[0]:
                _merge_sectors(stats_row[0])
            else:
                day_start = datetime.strptime(date_str, "%Y-%m-%d").timestamp()
                day_end = day_start + 86400
                c.execute("SELECT route FROM historia WHERE last_seen >= ? AND last_seen < ? AND route IS NOT NULL", (day_start, day_end))
                for row in c.fetchall():
                    if not row[0]: continue
                    try:
                        route = json.loads(row[0])
                        for point in route:
                            if point is None: continue
                            if isinstance(point, list) and len(point) == 2:
                                _process_point(point[0], point[1])
                    except:
                        pass
    elif mode == 'week' or mode == 'month':
        if mode == 'week':
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            start_week = dt - timedelta(days=dt.weekday())
            end_week = start_week + timedelta(days=6)
            s_str = start_week.strftime("%Y-%m-%d")
            e_str = end_week.strftime("%Y-%m-%d")
            start_ts = start_week.timestamp()
            end_ts = (end_week + timedelta(days=1)).timestamp()
        else: # month
            import calendar
            parts = date_str.split('-')
            y, m = int(parts[0]), int(parts[1])
            last_day = calendar.monthrange(y, m)[1]
            s_str = f"{y}-{m:02d}-01"
            e_str = f"{y}-{m:02d}-{last_day}"
            start_ts = datetime(y, m, 1).timestamp()
            end_ts = datetime(y, m, last_day, 23, 59, 59).timestamp()

        # Pobieramy zarchiwizowane mapy zasięgu 
        c.execute("SELECT day_date, range_map FROM daily_stats WHERE day_date >= ? AND day_date <= ?", (s_str, e_str))
        archived_days = set()
        for row in c.fetchall():
            archived_days.add(row[0])
            _merge_sectors(row[1])

        # Pobieramy to, czego jeszcze nie ma w daily_stats (np. dzisiejsze trasy lub wczorajsze przed archiwizacją)
        c.execute("SELECT last_seen, route FROM historia WHERE last_seen >= ? AND last_seen < ? AND route IS NOT NULL", (start_ts, end_ts))
        for row in c.fetchall():
            if not row[1]: continue
            row_date = datetime.fromtimestamp(row[0]).strftime("%Y-%m-%d")
            # Nie przetwarzaj tras z dni, które już mają kompletną zapisaną mapę zasięgu
            if row_date in archived_days:
                continue
            try:
                route = json.loads(row[1])
                for point in route:
                    if point is None: continue
                    if isinstance(point, list) and len(point) == 2:
                        _process_point(point[0], point[1])
            except:
                pass

    # 2. Dodaj aktywne samoloty (jeśli to dzisiejszy dzień)
    if mode == 'day' and date_str == today_str and active_planes:
        for plane in active_planes:
            if "lat" in plane and "lon" in plane:
                _process_point(plane["lat"], plane["lon"])

    # Buduj wynik
    result = []
    for i in range(NUM_SECTORS):
        result.append({
            "angle": i * SECTOR_SIZE,
            "dist": round(sectors[i], 1)
        })

    conn.close()
    return result

def delete_old_data():
    conn = sqlite3.connect(DB_NAME, timeout = 10)
    c = conn.cursor()
    limit = time.time() - (48 * 3600)
    c.execute("DELETE FROM historia WHERE last_seen < ?", (limit,))
    conn.commit()
    conn.close()