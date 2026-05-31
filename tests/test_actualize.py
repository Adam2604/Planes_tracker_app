import pytest
import time
import threading


# --- Kopia logiki z main.py (nie można importować main.py bez rtlsdr) ---

planes = {}
planes_data = {}
planes_lock = threading.Lock()

SPOOF_DIST_THRESHOLD = 400


def actualize_plane(icao, dane):
    with planes_lock:
        if icao not in planes:
            model_info = planes_data.get(icao, "Nieznany model")
            planes[icao] = {
                "icao": icao,
                "first_seen": time.time(),
                "model": model_info,
                "dist": 9999,
                "min_dist": 9999,
                "speed": 0,
                "max_speed": 0,
                "category": 0,
                "route": [],
                "spoof_score": 0,
                "is_spoofed": False,
                "rejected_jumps": 0
            }
        planes[icao].update(dane)
        planes[icao]["last_seen"] = time.time()

        if "lat" in dane and "lon" in dane:
            planes[icao]["route"].append([dane["lat"], dane["lon"]])

        if "dist" in dane:
            if planes[icao].get("min_dist") is None or dane["dist"] < planes[icao]["min_dist"]:
                planes[icao]["min_dist"] = dane["dist"]
            if planes[icao].get("max_dist") is None or dane["dist"] > planes[icao].get("max_dist", 0):
                planes[icao]["max_dist"] = dane["dist"]

        if "speed" in dane:
            if dane["speed"] > planes[icao]["max_speed"]:
                planes[icao]["max_speed"] = dane["speed"]


def evaluate_spoof_score(icao):
    """Ocenia prawdopodobieństwo spoofingu na podstawie wielu kryteriów.
    Ustawia is_spoofed=True gdy spoof_score >= 60."""
    with planes_lock:
        if icao not in planes:
            return
        plane = planes[icao]
        score = 0

        max_dist = plane.get("max_dist")
        speed = plane.get("speed", 0)
        altitude = plane.get("altitude")
        rejected = plane.get("rejected_jumps", 0)
        model = plane.get("model", "")

        # Reguła 1: Dystans powyżej progu = pewny spoofing
        if max_dist is not None and max_dist > SPOOF_DIST_THRESHOLD:
            score += 60

        # Reguła 2: Dystans w strefie podejrzanej (>300 km ale <400 km)
        if max_dist is not None and 300 < max_dist <= SPOOF_DIST_THRESHOLD:
            score += 30

        # Reguła 3: Pozycja daleko (>300km) ale brak prędkości/kursu
        if max_dist is not None and max_dist > 300 and speed == 0:
            score += 30

        # Reguła 4: Wiele odrzuconych skoków pozycji (>3)
        if rejected > 3:
            score += 30

        # Reguła 5: Nieznany ICAO + duża odległość
        if max_dist is not None and max_dist > 300:
            if model == "Nieznany model" or not model:
                score += 20

        # Reguła 6: Nierealnie wysoka/niska wysokość
        if altitude is not None:
            if altitude > 15000 or altitude < -100:
                score += 20

        plane["spoof_score"] = score
        plane["is_spoofed"] = score >= 60


# --- Fixture ---

@pytest.fixture(autouse=True)
def reset_globals():
    """Czyści globalny stan przed każdym testem."""
    planes.clear()
    planes_data.clear()
    yield
    planes.clear()
    planes_data.clear()


# --- Testy ---

