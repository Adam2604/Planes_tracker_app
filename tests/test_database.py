import pytest
import sqlite3
import json
import time
import os
import sys
from datetime import datetime, date, timedelta

# Dodanie katalogu projektu do ścieżki importów
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import data_base


# ─── Fixture: tymczasowa baza danych ───────────────────────────────────────────

@pytest.fixture(autouse=True)
def test_db(tmp_path):
    """Przekierowuje bazę na tymczasowy plik przed każdym testem."""
    db_path = str(tmp_path / "test_radar.db")
    data_base.DB_NAME = db_path
    data_base.init_db()
    yield db_path


# ─── Helpery ───────────────────────────────────────────────────────────────────

def _make_plane(icao="ABC123", callsign="LOT1", model="Boeing 737",
                min_dist=50.0, speed=800, max_speed=850, category=0,
                first_seen=None, last_seen=None, route=None):
    """Tworzy słownik samolotu do testów."""
    now = time.time()
    return {
        "icao": icao,
        "callsign": callsign,
        "model": model,
        "min_dist": min_dist,
        "speed": speed,
        "max_speed": max_speed,
        "category": category,
        "first_seen": first_seen or now - 120,
        "last_seen": last_seen or now,
        "route": route or [[51.0, 17.0], [51.5, 17.5]],
    }


def _insert_flight_raw(db_path, icao="ABC123", callsign="LOT1", model="Boeing 737",
                        min_dist=50.0, max_speed=800, category=0,
                        has_location=1, first_seen=None, last_seen=None, route=None):
    """Wstawia lot bezpośrednio do tabeli historia (bez logiki save_flight)."""
    now = time.time()
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("INSERT INTO historia VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
        icao, callsign, model, min_dist, max_speed, category,
        has_location,
        int(first_seen or now - 120),
        int(last_seen or now),
        json.dumps(route) if route else None,
    ))
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
#  1. init_db
# ═══════════════════════════════════════════════════════════════════════════════

class TestInitDb:

    def test_tables_exist(self, test_db):
        conn = sqlite3.connect(test_db)
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in c.fetchall()}
        conn.close()
        assert "historia" in tables
        assert "daily_stats" in tables

    def test_idempotent(self, test_db):
        """Dwukrotne wywołanie init_db nie rzuca wyjątku."""
        data_base.init_db()
        data_base.init_db()

    def test_historia_columns(self, test_db):
        conn = sqlite3.connect(test_db)
        c = conn.cursor()
        c.execute("PRAGMA table_info(historia)")
        cols = {row[1] for row in c.fetchall()}
        conn.close()
        assert "icao" in cols
        assert "callsign" in cols
        assert "route" in cols
        assert "min_dist" in cols

    def test_index_created(self, test_db):
        conn = sqlite3.connect(test_db)
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indexes = {row[0] for row in c.fetchall()}
        conn.close()
        assert "idx_icao_time" in indexes


# ═══════════════════════════════════════════════════════════════════════════════
#  2. save_flight
# ═══════════════════════════════════════════════════════════════════════════════

