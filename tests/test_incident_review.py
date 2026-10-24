import json
import sqlite3
import time

import pytest
import main
from anomaly import TrackDetector
from observation_store import ObservationStore, ReviewConflict
from scripts.anomaly_report import report


@pytest.fixture
def store(tmp_path, monkeypatch):
    store = ObservationStore(str(tmp_path/'review.db'), 'test-station')
    store.initialize()
    monkeypatch.setattr(main, 'observation_store', store)
    monkeypatch.setitem(main.app.config, 'ANOMALY_REVIEW_TOKEN', 'test-key')
    return store


def insert(store, t=None, track='track-a', event=True, lat=52):
    t=time.time() if t is None else t
    point=dict(time=t, lat=lat, lon=17, distance=100, sector=0, band=3,
               track_id=track, icao='ABC123', altitude=10000, speed=None)
    point['analysis']=TrackDetector().observe(point)
    point['event']=event
    store.submit(point);store.flush()
    return store.recent_events()[0]['id'] if event else None


def test_review_persists_across_restart_and_is_separate_from_detector(store):
    event=insert(store)
    before=store.recent_events()[0]['analysis']
    assert store.get_review(event)['status']=='pending'
    saved=store.save_review(event,'explained','Zanik odbioru <script>',0)
    restarted=ObservationStore(store.path,store.station)
    assert restarted.get_review(event)==saved
    public=restarted.recent_events()[0]
    assert public['analysis']==before
    assert public['review_status']=='explained'
    assert 'note' not in json.dumps(public)
    assert report(store.path)['saved_event_review_counts']=={'explained':1}


def test_concurrent_edit_cannot_overwrite_note(store):
    event=insert(store)
    store.save_review(event,'suspicious','First draft',0)
    with pytest.raises(ReviewConflict):
        store.save_review(event,'explained','Stale draft',0)
    assert store.get_review(event)['note']=='First draft'
    assert store.save_review(event,'explained','Reviewed',1)['revision']==2


@pytest.mark.parametrize('status,note,revision', [('wrong','',0),('pending',None,0),
    ('pending','x'*2001,0),('pending','',-1),('pending','',True)])
def test_invalid_reviews_rejected(store,status,note,revision):
    with pytest.raises(ValueError): store.save_review(insert(store),status,note,revision)


def test_review_is_station_scoped_and_missing_event_not_created(store):
    event=insert(store)
    other=ObservationStore(store.path,'other')
    assert other.get_review(event) is None
    assert other.save_review(event,'pending','',0) is None
    assert other.replay(event) is None
    assert store.save_review(99999,'pending','',0) is None


def test_private_review_requires_key_and_json_not_cookie(store):
    event=insert(store)
    client=main.app.test_client()
    url=f'/api/anomalies/{event}/review'
    body=dict(status='explained',note='private',revision=0)
    assert client.get(url).status_code==401
    assert client.post(url,json=body).status_code==401
    assert client.post(url,json=body,headers={'Authorization':'Bearer wrong'}).status_code==401
    headers={'Authorization':'Bearer test-key'}
    assert client.post(url,data=body,headers=headers).status_code==400
    response=client.post(url,json=body,headers=headers)
    assert response.status_code==200 and response.headers['Cache-Control']=='no-store'
    assert client.get(url,headers=headers).json['note']=='private'
    assert 'private' not in client.get('/api/anomalies').get_data(as_text=True)
    assert 'private' not in client.get(f'/api/anomalies/{event}/replay').get_data(as_text=True)
    assert client.post(url,json=body,headers=headers).status_code==409


def test_review_disabled_by_default_and_body_bounded(store,monkeypatch):
    event=insert(store);client=main.app.test_client();url=f'/api/anomalies/{event}/review'
    headers={'Authorization':'Bearer test-key'}
    assert client.post(url,json={'note':'x'*20000},headers=headers).status_code==413
    monkeypatch.setitem(main.app.config,'ANOMALY_REVIEW_TOKEN','')
    assert client.post(url,json={},headers=headers).status_code==503


def test_replay_window_order_breaks_and_retention_gap(store):
    now=time.time()
    event=insert(store,now)
    insert(store,now-121,event=False)
    insert(store,now-10,event=False)
    insert(store,now+10,event=False)
    insert(store,now+121,event=False)
    insert(store,now,track='other-track',event=False)
    replay=store.replay(event)
    assert [p['time'] for p in replay['points']]==[now-10,now,now+10]
    assert replay['has_before'] and replay['has_after']
    assert replay['points'][0]['speed'] is None
    with sqlite3.connect(store.path) as conn: conn.execute('DELETE FROM observations')
    replay=store.replay(event)
    assert replay['points']==[] and replay['event']['id']==event


def test_replay_has_explicit_cap(store):
    now=time.time();event=insert(store,now)
    with sqlite3.connect(store.path) as conn:
        for _ in range(13):
            conn.execute('''INSERT INTO observations (station,track_id,icao,observed_at,lat,lon,accepted,analysis)
                SELECT station,track_id,icao,observed_at,lat,lon,accepted,analysis FROM observations''')
    replay=store.replay(event)
    assert len(replay['points'])==5000 and replay['truncated']


def test_coverage_includes_unknown_sectors_and_matches_threshold(store):
    store.profiles={(0,3):dict(ready=True,tracks=40,days=4,p95_km=180,p99_km=200),
                    (1,3):dict(ready=False,tracks=1,days=1,p95_km=400,p99_km=400)}
    result=store.coverage_profile(3)
    assert len(result['sectors'])==36
    assert result['sectors'][0]['threshold_km']==230
    assert result['sectors'][1]['threshold_km'] is None
    assert result['sectors'][2]['p99_km'] is None
    assert not any(s['ready'] for s in store.coverage_profile(2)['sectors'])
    client=main.app.test_client()
    assert client.get('/api/coverage-profile?band=3').json['antenna']['lat']==main.MY_LAT
    for band in ('-1','5','abc','1.5'):
        assert client.get('/api/coverage-profile?band='+band).status_code==400
    assert client.get('/coverage').status_code==200


def test_review_retention_and_idempotent_migration(store):
    event=insert(store,time.time()-40*86400)
    store.save_review(event,'explained','Old',0)
    store.initialize();store.initialize()
    assert store.get_review(event) is None
    with sqlite3.connect(store.path) as conn:
        assert conn.execute('SELECT count(*) FROM anomaly_reviews').fetchone()[0]==0


def test_missing_event_and_unavailable_store_responses(store,monkeypatch):
    client=main.app.test_client()
    assert client.get('/api/anomalies/99999/replay').status_code==404
    assert client.get('/api/anomalies/99999/review',headers={'Authorization':'Bearer test-key'}).status_code==404
    monkeypatch.setattr(main,'observation_store',None)
    assert client.get('/api/coverage-profile').status_code==503
