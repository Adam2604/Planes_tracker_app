"""Buffered SQLite observations and daily per-track coverage samples."""
from datetime import datetime, timezone
import json
import logging
import queue
import sqlite3
import threading
import time

from anomaly import Settings, build_profiles

SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
 id INTEGER PRIMARY KEY, station TEXT NOT NULL, track_id TEXT NOT NULL,
 icao TEXT NOT NULL, observed_at REAL NOT NULL, lat REAL, lon REAL,
 altitude REAL, speed REAL, heading REAL, vertical_rate REAL, v_type TEXT,
 accepted INTEGER NOT NULL, distance REAL, sector INTEGER, band INTEGER,
 raw_message TEXT, analysis TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_observations_track_time ON observations(track_id, observed_at);
CREATE INDEX IF NOT EXISTS idx_observations_time ON observations(observed_at);
CREATE TABLE IF NOT EXISTS coverage_samples (
 station TEXT NOT NULL, track_id TEXT NOT NULL, sector INTEGER NOT NULL,
 band INTEGER NOT NULL, day TEXT NOT NULL, max_distance REAL NOT NULL,
 PRIMARY KEY (station, track_id, sector, band, day)
);
CREATE INDEX IF NOT EXISTS idx_coverage_station_day ON coverage_samples(station, day);
CREATE TABLE IF NOT EXISTS anomaly_events (
 id INTEGER PRIMARY KEY, station TEXT NOT NULL, track_id TEXT NOT NULL,
 icao TEXT NOT NULL, observed_at REAL NOT NULL, lat REAL, lon REAL,
 analysis TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_anomaly_event_time ON anomaly_events(observed_at);
"""


class ObservationStore:
    def __init__(self, path, station, settings=Settings()):
        self.path, self.station, self.settings = path, station, settings
        self.pending = queue.Queue(maxsize=20000)
        self.profiles = {}
        self.dropped = 0
        self.last_error = None
        self.stop_event = threading.Event()
        self.thread = None
        self.flush_lock = threading.Lock()
        self.retry_batch = []
        self.last_refresh = 0

    def initialize(self):
        with sqlite3.connect(self.path, timeout=10) as conn:
            conn.executescript(SCHEMA)
        self.refresh()

    def submit(self, observation):
        try:
            self.pending.put_nowait(observation)
        except queue.Full:
            self.dropped += 1
            if self.dropped == 1 or self.dropped % 1000 == 0:
                logging.error("Observation queue full: %s observations lost", self.dropped)

    def flush(self):
        # Keep the failed batch for a later retry; never silently lose evidence.
        with self.flush_lock:
            batch = self.retry_batch
            while len(batch) < 1000:
                try:
                    batch.append(self.pending.get_nowait())
                except queue.Empty:
                    break
            if not batch:
                return
            try:
                with sqlite3.connect(self.path, timeout=10) as conn:
                    for row in batch:
                        a = row["analysis"]
                        encoded = json.dumps(a, ensure_ascii=False, allow_nan=False)
                        conn.execute("""INSERT INTO observations
                            (station, track_id, icao, observed_at, lat, lon, altitude, speed,
                             heading, vertical_rate, v_type, accepted, distance, sector, band,
                             raw_message, analysis) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (self.station, row["track_id"], row["icao"], row["time"], row["lat"], row["lon"],
                             row.get("altitude"), row.get("speed"), row.get("heading"), row.get("vertical_rate"),
                             row.get("v_type"), int(a["accepted"]), row["distance"], row["sector"],
                             row["band"], row.get("raw_message"), encoded))
                        if a["trainable"] and row["band"] is not None:
                            day = datetime.fromtimestamp(row["time"], timezone.utc).date().isoformat()
                            conn.execute("""INSERT INTO coverage_samples VALUES (?,?,?,?,?,?)
                                ON CONFLICT(station,track_id,sector,band,day) DO UPDATE SET
                                max_distance=MAX(max_distance,excluded.max_distance)""",
                                (self.station, row["track_id"], row["sector"], row["band"], day, row["distance"]))
                        if row.get("event"):
                            conn.execute("INSERT INTO anomaly_events (station,track_id,icao,observed_at,lat,lon,analysis) VALUES (?,?,?,?,?,?,?)",
                                (self.station, row["track_id"], row["icao"], row["time"], row["lat"], row["lon"], encoded))
                self.retry_batch = []
                self.last_error = None
            except (sqlite3.Error, ValueError, TypeError) as exc:
                self.retry_batch = batch
                self.last_error = str(exc)
                logging.exception("Cannot persist observations; batch retained for retry")

    def refresh(self, now=None):
        now = time.time() if now is None else now
        today = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
        cutoff = now - self.settings.window_days * 86400
        cutoff_day = datetime.fromtimestamp(cutoff, timezone.utc).date().isoformat()
        with sqlite3.connect(self.path, timeout=10) as conn:
            rows = conn.execute("""SELECT sector,band,track_id,day,max_distance FROM coverage_samples
                WHERE station=? AND day>=? AND day<?""", (self.station, cutoff_day, today)).fetchall()
            conn.execute("DELETE FROM observations WHERE observed_at<?", (now - self.settings.observation_days * 86400,))
            conn.execute("DELETE FROM coverage_samples WHERE day<?", (cutoff_day,))
            conn.execute("DELETE FROM anomaly_events WHERE observed_at<?", (cutoff,))
        self.profiles = build_profiles(rows, self.settings)
        self.last_refresh = now

    def start(self):
        self.thread = threading.Thread(target=self._worker, name="observation-writer", daemon=True)
        self.thread.start()

    def _worker(self):
        while not self.stop_event.wait(1):
            self.flush()
            if time.time() - self.last_refresh >= 3600:
                try:
                    self.refresh()
                except sqlite3.Error as exc:
                    self.last_error = str(exc)
                    logging.exception("Cannot refresh coverage profile")

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=12)
        # Bounded shutdown even when storage is unavailable.
        while self.retry_batch or not self.pending.empty():
            self.flush()
            if self.last_error:
                logging.error("Unflushed observations remain at shutdown: %s", self.last_error)
                break

    def recent_events(self, limit=100):
        with sqlite3.connect(self.path, timeout=10) as conn:
            rows = conn.execute("""SELECT id,icao,track_id,observed_at,lat,lon,analysis
                FROM anomaly_events WHERE station=? ORDER BY observed_at DESC, id DESC LIMIT ?""",
                (self.station, min(200, max(1, limit)))).fetchall()
        return [dict(id=r[0], icao=r[1], track_id=r[2], time=r[3], lat=r[4], lon=r[5],
                     analysis=json.loads(r[6])) for r in rows]

    def health(self):
        return {"mode": "observe", "queued": self.pending.qsize() + len(self.retry_batch),
                "dropped": self.dropped, "storage_ok": self.last_error is None,
                "profile_updated_at": self.last_refresh,
                "ready_buckets": sum(p["ready"] for p in self.profiles.values())}