class TestSaveFlight:

    def test_saves_new_flight(self, test_db):
        plane = _make_plane()
        data_base.save_flight(plane)

        conn = sqlite3.connect(test_db)
        c = conn.cursor()
        c.execute("SELECT icao, model FROM historia")
        row = c.fetchone()
        conn.close()
        assert row[0] == "ABC123"
        assert row[1] == "Boeing 737"

    def test_filters_noise_short_flight(self, test_db):
        """Lot trwający < 5s nie jest zapisywany."""
        now = time.time()
        plane = _make_plane(first_seen=now - 2, last_seen=now)
        data_base.save_flight(plane)

        conn = sqlite3.connect(test_db)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM historia")
        count = c.fetchone()[0]
        conn.close()
        assert count == 0

    def test_exactly_5s_is_saved(self, test_db):
        """Lot trwający dokładnie 5s jest zapisywany."""
        now = time.time()
        plane = _make_plane(first_seen=now - 5, last_seen=now)
        data_base.save_flight(plane)

        conn = sqlite3.connect(test_db)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM historia")
        count = c.fetchone()[0]
        conn.close()
        assert count == 1

    def test_has_location_set_when_dist_known(self, test_db):
        plane = _make_plane(min_dist=15.0)
        data_base.save_flight(plane)

        conn = sqlite3.connect(test_db)
        c = conn.cursor()
        c.execute("SELECT has_location FROM historia")
        val = c.fetchone()[0]
        conn.close()
        assert val == 1

    def test_has_location_zero_when_no_position(self, test_db):
        plane = _make_plane(min_dist=9999)
        data_base.save_flight(plane)

        conn = sqlite3.connect(test_db)
        c = conn.cursor()
        c.execute("SELECT has_location FROM historia")
        val = c.fetchone()[0]
        conn.close()
        assert val == 0

    def test_route_saved_as_json(self, test_db):
        route = [[51.0, 17.0], [52.0, 18.0]]
        plane = _make_plane(route=route)
        data_base.save_flight(plane)

        conn = sqlite3.connect(test_db)
        c = conn.cursor()
        c.execute("SELECT route FROM historia")
        raw = c.fetchone()[0]
        conn.close()
        assert json.loads(raw) == route

    def test_merge_same_plane_same_day(self, test_db):
        """Ten sam ICAO dzisiaj → aktualizacja, nie duplikat."""
        now = time.time()
        plane1 = _make_plane(min_dist=100.0, max_speed=500,
                             first_seen=now - 300, last_seen=now - 200)
        plane2 = _make_plane(min_dist=30.0, max_speed=900,
                             first_seen=now - 100, last_seen=now)
        data_base.save_flight(plane1)
        data_base.save_flight(plane2)

        conn = sqlite3.connect(test_db)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM historia WHERE icao = 'ABC123'")
        count = c.fetchone()[0]
        c.execute("SELECT min_dist, max_speed FROM historia WHERE icao = 'ABC123'")
        row = c.fetchone()
        conn.close()
        assert count == 1
        assert row[0] == 30.0   # min z obu
        assert row[1] == 900    # max z obu

    def test_merge_routes_with_separator(self, test_db):
        """Scalanie tras wstawia None jako separator."""
        now = time.time()
        plane1 = _make_plane(route=[[51.0, 17.0]],
                             first_seen=now - 300, last_seen=now - 200)
        plane2 = _make_plane(route=[[52.0, 18.0]],
                             first_seen=now - 100, last_seen=now)
        data_base.save_flight(plane1)
        data_base.save_flight(plane2)

        conn = sqlite3.connect(test_db)
        c = conn.cursor()
        c.execute("SELECT route FROM historia WHERE icao = 'ABC123'")
        raw = c.fetchone()[0]
        conn.close()
        route = json.loads(raw)
        # Oczekiwany format: [[51,17], None, [52,18]]
        assert None in route
        assert route[0] == [51.0, 17.0]
        assert route[-1] == [52.0, 18.0]

    def test_different_icao_creates_separate_rows(self, test_db):
        data_base.save_flight(_make_plane(icao="AAA"))
        data_base.save_flight(_make_plane(icao="BBB"))

        conn = sqlite3.connect(test_db)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM historia")
        val = c.fetchone()[0]
        conn.close()
        assert val == 2


# ═══════════════════════════════════════════════════════════════════════════════
#  3. delete_old_data
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeleteOldData:

    def test_deletes_old_records(self, test_db):
        """Rekordy starsze niż 48h są usuwane."""
        old_time = time.time() - (50 * 3600)  # 50h temu
        _insert_flight_raw(test_db, icao="OLD1", last_seen=old_time, first_seen=old_time - 60)
        data_base.delete_old_data()

        conn = sqlite3.connect(test_db)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM historia WHERE icao = 'OLD1'")
        val = c.fetchone()[0]
        conn.close()
        assert val == 0

    def test_keeps_recent_records(self, test_db):
        """Rekordy z ostatnich 24h pozostają."""
        recent_time = time.time() - 3600  # 1h temu
        _insert_flight_raw(test_db, icao="NEW1", last_seen=recent_time, first_seen=recent_time - 60)
        data_base.delete_old_data()

        conn = sqlite3.connect(test_db)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM historia WHERE icao = 'NEW1'")
        val = c.fetchone()[0]
        conn.close()
        assert val == 1

    def test_mixed_old_and_new(self, test_db):
        """Usuwa tylko stare, zostawia nowe."""
        old_time = time.time() - (50 * 3600)
        new_time = time.time() - 3600
        _insert_flight_raw(test_db, icao="OLD", last_seen=old_time, first_seen=old_time - 60)
        _insert_flight_raw(test_db, icao="NEW", last_seen=new_time, first_seen=new_time - 60)
        data_base.delete_old_data()

        conn = sqlite3.connect(test_db)
        c = conn.cursor()
        c.execute("SELECT icao FROM historia")
        remaining = [row[0] for row in c.fetchall()]
        conn.close()
        assert "OLD" not in remaining
        assert "NEW" in remaining


