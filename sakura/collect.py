"""Run `python -m sakura.collect --once` or a single long-running `--watch` worker."""
import argparse
import csv
from datetime import date, datetime, timedelta
import hashlib
import io
import json
import re
import ssl
import time
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
import certifi
from bs4 import BeautifulSoup
from .sources import SOURCES, STATIONS
from .store import ROOT, DEFAULT_DB, connect, initialize, upsert_place

JST = ZoneInfo('Asia/Tokyo')

def now():
    return datetime.now(JST)

def japanese_day(value, year):
    match = re.search(r'(\d{1,2})月\s*(\d{1,2})日', value)
    if not match:
        return None
    try:
        return date(year, int(match[1]), int(match[2])).isoformat()
    except ValueError:
        return None

def parse_jma(html, source):
    soup = BeautifulSoup(html, 'html.parser')
    title = soup.find('h1')
    years = re.findall(r'(20\d{2})年?', title.get_text() if title else '')
    if not years:
        raise ValueError('找不到官方資料年份，停止匯入')
    results = []
    table_seen = False
    for tr in soup.select('table tr'):
        cells = [c.get_text(' ', strip=True) for c in tr.find_all(['td', 'th'], recursive=False)]
        if not cells or cells[0] not in STATIONS:
            continue
        table_seen = True
        station = cells[0]
        if source['format'] == 'jma-sakura':
            slots = [(int(years[0]), 1)]
        else:
            slots = [(int(y), 1 + 3*i) for i, y in enumerate(years[:2])]
        for year, index in slots:
            day = japanese_day(cells[index], year)
            # December sakura events in the current-season page belong to the prior year.
            if day and source['season'] == 'sakura' and day[5:7] == '12':
                day = japanese_day(cells[index], year-1)
            if day and day <= now().date().isoformat():
                results.append({'station': station, 'stage': source['event'], 'observed_on': day,
                                'date_basis': 'observed', 'note': cells[-1] if len(cells) > 7 else ''})
    if not table_seen:
        raise ValueError('官方表格結構不符預期，保留上次成功資料')
    return results

