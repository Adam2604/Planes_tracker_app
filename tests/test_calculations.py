import pytest
import math


def calculate_distance(lat1, lon1, lat2, lon2):
    """Kopia funkcji z main.py — importowana bezpośrednio, bo main.py
    wymaga rtlsdr, którego nie ma w środowisku testowym."""
    R = 6371
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2)**2
    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


class TestCalculateDistance:
    """Testy funkcji calculate_distance (wzór Haversine'a)."""

    def test_same_point_returns_zero(self):
        """Ten sam punkt → odległość 0."""
        assert calculate_distance(51.0, 17.0, 51.0, 17.0) == 0.0

    def test_known_distance_warsaw_krakow(self):
        """Warszawa–Kraków ≈ 252 km."""
        dist = calculate_distance(52.2297, 21.0122, 50.0647, 19.9450)
        assert dist == pytest.approx(252, abs=5)

    def test_known_distance_london_paris(self):
        """Londyn–Paryż ≈ 344 km."""
        dist = calculate_distance(51.5074, -0.1278, 48.8566, 2.3522)
        assert dist == pytest.approx(344, abs=5)

    def test_antipodes(self):
        """Dwa punkty na przeciwnych stronach Ziemi ≈ 20 015 km."""
        dist = calculate_distance(0.0, 0.0, 0.0, 180.0)
        assert dist == pytest.approx(20015, abs=20)

    def test_negative_coordinates(self):
        """Współrzędne na południowej/zachodniej półkuli."""
        dist = calculate_distance(-33.8688, 151.2093, -34.6037, -58.3816)
        assert dist > 11_000

    def test_short_distance(self):
        """Bardzo krótka odległość (~1 km)."""
        dist = calculate_distance(51.0, 17.0, 51.009, 17.0)
        assert dist == pytest.approx(1.0, abs=0.1)

    def test_symmetry(self):
        """Odległość A→B == B→A."""
        d1 = calculate_distance(52.0, 21.0, 50.0, 19.0)
        d2 = calculate_distance(50.0, 19.0, 52.0, 21.0)
        assert d1 == pytest.approx(d2, abs=0.001)

    def test_only_latitude_difference(self):
        """Ruch tylko po szerokości geograficznej (1° ≈ 111 km)."""
        dist = calculate_distance(50.0, 17.0, 51.0, 17.0)
        assert dist == pytest.approx(111, abs=2)

    def test_only_longitude_difference_at_equator(self):
        """Ruch tylko po długości geograficznej na równiku (1° ≈ 111 km)."""
        dist = calculate_distance(0.0, 0.0, 0.0, 1.0)
        assert dist == pytest.approx(111, abs=2)

    def test_result_is_always_positive(self):
        """Wynik zawsze jest liczbą dodatnią."""
        dist = calculate_distance(60.0, 10.0, -30.0, -50.0)
        assert dist > 0