# ═══════════════════════════════════════════════════════════════════════════════
#  4. get_flight_route
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetFlightRoute:

    def test_existing_flight_with_route(self, test_db):
        route = [[51.0, 17.0], [52.0, 18.0]]
        _insert_flight_raw(test_db, icao="RTX", route=route)

        conn = sqlite3.connect(test_db)
        c = conn.cursor()
        c.execute("SELECT rowid FROM historia WHERE icao = 'RTX'")
        rowid = c.fetchone()[0]
        conn.close()

        icao, result = data_base.get_flight_route(rowid)
        assert icao == "RTX"
        assert result == route

    def test_existing_flight_without_route(self, test_db):
        _insert_flight_raw(test_db, icao="NOR", route=None)

        conn = sqlite3.connect(test_db)
        c = conn.cursor()
        c.execute("SELECT rowid FROM historia WHERE icao = 'NOR'")
        rowid = c.fetchone()[0]
        conn.close()

        icao, result = data_base.get_flight_route(rowid)
        assert icao is None or result == []

    def test_nonexistent_rowid(self, test_db):
        icao, result = data_base.get_flight_route(99999)
        assert icao is None
        assert result == []


# ═══════════════════════════════════════════════════════════════════════════════
#  5. get_flights_list
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetFlightsList:

    def test_returns_todays_flights(self, test_db):
        now = time.time()
        _insert_flight_raw(test_db, icao="T1", last_seen=now, first_seen=now - 60)
        _insert_flight_raw(test_db, icao="T2", last_seen=now - 600, first_seen=now - 660)

        today_str = date.today().strftime("%Y-%m-%d")
        result = data_base.get_flights_list(today_str, today_str)
        icaos = [r["icao"] for r in result]
        assert "T1" in icaos
        assert "T2" in icaos

    def test_empty_when_no_flights(self, test_db):
        result = data_base.get_flights_list("2020-01-01", "2020-01-01")
        assert result == []

    def test_has_route_flag(self, test_db):
        now = time.time()
        _insert_flight_raw(test_db, icao="R1", last_seen=now, first_seen=now - 60,
                           route=[[51.0, 17.0]])
        _insert_flight_raw(test_db, icao="R2", last_seen=now, first_seen=now - 60,
                           route=None)

        today_str = date.today().strftime("%Y-%m-%d")
        result = data_base.get_flights_list(today_str, today_str)
        by_icao = {r["icao"]: r for r in result}
        assert by_icao["R1"]["has_route"] is True
        assert by_icao["R2"]["has_route"] is False

    def test_multi_day_format(self, test_db):
        """Zakres wielu dni → format czasu zawiera datę."""
        now = time.time()
        _insert_flight_raw(test_db, icao="M1", last_seen=now, first_seen=now - 60)

        today = date.today()
        yesterday = (today - timedelta(days=1)).strftime("%Y-%m-%d")
        today_str = today.strftime("%Y-%m-%d")
        result = data_base.get_flights_list(yesterday, today_str)
        if result:
            # Format wielodniowy: "dd.mm HH:MM"
            assert "." in result[0]["time"]

    def test_invalid_date_fallback(self, test_db):
        """Nieprawidłowy format daty → fallback na dzisiaj."""
        result = data_base.get_flights_list("bad-date", "bad-date")
        assert isinstance(result, list)

    def test_sorted_by_last_seen_desc(self, test_db):
        """Wyniki posortowane od najnowszych."""
        now = time.time()
        _insert_flight_raw(test_db, icao="OLD", last_seen=now - 3600, first_seen=now - 3660)
        _insert_flight_raw(test_db, icao="NEW", last_seen=now, first_seen=now - 60)

        today_str = date.today().strftime("%Y-%m-%d")
        result = data_base.get_flights_list(today_str, today_str)
        if len(result) >= 2:
            assert result[0]["icao"] == "NEW"

    def test_result_fields(self, test_db):
        """Sprawdzenie struktury zwracanego obiektu."""
        now = time.time()
        _insert_flight_raw(test_db, icao="F1", model="Airbus A320", min_dist=12.5,
                           max_speed=750, last_seen=now, first_seen=now - 60)

        today_str = date.today().strftime("%Y-%m-%d")
        result = data_base.get_flights_list(today_str, today_str)
        assert len(result) >= 1
        flight = result[0]
        assert "rowid" in flight
        assert "icao" in flight
        assert "model" in flight
        assert "time" in flight
        assert "dist" in flight
        assert "speed" in flight
        assert "has_route" in flight


