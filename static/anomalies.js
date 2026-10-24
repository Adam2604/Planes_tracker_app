'use strict';
(() => {
    const A=Analysis, filter=document.getElementById('review-filter');
    let cached=null;
    function render() {
        if(!cached) return;
        const container=document.getElementById('events');container.replaceChildren();
        const events=cached.events.filter(e=>filter.value==='all'||(e.review_status||'pending')===filter.value);
        if(!events.length) container.append(A.element('p', cached.events.length
            ? 'Brak zdarzeń o wybranej ocenie wśród 100 najnowszych zdarzeń.'
            : 'Brak zarejestrowanych zdarzeń. Profil zasięgu uczy się z nowych obserwacji.', 'muted'));
        events.forEach(event=>{
            const a=event.analysis, card=A.element('article',''), title=A.element('h2','');
            title.append(A.element('span',a.label,'tag '+a.status),document.createTextNode(event.icao));
            card.append(title,A.element('p',A.time(event.time),'muted'));
            card.append(A.element('p','Ocena użytkownika: '+A.reviewLabels[event.review_status||'pending']));
            const reasons=A.element('ul','');
            (a.reasons||[]).forEach(reason=>reasons.append(A.element('li',reason)));
            if(a.status==='clear') reasons.append(A.element('li','Ocena wygasła po okresie poprawnych obserwacji.'));
            card.append(reasons);
            const p=a.profile;
            card.append(A.element('p',p.ready?`Profil: ${p.tracks} sesji / ${p.days} dni, P99: ${p.p99_km} km.`
                :`Profil: za mało danych (${p.tracks} sesji / ${p.days} dni).`,'muted'));
            const detail=A.element('a','Odtwórz zdarzenie / dodaj ocenę');detail.href='/anomalies/'+event.id;
            card.append(detail);container.append(card);
        });
    }
    async function refresh() {
        try {
            cached=await A.json('/api/anomalies');
            const health=cached.health;
            document.getElementById('health').textContent=`Gotowe profile: ${health.ready_buckets||0}/180. Oczekujące obserwacje: ${health.queued||0}. Utracone: ${health.dropped||0}. `+
                (health.storage_ok?'Zapis działa.':'Problem z zapisem obserwacji.')+
                (cached.review_enabled?'':' Dodawanie ocen wymaga skonfigurowania klucza dostępu na stacji.');
            document.getElementById('health').className=health.storage_ok?'':'error';
            document.getElementById('error').textContent='';render();
        }catch(e){document.getElementById('error').textContent='Nie udało się odświeżyć danych. Wyświetlona historia może być nieaktualna.';}
        finally{setTimeout(refresh,10000);}
    }
    filter.addEventListener('change',render);refresh();
})();