class TestActualizePlaneNewEntry:
    """Testy tworzenia nowego samolotu."""

    def test_creates_new_plane(self):
        actualize_plane("ABC123", {"callsign": "LOT123"})
        assert "ABC123" in planes

    def test_new_plane_has_default_values(self):
        actualize_plane("ABC123", {})
        p = planes["ABC123"]
        assert p["icao"] == "ABC123"
        assert p["dist"] == 9999
        assert p["min_dist"] == 9999
        assert p["speed"] == 0
        assert p["max_speed"] == 0
        assert p["category"] == 0
        assert p["route"] == []

    def test_new_plane_has_unknown_model(self):
        actualize_plane("ABC123", {})
        assert planes["ABC123"]["model"] == "Nieznany model"

    def test_new_plane_gets_model_from_planes_data(self):
        planes_data["XYZ789"] = "Boeing 737 [Ryanair]"
        actualize_plane("XYZ789", {})
        assert planes["XYZ789"]["model"] == "Boeing 737 [Ryanair]"

    def test_new_plane_has_first_seen(self):
        before = time.time()
        actualize_plane("ABC123", {})
        after = time.time()
        assert before <= planes["ABC123"]["first_seen"] <= after

    def test_new_plane_has_last_seen(self):
        before = time.time()
        actualize_plane("ABC123", {})
        after = time.time()
        assert before <= planes["ABC123"]["last_seen"] <= after

    def test_new_plane_has_spoof_defaults(self):
        actualize_plane("ABC123", {})
        p = planes["ABC123"]
        assert p["spoof_score"] == 0
        assert p["is_spoofed"] == False
        assert p["rejected_jumps"] == 0


class TestActualizePlaneUpdate:
    """Testy aktualizacji istniejącego samolotu."""

    def test_update_merges_data(self):
        actualize_plane("ABC123", {"callsign": "LOT1"})
        actualize_plane("ABC123", {"altitude": 10000})
        p = planes["ABC123"]
        assert p["callsign"] == "LOT1"
        assert p["altitude"] == 10000

    def test_last_seen_updates_on_each_call(self):
        actualize_plane("ABC123", {})
        t1 = planes["ABC123"]["last_seen"]
        time.sleep(0.01)
        actualize_plane("ABC123", {})
        t2 = planes["ABC123"]["last_seen"]
        assert t2 >= t1

    def test_first_seen_does_not_change(self):
        actualize_plane("ABC123", {})
        first = planes["ABC123"]["first_seen"]
        time.sleep(0.01)
        actualize_plane("ABC123", {"speed": 500})
        assert planes["ABC123"]["first_seen"] == first


class TestMinDist:
    """Testy śledzenia minimalnego dystansu."""

    def test_min_dist_set_on_first_update(self):
        actualize_plane("A1", {"dist": 50.0})
        assert planes["A1"]["min_dist"] == 50.0

    def test_min_dist_decreases(self):
        actualize_plane("A1", {"dist": 100.0})
        actualize_plane("A1", {"dist": 30.0})
        assert planes["A1"]["min_dist"] == 30.0

    def test_min_dist_does_not_increase(self):
        actualize_plane("A1", {"dist": 30.0})
        actualize_plane("A1", {"dist": 100.0})
        assert planes["A1"]["min_dist"] == 30.0

    def test_min_dist_stays_with_equal_value(self):
        actualize_plane("A1", {"dist": 50.0})
        actualize_plane("A1", {"dist": 50.0})
        assert planes["A1"]["min_dist"] == 50.0

    def test_min_dist_default_when_no_dist(self):
        actualize_plane("A1", {"callsign": "XX"})
        assert planes["A1"]["min_dist"] == 9999


class TestMaxSpeed:
    """Testy śledzenia maksymalnej prędkości."""

    def test_max_speed_set_on_first_update(self):
        actualize_plane("A1", {"speed": 800})
        assert planes["A1"]["max_speed"] == 800

    def test_max_speed_increases(self):
        actualize_plane("A1", {"speed": 400})
        actualize_plane("A1", {"speed": 900})
        assert planes["A1"]["max_speed"] == 900

    def test_max_speed_does_not_decrease(self):
        actualize_plane("A1", {"speed": 900})
        actualize_plane("A1", {"speed": 400})
        assert planes["A1"]["max_speed"] == 900

    def test_max_speed_default_when_no_speed(self):
        actualize_plane("A1", {"callsign": "XX"})
        assert planes["A1"]["max_speed"] == 0