# ═══════════════════════════════════════════════════════════════════════════════
#  6. rarity_check
# ═══════════════════════════════════════════════════════════════════════════════

class TestRarityCheck:

    @pytest.mark.parametrize("model,expected", [
        ("NATO E-3 Sentry", 100),
        ("Air Force One", 100),
        ("Military Transport", 100),
        ("Police Helicopter", 100),
        ("LPR Eurocopter", 100),
        ("Antonov An-225", 100),
        ("Robinson R44", 100),
    ])
    def test_vip_models(self, model, expected):
        assert data_base.rarity_check(model) == expected

    @pytest.mark.parametrize("model,expected", [
        ("Airbus A380", 50),
        ("Cessna 172", 50),
        ("Piper PA-28", 50),
        ("Tecnam P2008", 50),
    ])
    def test_rare_models(self, model, expected):
        assert data_base.rarity_check(model) == expected

    @pytest.mark.parametrize("model,expected", [
        ("Boeing 737", 0),
        ("Airbus A320neo", 0),
        ("Airbus A321", 0),
        ("Embraer E195", 0),
        ("Ryanair Boeing 737", 0),
        ("Wizz Air A321", 0),
        ("Bombardier CRJ-900", 0),
        ("ATR 72-600", 0),
    ])
    def test_common_models(self, model, expected):
        assert data_base.rarity_check(model) == expected

    def test_unknown_model_gets_10(self):
        assert data_base.rarity_check("Dassault Falcon 900") == 10

    def test_empty_string(self):
        assert data_base.rarity_check("") == 10

    def test_case_insensitive(self):
        assert data_base.rarity_check("military transport") == 100
        assert data_base.rarity_check("CESSNA 172") == 50
        assert data_base.rarity_check("boeing 737") == 0


