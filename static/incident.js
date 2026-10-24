'use strict';
(() => {
    const A=Analysis, id=document.querySelector('main').dataset.eventId;
    const byId=id=>document.getElementById(id);
    let payload, map, layers, playing=false, timer, reviewRevision=0, dirty=false;
    const slider=byId('timeline');
    if(window.L) {
        map=L.map('incident-map').setView([51.978,17.498],7);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OpenStreetMap'}).addTo(map);
        layers=L.layerGroup().addTo(map);
    }
    const svgNS='http://www.w3.org/2000/svg';
    function svgElement(tag,attrs,text) {
        const el=document.createElementNS(svgNS,tag);
        Object.entries(attrs).forEach(([k,v])=>el.setAttribute(k,v));
        if(text!==undefined) el.textContent=text;
        return el;
    }
    function chart(field,selectedTime) {
        const svg=byId(field+'-chart'); svg.replaceChildren();
        const points=payload.points, values=points.map(p=>p[field]).filter(Number.isFinite);
        if(!values.length) {svg.append(svgElement('text',{x:20,y:100,fill:'#a8bacb'},'Brak danych')); return;}
        let min=Math.min(...values), max=Math.max(...values);
        if(min===max) {min-=1; max+=1;}
        const start=points[0].time, span=Math.max(1,points[points.length-1].time-start);
        const x=t=>60+(t-start)/span*440, y=v=>175-(v-min)/(max-min)*145;
        for(let i=0;i<3;i++) {
            const value=min+(max-min)*i/2;
            svg.append(svgElement('line',{x1:60,x2:500,y1:y(value),y2:y(value),stroke:'#304456'}),
                svgElement('text',{x:3,y:y(value)+4,fill:'#a8bacb','font-size':12},Math.round(value)));
        }
        let d='',previous=null;
        for(const p of points) {
            if(!Number.isFinite(p[field])) {previous=null;continue;}
            const split=!previous || p.time-previous.time>60 || p.break_route ||
                (field==='speed' && p.v_type!==previous.v_type);
            d+=(split?'M':'L')+x(p.time)+','+y(p[field])+' ';
            previous=p;
        }
        svg.append(svgElement('path',{d,fill:'none',stroke:'#38bdf8','stroke-width':2}));
        for(const p of points.filter(p=>!p.accepted && Number.isFinite(p[field])))
            svg.append(svgElement('circle',{cx:x(p.time),cy:y(p[field]),r:3,fill:'#fb923c'}));
        if(payload.event.time>=start && payload.event.time<=start+span)
            svg.append(svgElement('line',{x1:x(payload.event.time),x2:x(payload.event.time),y1:20,y2:180,stroke:'#f87171','stroke-dasharray':'4 4'}));
        svg.append(svgElement('line',{x1:x(selectedTime),x2:x(selectedTime),y1:20,y2:180,stroke:'#fff'}));
        for(const [t,anchor] of [[start,'start'],[start+span,'end']])
            svg.append(svgElement('text',{x:x(t),y:205,fill:'#a8bacb','text-anchor':anchor,'font-size':12},new Date(t*1000).toLocaleTimeString('pl-PL')));
    }
    function stop() {playing=false;clearInterval(timer);byId('play').textContent='Odtwórz';}
    function draw() {
        const t=Number(slider.value), visible=payload.points.filter(p=>p.time<=t), last=visible[visible.length-1];
        const fmt=v=>v==null?'brak danych':v;
        const nav=[...(payload.navigation || []).map(r=>({time:r.time,quality:r.quality})),
            ...visible.filter(p=>p.navigation).map(p=>({time:p.time,quality:p.navigation}))]
            .filter(r=>r.time<=t).sort((a,b)=>a.time-b.time).pop();
        byId('selected-navigation').textContent=A.navigationText(nav?.quality,t);
        const receiver=[...(payload.receiver || []),...visible.filter(p=>p.receiver).map(p=>({time:p.time,health:p.receiver}))]
            .filter(r=>r.time<=t).sort((a,b)=>a.time-b.time).pop();
        byId('selected-receiver').textContent=receiver ? `${A.receiverText(receiver.health)} · próbka sprzed ${(t-receiver.time).toFixed(1)} s` : 'Odbiornik: brak danych';
        byId('position-time').textContent=last ? `${A.time(t)} · obserwacja sprzed ${(t-last.time).toFixed(1)} s · wysokość: ${fmt(last.altitude)} m · prędkość: ${fmt(last.speed)} km/h (${last.v_type||'brak typu'}) · ${last.accepted?'punkt przyjęty':'punkt odrzucony'}` : `${A.time(t)} · brak wcześniejszej obserwacji`;
        if(layers) {
            layers.clearLayers();
            const segments=A.segments(visible);
            if(segments.length) L.polyline(segments,{color:'#0284c7',weight:3}).addTo(layers);
            let anchor=null;
            for(const p of visible) {
                if(p.accepted) anchor=p;
                else {
                    L.circleMarker([p.lat,p.lon],{radius:4,color:'#f97316'}).addTo(layers);
                    if(anchor && p.time-anchor.time<=60)
                        L.polyline([[anchor.lat,anchor.lon],[p.lat,p.lon]],{color:'#f97316',dashArray:'5 7',weight:2}).addTo(layers);
                }
            }
            if(last) L.circleMarker([last.lat,last.lon],{radius:7,color:last.accepted?'#0284c7':'#ea580c',fillOpacity:1}).addTo(layers);
        }
        chart('altitude',t);chart('speed',t);
    }
    slider.addEventListener('input',()=>{stop();draw();});
    byId('jump-event').addEventListener('click',()=>{
        stop();slider.value=Math.max(Number(slider.min),Math.min(Number(slider.max),payload.event.time));draw();
    });
    byId('play').addEventListener('click',()=>{
        if(playing) {stop();return;}
        if(Number(slider.value)>=Number(slider.max)) slider.value=slider.min;
        playing=true;byId('play').textContent='Pauza';
        let previous=performance.now();
        timer=setInterval(()=>{
            const now=performance.now(), delta=(now-previous)/1000;previous=now;
            slider.value=Math.min(Number(slider.max),Number(slider.value)+delta*Number(byId('pace').value));
            draw();if(Number(slider.value)>=Number(slider.max)) stop();
        },200);
    });
    async function load() {
        try {
            payload=await A.json(`/api/anomalies/${id}/replay`);
            const e=payload.event;
            byId('event-navigation').textContent=A.navigationText(e.analysis.navigation,e.time);
            byId('event-receiver').textContent=A.receiverText(e.analysis.receiver);
            byId('selected-navigation').textContent='Brak wybranej obserwacji.';
            byId('selected-receiver').textContent='Brak wybranej obserwacji.';
            const changes=new Map();
            for(const q of [e.analysis.navigation,...(payload.navigation || []).map(r=>r.quality)])
                for(const c of q?.changes || [])
                    if(c.time>=payload.window_start && c.time<=payload.window_end)
                        changes.set(`${c.time}:${c.field}:${c.before}:${c.after}`,c);
            byId('quality-availability').textContent=`${changes.size} zmian między świeżymi wartościami tej samej wersji ADS-B. `+
                (payload.navigation_truncated?'Historia jakości została ograniczona do 5000 próbek.':'Brak zmiany nie oznacza potwierdzonej poprawności nawigacji.');
            byId('quality-changes').replaceChildren(...[...changes.values()].sort((a,b)=>a.time-b.time).map(c=>{
                const tr=A.element('tr','');
                for(const value of [A.time(c.time),{nic:'NIC',nac_p:'NACp',nac_v:'NACv',sil:'SIL'}[c.field],c.before,c.after,c.direction==='down'?'Spadek':'Wzrost'])
                    tr.append(A.element('td',String(value)));
                return tr;
            }));
            byId('title').textContent=`Zdarzenie ${e.icao}`;
            byId('event-summary').textContent=`${A.time(e.time)} · ${e.analysis.label} · ${e.analysis.reasons.join('; ')}`;
            if(map && Number.isFinite(e.lat) && Number.isFinite(e.lon)) {
                L.circleMarker([e.lat,e.lon],{radius:9,color:'#ef4444',fill:false}).addTo(map).bindTooltip('Zdarzenie');
                const positions=payload.points.map(p=>[p.lat,p.lon]);
                map.fitBounds(positions.length?positions:[[e.lat,e.lon]],{padding:[25,25],maxZoom:10});
            }
            if(!payload.points.length && !(payload.navigation || []).length) {
                byId('availability').textContent=`Brak szczegółowych obserwacji w oknie ±2 minuty. Dane są przechowywane przez ${payload.observation_days} dni; starsze zdarzenia zachowują opis i ocenę.`;
                for(const field of ['altitude','speed'])
                    byId(field+'-chart').append(svgElement('text',{x:20,y:100,fill:'#a8bacb'},'Brak danych'));
                if(!map) byId('error').textContent='Mapa niedostępna.';
                return;
            }
            byId('availability').textContent=`${payload.points.length} obserwacji w oknie ±2 minuty. `+
                (!payload.has_before?'Brak obserwacji sprzed zdarzenia. ':'')+
                (!payload.has_after?'Brak obserwacji po zdarzeniu — dla bieżącego alarmu odśwież stronę później. ':'')+
                (payload.truncated?'Pokazano tylko pierwsze 5000 punktów.':'');
            const times=[e.time,...payload.points.map(p=>p.time),...(payload.navigation || []).map(r=>r.time)];
            slider.min=Math.min(...times);slider.max=Math.max(...times);
            slider.value=Math.max(Number(slider.min),Math.min(Number(slider.max),e.time));
            slider.disabled=false;byId('jump-event').disabled=false;
            byId('play').disabled=slider.min===slider.max;
            draw();
            if(!map) byId('error').textContent='Mapa niedostępna. Odtwarzanie czasu i wykresy pozostają dostępne.';
        }catch(e){byId('error').textContent=e.message;byId('event-summary').textContent='Nie udało się wczytać zdarzenia.';}
    }
    function auth() {return {Authorization:'Bearer '+byId('review-key').value};}
    byId('load-review').addEventListener('click',async()=>{
        const button=byId('load-review');button.disabled=true;byId('save-review').disabled=true;
        try {
            const data=await A.json(`/api/anomalies/${id}/review`,{headers:auth(),cache:'no-store'});
            reviewRevision=data.revision;byId('review-status').value=data.status;byId('review-note').value=data.note;
            byId('review-form').hidden=false;dirty=false;
            byId('review-message').textContent=data.updated_at?'Ostatni zapis: '+A.time(data.updated_at):'Zdarzenie czeka na ocenę.';
        }catch(e){byId('review-message').textContent=e.message;}
        finally{button.disabled=false;byId('save-review').disabled=false;}
    });
    byId('review-form').addEventListener('input',()=>{dirty=true;});
    byId('review-form').addEventListener('submit',async event=>{
        event.preventDefault();const button=byId('save-review');button.disabled=true;byId('load-review').disabled=true;
        // Freeze the submitted draft. Edits during the request remain unsaved.
        const draft={status:byId('review-status').value,note:byId('review-note').value,revision:reviewRevision};
        try {
            const data=await A.json(`/api/anomalies/${id}/review`,{method:'POST',headers:{...auth(),'Content-Type':'application/json'},body:JSON.stringify(draft)});
            reviewRevision=data.revision;
            dirty=byId('review-status').value!==draft.status || byId('review-note').value!==draft.note;
            byId('review-message').textContent='Zapisano ocenę. '+(dirty?'W polach są kolejne niezapisane zmiany.':'');
        }catch(e){byId('review-message').textContent=e.message;}
        finally{button.disabled=false;byId('load-review').disabled=false;}
    });
    window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
    load();
})();
