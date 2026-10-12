'use strict';
const $=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeUrl=v=>{try{const u=new URL(v);return ['https:','http:'].includes(u.protocol)?esc(u.href):'#';}catch{return '#';}};
const sourceLink=(url,label)=>`<a class="source-link" href="${safeUrl(url)}" target="_blank" rel="noopener noreferrer">${esc(label)} ↗</a>`;
const shortDate=v=>v?`${Number(v.slice(5,7))}/${Number(v.slice(8,10))}`:'—';
const utc=v=>new Date(`${v}T00:00:00Z`);
const iso=d=>d.toISOString().slice(0,10);
const DAY=86400000;
const today=document.body.dataset.today;
const FAVORITES_KEY='kisetsu.favorites.v1';
function readFavorites(){
  try{
    const saved=JSON.parse(localStorage.getItem(FAVORITES_KEY)||'null');
    const entries=Array.isArray(saved?.places)?saved.places.filter(p=>p&&typeof p.id==='string'&&p.id.length>0&&p.id.length<=200&&['momiji','sakura'].includes(p.season)).slice(0,1000):[];
    return {places:new Map(entries.map(p=>[p.id,p.season])),view:saved?.view==='favorites'?'favorites':'region',season:['momiji','sakura'].includes(saved?.season)?saved.season:null};
  }catch{return {places:new Map(),view:'region',season:null};}
}
const savedFavorites=readFavorites();
const state={season:savedFavorites.view==='favorites'&&savedFavorites.season?savedFavorites.season:document.body.dataset.season,date:today,region:'kanto',query:'',places:[],regions:[],sources:[],weather:null,validation:null,view:savedFavorites.view,favorites:savedFavorites.places};
function saveFavorites(){
  try{
    localStorage.setItem(FAVORITES_KEY,JSON.stringify({version:1,places:[...state.favorites].map(([id,season])=>({id,season})),view:state.view,season:state.season}));
    $('favorite-status').hidden=true;return true;
  }catch{
    $('favorite-status').textContent='這個瀏覽器無法保存收藏，目前僅此頁有效。';$('favorite-status').hidden=false;return false;
  }
}
function favoritesUI(){
  $('favorites-count').textContent=state.favorites.size;
  $('region-view').setAttribute('aria-pressed',String(state.view==='region'));
  $('favorites-view').setAttribute('aria-pressed',String(state.view==='favorites'));
  document.querySelector('.list-note').textContent=state.view==='favorites'?'本季收藏跨地區列出，官方消息仍會更新。收藏保存在此瀏覽器。':'近期官方紀錄優先，再列較舊紀錄與尚無紀錄的景點。';
}
function setListView(view){state.view=view;saveFavorites();renderPlaces();}
function toggleFavorite(id,button){
  const place=state.places.find(p=>p.id===id);if(!place)return;
  if(state.favorites.has(id))state.favorites.delete(id);else state.favorites.set(id,place.season);
  saveFavorites();favoritesUI();
  if(state.view==='favorites'){
    renderPlaces();
    const next=document.querySelector('.favorite-toggle');(next||$('favorites-view')).focus();
  }else{
    button.setAttribute('aria-pressed',String(state.favorites.has(id)));
    button.setAttribute('aria-label',`${state.favorites.has(id)?'取消收藏':'收藏'} ${place.name}`);
    button.querySelector('span').textContent=state.favorites.has(id)?'♥':'♡';
  }
}

