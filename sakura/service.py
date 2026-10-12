from calendar import monthrange
from datetime import date, timedelta
import json
import math
import re
from statistics import median
from .collect import now
from .sources import SOURCES, REGIONS
from .store import connect, place_dict, ROOT
from .regions import region_of, REGION_NAMES

STAGES = {'green': ('尚未變色', '#6f8d71'), 'coloring': ('開始著色', '#d6a256'),
          'peak': ('見頃', '#ba5a42'), 'fading': ('褪色／落葉中', '#927961'),
          'flowering': ('開花事件', '#d7879e'), 'full_bloom': ('滿開事件', '#b96183'),
          'red_leaves': ('紅葉事件', '#ba5a42'), 'leaf_fall': ('落葉事件', '#927961')}
SOURCES_BY_ID = {source['id']: source for source in SOURCES}
CATALOG = {p['id']:p for p in json.loads((ROOT/'data/spots.json').read_text())}

def decorate_observation(row, today=None):
    if not row:
        return None
    item = dict(row)
    today = today or now().date()
    item['age_days'] = (today-date.fromisoformat(item['observed_on'])).days
    item['freshness'] = 'recent' if 0 <= item['age_days'] <= 7 else 'stale'
    item['label'], item['color'] = STAGES.get(item['stage'], ('未分類', '#969c98'))
    item['source_name'] = SOURCES_BY_ID.get(item['source_id'], {}).get('name', item['source_id'])
    item['date_label'] = '現場觀測' if item['date_basis'] == 'observed' else '來源更新（現場日期未載明）'
    # Internal paths are not needed by public clients.
    item.pop('fingerprint', None)
    item.pop('raw_path', None)
    return item

def period_window(text, year):
    parts = re.findall(r'(\d{1,2})月\s*(上旬|中旬|下旬)', text or '')
    if not parts:
        return None
    first, last = parts[0], parts[-1]
    def boundary(part, end):
        month = int(part[0])
        if not 1 <= month <= 12:
            raise ValueError('invalid month')
        days = {'上旬': (1, 10), '中旬': (11, 20), '下旬': (21, monthrange(year, month)[1])}
        return date(year, month, days[part[1]][int(end)])
    try:
        start, end = boundary(first, False), boundary(last, True)
        return (start, end) if start <= end else None
    except ValueError:
        return None

def relation(target, start, end):
    if target < start:
        return 'before', '參考區間前', '#739282'
    if target > end:
        return 'after', '參考區間後', '#a99e91'
    return 'within', '參考區間內', '#bc7652'

def historical_reference(db, place, target):
    event = 'full_bloom' if place['season'] == 'sakura' else 'red_leaves'
    # Exclude target-year observations so historical comparisons cannot leak actual outcomes.
    rows = db.execute('SELECT * FROM historical WHERE station=? AND event=? AND year<? AND year>=? '
                      'ORDER BY year DESC', (place.get('station'), event, target.year, target.year-15)).fetchall()
    if not rows:
        return None
    # Preserve species scope: do not combine regular and substitute species in a baseline.
    species = int(rows[0]['quality']) >= 8
    rows = [r for r in rows if (int(r['quality']) >= 8) == species][:10]
    if len(rows) < 5:
        return None
    days = sorted((date(2000, int(r['day'][5:7]), int(r['day'][8:10]))-date(2000, 1, 1)).days for r in rows)
    lower = days[math.floor((len(days)-1)*.1)]
    upper = days[math.ceil((len(days)-1)*.9)]
    def in_year(offset):
        ref = date(2000, 1, 1)+timedelta(days=round(offset))
        return date(target.year, ref.month, min(ref.day, monthrange(target.year, ref.month)[1]))
    start, end = in_year(lower), in_year(upper)
    code, label, color = relation(target, start, end)
    return {'kind': 'historical_reference', 'label': '區域歷史基準', 'relation': code,
            'date_label': label, 'color': color, 'start': start.isoformat(), 'end': end.isoformat(),
            'median': in_year(median(days)).isoformat(), 'sample_count': len(rows),
            'sample_years': [r['year'] for r in rows], 'source_url': rows[0]['source_url'],
            'description': '同類標本木最近最多 10 年的事件日期分布（10–90 百分位）；不是氣象校正預測或信心區間，也不代表附近景點。',
            'event': STAGES[event][0], 'method': 'historical-v1', 'weather_adjusted': False}