# ═══════════════════════════════════════════════════════════════════════════════
#  7. get_stat_today
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetStatToday:

    def test_empty_db(self, test_db):
        stats = data_base.get_stat_today()
        assert stats["stat_total"] == 0
        assert stats["stat_close"] == 0
        assert stats["stat_rarest"] == "Brak danych"
        assert stats["stat_military_ghost"] is False
        assert stats["stat_light"] == 0

    def test_counts_todays_flights(self, test_db):
        now = time.time()
        _insert_flight_raw(test_db, icao="A1", last_seen=now, first_seen=now - 60)
        _insert_flight_raw(test_db, icao="A2", last_seen=now - 600, first_seen=now - 660)
        _insert_flight_raw(test_db, icao="A3", last_seen=now - 1200, first_seen=now - 1260)

        stats = data_base.get_stat_today()
        assert stats["stat_total"] == 3

    def test_counts_close_flights(self, test_db):
        now = time.time()
        _insert_flight_raw(test_db, icao="C1", min_dist=3.0, last_seen=now, first_seen=now - 60)
        _insert_flight_raw(test_db, icao="C2", min_dist=4.9, last_seen=now, first_seen=now - 60)
        _insert_flight_raw(test_db, icao="C3", min_dist=50.0, last_seen=now, first_seen=now - 60)

        stats = data_base.get_stat_today()
        assert stats["stat_close"] == 2

    def test_rarest_model(self, test_db):
        now = time.time()
        _insert_flight_raw(test_db, icao="R1", model="Boeing 737", last_seen=now, first_seen=now - 60)
        _insert_flight_raw(test_db, icao="R2", model="NATO E-3 Sentry", last_seen=now, first_seen=now - 60)

        stats = data_base.get_stat_today()
        assert stats["stat_rarest"] == "NATO E-3 Sentry"

    def test_military_ghost_detected(self, test_db):
        now = time.time()
        _insert_flight_raw(test_db, icao="G1", model="Military Transport",
                           has_location=0, last_seen=now, first_seen=now - 60)

        stats = data_base.get_stat_today()
        assert stats["stat_military_ghost"] is True

    def test_no_ghost_when_military_has_location(self, test_db):
        now = time.time()
        _insert_flight_raw(test_db, icao="G1", model="Military Transport",
                           has_location=1, last_seen=now, first_seen=now - 60)

        stats = data_base.get_stat_today()
        assert stats["stat_military_ghost"] is False

    def test_light_aircraft_count(self, test_db):
        now = time.time()
        _insert_flight_raw(test_db, icao="L1", category=1, min_dist=3.0,
                           last_seen=now, first_seen=now - 60)
        _insert_flight_raw(test_db, icao="L2", category=0, min_dist=3.0,
                           last_seen=now, first_seen=now - 60)

        stats = data_base.get_stat_today()
        assert stats["stat_light"] == 1


# ═══════════════════════════════════════════════════════════════════════════════
#  8. get_detailed_stats_today
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetDetailedStatsToday:

    def test_empty_db(self, test_db):
        stats = data_base.get_detailed_stats_today()
        assert stats["total"] == 0
        assert stats["close"] == 0
        assert stats["light"] == 0
        assert stats["top_models"] == []
        assert stats["rare_models"] == []

    def test_top_models_sorted(self, test_db):
        now = time.time()
        for i in range(5):
            _insert_flight_raw(test_db, icao=f"B{i}", model="Boeing 737",
                               last_seen=now - i * 10, first_seen=now - i * 10 - 60)
        for i in range(2):
            _insert_flight_raw(test_db, icao=f"A{i}", model="Airbus A320",
                               last_seen=now - (i + 5) * 10, first_seen=now - (i + 5) * 10 - 60)

        stats = data_base.get_detailed_stats_today()
        assert len(stats["top_models"]) >= 2
        assert stats["top_models"][0][0] == "Boeing 737"
        assert stats["top_models"][0][1] == 5

    def test_farthest_plane(self, test_db):
        now = time.time()
        _insert_flight_raw(test_db, icao="F1", model="Długi Lot", min_dist=350.0,
                           last_seen=now, first_seen=now - 60)
        _insert_flight_raw(test_db, icao="F2", model="Krótki Lot", min_dist=10.0,
                           last_seen=now, first_seen=now - 60)

        stats = data_base.get_detailed_stats_today()
        assert stats["farthest"] is not None
        assert stats["farthest"]["model"] == "Długi Lot"
        assert stats["farthest"]["dist"] == 350.0

    def test_farthest_ignores_9999(self, test_db):
        """Samoloty bez lokalizacji (dist 9999) nie są najdalszymi."""
        now = time.time()
        _insert_flight_raw(test_db, icao="NO", model="Brak pozycji", min_dist=9999,
                           last_seen=now, first_seen=now - 60)
        _insert_flight_raw(test_db, icao="OK", model="Ma pozycję", min_dist=100.0,
                           last_seen=now, first_seen=now - 60)

        stats = data_base.get_detailed_stats_today()
        assert stats["farthest"]["model"] == "Ma pozycję"


# ═══════════════════════════════════════════════════════════════════════════════
#  9. archive_past_days
# ═══════════════════════════════════════════════════════════════════════════════

