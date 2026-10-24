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
