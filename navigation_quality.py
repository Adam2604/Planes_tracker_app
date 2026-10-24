"""Version-aware airborne ADS-B quality. No inference of version from silence.

TC31 subtype 0 supplies version/NIC-A/NACp/SIL; TC19 supplies NACv;
TC9-18 supplies NIC-B and the position type code. Missing/reserved != zero.
"""
from collections import deque


class NavigationQuality:
    def __init__(self):
        self.status = None
        self.position = None
        self.velocity = None
        self.changes = deque(maxlen=20)
        self.last_saved = None

    def update(self, message, now, adsb):
        bits = f'{int(message, 16):0112b}'
        tc = int(bits[32:37], 2)
        before = self.snapshot(now, adsb)
        if tc == 31 and int(bits[37:40], 2) == 0:
            if self.status and adsb.version(message) != adsb.version(self.status[0]):
                self.position = self.velocity = None
            self.status = (message, now)
        elif 9 <= tc <= 18:
            self.position = (message, now)
        elif tc == 19 and int(bits[37:40], 2) in (1, 2, 3, 4):
            self.velocity = (message, now)
        else:
            return False
        after = self.snapshot(now, adsb)
        # Compare only fresh values of the same version and SIL basis.
        if before['version'] == after['version'] and not before['version_stale']:
            for key in ('nic', 'nac_p', 'nac_v', 'sil'):
                old, new = before[key], after[key]
                if (old['value'] is not None and new['value'] is not None
                        and not old['stale'] and not new['stale'] and old['value'] != new['value']
                        and (key != 'sil' or before['sil_basis'] == after['sil_basis'])):
                    self.changes.append(dict(time=now, field=key, before=old['value'], after=new['value'],
                                             direction='down' if new['value'] < old['value'] else 'up'))
        return True

    def snapshot(self, now, adsb):
        version = adsb.version(self.status[0]) if self.status else None
        version_stale = self.status is None or not 0 <= now-self.status[1] <= 60
        supported = version in (1, 2)
        def field(value=None, timestamp=None, ttl=60):
            return dict(value=value, updated_at=timestamp,
                        stale=timestamp is None or not 0 <= now-timestamp <= ttl or version_stale)
        result = dict(time=now, version=version, version_stale=version_stale,
                      version_updated_at=self.status[1] if self.status else None,
                      supported=supported, nic=field(), nac_p=field(), nac_v=field(), sil=field(),
                      sil_basis=None, changes=[dict(c) for c in self.changes if 0 <= now-c['time'] <= 120])
        if not supported:
            return result
        message, timestamp = self.status
        bits = f'{int(message, 16):0112b}'
        nacp = adsb.nac_p(message)[0]
        result['nac_p'] = field(nacp if 0 <= nacp <= 11 else None, timestamp)
        result['sil'] = field(int(bits[82:84], 2), timestamp)
        # V1 predates the per-hour/per-sample supplement; do not invent a basis.
        result['sil_basis'] = adsb.sil(message, version)[2] if version == 2 else 'unknown'
        if self.velocity:
            nacv = adsb.nac_v(self.velocity[0])[0]
            result['nac_v'] = field(nacv if 0 <= nacv <= 4 else None, self.velocity[1], 10)
        if self.position:
            pos, pos_time = self.position
            if version == 1:
                nic = adsb.nic_v1(pos, adsb.nic_s(message))[0]
            else:
                nic = adsb.nic_v2(pos, adsb.nic_a_c(message)[0], adsb.nic_b(pos))[0]
            result['nic'] = field(nic, pos_time, 10)
            # Status supplements may be older than 10s, but position must be fresh.
            result['nic']['stale'] = version_stale or not 0 <= now-pos_time <= 10
        return result

    def should_save(self, quality, now):
        signature = (quality['version'], quality['version_stale'], quality['sil_basis'],
                     tuple((quality[k]['value'], quality[k]['stale']) for k in ('nic','nac_p','nac_v','sil')))
        save = self.last_saved is None or self.last_saved[0] != signature or now-self.last_saved[1] >= 5
        if save:
            self.last_saved = (signature, now)
        return save
