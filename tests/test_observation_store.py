from datetime import datetime, timezone
import json
import sqlite3

from anomaly import TrackDetector
from observation_store import ObservationStore
from scripts.anomaly_report import report


def observation(t=100, **changes):
    row = dict(time=t, icao='ABC123', track_id='track-a', lat=52, lon=17,
               altitude=10000, distance=100, sector=0, band=3)
    row.update(changes)
    row['analysis'] = TrackDetector().observe(row)
    row['event'] = True
    return row


def test_raw_rejected_points_and_event_survive_restart(tmp_path):
    path = str(tmp_path / 'observations.db')
    store = ObservationStore(path, 'station-a')
    store.initialize()
    row = observation()
    row['analysis'].update(accepted=False, status='anomaly', reason_codes=['jump'])
    store.submit(row)
    store.flush()
    reopened = ObservationStore(path, 'station-a')
    events = reopened.recent_events()
    assert events[0]['analysis']['reason_codes'] == ['jump']
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT accepted,lat FROM observations').fetchone() == (0, 52)


def test_replay_quality_and_receiver_context_scoped_and_retained(tmp_path):
    store = ObservationStore(str(tmp_path / 'telemetry.db'), 'one')
    store.initialize()
    base = 40*86400
    point = observation(base+1000)
    point['analysis']['navigation'] = {'version': 2}
    point['analysis']['receiver'] = {'state': 'running'}
    store.submit(point)
    for station, track, at in [('one', 'track-a', 1001), ('one', 'other-track', 1002),
                                ('other', 'track-a', 1003), ('one', 'track-a', 1300)]:
        writer = ObservationStore(store.path, station)
        writer.submit(dict(kind='navigation', time=base+at, track_id=track, icao='ABC123', quality={'version': 2}))
        writer.submit(dict(kind='receiver', time=base+at, health={'state': 'quiet'}))
        writer.flush()
    store.flush()
    event_id = store.recent_events()[0]['id']
    replay = store.replay(event_id)
    assert [r['time'] for r in replay['navigation']] == [base+1001]
    assert [r['time'] for r in replay['receiver']] == [base+1001, base+1002]
    assert replay['points'][0]['navigation']['version'] == 2
    assert replay['event']['analysis']['receiver']['state'] == 'running'
    store.refresh(now=base+1000+8*86400)
    replay = store.replay(event_id)
    assert replay['navigation'] == replay['receiver'] == replay['points'] == []
    assert replay['event']['analysis']['navigation'] == {'version': 2}


def test_profiles_exclude_current_day_and_other_station(tmp_path):
    store = ObservationStore(str(tmp_path / 'observations.db'), 'station-a')
    store.initialize()
    for station, track, day, distance in [
        ('station-a', 'one', '2026-10-20', 200),
        ('station-a', 'one', '2026-10-20', 220),
        ('station-a', 'today', '2026-10-23', 700),
        ('station-b', 'other', '2026-10-20', 800),
    ]:
        row = observation(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp(), track_id=track, distance=distance)
        row['analysis']['trainable'] = True
        writer = ObservationStore(store.path, station)
        writer.submit(row)
        writer.flush()
    store.refresh(datetime(2026, 10, 23, 12, tzinfo=timezone.utc).timestamp())
    p = store.profiles[(0, 3)]
    assert p['tracks'] == 1 and p['p99_km'] == 220


def test_failed_write_is_retried_without_loss_or_duplicates(tmp_path):
    store = ObservationStore(str(tmp_path / 'not_initialized.db'), 'station')
    store.submit(observation())
    store.flush()
    assert store.last_error and len(store.retry_batch) == 1
    store.initialize()
    store.flush()
    assert not store.retry_batch and store.last_error is None
    assert len(store.recent_events()) == 1


def test_retention_and_schema_idempotency(tmp_path):
    store = ObservationStore(str(tmp_path / 'observations.db'), 'station')
    store.initialize()
    store.initialize()
    store.submit(observation(100))
    store.flush()
    store.refresh(now=40*86400)
    with sqlite3.connect(store.path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM observations').fetchone()[0] == 0
        assert conn.execute('SELECT COUNT(*) FROM anomaly_events').fetchone()[0] == 0


def test_unknown_altitude_cannot_train_profile(tmp_path):
    store = ObservationStore(str(tmp_path / 'observations.db'), 'station')
    store.initialize()
    row = observation(band=None, altitude=None)
    row['analysis']['trainable'] = True
    store.submit(row)
    store.flush()
    with sqlite3.connect(store.path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM coverage_samples').fetchone()[0] == 0


def test_calibration_report_counts_tracks_not_repeated_events(tmp_path):
    store = ObservationStore(str(tmp_path / 'observations.db'), 'station')
    store.initialize()
    for t in (100, 101):
        row = observation(t)
        row['analysis'].update(status='anomaly', reason_codes=['jump'])
        store.submit(row)
    store.flush()
    result = report(store.path)
    assert result['tracks'] == result['tracks_with_anomalies'] == 1
    assert result['observations'] == 2
    assert result['reason_observation_counts']['jump'] == 2


def test_raw_retention_is_shorter_than_event_retention(tmp_path):
    store = ObservationStore(str(tmp_path / 'observations.db'), 'station')
    store.initialize()
    now = 2_000_000_000
    store.submit(observation(now - 10*86400))
    store.flush()
    store.refresh(now=now)
    with sqlite3.connect(store.path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM observations').fetchone()[0] == 0
        assert conn.execute('SELECT COUNT(*) FROM anomaly_events').fetchone()[0] == 1