class TestRoute:
    """Testy rejestrowania trasy lotu."""

    def test_route_adds_point(self):
        actualize_plane("A1", {"lat": 51.0, "lon": 17.0})
        assert planes["A1"]["route"] == [[51.0, 17.0]]

    def test_route_grows_with_each_position(self):
        actualize_plane("A1", {"lat": 51.0, "lon": 17.0})
        actualize_plane("A1", {"lat": 52.0, "lon": 18.0})
        actualize_plane("A1", {"lat": 53.0, "lon": 19.0})
        assert len(planes["A1"]["route"]) == 3
        assert planes["A1"]["route"][-1] == [53.0, 19.0]

    def test_route_not_updated_without_lat_lon(self):
        actualize_plane("A1", {"speed": 500})
        assert planes["A1"]["route"] == []

    def test_route_not_updated_with_only_lat(self):
        actualize_plane("A1", {"lat": 51.0})
        assert planes["A1"]["route"] == []

    def test_route_not_updated_with_only_lon(self):
        actualize_plane("A1", {"lon": 17.0})
        assert planes["A1"]["route"] == []


class TestMultiplePlanes:
    """Testy z wieloma samolotami jednocześnie."""

    def test_independent_planes(self):
        actualize_plane("A1", {"speed": 800})
        actualize_plane("B2", {"speed": 400})
        assert planes["A1"]["speed"] == 800
        assert planes["B2"]["speed"] == 400

    def test_planes_dont_share_routes(self):
        actualize_plane("A1", {"lat": 51.0, "lon": 17.0})
        actualize_plane("B2", {"lat": 52.0, "lon": 18.0})
        assert len(planes["A1"]["route"]) == 1
        assert len(planes["B2"]["route"]) == 1
        assert planes["A1"]["route"][0] != planes["B2"]["route"][0]

    def test_many_planes(self):
        for i in range(50):
            actualize_plane(f"ICAO{i}", {"speed": i * 10})
        assert len(planes) == 50
        assert planes["ICAO49"]["speed"] == 490


