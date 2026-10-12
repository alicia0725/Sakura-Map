"""Read-only region aggregation. Schematic guide, never individual scenic peak dates."""
from datetime import date, datetime, timedelta
from statistics import median
import json
from .sources import REGIONS, BASE
from .collect import now
from .store import connect

REGION_NAMES = {k:v[0] for k,v in REGIONS.items()}
REGION_NAMES.update(kyushu='九州', okinawa='沖繩')
OKINAWA = {'那覇','石垣島','宮古島','南大東島'}
MODEL_VERSION = 'momiji-ridge-v1'
COLORS = {'before':'#819f82','approaching':'#ddb955','within':'#ce7956','after':'#9c8473','unavailable':'#c7cdca'}
LABELS = {'before':'轉紅前','approaching':'接近轉紅','within':'轉紅區間','after':'區間後','unavailable':'資料不足'}

def region_of(place):
    if place.get('station') in OKINAWA or '沖' in str(place.get('prefecture','')) or place.get('region') == 'okinawa':
        return 'okinawa'
    if place.get('station'):
        return next((k for k,(_,names) in REGIONS.items() if place['station'] in names.split()), None)
    return place.get('region')

def quantile(values, q):
    values = sorted(values)
    position = (len(values)-1)*q
    lo = int(position); hi = min(lo+1,len(values)-1)
    return values[lo] + (values[hi]-values[lo])*(position-lo)

def ordinal(day, autumn=False):
    d = date.fromisoformat(day)
    offset=(date(2000,d.month,d.day)-date(2000,1,1)).days
    return offset+366 if autumn and d.month<8 else offset

def to_date(year, value):
    ref = date(2000,1,1)+timedelta(days=round(value))
    return date(year+ref.year-2000,ref.month,ref.day).isoformat()

def stage_for(target, start, end):
    if not start or not end:
        return 'unavailable'
    if target < date.fromisoformat(start)-timedelta(days=14):
        return 'before'
    if target < date.fromisoformat(start):
        return 'approaching'
    return 'within' if target <= date.fromisoformat(end) else 'after'

def station_baselines(db, season, year):
    event = 'red_leaves' if season == 'momiji' else 'full_bloom'
    # Only completed years, at most twenty. Same regular/substitute species group.
    rows = db.execute('SELECT * FROM historical WHERE event=? AND year<? AND year>=? ORDER BY station,year DESC',
                      (event,min(year,now().year),min(year,now().year)-20)).fetchall()
    grouped = {}
    for r in rows:
        grouped.setdefault(r['station'],[]).append(dict(r))
    results = {}
    for station, records in grouped.items():
        group = int(records[0]['quality']) >= 8
        # Substitute remark does not identify its species. Until audited, do not pool it as one species.
        if season=='momiji' and not group:
            continue
        records = [r for r in records if (int(r['quality'])>=8)==group]
        if len(records)<15:
            continue
        days = [ordinal(r['day'],season=='momiji') for r in records]
        results[station] = dict(station=station, median=to_date(year,median(days)),
            start=to_date(year,quantile(days,.1)),end=to_date(year,quantile(days,.9)),
            sample_count=len(days),sample_years=[r['year'] for r in records],
            species='正規種目' if group else '替代種目',source_url=records[0]['source_url'])
    return results

def get_regions(db_path, season, target):
    with connect(db_path) as db:
        cities = station_baselines(db,season,target.year)
        run = db.execute('SELECT * FROM model_runs WHERE target_year=? ORDER BY id DESC LIMIT 1', (target.year,)).fetchone() if season=='momiji' else None
        report = json.loads(run['report']) if run else None
        weather = db.execute('SELECT * FROM weather_attempts ORDER BY id DESC LIMIT 1').fetchone()
        latest_collection = db.execute("SELECT finished_at FROM collection_runs WHERE source_id=? AND status='ok' ORDER BY id DESC LIMIT 1",('jma-history-015' if season=='momiji' else 'jma-history-005',)).fetchone()
        published = latest_collection['finished_at'] if latest_collection else None
        kind = 'historical_baseline'
        if run and report.get('enabled'):
            # Only use cities with a successful retained estimate. No mixed unnamed fallback.
            estimates = json.loads(run['estimates'])
            if estimates:
                cities = estimates; kind='weather_model';published=run['published_at']
        stale = False
        if kind=='weather_model':
            stale = now()-datetime.fromisoformat(published)>timedelta(hours=48) or bool(weather and weather['status']=='error' and weather['finished_at']>published)
        results=[]
        for code,name in REGION_NAMES.items():
            members=[v for station,v in cities.items() if region_of({'station':station})==code]
            start=to_date(target.year,quantile([ordinal(v['start'],season=='momiji') for v in members],.1)) if members else None
            end=to_date(target.year,quantile([ordinal(v['end'],season=='momiji') for v in members],.9)) if members else None
            mid=to_date(target.year,median([ordinal(v['median'],season=='momiji') for v in members])) if members else None
            stage=stage_for(target,start,end)
            results.append(dict(id=code,name=name,stage=stage,label=(dict(before='滿開前',approaching='接近滿開',within='滿開區間',after='區間後',unavailable='資料不足')[stage] if season=='sakura' else LABELS[stage]),color=('#d9a0b3' if season=='sakura' and stage=='within' else COLORS[stage]),
                start=start,end=end,median=mid,kind=kind if members else 'unavailable',
                kind_label=('天氣校正模型' if kind=='weather_model' else '歷年基準') if members else '資料不足',
                cities=members,published_at=published if members else None,stale=stale if members else False,
                cutoff=run['cutoff'] if run and kind=='weather_model' else f'{min(target.year,now().year)-1}-12-31',
                model_version=run['model_version'] if run and kind=='weather_model' else 'historical-20y-v1',
                sources=[{'name':'氣象廳歷年標本木紀錄','url':BASE+('ruinenchi/015.csv' if season=='momiji' else 'ruinenchi/005.csv')}] + ([{'name':'Open-Meteo ERA5 / GFS','url':'https://open-meteo.com/en/docs'}] if kind=='weather_model' else []),
                description=('觀測城市日期的中位數與分布；不代表所有海拔或個別景點。' if members else '未達15年可確認同樹種紀錄，或替代樹種尚未核對。景點與官方紀錄仍保留。') if season=='momiji' else '櫻花使用標本木滿開歷年基準，尚無櫻花天氣模型。',
                range_description='歷年氣候情境與城市分布範圍，並非校準信心區間。' if kind=='weather_model' else '同樹種最多20年、至少15年，城市日期分布。'))
    return {'regions':results,'season':season,'date':target.isoformat(),'today':now().date().isoformat(),
            'validation':{k:report[k] for k in ('enabled','cases','improvement','reason') if k in report} if report else {'enabled':False,'reason':'尚未完成氣象回測，使用歷年基準'},
            'weather_status':dict(weather) if weather else None}
