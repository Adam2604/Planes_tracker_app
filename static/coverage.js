'use strict';
(() => {
    const A = Analysis;
    let map, layer, generation=0;
    if (window.L) {
        map=L.map('coverage-map').setView([51.978,17.498],7);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {attribution:'© OpenStreetMap'}).addTo(map);
        layer=L.layerGroup().addTo(map);
    }
    function wedge(antenna, angle, distance) {
        const points=[[antenna.lat,antenna.lon]];
        for (let i=0;i<=10;i+=2) points.push(A.destination(antenna.lat,antenna.lon,angle+i,distance));
        return points;
    }
    async function refresh() {
        const current=++generation;
        document.getElementById('summary').textContent='Ładowanie profilu…';
        document.getElementById('sectors').replaceChildren();
        if (layer) layer.clearLayers();
        try {
            const data=await A.json('/api/coverage-profile?band='+document.getElementById('band').value);
            if(current!==generation) return;
            const ready=data.sectors.filter(s=>s.ready).length;
            document.getElementById('summary').textContent=`Gotowe sektory: ${ready}/36. Minimum ${data.min_tracks} sesji z ${data.min_days} dni. Okno: ${data.window_days} zakończonych dni UTC. Aktualizacja: ${A.time(data.updated_at)}.`;
            const table=document.getElementById('sectors');
            const bounds=[];
            data.sectors.forEach(s=>{
                const range=`${s.angle}–${s.angle+10}°`;
                const state=s.ready?'Gotowy':'Za mało danych';
                const km=v=>v==null?'—':v.toFixed(1)+' km';
                const row=A.element('tr','');
                [range,state,`${s.tracks} / ${s.days}`,km(s.p95_km),km(s.p99_km),km(s.threshold_km)].forEach(v=>row.append(A.element('td',v)));
                table.append(row);
                if (!layer) return;
                const popup=A.element('div',`${range} · ${state} · ${s.tracks} sesji / ${s.days} dni · P99: ${km(s.p99_km)} · Próg: ${km(s.threshold_km)}`);
                if(s.ready) {
                    const outer=wedge(data.antenna,s.angle,s.threshold_km);
                    bounds.push(...outer);
                    L.polygon(outer,{color:'#fb923c',fill:false,weight:1,dashArray:'5 5'}).addTo(layer).bindPopup(popup);
                    L.polygon(wedge(data.antenna,s.angle,s.p99_km),{color:'#16a34a',weight:1,fillOpacity:.15}).addTo(layer).bindPopup(popup.cloneNode(true));
                    L.polygon(wedge(data.antenna,s.angle,s.p95_km),{color:'#0284c7',weight:1,fillOpacity:.3}).addTo(layer).bindPopup(popup.cloneNode(true));
                } else {
                    L.polyline([[data.antenna.lat,data.antenna.lon],A.destination(data.antenna.lat,data.antenna.lon,s.angle+5,20)],
                        {color:'#64748b',weight:2,dashArray:'2 5'}).addTo(layer).bindPopup(popup);
                }
            });
            if(map) {
                L.circleMarker([data.antenna.lat,data.antenna.lon],{radius:5,color:'#111827',fillOpacity:1}).addTo(layer).bindTooltip('Stacja odbiorcza');
                if(bounds.length) map.fitBounds(bounds,{padding:[20,20],maxZoom:9});
                else map.setView([data.antenna.lat,data.antenna.lon],8);
            }
            document.getElementById('error').textContent=map?'':'Mapa niedostępna. Dane sektorów są dostępne w tabeli.';
        } catch(e) {
            if(current!==generation) return;
            document.getElementById('summary').textContent='Profil niedostępny.';
            document.getElementById('error').textContent=e.message;
        }
    }
    document.getElementById('band').addEventListener('change',refresh);
    refresh();
})();
