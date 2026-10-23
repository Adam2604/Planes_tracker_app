import sqlite3
import time
import pytest
import main
import data_base
from anomaly import bearing
from observation_store import ObservationStore


@pytest.fixture
def receiver(tmp_path, monkeypatch):
    path = str(tmp_path / 'radar.db')
    monkeypatch.setattr(data_base, 'DB_NAME', path)
    data_base.init_db()
    store = ObservationStore(path, main.STATION_ID)
    store.initialize()
    monkeypatch.setattr(main, 'observation_store', store)
    main.planes.clear()
    main.detectors.clear()
    main.cpr_buffer.clear()
    yield store
    main.planes.clear()
    main.detectors.clear()
    main.cpr_buffer.clear()


def test_rejection_is_persisted_and_explained_without_changing_accepted_route(receiver):
    now = time.time()
    main.actualize_plane('ABC123', {'altitude': 10000})
    main.process_position('ABC123', 52, 17, now)
    result = main.process_position('ABC123', 55, 17, now+1)
    assert not result['accepted']
    assert main.planes['ABC123']['route'] == [[52, 17]]
    assert main.planes['ABC123']['anomaly']['status'] == 'anomaly'
    receiver.flush()
    with sqlite3.connect(receiver.path) as conn:
        assert conn.execute('SELECT accepted FROM observations ORDER BY observed_at').fetchall() == [(1,), (0,)]
    api = main.app.test_client()
    assert api.get('/data').json[0]['anomaly']['reasons']
    assert api.get('/route/ABC123').json['suspect_segments']
    assert api.get('/api/anomalies').json['events'][0]['analysis']['status'] == 'anomaly'
    assert api.get('/anomalies').status_code == 200


def test_observe_mode_never_excludes_suspected_flight(receiver):
    now = time.time()
    main.actualize_plane('ABC123', {'altitude': 10000})
    main.process_position('ABC123', 52, 17, now)
    for offset, lat in ((1, 55), (4, 56), (7, 57)):
        sector = int(bearing(main.MY_LAT, main.MY_LON, lat, 17)//10)
        receiver.profiles[(sector, 3)] = dict(ready=True, tracks=40, days=5, p95_km=100, p99_km=120)
        result = main.process_position('ABC123', lat, 17, now+offset)
    assert result['status'] == 'suspected'
    assert not main.planes['ABC123']['is_spoofed']
    data_base.save_flight(main.planes['ABC123'])
    with sqlite3.connect(receiver.path) as conn:
        assert conn.execute('SELECT is_spoofed FROM historia').fetchone()[0] == 0


def test_real_cpr_decoding_and_unknown_velocity(receiver):
    main.decode_details('8D40621D58C382D690C8AC2863A7')
    main.decode_details('8D40621D58C386435CC412692AD6')
    plane = main.planes['40621D']
    assert plane['lat'] is not None
    assert plane['speed'] is None
    assert plane['anomaly']['status'] == 'clear'


def test_api_marks_stale_position_even_when_other_messages_keep_track_alive(receiver):
    main.process_position('ABC123', 52, 17, time.time()-20)
    main.actualize_plane('ABC123', {'callsign': 'TEST'})
    assert main.app.test_client().get('/data').json[0]['anomaly']['stale']


def test_reacquired_track_has_separator_and_history_still_loads(receiver):
    now = time.time()
    main.process_position('ABC123', 55, 17, now)
    for t in (1, 3, 6):
        main.process_position('ABC123', 52, 17, now+t)
    assert None in main.planes['ABC123']['route']
    data_base.save_flight(main.planes['ABC123'])
    assert main.app.test_client().get('/api/list').status_code == 200
