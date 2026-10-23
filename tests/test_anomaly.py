from anomaly import TrackDetector, Settings, build_profiles, altitude_band, bearing
import pytest


def point(t, lat=52, lon=17, distance=100, **kwargs):
    return dict(time=t, lat=lat, lon=lon, distance=distance, **kwargs)


PROFILE = dict(ready=True, tracks=40, days=5, p95_km=190, p99_km=200)


def test_far_first_position_not_automatically_spoofed():
    result = TrackDetector().observe(point(100, distance=650))
    assert result['status'] == 'clear'
    assert result['profile_status'] == 'insufficient_data'
    assert result['accepted']


def test_coverage_alone_is_only_anomaly_and_does_not_censor_learning():
    detector = TrackDetector()
    for t in (100, 110, 120):
        result = detector.observe(point(t, distance=400), PROFILE)
    assert result['status'] == 'anomaly'
    assert result['trainable']


def test_sparse_profile_does_not_trigger():
    result = TrackDetector().observe(point(100, distance=600), dict(PROFILE, ready=False))
    assert result['status'] == 'clear'


def test_rejected_jump_immediately_updates_assessment():
    detector = TrackDetector()
    detector.observe(point(100))
    result = detector.observe(point(101, lat=54))
    assert not result['accepted']
    assert result['status'] == 'anomaly'
    assert 'jump' in result['reason_codes']
    assert not result['trainable']


def test_combined_persistent_evidence_is_suspected():
    detector = TrackDetector()
    detector.observe(point(100))
    for t, lat in ((101, 55), (104, 56), (107, 57)):
        result = detector.observe(point(t, lat=lat, distance=400), PROFILE)
    assert result['status'] == 'suspected'
    assert result['mode'] == 'observe'
    assert result['score'] == 70


def test_jump_and_speed_are_not_independent_spoof_evidence():
    detector = TrackDetector()
    detector.observe(point(100))
    for t, lat in ((105, 54), (108, 55), (111, 56)):
        result = detector.observe(point(t, lat=lat, speed=800, v_type='GS', velocity_time=t))
    assert result['status'] == 'anomaly'


def test_bad_first_point_can_recover_without_false_connecting_line():
    detector = TrackDetector()
    detector.observe(point(100, lat=55))
    assert not detector.observe(point(101))['accepted']
    assert not detector.observe(point(103, lat=52.001))['accepted']
    result = detector.observe(point(106, lat=52.002))
    assert result['accepted'] and result['break_route']
    assert not result['trainable']
    assert 'reacquired' in result['reason_codes']


def test_legitimate_turn_and_reception_gap():
    detector = TrackDetector()
    detector.observe(point(100))
    detector.observe(point(110, lat=52.01))
    result = detector.observe(point(120, lat=52.01, lon=17.02))
    assert result['status'] == 'clear' and result['accepted']
    result = detector.observe(point(200, lat=53))
    assert result['status'] == 'clear' and result['break_route']


@pytest.mark.parametrize('speed,v_type,velocity_time', [(None, 'GS', 106), (0, 'GS', 50), (0, 'IAS', 106)])
def test_missing_stale_and_airspeed_are_not_motion_evidence(speed, v_type, velocity_time):
    detector = TrackDetector()
    detector.observe(point(100))
    result = detector.observe(point(106, lat=52.02, speed=speed, v_type=v_type, velocity_time=velocity_time))
    assert 'speed' not in result['reason_codes']


def test_fresh_zero_speed_is_distinct_from_missing_speed():
    detector = TrackDetector()
    detector.observe(point(100))
    result = detector.observe(point(106, lat=52.02, speed=0, v_type='GS', velocity_time=106))
    assert 'speed' in result['reason_codes']


def test_alarm_expires_after_clean_observations_not_lifetime_max_distance():
    detector = TrackDetector()
    result = detector.observe(point(100, distance=500), PROFILE)
    assert result['status'] == 'anomaly'
    for t in range(110, 161, 10):
        result = detector.observe(point(t, distance=100), PROFILE)
    assert result['status'] == 'clear' and result['score'] == 0
    assert result['since'] is None and not result['reasons']


def test_profiles_count_independent_tracks_and_days():
    rows = [(0, 3, 'one', '2026-10-01', 100)] * 500
    rows += [(0, 3, 'one', '2026-10-02', 150)]
    profiles = build_profiles(rows)
    assert profiles[(0, 3)]['tracks'] == 1
    assert profiles[(0, 3)]['p99_km'] == 150
    assert not profiles[(0, 3)]['ready']


def test_profile_readiness_and_separation():
    rows = [(0, 3, str(i), f'2026-10-0{1+i%3}', 200+i) for i in range(30)]
    rows += [(1, 3, 'separate', '2026-10-01', 700), (0, 0, 'low', '2026-10-01', 50)]
    p = build_profiles(rows)
    assert p[(0, 3)]['ready']
    assert p[(0, 3)]['p99_km'] < 230
    assert not p[(1, 3)]['ready'] and not p[(0, 0)]['ready']


def test_geometry_and_altitude_bands():
    assert bearing(51, 17, 52, 17) == 0
    assert bearing(51, 17, 50, 17) == 180
    assert altitude_band(None) is None
    assert [altitude_band(a) for a in (100, 3000, 6000, 9000, 12000)] == [0, 1, 2, 3, 4]


def test_old_motion_evidence_cannot_keep_coverage_only_suspected_forever():
    detector = TrackDetector()
    detector.observe(point(100))
    for t, lat in ((101, 55), (104, 56), (107, 57)):
        result = detector.observe(point(t, lat=lat, distance=400), PROFILE)
    assert result['status'] == 'suspected'
    # Return to the accepted route, keeping only the coverage anomaly.
    for t in range(110, 151, 5):
        result = detector.observe(point(t, distance=400), PROFILE)
    assert result['status'] == 'anomaly'
    assert result['score'] == 30
