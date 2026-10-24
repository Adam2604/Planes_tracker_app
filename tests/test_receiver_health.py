import json
import sys
import types

import pyModeS as pms
from receiver_health import ReceiverHealth
from radio_decoder import FrameValidator
from observation_store import ObservationStore


def test_crc_denominator_is_only_df17_18_and_window_expires():
    h, validator = ReceiverHealth(), FrameValidator()
    h.start(100)
    for msg in ['8D40621D58C382D690C8AC2863A7', '8D40621D58C382D690C8AC2863A0', '5D484FDEA248F5']:
        result = validator.validate(msg, pms, 100)
        h.frame(accepted=result is not None, now=100, **validator.last_check)
    h.frame(decode_error=True, now=100)
    s = h.snapshot(110)
    assert s['window']['accepted'] == 2 and s['window']['candidates'] == 3
    assert s['crc_valid_percent'] == 50 and s['window']['crc_checked'] == 2
    assert s['accepted_per_second'] == .2
    assert h.snapshot(161)['crc_valid_percent'] is None
    assert h.snapshot(161)['window']['accepted'] == 0
    assert h.snapshot(161)['totals']['accepted'] == 2


def test_gap_noise_and_error_states():
    h = ReceiverHealth()
    assert h.snapshot(100)['state'] == 'not_started'
    h.start(100)
    h.read(.1, 100)
    h.frame(accepted=True, now=100)
    assert h.snapshot(101)['state'] == 'running'
    assert h.snapshot(101)['noise_db_relative'] == -20
    assert h.snapshot(106)['state'] == 'stalled'
    assert h.snapshot(106)['noise_db_relative'] is None
    h.read(0, 120)
    s = h.snapshot(120)
    assert s['read_gaps'] == 1 and s['max_read_gap_s'] == 20
    assert s['state'] == 'quiet' and s['noise_db_relative'] is None
    json.dumps(s, allow_nan=False)
    h.failed('USB disconnected')
    h.stop()
    assert h.snapshot(121)['state'] == 'error'


def test_init_failure_is_visible_in_api(monkeypatch):
    import main
    def fail():
        raise OSError('No SDR')
    monkeypatch.setitem(sys.modules, 'rtlsdr', types.SimpleNamespace(RtlSdr=fail))
    monkeypatch.setattr(main, 'receiver_health', ReceiverHealth())
    monkeypatch.setattr(main, 'observation_store', None)
    main.radio_loop()
    response = main.app.test_client().get('/api/receiver-health')
    assert response.status_code == 200
    assert response.json['receiver']['state'] == 'error'
    assert response.json['receiver']['error'] == 'No SDR'
    assert response.json['history'] == []
    assert main.app.test_client().get('/receiver').status_code == 200


def test_telemetry_continues_during_failure_and_retains_by_station(tmp_path):
    health = ReceiverHealth()
    health.failed('Disconnected')
    store = ObservationStore(str(tmp_path / 'health.db'), 'one', telemetry_provider=lambda: health.snapshot(100))
    store.initialize()
    store.collect_telemetry(100)
    store.collect_telemetry(101)
    store.collect_telemetry(105)
    store.flush()
    assert len(store.receiver_history(106)) == 2
    assert store.receiver_history(106)[0]['health']['state'] == 'error'
    other = ObservationStore(store.path, 'other')
    assert other.receiver_history(106) == []
    store.refresh(now=40*86400)
    assert store.receiver_history(40*86400) == []
