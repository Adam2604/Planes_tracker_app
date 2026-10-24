// Behaviour tests without a browser; no third-party DOM dependency.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

class Element {
    constructor() { this.children=[];this.listeners={};this.attributes={};this.dataset={};this.textContent='';this.value=''; }
    append(...items) {this.children.push(...items);}
    replaceChildren(...items) {this.children=[...items];}
    addEventListener(name,fn) {this.listeners[name]=fn;}
    setAttribute(name,value) {this.attributes[name]=value;}
}
function harness(fetchData) {
    const elements=new Map();
    const element=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
    const context={console,URL,Date,Math,Number,JSON,performance:{now:()=>0},
        setTimeout:()=>0,setInterval:()=>0,clearInterval:()=>{},addEventListener:()=>{},
        document:{createElement:()=>new Element(),createElementNS:()=>new Element(),
            createTextNode:text=>({textContent:text}),getElementById:element,
            querySelector:()=>({dataset:{eventId:'1'}})},
        fetch:async(url,options)=>({ok:true,json:async()=>fetchData(url,options)})};
    context.window=context;vm.createContext(context);
    function run(name) {vm.runInContext(fs.readFileSync(path.join(__dirname,'..','static',name),'utf8'),context);}
    run('analysis-common.js');
    return {context,element,run,settle:()=>new Promise(resolve=>setImmediate(resolve))};
}
function text(el) {return el.textContent+' '+(el.children||[]).map(text).join(' ');}

test('replay geometry splits at rejected points, reacquisition and long gaps',()=>{
    const h=harness();
    const p=(time,extra={})=>({time,lat:52,lon:17,accepted:true,...extra});
    const result=h.context.Analysis.segments([p(0),p(1),p(2,{accepted:false}),p(3),p(4,{break_route:true}),p(100)]);
    assert.equal(result.length,4);
    assert.equal(result[0].length,2);
    const north=h.context.Analysis.destination(0,0,0,111.195);
    assert.ok(Math.abs(north[0]-1)<.001 && Math.abs(north[1])<.001);
});

test('coverage table remains usable when map library cannot load',async()=>{
    const sectors=Array.from({length:36},(_,sector)=>({sector,angle:sector*10,ready:false,tracks:0,days:0,p95_km:null,p99_km:null,threshold_km:null}));
    const h=harness(()=>({sectors,antenna:{lat:52,lon:17},min_tracks:30,min_days:3,window_days:30,updated_at:100}));
    h.element('band').value='3';h.run('coverage.js');await h.settle();
    assert.equal(h.element('sectors').children.length,36);
    assert.match(h.element('error').textContent,/Mapa niedostępna/);
    assert.match(h.element('summary').textContent,/0\/36/);
});

test('review filter changes immediately without another network request',async()=>{
    const analysis={label:'Anomalia',status:'anomaly',reasons:[],profile:{ready:false,tracks:0,days:0}};
    const events=[{id:1,icao:'AAA111',time:100,analysis,review_status:'pending'},
        {id:2,icao:'BBB222',time:100,analysis,review_status:'explained'}];
    let requests=0;
    const h=harness(()=>{requests++;return {events,health:{storage_ok:true},review_enabled:true};});
    h.element('review-filter').value='all';h.run('anomalies.js');await h.settle();
    assert.equal(h.element('events').children.length,2);
    h.element('review-filter').value='explained';h.element('review-filter').listeners.change();
    assert.equal(h.element('events').children.length,1);assert.equal(requests,1);
    assert.match(text(h.element('events')),/BBB222/);
});

