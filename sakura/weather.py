"""Background-only Open-Meteo ingestion. No network in read services."""
import argparse
from datetime import date, datetime, timedelta
import hashlib
import json
import ssl
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import certifi
from .collect import now
from .sources import STATIONS
from .store import ROOT, DEFAULT_DB, connect, initialize

ARCHIVE = 'https://archive-api.open-meteo.com/v1/archive'
FORECAST = 'https://api.open-meteo.com/v1/forecast'

def fetch(url):
    context=ssl.create_default_context(cafile=certifi.where())
    for attempt in range(3):
        try:
            with urlopen(Request(url,headers={'User-Agent':'Kisetsu/4.0 research local map'}),timeout=60,context=context) as response:
                raw=response.read(8_000_001)
                if len(raw)>8_000_000: raise ValueError('氣象回應過大')
                return raw
        except (URLError, TimeoutError) as exc:
            if isinstance(exc,HTTPError) and exc.code<500:
                raise # Respect 429 immediately rather than retrying the rate limit.
            if attempt==2:raise
            time.sleep(2*(attempt+1))

def ingest(station, kind, start, end, db_path=DEFAULT_DB, fetcher=fetch, raw_root=None):
    lat,lng=STATIONS[station]
    model='era5' if kind=='archive' else 'gfs_seamless'
    params=dict(latitude=lat,longitude=lng,daily='temperature_2m_mean',timezone='Asia/Tokyo',models=model)
    if kind=='archive':params.update(start_date=start,end_date=end)
    else:params.update(forecast_days=16,past_days=7)
    url=(ARCHIVE if kind=='archive' else FORECAST)+'?'+urlencode(params)
    raw=fetcher(url)
    directory=raw_root or ROOT/'data/raw/open-meteo'
    directory.mkdir(parents=True,exist_ok=True)
    path=directory/(hashlib.sha256(raw).hexdigest()+'.json');path.write_bytes(raw)
    payload=json.loads(raw)
    daily=payload.get('daily',{})
    days=daily.get('time',[]);temps=daily.get('temperature_2m_mean',[])
    if not days or len(days)!=len(temps):raise ValueError('氣象日資料格式改變')
    valid={}
    for day,value in zip(days,temps):
        date.fromisoformat(day)
        if value is not None and isinstance(value,(int,float)) and -80<value<65:
            valid[day]=value
    if not valid:raise ValueError('氣象資料全部缺測')
    with connect(db_path) as db:
        db.execute('INSERT INTO weather_fetches(station,kind,provider,model,latitude,longitude,fetched_at,start_date,end_date,url,raw_path,payload) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
            (station,kind,'Open-Meteo',model,lat,lng,now().isoformat(timespec='seconds'),min(valid),max(valid),url,str(path),json.dumps(valid)))
    return len(valid)

def load_weather(db_path):
    archives={};forecasts={};metadata={}
    with connect(db_path) as db:
        for row in db.execute('SELECT * FROM weather_fetches ORDER BY id'):
            dest=archives if row['kind']=='archive' else forecasts
            dest.setdefault(row['station'],{}).update(json.loads(row['payload']))
            metadata.setdefault(row['station'],{})[row['kind']]={k:row[k] for k in ('id','model','fetched_at','start_date','end_date','url','latitude','longitude')}
    # Forecasts must come from the latest snapshot, not a union of obsolete forecasts.
    with connect(db_path) as db:
        for station in forecasts:
            row=db.execute("SELECT payload FROM weather_fetches WHERE station=? AND kind='forecast' ORDER BY id DESC LIMIT 1",(station,)).fetchone()
            forecasts[station]=json.loads(row['payload'])
    return archives,forecasts,metadata

def collect_weather(db_path=DEFAULT_DB, force=False, fetcher=fetch, pause=8, retry_failed=False):
    initialize(db_path)
    today=now().date(); end=today-timedelta(days=5) # ERA5 conservative availability delay
    with connect(db_path) as db:
        last=db.execute('SELECT * FROM weather_attempts ORDER BY id DESC LIMIT 1').fetchone()
        if last and not force and not retry_failed:
            delay=timedelta(hours=24 if last['status']=='ok' else 1)
            if now()-datetime.fromisoformat(last['finished_at'])<delay:return None
        stations=[r[0] for r in db.execute("SELECT station FROM historical WHERE event='red_leaves' AND year>=? AND year<? GROUP BY station HAVING COUNT(*)>=15",(today.year-25,today.year)) if r[0] in STATIONS]
    if retry_failed and last and last['status']=='error':
        failed={e.split(':',1)[0] for e in (last['error'] or '').split('; ')}
        with connect(db_path) as db:
            covered={r[0] for r in db.execute("SELECT station FROM weather_fetches GROUP BY station HAVING COUNT(DISTINCT kind)=2")}
        stations=[station for station in stations if station in failed or station not in covered]
    errors=[];records=0
    for station in stations:
        try:
            with connect(db_path) as db:
                row=db.execute("SELECT end_date FROM weather_fetches WHERE station=? AND kind='archive' ORDER BY id DESC LIMIT 1",(station,)).fetchone()
            # Bootstrap 25 years allows the oldest of the five holdouts 20 training years.
            start=date(today.year-25,8,1) if not row else date.fromisoformat(row['end_date'])-timedelta(days=7)
            if start<=end: records+=ingest(station,'archive',start.isoformat(),end.isoformat(),db_path,fetcher)
            records+=ingest(station,'forecast',None,None,db_path,fetcher)
            print(f'weather {station}: ok',flush=True)
        except Exception as exc:
            errors.append(f'{station}: {type(exc).__name__}: {exc}')
            print(errors[-1],flush=True)
            # Stop rate-limited passes, keep all existing successful snapshots.
            if getattr(exc,'code',None)==429:break
        if pause:time.sleep(pause)
    with connect(db_path) as db:
        db.execute('INSERT INTO weather_attempts(finished_at,status,records,error) VALUES (?,?,?,?)',
            (now().isoformat(timespec='seconds'),'error' if errors else 'ok',records,'; '.join(errors) or None))
    return {'status':'error' if errors else 'ok','records':records,'errors':errors}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--watch',action='store_true');parser.add_argument('--once',action='store_true');parser.add_argument('--force',action='store_true');parser.add_argument('--offline',action='store_true');parser.add_argument('--retry-failed',action='store_true')
    args=parser.parse_args()
    from .model import publish
    while True:
        if not args.offline:
            result=collect_weather(force=args.force,retry_failed=args.retry_failed)
            if result is not None:print(result,flush=True)
        # All train / evaluation work stays in this background process.
        publish()
        if not args.watch:break
        args.force=False;args.retry_failed=False;time.sleep(300)

if __name__=='__main__':main()