class TestSpoofDetection:
    """Testy systemu detekcji spoofingu."""

    def test_normal_plane_not_spoofed(self):
        """Samolot z normalnym dystansem nie powinien być oznaczony."""
        planes_data["NORMAL"] = "Boeing 737 [Ryanair]"
        actualize_plane("NORMAL", {"dist": 150.0, "speed": 800})
        evaluate_spoof_score("NORMAL")
        assert planes["NORMAL"]["is_spoofed"] == False
        assert planes["NORMAL"]["spoof_score"] == 0

    def test_far_plane_spoofed_over_threshold(self):
        """Samolot z max_dist > 400 km = pewny spoofing (score >= 60)."""
        actualize_plane("FAR1", {"dist": 600.0, "speed": 800})
        evaluate_spoof_score("FAR1")
        assert planes["FAR1"]["is_spoofed"] == True
        assert planes["FAR1"]["spoof_score"] >= 60

    def test_suspicious_distance_not_spoofed_alone(self):
        """300-400 km sam z siebie daje 30 pkt — nie wystarczy na spoofing."""
        planes_data["SUS1"] = "Airbus A320 [Wizz Air]"
        actualize_plane("SUS1", {"dist": 350.0, "speed": 800})
        evaluate_spoof_score("SUS1")
        assert planes["SUS1"]["is_spoofed"] == False
        assert planes["SUS1"]["spoof_score"] == 30

    def test_suspicious_distance_plus_no_speed_is_spoofed(self):
        """300-400 km + brak prędkości = 30 + 30 = 60 → spoofing."""
        actualize_plane("SUS2", {"dist": 350.0, "speed": 0})
        evaluate_spoof_score("SUS2")
        assert planes["SUS2"]["is_spoofed"] == True
        assert planes["SUS2"]["spoof_score"] >= 60

    def test_unknown_icao_far_adds_points(self):
        """Nieznany ICAO + >300km dodaje 20 pkt."""
        # Nie dodajemy do planes_data → model = "Nieznany model"
        actualize_plane("UNK1", {"dist": 350.0, "speed": 800})
        evaluate_spoof_score("UNK1")
        # 30 (podejrzany dystans) + 20 (nieznany ICAO) = 50, nie spoofed
        assert planes["UNK1"]["spoof_score"] == 50
        assert planes["UNK1"]["is_spoofed"] == False

    def test_unknown_icao_far_no_speed_is_spoofed(self):
        """Nieznany ICAO + >300km + brak prędkości = 30+30+20 = 80 → spoofing."""
        actualize_plane("UNK2", {"dist": 350.0, "speed": 0})
        evaluate_spoof_score("UNK2")
        assert planes["UNK2"]["is_spoofed"] == True
        assert planes["UNK2"]["spoof_score"] >= 60

    def test_many_rejected_jumps(self):
        """Wiele odrzuconych skoków (>3) dodaje 30 pkt."""
        actualize_plane("JUMP1", {"dist": 100.0, "speed": 800})
        planes["JUMP1"]["rejected_jumps"] = 5
        evaluate_spoof_score("JUMP1")
        assert planes["JUMP1"]["spoof_score"] == 30
        assert planes["JUMP1"]["is_spoofed"] == False

    def test_many_rejected_jumps_plus_far_is_spoofed(self):
        """Wiele skoków + podejrzany dystans = spoofing."""
        actualize_plane("JUMP2", {"dist": 350.0, "speed": 800})
        planes["JUMP2"]["rejected_jumps"] = 5
        evaluate_spoof_score("JUMP2")
        # 30 (dystans 300-400) + 30 (skoki) = 60 → spoofing
        assert planes["JUMP2"]["is_spoofed"] == True

    def test_unrealistic_altitude_adds_points(self):
        """Nierealnie wysoka wysokość dodaje 20 pkt."""
        planes_data["ALT1"] = "Boeing 777"
        actualize_plane("ALT1", {"dist": 200.0, "speed": 800, "altitude": 16000})
        evaluate_spoof_score("ALT1")
        assert planes["ALT1"]["spoof_score"] == 20
        assert planes["ALT1"]["is_spoofed"] == False

    def test_negative_altitude_adds_points(self):
        """Ujemna wysokość poniżej -100m dodaje 20 pkt."""
        planes_data["ALT2"] = "Cessna 172"
        actualize_plane("ALT2", {"dist": 50.0, "speed": 200, "altitude": -500})
        evaluate_spoof_score("ALT2")
        assert planes["ALT2"]["spoof_score"] == 20

    def test_normal_altitude_no_points(self):
        """Normalna wysokość nie dodaje punktów."""
        planes_data["ALT3"] = "Boeing 737"
        actualize_plane("ALT3", {"dist": 200.0, "speed": 800, "altitude": 10000})
        evaluate_spoof_score("ALT3")
        assert planes["ALT3"]["spoof_score"] == 0

    def test_close_plane_never_spoofed(self):
        """Bliski samolot (< 100km) nigdy nie powinien być spoofowany."""
        actualize_plane("CLOSE1", {"dist": 50.0, "speed": 800, "altitude": 10000})
        evaluate_spoof_score("CLOSE1")
        assert planes["CLOSE1"]["is_spoofed"] == False
        assert planes["CLOSE1"]["spoof_score"] == 0

    def test_score_resets_on_reevaluation(self):
        """Score jest przeliczany od zera przy każdej ewaluacji."""
        actualize_plane("RESET1", {"dist": 600.0, "speed": 800})
        evaluate_spoof_score("RESET1")
        assert planes["RESET1"]["is_spoofed"] == True

        # Wyobraź sobie, że max_dist się nie zmienia - nadal spoofed
        evaluate_spoof_score("RESET1")
        assert planes["RESET1"]["is_spoofed"] == True

    def test_nonexistent_icao_no_crash(self):
        """Ewaluacja dla nieistniejącego ICAO nie powoduje crash."""
        evaluate_spoof_score("NOPE")  # nie powinno rzucić wyjątku

    def test_cumulative_scoring(self):
        """Wiele reguł naraz kumuluje punkty."""
        # Far (>400) + no speed + unknown ICAO + high altitude
        actualize_plane("MEGA", {"dist": 600.0, "speed": 0, "altitude": 16000})
        planes["MEGA"]["rejected_jumps"] = 5
        evaluate_spoof_score("MEGA")
        # 60 (far) + 30 (no speed far) + 30 (jumps) + 20 (unknown) + 20 (altitude) = 160
        assert planes["MEGA"]["spoof_score"] == 160
        assert planes["MEGA"]["is_spoofed"] == True
