'use strict';
window.Analysis = {
    element(tag, text, className) {
        const el = document.createElement(tag);
        el.textContent = text;
        if (className) el.className = className;
        return el;
    },
    async json(url, options) {
        const response = await fetch(url, options);
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || `Błąd serwera (${response.status}).`);
        return data;
    },
    time(value) { return new Date(value * 1000).toLocaleString('pl-PL'); },
    navigationText(q, now) {
        if (!q) return 'Jakość ADS-B: brak danych';
        now = now ?? q.time;
        const aged = (at, ttl) => at == null || now-at > ttl || now < at;
        const versionStale = q.version_stale || aged(q.version_updated_at, 60);
        const version = q.version == null ? 'nieznana wersja' : `wersja ${q.version}${versionStale?' (nieaktualna)':''}`;
        if (!q.supported) return `Jakość ADS-B: ${version} · wskaźniki niedostępne`;
        const fields = [['nic','NIC',10],['nac_p','NACp',60],['nac_v','NACv',10],['sil','SIL',60]];
        const values = fields.map(([key,label,ttl]) => {
            const f=q[key];
            return `${label}: ${f?.value == null ? 'brak danych' : f.value+((f.stale || versionStale || aged(f.updated_at,ttl))?' (nieaktualne)':'')}`;
        });
        const basis = {hour:'na godzinę',sample:'na próbkę',unknown:'nieokreślona'}[q.sil_basis] || 'nieokreślona';
        return `ADS-B ${version} · ${values.join(' · ')} · podstawa SIL: ${basis}`;
    },
    receiverLabels: {not_started:'Nie uruchomiono', running:'Odbiór działa', quiet:'Odczyt działa, brak świeżych ramek',
        stalled:'Przerwa w odczycie próbek', error:'Błąd odbiornika', stopped:'Odbiornik zatrzymany'},
    receiverText(h) {
        if (!h) return 'Odbiornik: brak danych';
        return `${this.receiverLabels[h.state] || h.state} · ${h.accepted_per_second ?? '—'} ramek/s · CRC DF17/18: ${h.crc_valid_percent == null?'brak danych':h.crc_valid_percent+'%'} · ostatni odczyt: ${h.read_age_s == null?'brak':h.read_age_s+' s temu'}`;
    },
    reviewLabels: {pending: 'Do sprawdzenia', explained: 'Wyjaśnione', suspicious: 'Podejrzane'},
    // Great-circle endpoint for a coverage wedge, distance in kilometres.
    destination(lat, lon, degrees, km) {
        const p = lat*Math.PI/180, l = lon*Math.PI/180, a = degrees*Math.PI/180, d = km/6371;
        const p2 = Math.asin(Math.sin(p)*Math.cos(d) + Math.cos(p)*Math.sin(d)*Math.cos(a));
        const l2 = l + Math.atan2(Math.sin(a)*Math.sin(d)*Math.cos(p), Math.cos(d)-Math.sin(p)*Math.sin(p2));
        return [p2*180/Math.PI, ((l2*180/Math.PI+540)%360)-180];
    },
    segments(points) {
        const result = [];
        let segment = [], previous = null;
        for (const p of points) {
            if (!p.accepted) { if (segment.length) result.push(segment); segment=[]; previous=null; continue; }
            if (p.break_route || (previous && p.time-previous.time > 60)) {
                if (segment.length) result.push(segment);
                segment=[];
            }
            segment.push([p.lat, p.lon]); previous=p;
        }
        if (segment.length) result.push(segment);
        return result;
    }
};
