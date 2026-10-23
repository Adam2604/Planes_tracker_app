"""Explainable, observation-only ADS-B anomaly detection (no radio dependency).

Scores are heuristic evidence weights, never probabilities. Bearing is derived
from the reported position; it is not a measured direction of arrival.
"""
from collections import deque
from dataclasses import dataclass
import math

VERSION = "sector-motion-v1"
LABELS = {"clear": "Brak wykrytych anomalii", "anomaly": "Anomalia",
          "suspected": "Podejrzenie spoofingu"}
REASONS = {
    "coverage": "Pozycja poza typowym zasięgiem sektora i wysokości",
    "jump": "Przemieszczenie zbyt duże względem czasu między pozycjami",
    "speed": "Przemieszczenie niespójne z aktualną prędkością względem ziemi",
    "reacquired": "Ponownie ustalono trasę po serii niespójnych pozycji",
}


def calculate_distance(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin(math.radians(lat2 - lat1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 6371 * 2 * math.asin(math.sqrt(max(0, min(1, a))))


def bearing(lat1, lon1, lat2, lon2):
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    return math.degrees(math.atan2(math.sin(dl) * math.cos(p2),
        math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl))) % 360


def altitude_band(altitude):
    if altitude is None or not math.isfinite(altitude):
        return None
    return sum(altitude >= edge for edge in (3000, 6000, 9000, 12000))


@dataclass(frozen=True)
class Settings:
    window_days: int = 30
    observation_days: int = 7
    min_tracks: int = 30
    min_days: int = 3
    recovery_seconds: float = 60
    evidence_seconds: float = 30
    velocity_max_age: float = 10
    gap_seconds: float = 60
    coverage_margin_km: float = 30
    coverage_margin_ratio: float = 0.15


def percentile(values, q):
    values = sorted(values)
    k = (len(values) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


def build_profiles(rows, settings=Settings()):
    """Rows: sector, band, track_id, UTC day, maximum qualified distance.

    One vote per track per bucket, including tracks spanning midnight.
    """
    buckets = {}
    for sector, band, track_id, day, distance in rows:
        bucket = buckets.setdefault((sector, band), {"tracks": {}, "days": set()})
        bucket["tracks"][track_id] = max(distance, bucket["tracks"].get(track_id, 0))
        bucket["days"].add(day)
    profiles = {}
    for key, bucket in buckets.items():
        distances = list(bucket["tracks"].values())
        profiles[key] = {
            "tracks": len(distances), "days": len(bucket["days"]),
            "p95_km": round(percentile(distances, .95), 1),
            "p99_km": round(percentile(distances, .99), 1),
            "ready": len(distances) >= settings.min_tracks and len(bucket["days"]) >= settings.min_days,
        }
    return profiles


class TrackDetector:
    def __init__(self, settings=Settings()):
        self.settings = settings
        self.last = None
        self.history = deque(maxlen=180)
        self.candidate = None
        self.candidate_since = None
        self.candidate_count = 0
        self.evidence = deque(maxlen=300)
        self.last_anomaly = None
        self.first_time = None
        self.since = None
        self.status = "clear"
        self.active_codes = []

    def observe(self, point, profile=None):
        """point has time, lat/lon, distance, and nullable fresh velocity fields."""
        now = point["time"]
        if self.first_time is None:
            self.first_time = now
        codes = []
        accepted, break_route = True, False
        ready = bool(profile and profile["ready"])
        if ready:
            limit = profile["p99_km"] + max(self.settings.coverage_margin_km,
                        profile["p99_km"] * self.settings.coverage_margin_ratio)
            if point["distance"] > limit:
                codes.append("coverage")

        if self.last:
            dt = now - self.last["time"]
            jump = calculate_distance(self.last["lat"], self.last["lon"], point["lat"], point["lon"])
            if dt <= 0:
                accepted = False
                codes.append("jump")
            elif dt > self.settings.gap_seconds:
                break_route = True
                self.history.clear()
            elif jump > max(2, .4 * dt):
                accepted = False
                codes.append("jump")

        # Compare over >=5s: per-packet comparisons drown in position quantization.
        anchors = [p for p in self.history if 5 <= now - p["time"] <= 15]
        speed = point.get("speed")
        velocity_time = point.get("velocity_time")
        if (anchors and speed is not None and point.get("v_type") == "GS"
                and velocity_time is not None and 0 <= now - velocity_time <= self.settings.velocity_max_age):
            anchor = anchors[-1]
            distance = calculate_distance(anchor["lat"], anchor["lon"], point["lat"], point["lon"])
            expected = speed * (now - anchor["time"]) / 3600
            # Only excessive displacement: a turn can legitimately shorten the chord.
            if distance > expected + max(2, expected * .6):
                codes.append("speed")

        if not accepted:
            coherent = (self.candidate is not None and 0 < now - self.candidate["time"] <= 10
                and calculate_distance(self.candidate["lat"], self.candidate["lon"],
                    point["lat"], point["lon"]) <= max(2, .4 * (now - self.candidate["time"])))
            if not coherent:
                self.candidate_since, self.candidate_count = now, 0
            self.candidate_count += 1
            self.candidate = point.copy()
            if self.candidate_count >= 3 and now - self.candidate_since >= 5:
                accepted, break_route = True, True
                self.history.clear()
                codes.append("reacquired")
        if accepted:
            self.last = point.copy()
            self.history.append(point.copy())
            self.candidate, self.candidate_count = None, 0

        if codes:
            self.last_anomaly = now
            self.evidence.append((now, codes))
        while self.evidence and now - self.evidence[0][0] > self.settings.evidence_seconds:
            self.evidence.popleft()
        recent = {code for _, items in self.evidence for code in items}
        # Jump + speed are correlated; they count as ONE motion evidence family.
        motion = bool(recent & {"jump", "speed", "reacquired"})
        repeated = len(self.evidence) >= 3 and now - self.evidence[0][0] >= 5
        desired = "suspected" if "coverage" in recent and motion and repeated else "anomaly"
        if codes:
            if self.since is None:
                self.since = now
            self.active_codes = sorted(recent)
            self.status = desired
        elif self.last_anomaly is not None and now - self.last_anomaly >= self.settings.recovery_seconds:
            self.status, self.active_codes, self.since = "clear", [], None
        score = (30 if "coverage" in self.active_codes else 0) + (
            40 if set(self.active_codes) & {"jump", "speed", "reacquired"} else 0)
        return {
            "accepted": accepted, "break_route": break_route,
            "reason_codes": codes, "status": self.status, "label": LABELS[self.status],
            "reasons": [REASONS[c] for c in self.active_codes], "score": score,
            "since": self.since, "last_anomaly": self.last_anomaly,
            "profile": profile or {"ready": False, "tracks": 0, "days": 0},
            "profile_status": "ready" if ready else "insufficient_data",
            # Coverage alone must not censor learning and reinforce its own limit.
            "trainable": accepted and not (set(codes) & {"jump", "speed", "reacquired"})
                and now - self.first_time >= 15
                and not any(set(c) & {"jump", "speed", "reacquired"} for _, c in self.evidence),
            "version": VERSION, "mode": "observe", "evaluated_at": now,
        }