test('incident loads charts and saves a review with revision and bearer header',async()=>{
    let saved;
    const payload={event:{time:101,icao:'ABC123',lat:52,lon:17,analysis:{label:'Anomalia',reasons:['Skok']}},
        points:[{time:100,lat:52,lon:17,altitude:10000,speed:null,accepted:true},
            {time:101,lat:53,lon:17,altitude:10020,speed:800,v_type:'GS',accepted:false},
            {time:102,lat:52.01,lon:17,altitude:10030,speed:810,v_type:'GS',accepted:true}],
        has_before:true,has_after:true,observation_days:7};
    const h=harness((url,options)=>{
        if(url.endsWith('replay'))return payload;
        if(options?.method==='POST'){saved=options;return {revision:2};}
        return {revision:1,status:'pending',note:'draft'};
    });
    h.run('incident.js');await h.settle();
    assert.match(h.element('title').textContent,/ABC123/);
    assert.ok(h.element('altitude-chart').children.length>0);
    assert.equal(h.element('timeline').disabled,false);
    h.element('review-key').value='example-key';
    await h.element('load-review').listeners.click();
    assert.equal(h.element('review-note').value,'draft');
    h.element('review-note').value='<script>plain text</script>';
    h.element('review-status').value='explained';
    await h.element('review-form').listeners.submit({preventDefault(){}});
    assert.equal(saved.headers.Authorization,'Bearer example-key');
    assert.equal(JSON.parse(saved.body).revision,1);
    assert.equal(JSON.parse(saved.body).note,'<script>plain text</script>');
    assert.match(h.element('review-message').textContent,/Zapisano/);
});

test('expired observations leave event description and review accessible',async()=>{
    const h=harness(()=>({event:{time:101,icao:'ABC123',analysis:{label:'Anomalia',reasons:[]}},points:[],observation_days:7}));
    h.run('incident.js');await h.settle();
    assert.match(h.element('availability').textContent,/Brak szczegółowych obserwacji/);
    assert.match(h.element('title').textContent,/ABC123/);
});

test('navigation distinguishes missing, zero and stale values during replay',()=>{
    const h=harness(), A=h.context.Analysis;
    assert.match(A.navigationText(null),/brak danych/);
    const q={time:100,version:2,version_updated_at:100,supported:true,sil_basis:'hour',
        nic:{value:8,updated_at:100},nac_p:{value:0,updated_at:100},nac_v:{value:null},sil:{value:3,updated_at:100}};
    assert.match(A.navigationText(q,100),/NACp: 0 · NACv: brak danych/);
    assert.match(A.navigationText(q,111),/NIC: 8 \(nieaktualne\)/);
    assert.doesNotMatch(A.navigationText(q,111),/NACp: 0 \(nieaktualne\)/);
    assert.match(A.navigationText(q,161),/wersja 2 \(nieaktualna\)/);
});

test('receiver displays empty history, zero rates and errors as text',async()=>{
    const h=harness(()=>({receiver:{time:100,state:'error',error:'<script>USB failed</script>',window_seconds:60,
        accepted_per_second:0,candidates_per_second:0,crc_valid_percent:null,read_age_s:null,valid_frame_age_s:null,
        noise_db_relative:null,read_gaps:0,max_read_gap_s:0,window:{crc_ok:0,crc_checked:0,decode_errors:0}},
        storage:{storage_ok:false,queued:3,dropped:1},history:[]}));
    h.run('receiver.js');await h.settle();
    assert.match(h.element('receiver-state').textContent,/Błąd odbiornika/);
    assert.equal(h.element('receiver-error').textContent,'<script>USB failed</script>');
    assert.equal(h.element('metrics').children.length,8);
    assert.match(text(h.element('metrics')),/brak danych/);
    assert.match(h.element('storage').textContent,/oczekujące rekordy: 3/);
    assert.match(h.element('history-summary').textContent,/Brak zapisanych próbek/);
});

test('quality replay continues after final position and shows degradation once',async()=>{
    const quality={time:110,version:2,version_updated_at:110,supported:true,nac_p:{value:2,updated_at:110},
        changes:[{time:110,field:'nac_p',before:9,after:2,direction:'down'}]};
    const h=harness(()=>({event:{time:100,icao:'ABC123',analysis:{label:'Anomalia',reasons:[]}},
        points:[{time:100,lat:52,lon:17,accepted:true}],navigation:[{time:110,quality},{time:115,quality}],
        receiver:[],window_start:-20,window_end:220,observation_days:7}));
    h.run('incident.js');await h.settle();
    assert.equal(Number(h.element('timeline').max),115);
    assert.equal(h.element('quality-changes').children.length,1);
    h.element('timeline').value=115;h.element('timeline').listeners.input();
    assert.match(h.element('selected-navigation').textContent,/NACp: 2/);
    assert.match(text(h.element('quality-changes')),/Spadek/);
});