const historyCache=new Map();let controller,serial=0;
const labels=()=>state.season==='momiji'?['轉紅前','接近轉紅','轉紅區間','區間後','資料不足']:['滿開前','接近滿開','滿開區間','區間後','資料不足'];
const stageKeys=['before','approaching','within','after','unavailable'];
const colors=()=>['#819f82','#ddb955',state.season==='momiji'?'#ce7956':'#d9a0b3','#9c8473','#c7cdca'];
function stageOf(region){
  if(!region?.start||!region?.end)return 'unavailable';
  const date=utc(state.date),start=utc(region.start),end=utc(region.end);
  if(date<start-14*DAY)return 'before';
  if(date<start)return 'approaching';
  return date<=end?'within':'after';
}
function configureDates(){
  const year=Number(state.date.slice(0,4)),current=Number(today.slice(0,4));
  $('year').innerHTML=Array.from(new Set([current,current+1,current+2,year])).sort().map(y=>`<option value="${y}"${year===y?' selected':''}>${y}</option>`).join('');
  $('date-input').min=`${current}-01-01`;$('date-input').max=`${current+2}-12-31`;
  $('date-slider').max=(utc(`${year}-12-31`)-utc(`${year}-01-01`))/DAY;
  updateDates();
}
function updateDates(){
  $('date-input').value=state.date;
  $('date-slider').value=(utc(state.date)-utc(`${state.date.slice(0,4)}-01-01`))/DAY;
  $('date-slider').setAttribute('aria-valuetext',`${state.date} ${state.season==='momiji'?'紅葉':'櫻花'}區域預估`);
  $('previous-day').disabled=state.date===$('date-input').min;
  $('next-day').disabled=state.date===$('date-input').max;
}
function setDate(value){
  if(!/^\d{4}-\d{2}-\d{2}$/.test(value)||value<$('date-input').min||value>$('date-input').max)return;
  const changedYear=value.slice(0,4)!==state.date.slice(0,4);
  state.date=value;
  if(changedYear){configureDates();state.regions=[];renderMap();loadData();}
  else{updateDates();renderMap();renderRegionInfo();}
}
function renderMap(){
  document.querySelectorAll('[data-region]').forEach(button=>{
    const region=state.regions.find(r=>r.id===button.dataset.region),stage=stageOf(region),index=stageKeys.indexOf(stage);
    button.style.setProperty('--fill',colors()[index]);button.dataset.stage=stage;
    button.classList.toggle('selected',state.region===button.dataset.region);
    button.setAttribute('aria-pressed',String(state.region===button.dataset.region));
    button.querySelector('.region-stage').textContent=labels()[index];
    const count=state.places.filter(p=>p.region===button.dataset.region).length;
    button.querySelector('.region-count').textContent=`${count} 景點`;
    button.setAttribute('aria-label',`${button.querySelector('strong').textContent}，${labels()[index]}，${count}個景點`);
  });
  $('legend').innerHTML='<span class="legend-title">區域預估</span>'+labels().map((l,i)=>`<span><i style="background:${colors()[i]}"></i>${l}</span>`).join('');
  $('estimate-type').textContent=state.regions.some(r=>r.kind==='weather_model')?'天氣校正模型':'歷年基準';
  const v=state.validation;
  $('validation-note').textContent=state.season==='sakura'?'滿開歷年基準；尚無櫻花氣象模型。':v?.enabled?`天氣模型已通過回測（${v.cases}案例，誤差改善${(v.improvement*100).toFixed(1)}%）。`:v?.reason||'正在讀取區域資料。';
}
function wireDisclosure(detail){
  const summary=detail.querySelector(':scope > summary');
  if(!summary)return;
  summary.setAttribute('role','button');summary.tabIndex=0;
  summary.setAttribute('aria-expanded',String(detail.open));
  const toggle=e=>{e.preventDefault();detail.open=!detail.open;summary.setAttribute('aria-expanded',String(detail.open));};
  summary.addEventListener('click',toggle);
  summary.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){toggle(e);}});
  detail.addEventListener('toggle',()=>summary.setAttribute('aria-expanded',String(detail.open)));
}
function renderRegionInfo(){
  const r=state.regions.find(r=>r.id===state.region);
  if(!r){$('region-info').innerHTML='<p>區域資料載入中。</p>';return;}
  const stage=stageKeys.indexOf(stageOf(r));
  const event=state.season==='momiji'?'轉紅':'滿開';
  $('region-info').innerHTML=`<h3>${esc(r.name)} · ${labels()[stage]}</h3>
    <p class="range">${r.start?`${shortDate(r.start)} — ${shortDate(r.end)}`:'尚無適用的區域日期'}</p>
    <p>${esc(r.kind_label)}${r.median?` · 城市${event}中位日期 ${shortDate(r.median)}`:''}</p>
    <p>${esc(r.description)} ${esc(r.range_description)}</p>
    ${r.stale?'<p class="stale">氣象資料過期或更新失敗，保留最後成功預估。</p>':''}
    ${state.season==='momiji'&&state.weather?.status==='error'?'<p class="stale">氣象來源最近取得失敗，官方景點資料仍可查閱。</p>':''}
    <details><summary>參與城市與估計依據（${r.cities.length} 城市）</summary>
      ${r.cities.length?r.cities.map(c=>`<div class="city-row"><span>${esc(c.station)} <small>${esc(c.species)} · ${c.sample_count} 年</small></span><span>${shortDate(c.median)}</span></div>`).join(''):'<p>未達同樹種15年有效紀錄，或替代樹種尚未核對，保持灰色。</p>'}
      <p>資料截止 ${esc(r.cutoff||'—')}<br>發布／來源取得 ${esc(r.published_at?.replace('T',' ').slice(0,19)||'尚無紀錄')}<br>版本 ${esc(r.model_version)}</p>
      ${r.sources.map(s=>sourceLink(s.url,s.name)).join('')}
    </details>`;
  $('region-info').querySelectorAll('details').forEach(wireDisclosure);
}
function groupOf(place){const o=place.observation;return !o?2:o.freshness==='recent'?0:1;}
function sortedPlaces(){
  const q=state.query.toLocaleLowerCase();
  return state.places.filter(p=>state.view!=='favorites'||state.favorites.has(p.id)).filter(p=>q?['name','name_ja','name_en','prefecture','region_name'].some(k=>String(k==='prefecture'?String(p[k]||'').replace(/[都道府縣県]$/,''):p[k]||'').toLocaleLowerCase().includes(q)):state.view==='favorites'||p.region===state.region)
    .sort((a,b)=>groupOf(a)-groupOf(b)||(b.observation?.observed_on||'').localeCompare(a.observation?.observed_on||'')||a.name.localeCompare(b.name,'zh-Hant')||a.id.localeCompare(b.id));
}
function card(p){
  const o=p.observation,official=p.forecast?.kind==='official_outlook'?p.forecast:null;
  const location=[p.region_name,p.prefecture,p.name_ja!==p.name?p.name_ja:null].filter(Boolean).join(' · ');
  return `<article class="place-shell"><button type="button" class="favorite-toggle" data-favorite="${esc(p.id)}" aria-pressed="${state.favorites.has(p.id)}" aria-label="${state.favorites.has(p.id)?'取消收藏':'收藏'} ${esc(p.name)}"><span aria-hidden="true">${state.favorites.has(p.id)?'♥':'♡'}</span></button><details class="place-card" data-place="${esc(p.id)}"><summary>
    <div class="card-heading"><div><h3>${esc(p.name)}</h3><p class="location">${esc(location)}</p></div><span class="expand-icon" aria-hidden="true">+</span></div>
    <div class="facts"><div class="fact"><span class="fact-label">最新官方實況</span><span class="fact-value">${o?`<i class="status-dot" style="background:${esc(o.color)}"></i>${esc(o.label)}`:'尚無官方紀錄'}</span><small>${o?`${esc(o.observed_on)} · ${o.freshness==='recent'?'近7日紀錄':'較舊紀錄'}<br>${esc(o.date_label)}`:'等待接入現場觀測'}</small></div>
    <div class="fact"><span class="fact-label">官方${state.season==='momiji'?'見頃':'花期'}預測</span><span class="fact-value">${official?`${shortDate(official.start)} — ${shortDate(official.end)}`:'尚未提供'}</span><small>${official?`${esc(official.start.slice(0,4))}年 · ${esc(official.period)}<br>來源更新 ${esc(official.issued_on)}`:'不以區域模型代替景點預測'}</small></div></div>
    ${p.usual_period?`<p class="usual">通常觀賞期 · ${esc(p.usual_period)}（介紹參考，非今年預測）</p>`:''}</summary>
    <div class="card-details"><p>${esc(p.description||'尚無景點介紹。')}</p>${p.address?`<p>${esc(p.address)}</p>`:''}
      ${p.lat!=null&&p.lng!=null?sourceLink(`https://www.google.com/maps/search/?api=1&query=${p.lat},${p.lng}`,'查看景點位置'):p.official_url?sourceLink(p.official_url,'官方景點介紹與位置'):'<p>官方尚未提供可用座標。</p>'}
      <h4>官方來源</h4>${o?sourceLink(o.source_url,o.source_name):'<p>尚無官方實況來源。</p>'}${official&&official.source_url!==o?.source_url?sourceLink(official.source_url,official.source_name):''}
      ${o?.note?`<p>${esc(o.note)}</p>`:''}<h4>觀測歷史</h4><div class="history" role="status">展開後載入紀錄。</div>
    </div></details></article>`;
}
function renderPlaces(){
  const open=new Set([...document.querySelectorAll('.place-card[open]')].map(e=>e.dataset.place));
  const places=sortedPlaces();let lastGroup=-1;
  const name=state.regions.find(r=>r.id===state.region)?.name||document.querySelector(`[data-region="${state.region}"] strong`).textContent;
  favoritesUI();
  $('list-eyebrow').textContent=state.view==='favorites'?'儲存在這個瀏覽器':state.query?'搜尋全日本':`探索${name}`;
  $('list-title').textContent=state.view==='favorites'?(state.query?'收藏搜尋結果':`我的${state.season==='momiji'?'紅葉':'櫻花'}收藏`):state.query?'搜尋結果':`${name}景點`;
  $('list-count').textContent=`${places.length} 處`;
  $('clear-search').hidden=!state.query;
  $('total-count').textContent=`${state.season==='momiji'?'紅葉':'櫻花'}共收錄 ${state.places.length} 處景點`;
  $('places').innerHTML=places.map(p=>{
    const group=groupOf(p);const label=group!==lastGroup?`<div class="group-label">${['近 7 日官方紀錄','較舊官方紀錄','尚無官方紀錄'][group]}</div>`:'';lastGroup=group;return label+card(p);
  }).join('')||`<div class="empty">${state.query?'找不到符合的景點，試試城市或縣名。':state.view==='favorites'?`還沒有${state.season==='momiji'?'紅葉':'櫻花'}收藏。<br>點景點卡上的 ♡，下次回來就能在這裡找到。${state.favorites.size?'也可以切換季節查看其他收藏。':''}`:'這個分區目前尚無收錄景點。<br>其他分區可繼續點選探索。'}</div>`;
  document.querySelectorAll('[data-favorite]').forEach(button=>button.onclick=()=>toggleFavorite(button.dataset.favorite,button));
  document.querySelectorAll('.place-card').forEach(detail=>{
    wireDisclosure(detail);
    detail.addEventListener('toggle',()=>{if(detail.open)loadHistory(detail);});
    if(open.has(detail.dataset.place))detail.open=true;
  });
}
async function loadHistory(detail){
  const id=detail.dataset.place,node=detail.querySelector('.history');node.textContent='讀取官方歷史…';
  try{
    if(!historyCache.has(id)){
      const response=await fetch(`/api/places/${encodeURIComponent(id)}/history`);if(!response.ok)throw new Error();
      historyCache.set(id,(await response.json()).observations);
    }
    const observations=historyCache.get(id);
    node.innerHTML=observations.length?`<ul class="history-list">${observations.map(o=>`<li>${esc(o.observed_on)} · ${esc(o.label)}<small>${esc(o.date_label)} · ${esc(o.source_name)}</small>${sourceLink(o.source_url,'原始公告')}</li>`).join('')}</ul>`:'尚無官方觀測歷史。';
  }catch{node.innerHTML='歷史載入失敗。<button class="quiet-button" type="button">重試</button>';node.querySelector('button').onclick=()=>loadHistory(detail);}
}
async function loadData(){
  controller?.abort();controller=new AbortController();const version=++serial;
  $('load-status').textContent='讀取官方景點與區域預估…';
  try{
    const args=new URLSearchParams({season:state.season,date:state.date});
    const results=await Promise.all([fetch(`/api/places?${args}&kind=spot`,{signal:controller.signal}),fetch(`/api/regions?${args}`,{signal:controller.signal})]);
    if(results.some(r=>!r.ok))throw new Error();
    const [places,regions]=await Promise.all(results.map(r=>r.json()));if(version!==serial)return;
    state.places=places.places;state.regions=regions.regions;state.validation=regions.validation;state.weather=regions.weather_status;
    $('load-status').textContent='';renderMap();renderPlaces();renderRegionInfo();
  }catch(error){if(error.name!=='AbortError'&&version===serial)$('load-status').innerHTML='資料讀取失敗。<button class="quiet-button" id="retry-data">重新載入</button>';if($('retry-data'))$('retry-data').onclick=loadData;}
}
function chooseRegion(code){state.view='region';saveFavorites();state.region=code;state.query='';$('search').value='';renderMap();renderPlaces();renderRegionInfo();}
function setSeason(season){
  state.season=season;if(state.view==='favorites')saveFavorites();state.places=[];state.regions=[];state.validation=null;
  document.querySelectorAll('button[data-season]').forEach(b=>b.classList.toggle('active',b.dataset.season===season));
  $('season-title').textContent=`日本${season==='momiji'?'紅葉':'櫻花'}地圖`;
  renderMap();$('places').innerHTML='';renderRegionInfo();loadData();
}
async function showSources(){
  $('sources-dialog').showModal();$('source-list').textContent='讀取來源狀態…';
  try{
    const response=await fetch('/api/sources');if(!response.ok)throw new Error();
    state.sources=(await response.json()).sources;
    $('source-list').innerHTML=state.sources.map(s=>`<div class="source-entry"><strong>${esc(s.name)}</strong><small>${esc(s.scope)} · ${esc(s.description)}</small>${sourceLink(s.url,'官方網站')}<small class="${s.last_run?.status==='error'?'stale':''}">${s.last_run?.status==='error'?'最近取得失敗，保留前次資料。':s.last_success_at?'最後成功取得：'+esc(s.last_success_at.replace('T',' ').slice(0,19)):'尚未成功取得'}</small></div>`).join('')+`<div class="source-entry"><strong>Open-Meteo · 氣象與模型</strong><small>ERA5 歷史氣溫 / GFS Seamless 近期預報。背景更新，網頁不訓練模型。</small>${sourceLink('https://open-meteo.com/en/docs','氣象服務文件')}<small>${state.weather?`${esc(state.weather.finished_at)} · ${state.weather.status==='ok'?'取得成功':'取得失敗，保留最後成功結果'}`:'尚未取得氣象資料'}</small><small>${esc(state.validation?.reason||'尚未完成回測')}</small></div>`;
  }catch{$('source-list').textContent='來源狀態載入失敗，請關閉後重試。';}
}
$('date-slider').addEventListener('input',e=>setDate(iso(new Date(utc(`${state.date.slice(0,4)}-01-01`).getTime()+Number(e.target.value)*DAY))));
$('date-input').addEventListener('change',e=>setDate(e.target.value));
$('year').addEventListener('change',e=>{const y=Number(e.target.value),m=Number(state.date.slice(5,7)),d=Number(state.date.slice(8,10));const max=new Date(Date.UTC(y,m,0)).getUTCDate();setDate(`${y}-${String(m).padStart(2,'0')}-${String(Math.min(d,max)).padStart(2,'0')}`);});
$('today').onclick=()=>setDate(today);
$('previous-day').onclick=()=>setDate(iso(new Date(utc(state.date).getTime()-DAY)));
$('next-day').onclick=()=>setDate(iso(new Date(utc(state.date).getTime()+DAY)));
$('search').addEventListener('input',e=>{state.query=e.target.value.trim();renderPlaces();});
$('clear-search').onclick=()=>{state.query='';$('search').value='';renderPlaces();$('search').focus();};
document.querySelectorAll('[data-region]').forEach(b=>b.onclick=()=>chooseRegion(b.dataset.region));
document.querySelectorAll('button[data-season]').forEach(b=>b.onclick=()=>setSeason(b.dataset.season));
$('region-view').onclick=()=>setListView('region');$('favorites-view').onclick=()=>setListView('favorites');
window.addEventListener('storage',event=>{if(event.key===FAVORITES_KEY||event.key===null){state.favorites=readFavorites().places;renderPlaces();}});
$('sources-button').onclick=showSources;$('close-sources').onclick=()=>$('sources-dialog').close();
$('sources-dialog').querySelectorAll('details').forEach(wireDisclosure);
configureDates();setSeason(state.season);
