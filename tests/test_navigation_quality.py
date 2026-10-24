import pyModeS as pms
import pytest

from navigation_quality import NavigationQuality


def message(tc, fields=()):
    bits = list('0' * 112)
    for start, width, value in [(0, 8, 0x8D), (8, 24, 0xABC123), (32, 5, tc), *fields]:
        bits[start:start+width] = f'{value:0{width}b}'
    raw = f'{int("".join(bits), 2):028X}'
    return raw[:-6] + f'{pms.crc(raw):06X}'


def status(version=2, nacp=9, sil=3, supplement=0, basis=0):
    return message(31, [(72, 3, version), (75, 1, supplement), (76, 4, nacp), (82, 2, sil), (86, 1, basis)])


def test_unknown_version_and_missing_are_not_zero():
    q = NavigationQuality()
    q.update(message(11), 100, pms.adsb)
    q.update(message(19, [(37, 3, 1), (42, 3, 3)]), 100, pms.adsb)
    s = q.snapshot(100, pms.adsb)
    assert s['version'] is None and not s['supported']
    assert all(s[k]['value'] is None for k in ('nic', 'nac_p', 'nac_v', 'sil'))
    q.update(status(nacp=0, sil=0), 101, pms.adsb)
    s = q.snapshot(101, pms.adsb)
    assert s['nic']['value'] == 8
    assert s['nac_p']['value'] == s['sil']['value'] == 0
    assert s['nac_v']['value'] == 3


@pytest.mark.parametrize('version,supplement,b,expected', [(1, 0, 0, 8), (1, 1, 0, 9), (2, 0, 0, 8), (2, 1, 1, 9), (2, 1, 0, None)])
def test_nic_uses_version_and_supplements(version, supplement, b, expected):
    q = NavigationQuality()
    q.update(status(version=version, supplement=supplement), 100, pms.adsb)
    q.update(message(11, [(39, 1, b)]), 101, pms.adsb)
    assert q.snapshot(101, pms.adsb)['nic']['value'] == expected


@pytest.mark.parametrize('version', [0, 3, 7])
def test_unsupported_versions_are_not_interpreted(version):
    q = NavigationQuality()
    q.update(status(version=version), 100, pms.adsb)
    assert not q.snapshot(100, pms.adsb)['supported']
    assert q.snapshot(100, pms.adsb)['nac_p']['value'] is None


def test_reserved_values_and_surface_status_are_not_interpreted():
    q = NavigationQuality()
    assert not q.update(message(31, [(37, 3, 1), (72, 3, 2)]), 100, pms.adsb)
    q.update(status(nacp=15), 100, pms.adsb)
    q.update(message(19, [(37, 3, 1), (42, 3, 7)]), 101, pms.adsb)
    s = q.snapshot(101, pms.adsb)
    assert s['nac_p']['value'] is None and s['nac_v']['value'] is None


def test_expiry_and_version_change_clear_cached_metrics():
    q = NavigationQuality()
    q.update(status(), 100, pms.adsb)
    q.update(message(11), 120, pms.adsb)
    assert not q.snapshot(120, pms.adsb)['nic']['stale']
    assert q.snapshot(131, pms.adsb)['nic']['stale']
    q.update(message(11), 160, pms.adsb)
    assert q.snapshot(161, pms.adsb)['nic']['stale']  # expired version
    q.update(status(version=1), 162, pms.adsb)
    assert q.snapshot(162, pms.adsb)['nic']['value'] is None


def test_quality_drop_without_position_and_save_throttle():
    q = NavigationQuality()
    q.update(status(), 100, pms.adsb)
    assert q.should_save(q.snapshot(100, pms.adsb), 100)
    q.update(status(), 101, pms.adsb)
    assert not q.should_save(q.snapshot(101, pms.adsb), 101)
    q.update(status(nacp=3, sil=1), 102, pms.adsb)
    s = q.snapshot(102, pms.adsb)
    assert q.should_save(s, 102)
    assert {(c['field'], c['direction']) for c in s['changes']} == {('nac_p', 'down'), ('sil', 'down')}
    q.update(status(nacp=3, sil=3, basis=1), 103, pms.adsb)
    assert len(q.snapshot(103, pms.adsb)['changes']) == 2  # different SIL basis
    q.update(status(nacp=9), 200, pms.adsb)
    assert len(q.changes) == 2  # no comparison with expired status


def test_decode_persists_quality_even_without_position(tmp_path, monkeypatch):
    import main
    from observation_store import ObservationStore
    store = ObservationStore(str(tmp_path / 'quality.db'), 'station')
    store.initialize()
    for name in ('planes', 'navigation_states', 'detectors', 'cpr_buffer'):
        monkeypatch.setattr(main, name, {})
    monkeypatch.setattr(main, 'observation_store', store)
    monkeypatch.setattr(main.time, 'time', lambda: 100)
    main.decode_details(status())
    monkeypatch.setattr(main.time, 'time', lambda: 102)
    main.decode_details(status(nacp=2))
    store.flush()
    import sqlite3, json
    with sqlite3.connect(store.path) as conn:
        rows = conn.execute('SELECT quality FROM navigation_updates ORDER BY observed_at').fetchall()
        assert conn.execute('SELECT COUNT(*) FROM observations').fetchone()[0] == 0
    assert len(rows) == 2 and json.loads(rows[-1][0])['changes'][0]['after'] == 2
    assert main.planes['ABC123']['spoof_score'] == 0
    monkeypatch.setattr(main.time, 'time', lambda: 200)
    plane = main.app.test_client().get('/data').get_json()[0]
    assert plane['navigation']['nac_p']['stale']
