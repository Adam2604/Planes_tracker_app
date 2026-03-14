import pytest
import time
import threading


# --- Kopia logiki z main.py (nie można importować main.py bez rtlsdr) ---

planes = {}
planes_data = {}
planes_lock = threading.Lock()


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
                "route": []
            }
        planes[icao].update(dane)
        planes[icao]["last_seen"] = time.time()

        if "lat" in dane and "lon" in dane:
            planes[icao]["route"].append([dane["lat"], dane["lon"]])

        if "dist" in dane:
            if dane["dist"] < planes[icao]["min_dist"]:
                planes[icao]["min_dist"] = dane["dist"]

        if "speed" in dane:
            if dane["speed"] > planes[icao]["max_speed"]:
                planes[icao]["max_speed"] = dane["speed"]


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
