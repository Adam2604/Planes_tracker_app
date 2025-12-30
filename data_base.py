import sqlite3
import time
from datetime import datetime, date

DB_NAME = "radar.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS historia (
                    icao TEXT,
                    callsign TEXT,
                    model TEXT,
                    min_dist REAL,
                    max_speed INTEGER,
                    category INTEGER,
                    has_location INTEGER,
                    first_seen INTEGER,
                    last_seen INTEGER
                )''')
    c.execute("CREATE INDEX IF NOT EXISTS idx_icao_time ON historia (icao, last_seen)")
    conn.commit()
    conn.close()

def save_flight(plane):
    # Ignorujemy szumy (krótsze niż 10s)
    if plane['last_seen'] - plane['first_seen'] < 10:
        return

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Dane do zapisu
    icao = plane.get('icao')
    current_min_dist = plane.get('min_dist', 9999)
    current_speed = plane.get('speed', 0)
    current_max_speed = plane.get('max_speed', current_speed) 
    current_last_seen = int(plane['last_seen'])
    
    today_midnight = datetime.combine(date.today(), datetime.min.time()).timestamp()

    # Sprawdzamy, czy ten samolot już był dzisiaj w bazie
    c.execute("""SELECT rowid, min_dist, max_speed, first_seen, has_location 
                 FROM historia 
                 WHERE icao = ? AND last_seen > ?""", (icao, today_midnight))
    
    existing_row = c.fetchone()

    if existing_row:
        # Samolot już był dzisiaj. Scalamy dane.
        row_id, old_dist, old_speed, old_first, old_has_loc = existing_row
        
        # Wybieramy najlepsze wartości z obu przelotów
        new_best_dist = min(old_dist, current_min_dist)
        new_best_speed = max(old_speed, current_max_speed)
        new_has_loc = 1 if new_best_dist != 9999 else 0
        
        # Aktualizujemy rekord
        c.execute("""UPDATE historia SET 
                     last_seen = ?, 
                     min_dist = ?, 
                     max_speed = ?,
                     has_location = ?
                     WHERE rowid = ?""", 
                     (current_last_seen, new_best_dist, new_best_speed, new_has_loc, row_id))

    else:
        # NOWY WPIS
        has_loc = 1 if current_min_dist != 9999 else 0
        
        c.execute("INSERT INTO historia VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (
            icao,
            plane.get('callsign', 'N/A'),
            plane.get('model', 'Nieznany'),
            current_min_dist,
            current_max_speed,
            plane.get('category', 0),
            has_loc,
            int(plane['first_seen']),
            current_last_seen
        ))

    conn.commit()
    conn.close()

def rarity_check(model_text):
    #zwraca punkty w zależności od rzadkości samolotu
    text = model_text.upper()

    #lista "VIP" -> najrzadsze samoloty 100 pkt
    vip = ["AIR FORCE", "MILITARY", "NATO", "NAVY", "POLICE", "LPR", "CESSNA", "PIPER", "ANTONOV", "ROBINSON"]
    if any(x in text for x in vip): return 100

    #lista częstych samolotów -> 0 pkt
    common = ["BOEING", "AIRBUS A320", "AIRBUS A321", "EMBRAER", "RYANAIR", "WIZZ AIR", "CRJ", "ATR 72"]
    if any(x in text for x in common): return 0

    #reszta 10 pkt
    return 10

def get_stat_today():
    #Zwraca statystyki od północy do teraz
    conn = sqlite3.connect(DB_NAME)
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
    conn = sqlite3.connect(DB_NAME)
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
        AND model != 'Nieznany'
        AND model != 'None'
        AND TRIM(model) != ''
        GROUP BY model 
        ORDER BY cnt DESC 
        LIMIT 3
    """, (today_midnight,))
    top_models = c.fetchall()
    conn.close()

    return {
        "total": total,
        "close": close_5km,
        "light": light_total,
        "ghost_model": ghost_info,
        "top_models": top_models
    }

def get_flights_list():
    #Pobiera listę lotów z dzisiaj do wyświetlenia w tabeli
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    today_midnight = datetime.combine(date.today(), datetime.min.time()).timestamp()
    
    c.execute("""
        SELECT icao, model, last_seen, min_dist, max_speed 
        FROM historia 
        WHERE last_seen > ? 
        ORDER BY last_seen DESC
    """, (today_midnight,))
    
    rows = c.fetchall()
    conn.close()
    
    results = []
    for row in rows:
        # Konwersja znacznika czasu na godzinę (np. "15:43")
        time_str = datetime.fromtimestamp(row[2]).strftime('%H:%M')
        
        results.append({
            "icao": row[0],
            "model": row[1],
            "time": time_str,
            "dist": round(row[3], 1),
            "speed": row[4]
        })
        
    return results

def delete_old_data():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    limit = time.time() - (48 * 3600)
    c.execute("DELETE FROM historia WHERE last_seen < ?", (limit,))
    conn.commit()
    conn.close()