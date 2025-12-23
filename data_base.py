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
    conn.commit()
    conn.close()

def save_flight(plane):
    # Lot jest zapisywane gdy samolot znika z radaru
    # Ignorujemy szumy (krótsze niż 10s)
    if plane['last_seen'] - plane['first_seen'] < 10:
        return

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    min_dist = plane.get('min_dist', 9999)
    has_loc = 1 if min_dist != 9999 else 0

    c.execute("INSERT INTO historia VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (
        plane.get('icao'),
        plane.get('callsign', 'N/A'),
        plane.get('model', 'Nieznany'),
        min_dist,
        plane.get('speed', 0),
        plane.get('category', 0),
        has_loc,
        int(plane['first_seen']),
        int(plane['last_seen'])
    ))
    conn.commit()
    conn.close()

def get_stat_today():
    """Zwraca statystyki od północy do teraz"""
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
    c.execute("""
        SELECT model, COUNT(*) as cnt 
        FROM historia 
        WHERE last_seen > ? 
        GROUP BY model 
        ORDER BY cnt ASC 
        LIMIT 1
    """, (today_midnight,))
    rearest = c.fetchone()
    if rearest:
        rearest = f"{rearest[0]} (widziany {rearest[1]} raz)"
    else:
        rearest = "Brak przelotów < 5km"

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
        "stat_rarest": rearest,
        "stat_military_ghost": military_invisible > 0, # Zwraca True/False
        "stat_light": lekkie_5km
    }

def delete_old_data():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    limit = time.time() - (48 * 3600)
    c.execute("DELETE FROM historia WHERE last_seen < ?", (limit,))
    conn.commit()
    conn.close()