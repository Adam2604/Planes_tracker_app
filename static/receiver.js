'use strict';
(() => {
    const A=Analysis, byId=id=>document.getElementById(id), fmt=v=>v==null?'brak danych':v;
    async function refresh() {
        try {
            const data=await A.json('/api/receiver-health',{cache:'no-store'}), h=data.receiver, w=h.window;
            byId('error').textContent='';
            byId('receiver-state').textContent=A.receiverLabels[h.state] || h.state;
            byId('updated').textContent=`Stan na ${A.time(h.time)} · okno ${h.window_seconds} s`;
            byId('receiver-error').textContent=h.error || '';
            const metrics=[['Zaakceptowane ramki/s',h.accepted_per_second],['Kandydaci na ramkę/s',h.candidates_per_second],
                ['Poprawne CRC DF17/18',h.crc_valid_percent==null?'brak danych':`${h.crc_valid_percent}% (${w.crc_ok}/${w.crc_checked})`],
                ['Ostatnia poprawna ramka [s temu]',h.valid_frame_age_s],['Ostatni odczyt [s temu]',h.read_age_s],
                ['Tło [dB wzgl.]',h.noise_db_relative],['Błędy dekodowania w oknie',w.decode_errors],
                ['Przerwy od uruchomienia / najdłuższa',`${h.read_gaps} / ${h.max_read_gap_s} s`]];
            byId('metrics').replaceChildren(...metrics.map(([label,value])=>{
                const item=A.element('div','');item.append(A.element('span',label,'muted'),A.element('div',String(fmt(value))));return item;
            }));
            const s=data.storage;
            byId('storage').textContent=`${s.storage_ok?'Zapis dostępny':'Zapis lub odczyt historii niedostępny'} · oczekujące rekordy: ${s.queued} · utracone przez przepełnienie kolejki: ${s.dropped}`;
            byId('history-summary').textContent=data.history.length?`${data.history.length} próbek · najnowsze na górze · zapis co około 5 s.`:'Brak zapisanych próbek. Historia pojawi się po uruchomieniu odbiornika i zapisu danych.';
            byId('history').replaceChildren(...[...data.history].reverse().map(row=>{
                const v=row.health, tr=A.element('tr','');
                for(const value of [A.time(row.time),A.receiverLabels[v.state] || v.state,v.accepted_per_second,
                    v.crc_valid_percent==null?null:v.crc_valid_percent+'%',v.noise_db_relative,v.read_age_s])
                    tr.append(A.element('td',String(fmt(value))));
                return tr;
            }));
        } catch(e) {byId('error').textContent=`Nie udało się odświeżyć: ${e.message}. Wyświetlone dane mogą być nieaktualne.`;}
        finally {setTimeout(refresh,5000);}
    }
    refresh();
})();