class TestArchivePastDays:

    def test_archives_yesterday(self, test_db):
        """Loty z wczoraj → nowy wiersz w daily_stats."""
        yesterday = time.time() - 86400
        _insert_flight_raw(test_db, icao="Y1", last_seen=yesterday, first_seen=yesterday - 60)

        data_base.archive_past_days()

        conn = sqlite3.connect(test_db)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM daily_stats")
        count = c.fetchone()[0]
        conn.close()
        assert count >= 1

    def test_does_not_archive_today(self, test_db):
        """Dzisiejsze loty nie są archiwizowane."""
        now = time.time()
        _insert_flight_raw(test_db, icao="T1", last_seen=now, first_seen=now - 60)

        data_base.archive_past_days()

        today_str = date.today().strftime("%Y-%m-%d")
        conn = sqlite3.connect(test_db)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM daily_stats WHERE day_date = ?", (today_str,))
        count = c.fetchone()[0]
        conn.close()
        assert count == 0

    def test_no_duplicate_archive(self, test_db):
        """Powtórne wywołanie nie tworzy duplikatu."""
        yesterday = time.time() - 86400
        _insert_flight_raw(test_db, icao="Y1", last_seen=yesterday, first_seen=yesterday - 60)

        data_base.archive_past_days()
        data_base.archive_past_days()

        conn = sqlite3.connect(test_db)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM daily_stats")
        count = c.fetchone()[0]
        conn.close()
        assert count == 1

    def test_archive_counts(self, test_db):
        """Sprawdzenie poprawności liczników w archiwum."""
        yesterday = time.time() - 86400
        _insert_flight_raw(test_db, icao="A1", min_dist=3.0, category=1,
                           last_seen=yesterday, first_seen=yesterday - 60)
        _insert_flight_raw(test_db, icao="A2", min_dist=50.0, category=0,
                           last_seen=yesterday + 100, first_seen=yesterday + 40)
        _insert_flight_raw(test_db, icao="A3", min_dist=4.0, category=0,
                           last_seen=yesterday + 200, first_seen=yesterday + 140)

        data_base.archive_past_days()

        conn = sqlite3.connect(test_db)
        c = conn.cursor()
        c.execute("SELECT total_flights, close_flights, light_flights FROM daily_stats LIMIT 1")
        row = c.fetchone()
        conn.close()
        assert row[0] == 3   # total
        assert row[1] == 2   # close (dist <= 5)
        assert row[2] == 1   # light (category == 1)


# ═══════════════════════════════════════════════════════════════════════════════
#  10. get_history_stats
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetHistoryStats:

    def test_day_mode_today_delegates(self, test_db):
        """Tryb day + data dzisiejsza → deleguje do get_detailed_stats_today."""
        today_str = date.today().strftime("%Y-%m-%d")
        result = data_base.get_history_stats(today_str, "day")
        # get_detailed_stats_today zwraca dict z kluczem 'total'
        assert "total" in result

    def test_day_mode_past_date_no_data(self, test_db):
        """Tryb day + data bez danych → None."""
        result = data_base.get_history_stats("2020-01-01", "day")
        assert result is None

    def test_day_mode_past_date_with_archive(self, test_db):
        """Tryb day + data z archiwum → zwraca statystyki."""
        yesterday = time.time() - 86400
        _insert_flight_raw(test_db, icao="H1", last_seen=yesterday, first_seen=yesterday - 60)
        data_base.archive_past_days()

        yesterday_str = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        result = data_base.get_history_stats(yesterday_str, "day")
        assert result is not None
        assert result["total"] >= 1

    def test_month_mode_no_data(self, test_db):
        result = data_base.get_history_stats("2020-01", "month")
        assert result is None

    def test_month_mode_with_data(self, test_db):
        """Tryb month z zarchiwizowanymi danymi."""
        yesterday = time.time() - 86400
        _insert_flight_raw(test_db, icao="M1", last_seen=yesterday, first_seen=yesterday - 60)
        data_base.archive_past_days()

        month_str = (date.today() - timedelta(days=1)).strftime("%Y-%m")
        result = data_base.get_history_stats(month_str, "month")
        assert result is not None
        assert result["total"] >= 1
