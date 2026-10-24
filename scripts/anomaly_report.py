"""Read-only observation-mode report; no inferred ground-truth labels."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3


def report(path):
    with sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True) as conn:
        tracks = conn.execute('SELECT COUNT(DISTINCT track_id) FROM observations').fetchone()[0]
        observed = conn.execute('SELECT MIN(observed_at), MAX(observed_at), COUNT(*) FROM observations').fetchone()
        affected = set()
        suspected = set()
        reasons = Counter()
        for track, encoded in conn.execute('SELECT track_id, analysis FROM observations'):
            analysis = json.loads(encoded)
            if analysis['status'] != 'clear':
                affected.add(track)
            if analysis['status'] == 'suspected':
                suspected.add(track)
            reasons.update(analysis['reason_codes'])
        reviewed_events = {}
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='anomaly_reviews'").fetchone():
            reviewed_events = dict(conn.execute('''SELECT r.status,COUNT(*) FROM anomaly_reviews r
                JOIN anomaly_events e ON e.id=r.event_id AND e.station=r.station GROUP BY r.status''').fetchall())
    return dict(tracks=tracks, tracks_with_anomalies=len(affected),
                tracks_with_suspicions=len(suspected), observations=observed[2],
                first_observation=observed[0], last_observation=observed[1],
                reason_observation_counts=dict(reasons),
                saved_event_review_counts=reviewed_events,
                note='Alarm frequency only. False-positive rate requires reviewed labels.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database')
    args = parser.parse_args()
    print(json.dumps(report(args.database), indent=2))