def parse_history(raw, source):
    rows = list(csv.reader(io.StringIO(raw.decode('cp932'))))
    if len(rows) < 3 or rows[1][:2] != ['番号', '地点名']:
        raise ValueError('歷年 CSV 欄位不符預期')
    years = [(i, int(value)) for i, value in enumerate(rows[1]) if re.fullmatch(r'20\d{2}|19\d{2}', value)]
    records = []
    for row in rows[2:]:
        if len(row) != len(rows[1]):
            raise ValueError('歷年 CSV 列長度改變')
        station = row[1].strip()
        for index, year in years:
            if not row[index].isdigit() or index+1 >= len(row):
                continue
            value = int(row[index])
            # JMA codes 6/7: substitute species; 8/9: regular species. Exclude 0, 3, 4.
            if value == 0 or row[index+1] not in ('6', '7', '8', '9'):
                continue
            try:
                calendar_year = year-1 if source['season'] == 'sakura' and value//100 == 12 else year
                if source['season']=='momiji' and value//100<8:
                    calendar_year=year+1 # JMA autumn series assigns next-Jan events to the previous season year.
                day = date(calendar_year, value//100, value%100)
            except ValueError:
                continue
            if day <= now().date():
                records.append((station, source['season'], source['event'], year, day.isoformat(),
                                row[index+1], source['url']))
    if not records:
        raise ValueError('歷年 CSV 無有效觀測')
    return records

def parse_nikko(html):
    soup = BeautifulSoup(html, 'html.parser')
    # Parse literal coordinates; never execute third-party scripts.
    coords = {}
    for block in re.findall(r'markerData\.push\(\{(.*?)\}\);', html, re.S):
        name = re.search(r"name:\s*'([^']+)'", block)
        lat = re.search(r"lat:\s*Number\('([\d.]+)'\)", block)
        lng = re.search(r"lng:\s*Number\('([\d.]+)'\)", block)
        if name and lat and lng:
            coords[name[1]] = (float(lat[1]), float(lng[1]))
    records = []
    stages = {'✕': 'green', '×': 'green', '△': 'coloring', '〇': 'peak', '○': 'peak',
              '◎': 'peak', '▼': 'fading'}
    for card in soup.select('.post-info'):
        title = card.select_one('.post-title')
        degree = card.select_one('.post-degree')
        update = card.select_one('.post-last-update')
        if not all([title, degree, update]):
            raise ValueError('日光景點欄位不完整')
        name = title.get_text(strip=True)
        match = re.search(r'(20\d{2})年\s*(\d+)月\s*(\d+)日', update.get_text())
        symbol = degree.get_text(strip=True).split('：')[-1].strip()
        if not match or symbol not in stages:
            raise ValueError('日光日期、狀態或座標格式改變')
        reported = date(*map(int, match.groups()))
        if reported > now().date():
            continue
        note_node = card.select_one('.post-description')
        note = note_node.get_text(' ', strip=True) if note_node else ''
        observed = reported
        basis = 'source_updated'
        explicit = re.search(r'(\d{1,2})/(\d{1,2})現在', note)
        if explicit:
            observed = date(reported.year, int(explicit[1]), int(explicit[2]))
            if observed > reported:
                raise ValueError('日光現場日期晚於公告日期')
            basis = 'observed'
        link = title.select_one('a')
        href = link['href'] if link else '/flowering/autumn-leaves'
        spot_number = re.search(r'/spot/(\d+)', href)
        identifier = ('nikko-chuzenji' if spot_number[1] == '12' else 'nikko-official-' + spot_number[1]) if spot_number else 'nikko-official-' + hashlib.sha256(name.encode()).hexdigest()[:12]
        period_node = card.select_one('.post-situation')
        period = period_node.get_text(strip=True).replace('見頃予測：', '') if period_node else ''
        records.append({'place': {'id': identifier, 'name': name, 'season': 'momiji', 'kind': 'spot',
                          'lat': coords.get(name, (None, None))[0], 'lng': coords.get(name, (None, None))[1],
                          'metadata': {'prefecture': '栃木縣', 'region': 'kanto', 'region_name': '關東',
                          'name_ja': name, 'catalog_verified': True,
                          'official_url': 'https://www.nikko-kankou.org' + href,
                          'description': '日光市觀光協會紅葉觀測景點。草紅葉景點依官方分類收錄。'}},
                        'stage': stages[symbol], 'observed_on': observed.isoformat(),
                        'date_basis': basis, 'note': note,
                        'reported_on': reported.isoformat(), 'period': period})
    if len(records) < 5:
        raise ValueError('日光資料數量異常，停止匯入')
    return records

def fetch(source):
    req = Request(source['url'], headers={'User-Agent': 'SakuraMap/3.0 (official observation reader)'})
    context = ssl.create_default_context(cafile=certifi.where())
    with urlopen(req, timeout=25, context=context) as response:
        raw = response.read(4_000_001)
        if len(raw) > 4_000_000:
            raise ValueError('來源超過大小限制')
        return raw

def insert_observation(db, source, record, place_id, timestamp, raw_path):
    content = {k: record.get(k, '') for k in ('stage', 'observed_on', 'date_basis', 'note')}
    fingerprint = hashlib.sha256(json.dumps([source['id'], place_id, content], sort_keys=True,
                                            ensure_ascii=False).encode()).hexdigest()
    db.execute('INSERT OR IGNORE INTO observations '
               '(place_id,season,stage,observed_on,date_basis,source_id,source_url,fetched_at,raw_path,note,fingerprint) '
               'VALUES (?,?,?,?,?,?,?,?,?,?,?)',
               (place_id, source['season'], content['stage'], content['observed_on'], content['date_basis'],
                source['id'], source['url'], timestamp, raw_path, content['note'], fingerprint))

def collect_source(source, db_path=DEFAULT_DB, fetcher=fetch, raw_root=None):
    started = now().isoformat(timespec='seconds')
    raw_path = None
    try:
        raw = fetcher(source)
        digest = hashlib.sha256(raw).hexdigest()
        directory = (Path(raw_root) if raw_root else ROOT / 'data' / 'raw') / source['id']
        directory.mkdir(parents=True, exist_ok=True)
        suffix = '.csv' if source['format'] == 'jma-csv' else '.html'
        path = directory / (digest + suffix)
        if not path.exists():
            path.write_bytes(raw)
        raw_path = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
        if source['format'] == 'jma-csv':
            records = parse_history(raw, source)
        elif source['format'] == 'nikko':
            records = parse_nikko(raw.decode('utf-8'))
        else:
            records = parse_jma(raw.decode('utf-8'), source)
        with connect(db_path) as db:
            if source['format'] == 'jma-csv':
                db.executemany('INSERT INTO historical VALUES (?,?,?,?,?,?,?) ON CONFLICT(station,event,year) '
                               'DO UPDATE SET day=excluded.day,quality=excluded.quality,source_url=excluded.source_url', records)
            else:
                for record in records:
                    if source['format'] == 'nikko':
                        place = record['place']
                    else:
                        station = record['station']
                        lat, lng = STATIONS[station]
                        place = {'id': f"jma-{source['season']}-{station}", 'name': station + '・氣象廳標本木',
                                 'season': source['season'], 'kind': 'station', 'lat': lat, 'lng': lng,
                                 'metadata': {'station': station, 'coordinate_precision': 'city',
                                              'description': '標記為城市參考位置，不是標本木的精確位置。'}}
                    upsert_place(db, place)
                    insert_observation(db, source, record, place['id'], started, raw_path)
                    if source['format'] == 'nikko' and record['period']:
                        year = int(record['reported_on'][:4])
                        db.execute('INSERT INTO outlooks VALUES (?,?,?,?,?,?,?,?,?) '
                                   'ON CONFLICT(place_id,source_id,target_year) DO UPDATE SET '
                                   'period=excluded.period,issued_on=excluded.issued_on,fetched_at=excluded.fetched_at,raw_path=excluded.raw_path',
                                   (place['id'], source['id'], source['season'], year, record['period'],
                                    record['reported_on'], source['url'], started, raw_path))
            db.execute('INSERT INTO collection_runs(source_id,started_at,finished_at,status,records,raw_path) VALUES (?,?,?,?,?,?)',
                       (source['id'], started, now().isoformat(timespec='seconds'), 'ok', len(records), raw_path))
        return {'source': source['id'], 'status': 'ok', 'records': len(records)}
    except Exception as exc:
        with connect(db_path) as db:
            db.execute('INSERT INTO collection_runs(source_id,started_at,finished_at,status,records,error,raw_path) VALUES (?,?,?,?,?,?,?)',
                       (source['id'], started, now().isoformat(timespec='seconds'), 'error', 0,
                        f'{type(exc).__name__}: {exc}', raw_path))
        return {'source': source['id'], 'status': 'error', 'error': str(exc)}

def collect_all(db_path=DEFAULT_DB, force=False):
    initialize(db_path)
    results = []
    for source in SOURCES:
        with connect(db_path) as db:
            attempt = db.execute('SELECT finished_at,status FROM collection_runs WHERE source_id=? ORDER BY id DESC LIMIT 1', (source['id'],)).fetchone()
            last = db.execute("SELECT finished_at FROM collection_runs WHERE source_id=? AND status='ok' ORDER BY id DESC LIMIT 1",
                              (source['id'],)).fetchone()
        if not force and attempt and attempt['status'] == 'error' and now()-datetime.fromisoformat(attempt['finished_at']) < timedelta(minutes=30):
            continue
        if not force and last and now() - datetime.fromisoformat(last['finished_at']) < timedelta(hours=source['cadence_hours']):
            continue
        results.append(collect_source(source, db_path))
    return results

def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--once', action='store_true')
    group.add_argument('--watch', action='store_true')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    if args.once:
        results = collect_all(force=args.force)
        print(json.dumps(results, ensure_ascii=False, indent=2))
        raise SystemExit(1 if any(x['status'] == 'error' for x in results) else 0)
    while True:
        results = collect_all()
        if results:
            print(json.dumps(results, ensure_ascii=False), flush=True)
        time.sleep(300)

if __name__ == '__main__':
    main()
