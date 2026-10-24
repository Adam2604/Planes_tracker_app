"""Bounded, thread-safe receiver diagnostics; noise is relative, not calibrated dBm."""
from collections import deque
import math
import threading
import time


class ReceiverHealth:
    def __init__(self):
        self.lock = threading.Lock()
        self.started = None
        self.state = 'not_started'
        self.last_read = self.last_valid = self.noise = None
        self.error = None
        self.gaps = 0
        self.max_gap = 0
        self.buckets = deque(maxlen=61)
        self.totals = dict(candidates=0, accepted=0, crc_checked=0, crc_ok=0, decode_errors=0)

    def start(self, now=None):
        with self.lock:
            self.started = time.time() if now is None else now
            self.state, self.error = 'running', None

    def read(self, noise, now=None):
        now = time.time() if now is None else now
        with self.lock:
            if self.last_read is not None:
                gap = max(0, now-self.last_read)
                self.max_gap = max(self.max_gap, gap)
                if gap > 2:
                    self.gaps += 1
            self.last_read = now
            self.noise = round(20*math.log10(noise), 1) if noise > 0 and math.isfinite(noise) else None

    def frame(self, accepted=False, crc_checked=False, crc_ok=False, decode_error=False, now=None):
        now = time.time() if now is None else now
        with self.lock:
            second = int(now)
            if not self.buckets or self.buckets[-1][0] != second:
                self.buckets.append((second, dict.fromkeys(self.totals, 0)))
            increments = dict(candidates=int(not decode_error), accepted=int(accepted),
                              crc_checked=int(crc_checked), crc_ok=int(crc_checked and crc_ok),
                              decode_errors=int(decode_error))
            for k, v in increments.items():
                self.buckets[-1][1][k] += v
                self.totals[k] += v
            if accepted:
                self.last_valid = now

    def failed(self, error):
        with self.lock:
            self.state, self.error = 'error', str(error)

    def stop(self):
        with self.lock:
            if self.state != 'error':
                self.state = 'stopped'

    def snapshot(self, now=None):
        now = time.time() if now is None else now
        with self.lock:
            age = lambda t: None if t is None else round(max(0, now-t), 1)
            totals = {k: sum(row[k] for ts, row in self.buckets if 0 <= now-ts < 60) for k in self.totals}
            elapsed = min(60, max(1, now-self.started)) if self.started is not None else 1
            state = self.state
            if state == 'running':
                if self.last_read is None or now-self.last_read > 5:
                    state = 'stalled'
                elif self.last_valid is None or now-self.last_valid > 15:
                    state = 'quiet'
            return dict(time=now, state=state, error=self.error,
                        read_age_s=age(self.last_read), valid_frame_age_s=age(self.last_valid),
                        noise_db_relative=self.noise if self.last_read is not None and now-self.last_read <= 5 else None,
                        noise_at=self.last_read, read_gaps=self.gaps, max_read_gap_s=round(self.max_gap, 2),
                        window_seconds=round(elapsed, 1), window=totals, totals=dict(self.totals),
                        accepted_per_second=round(totals['accepted']/elapsed, 2),
                        candidates_per_second=round(totals['candidates']/elapsed, 2),
                        crc_valid_percent=round(100*totals['crc_ok']/totals['crc_checked'], 1) if totals['crc_checked'] else None)
