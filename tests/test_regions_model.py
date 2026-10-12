from datetime import date, datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo
from sakura.store import initialize, connect
from sakura.regions import stage_for, get_regions, region_of, ordinal, to_date
from sakura.weather import ingest, load_weather, collect_weather
from sakura.model import fit, scenario_dates, backtest, publish
from sakura.service import get_places
from app import create_app

NOW=datetime(2026,10,6,12,tzinfo=ZoneInfo('Asia/Tokyo'))

class RegionModelTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.db=self.root/'test.sqlite3';initialize(self.db)
    def tearDown(self):self.temp.cleanup()
    def history(self,station='東京',count=20,quality='9'):
        with connect(self.db) as db:
            for year in range(2026-count,2026):
                db.execute('INSERT INTO historical VALUES (?,?,?,?,?,?,?)',(station,'momiji','red_leaves',year,f'{year}-11-25',quality,'https://www.data.jma.go.jp/'))
    def test_autumn_rollover(self):
        self.assertEqual(to_date(2006,ordinal('2006-01-04',True)),'2007-01-04')
        self.assertEqual(to_date(2026,ordinal('2026-11-25',True)),'2026-11-25')

    def test_boundaries_and_selection_range(self):
        lo='2026-11-20';hi='2026-11-30'
        for day,expected in [('11-05','before'),('11-06','approaching'),('11-19','approaching'),('11-20','within'),('11-30','within'),('12-01','after')]:
            self.assertEqual(stage_for(date.fromisoformat('2026-'+day),lo,hi),expected)
        self.assertEqual(stage_for(date(2026,10,1),None,None),'unavailable')
    def test_same_species_threshold_and_okinawa(self):
        self.history(count=14)
        self.assertEqual(next(r for r in get_regions(self.db,'momiji',date(2026,11,25))['regions'] if r['id']=='kanto')['kind'],'unavailable')
        with connect(self.db) as db:
            db.execute('INSERT INTO historical VALUES (?,?,?,?,?,?,?)',('東京','momiji','red_leaves',2011,'2011-11-25','7','https://www.data.jma.go.jp/'))
        self.assertEqual(next(r for r in get_regions(self.db,'momiji',date(2026,11,25))['regions'] if r['id']=='kanto')['kind'],'unavailable')
        self.assertEqual(region_of({'station':'那覇'}),'okinawa')
        self.assertEqual(region_of({'prefecture':'沖縄県','region':'kyushu'}),'okinawa')
    def test_api_is_read_only_and_excludes_future_actuals(self):
        self.history()
        with connect(self.db) as db:
            db.execute('INSERT INTO historical VALUES (?,?,?,?,?,?,?)',('東京','momiji','red_leaves',2026,'2026-12-20','9','https://www.data.jma.go.jp/'))
        c=create_app(self.db).test_client()
        with patch('sakura.weather.fetch',side_effect=AssertionError('network on read')),patch('sakura.model.fit',side_effect=AssertionError('training on read')):
            regions=c.get('/api/regions?season=momiji&date=2026-11-25').get_json()['regions']
            r=next(r for r in regions if r['id']=='kanto');self.assertEqual(r['median'],'2026-11-25');self.assertNotIn(2026,r['cities'][0]['sample_years'])
            self.assertEqual(next(r for r in regions if r['id']=='okinawa')['stage'],'unavailable')
            a=c.get('/api/places?season=momiji&date=2026-09-01').get_json()['places']
            b=c.get('/api/places?season=momiji&date=2026-12-31').get_json()['places']
            self.assertEqual([(p['id'],p['observation']) for p in a],[(p['id'],p['observation']) for p in b])
        for url in ['/api/regions?season=bad','/api/regions?date=2026-02-30']:
            self.assertEqual(c.get(url).status_code,400)
        self.assertEqual(c.post('/api/regions').status_code,405)
    def test_forecast_snapshot_and_raw_provenance(self):
        raw=json.dumps({'daily':{'time':['2026-10-06','2026-10-07'],'temperature_2m_mean':[22,23]}}).encode()
        ingest('東京','forecast',None,None,self.db,lambda _:raw,self.root/'raw')
        newer=json.dumps({'daily':{'time':['2026-10-06'],'temperature_2m_mean':[20]}}).encode()
        ingest('東京','forecast',None,None,self.db,lambda _:newer,self.root/'raw')
        _,forecasts,metadata=load_weather(self.db)
        self.assertEqual(forecasts['東京'],{'2026-10-06':20})
        with connect(self.db) as db:
            r=db.execute('SELECT * FROM weather_fetches LIMIT 1').fetchone()
            self.assertEqual(r['provider'],'Open-Meteo');self.assertEqual(r['model'],'gfs_seamless');self.assertTrue(Path(r['raw_path']).exists());self.assertEqual(r['latitude'],35.681)
    def test_weather_failure_retains_success_and_official_records(self):
        self.history();raw=json.dumps({'daily':{'time':['2026-10-01'],'temperature_2m_mean':[22]}}).encode()
        ingest('東京','archive','2026-10-01','2026-10-01',self.db,lambda _:raw,self.root/'raw')
        with patch('sakura.weather.now',return_value=NOW):
            result=collect_weather(self.db,force=True,fetcher=lambda _:(_ for _ in ()).throw(OSError('offline')),pause=0)
        self.assertEqual(result['status'],'error');self.assertEqual(load_weather(self.db)[0]['東京']['2026-10-01'],22)
        with connect(self.db) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM historical').fetchone()[0],20)
    def test_stale_published_model_is_retained(self):
        self.history();cities={'東京':dict(station='東京',median='2026-11-25',start='2026-11-20',end='2026-11-30',sample_count=20,sample_years=list(range(2006,2026)),species='正規種目')}
        with connect(self.db) as db:
            db.execute('INSERT INTO model_runs(target_year,published_at,cutoff,model_version,sources,report,estimates) VALUES (?,?,?,?,?,?,?)',(2026,'2026-10-01T12:00:00+09:00','2026-10-01','test','{}',json.dumps({'enabled':True,'cases':120,'improvement':.15,'reason':'pass'}),json.dumps(cities)))
            db.execute('INSERT INTO weather_attempts(finished_at,status,records,error) VALUES (?,?,?,?)',('2026-10-06T12:00:00+09:00','error',0,'offline'))
        r=next(r for r in get_regions(self.db,'momiji',date(2026,11,25))['regions'] if r['id']=='kanto')
        self.assertTrue(r['stale']);self.assertEqual(r['kind'],'weather_model');self.assertEqual(r['start'],'2026-11-20')
    def test_future_weather_and_outcomes_cannot_leak(self):
        records={'東京':[]};archive={}
        for year in range(2001,2026):
            variation=(year%5)-2
            for month,days in ((8,31),(9,30),(10,31)):
                for day in range(1,days+1):archive[f'{year}-{month:02d}-{day:02d}']=20+variation
            records['東京'].append(dict(year=year,day=f'{year}-11-{25+variation:02d}',quality='9',source_url='jma'))
        model=fit(records,{'東京':archive},2021)
        cutoff=date(2021,10,15)
        a=scenario_dates(model,'東京',archive,{},cutoff)
        contaminated=dict(archive)
        for key in list(contaminated):
            if date.fromisoformat(key)>cutoff-timedelta(days=5):contaminated[key]=1000
        b=scenario_dates(model,'東京',contaminated,{},cutoff)
        self.assertEqual(a,b)
        changed={'東京':[dict(r,day=f"{r['year']}-12-31") if r['year']>=2021 else r for r in records['東京']]}
        self.assertEqual(fit(records,{'東京':archive},2021)['beta'],fit(changed,{'東京':archive},2021)['beta'])
        report=backtest(records,{'東京':archive},2025)
        self.assertEqual(len(report['folds']),5);self.assertFalse(report['enabled']);self.assertLess(report['cases'],100)
        for case in report['case_details']:self.assertLess(max(case['training_years']),case['year'])
    def test_gate_enables_only_with_enough_improved_cases(self):
        from sakura.sources import STATIONS
        records={};archives={}
        for station in list(STATIONS)[8:16]:
            history=[];weather={}
            for year in range(2001,2026):
                anomaly=(year%5)-2
                for month,days in ((8,31),(9,30),(10,31)):
                    for day in range(1,days+1):weather[f'{year}-{month:02d}-{day:02d}']=20+anomaly
                history.append(dict(year=year,day=f'{year}-11-{25+anomaly*2:02d}',quality='9',source_url='jma'))
            records[station]=history;archives[station]=weather
        report=backtest(records,archives,2025)
        self.assertGreaterEqual(report['cases'],100);self.assertGreaterEqual(report['improvement'],.10);self.assertTrue(report['enabled'])
        for history in records.values():
            for r in history:r['quality']='6'
        self.assertIsNone(fit(records,archives,2026))

    def test_publish_never_writes_official_tables(self):
        self.history()
        with connect(self.db) as db:before={t:[tuple(r) for r in db.execute(f'SELECT * FROM {t}')] for t in ('places','historical','observations','outlooks')}
        with patch('sakura.model.now',return_value=NOW):publish(self.db,self.root/'reports')
        with connect(self.db) as db:
            for t,rows in before.items():self.assertEqual([tuple(r) for r in db.execute(f'SELECT * FROM {t}')],rows)
        self.assertTrue((self.root/'reports/model-backtest.md').exists())

if __name__=='__main__':unittest.main()