def forecast_for(db, place, target):
    if place['kind'] == 'station':
        reference = historical_reference(db, place, target)
        if reference:
            return reference
    outlook = db.execute('SELECT * FROM outlooks WHERE place_id=? AND target_year=? ORDER BY issued_on DESC LIMIT 1',
                         (place['id'], target.year)).fetchone()
    if outlook:
        window = period_window(outlook['period'], target.year)
        if window:
            start, end = window
            code, label, color = relation(target, start, end)
            return {'kind': 'official_outlook', 'label': '官方見頃預測', 'relation': code,
                    'date_label': label, 'color': color, 'start': start.isoformat(), 'end': end.isoformat(),
                    'period': outlook['period'], 'issued_on': outlook['issued_on'],
                    'age_days': (now().date()-date.fromisoformat(outlook['issued_on'])).days,
                    'source_url': outlook['source_url'], 'source_name': SOURCES_BY_ID[outlook['source_id']]['name'],
                    'description': '官方提供的旬別見頃區間；不推算精確開花比例。來源更新日不一定等於預測最初發布日。'}
    window = period_window(place.get('best_period'), target.year)
    if window:
        start, end = window
        code, label, color = relation(target, start, end)
        return {'kind': 'catalog_reference', 'label': '景點季節參考', 'relation': code,
                'date_label': label, 'color': color, 'start': start.isoformat(), 'end': end.isoformat(),
                'period': place['best_period'],
                'description': '沿用原景點介紹的通常觀賞期，尚未由官方來源校驗；不是今年預測。'}
    return {'kind': 'unavailable', 'label': '尚無日期預測', 'date_label': '資料不足',
            'color': '#a4aca8', 'description': '尚無可使用的官方預測或歷史基準。'}

def get_places(db_path, season, target):
    with connect(db_path) as db:
        latest = {r['place_id']: r for r in db.execute('''SELECT o.* FROM observations o WHERE o.season=?
            AND o.id=(SELECT x.id FROM observations x WHERE x.place_id=o.place_id
            ORDER BY x.observed_on DESC,x.fetched_at DESC,x.id DESC LIMIT 1)''', (season,))}
        result = []
        for row in db.execute('SELECT * FROM places WHERE season=? ORDER BY kind,name', (season,)):
            item = place_dict(row)
            if item['kind'] == 'station':
                for code, (label, names) in REGIONS.items():
                    if item.get('station') in names.split():
                        item['region'], item['region_name'] = code, label
                        break
            item['region'] = region_of(item)
            item['region_name'] = REGION_NAMES.get(item['region'], item.get('region_name',''))
            original=CATALOG.get(item['id'],{})
            if original:
                # Keep catalog descriptions/identity alongside official enrichment, never import legacy statuses.
                item['name']=original['name']
                for key in ('name_ja','name_en','address','description','best_period'):
                    if original.get(key):item[key]=original[key]
            item['usual_period'] = item.get('best_period')
            item['observation'] = decorate_observation(latest.get(item['id']))
            item['forecast'] = forecast_for(db, item, target)
            result.append(item)
        return result

def source_status(db_path):
    with connect(db_path) as db:
        results = []
        for source in SOURCES:
            item = dict(source)
            last = db.execute('SELECT * FROM collection_runs WHERE source_id=? ORDER BY id DESC LIMIT 1',
                              (source['id'],)).fetchone()
            success = db.execute("SELECT finished_at FROM collection_runs WHERE source_id=? AND status='ok' ORDER BY id DESC LIMIT 1",
                                 (source['id'],)).fetchone()
            item['last_run'] = {k:last[k] for k in ('finished_at','status','records','error')} if last else None
            item['last_success_at'] = success['finished_at'] if success else None
            results.append(item)
        return results
