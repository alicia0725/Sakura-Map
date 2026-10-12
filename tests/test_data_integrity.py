import csv
from datetime import date, datetime
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo
from sakura.collect import collect_source, parse_history, parse_jma, parse_nikko
from sakura.sources import SOURCES
from sakura.store import ROOT, connect, initialize, upsert_place
from sakura.service import decorate_observation, forecast_for, historical_reference, period_window
from app import create_app

TODAY = datetime(2026, 10, 5, 12, tzinfo=ZoneInfo('Asia/Tokyo'))
SOURCE = {s['id']: s for s in SOURCES}

class DataIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'test.sqlite3'
        self.raw = Path(self.temp.name) / 'raw'
        initialize(self.db)
        self.time = patch('sakura.collect.now', return_value=TODAY)
        self.time.start()

    def tearDown(self):
        self.time.stop()
        self.temp.cleanup()

    def test_legacy_values_are_never_observations(self):
        with connect(self.db) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM observations').fetchone()[0], 0)
        client = create_app(self.db).test_client()
        spots = client.get('/api/places?season=momiji').get_json()['places']
        self.assertTrue(spots)
        self.assertTrue(all(s['observation'] is None for s in spots))
        self.assertTrue(all(s['forecast']['kind'] in ('catalog_reference','unavailable') for s in spots))

    def test_jma_uses_page_year_not_collection_year(self):
        html = '<h1>かえでの紅葉日 (2025年-2026年)</h1><table><tr><td>東京</td><td>11月23日</td><td>0</td><td>0</td><td>-</td><td>///</td><td>///</td><td></td></tr></table>'
        rows = parse_jma(html, SOURCE['jma-maple-red'])
        self.assertEqual(rows[0]['observed_on'], '2025-11-23')
        self.assertEqual(len(rows), 1)

    def test_sakura_december_belongs_to_previous_calendar_year(self):
        html = '<h1>2026年のさくらの開花状況</h1><table><tr><th>那覇</th><td>12月30日</td></tr></table>'
        self.assertEqual(parse_jma(html,SOURCE['jma-sakura-open'])[0]['observed_on'],'2025-12-30')

    def test_autumn_january_belongs_to_next_calendar_year(self):
        rows=[['15','かえで紅葉'],['番号','地点名','2006','rm'],['476','佐賀','104','9']]
        output=io.StringIO();csv.writer(output).writerows(rows)
        self.assertEqual(parse_history(output.getvalue().encode('cp932'),SOURCE['jma-history-015'])[0][4],'2007-01-04')

    def test_future_observations_not_imported(self):
        html = '<h1>2026年のさくらの開花状況</h1><table><tr><th>東京</th><td>11月1日</td></tr></table>'
        self.assertEqual(parse_jma(html,SOURCE['jma-sakura-open']), [])

    def test_changed_jma_layout_fails_closed(self):
        with self.assertRaises(ValueError):
            parse_jma('<h1>2026年</h1><p>service error</p>', SOURCE['jma-sakura-open'])

    def test_historical_quality_and_missing_codes(self):
        rows = [['4','さくら開花'],['番号','地点名','2020','rm','2021','rm','2022','rm','2023','rm','2024','rm'],
                ['476','東京','320','8','321','9','0','0','319','4','323','7']]
        output = io.StringIO();csv.writer(output).writerows(rows)
        parsed = parse_history(output.getvalue().encode('cp932'),SOURCE['jma-history-004'])
        self.assertEqual([r[3] for r in parsed],[2020,2021,2024])

    def test_aging_uses_evidence_date_not_fetch_time(self):
        record = {'observed_on':'2025-11-23','stage':'red_leaves','date_basis':'observed',
                  'source_id':'jma-maple-red','fetched_at':'2026-10-05T12:00:00+09:00'}
        self.assertEqual(decorate_observation(record, date(2026,10,5))['freshness'],'stale')

    def test_nikko_real_page_explicit_dates_and_missing_coordinates(self):
        path = ROOT/'tests/fixtures/nikko-2026-10-05.html'
        rows = parse_nikko(path.read_text())
        self.assertGreaterEqual(len(rows),20)
        ryuzu = next(r for r in rows if r['place']['id']=='nikko-official-6')
        self.assertEqual(ryuzu['observed_on'],'2026-09-16')
        self.assertEqual(ryuzu['date_basis'],'observed')
        self.assertTrue(any(r['place']['lat'] is None for r in rows))

    def test_collection_is_idempotent_and_failure_preserves_observations(self):
        source = SOURCE['nikko-leaves']
        raw = (ROOT/'tests/fixtures/nikko-2026-10-05.html').read_bytes()
        first = collect_source(source,self.db,lambda _:raw,raw_root=self.raw)
        self.assertEqual(first['status'],'ok')
        collect_source(source,self.db,lambda _:raw,raw_root=self.raw)
        with connect(self.db) as db:
            before = db.execute('SELECT COUNT(*) FROM observations').fetchone()[0]
        self.assertEqual(before,first['records'])
        broken = collect_source(source,self.db,lambda _:b'<html>upstream error</html>',raw_root=self.raw)
        self.assertEqual(broken['status'],'error')
        with connect(self.db) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM observations').fetchone()[0],before)
            self.assertEqual(db.execute('SELECT status FROM collection_runs ORDER BY id DESC LIMIT 1').fetchone()[0],'error')

    def test_reference_excludes_target_year_and_species_changes(self):
        p={'id':'test-station','kind':'station','season':'sakura','name':'test','station':'東京'}
        with connect(self.db) as db:
            upsert_place(db,p)
            for year in range(2016,2027):
                db.execute('INSERT INTO historical VALUES (?,?,?,?,?,?,?)',('東京','sakura','full_bloom',year,f'{year}-04-02','9','https://www.data.jma.go.jp/'))
            ref=historical_reference(db,p,date(2026,4,3))
            self.assertNotIn(2026,ref['sample_years'])
            self.assertEqual(ref['start'],'2026-04-02')
            self.assertEqual(ref['kind'],'historical_reference')
            self.assertFalse(ref['weather_adjusted'])

    def test_official_outlook_does_not_leak_into_next_year(self):
        source=SOURCE['nikko-leaves']
        raw=(ROOT/'tests/fixtures/nikko-2026-10-05.html').read_bytes()
        collect_source(source,self.db,lambda _:raw,raw_root=self.raw)
        with connect(self.db) as db:
            place={'id':'nikko-official-6','kind':'spot','season':'momiji'}
            self.assertEqual(forecast_for(db,place,date(2026,10,10))['kind'],'official_outlook')
            self.assertEqual(forecast_for(db,place,date(2027,10,10))['kind'],'unavailable')

    def test_periods_and_api_validation(self):
        self.assertEqual(period_window('10月中旬～11月上旬',2026),(date(2026,10,11),date(2026,11,10)))
        self.assertEqual(period_window('2月下旬',2028),(date(2028,2,21),date(2028,2,29)))
        self.assertIsNone(period_window('見頃予測なし',2026))
        c=create_app(self.db).test_client()
        for url in ['/api/places?season=bad','/api/places?date=bad','/api/places?date=2026-02-30','/api/places?kind=bad']:
            self.assertEqual(c.get(url).status_code,400)
        self.assertEqual(c.get('/api/places/no-such-place/history').status_code,404)
        self.assertEqual(c.post('/api/spots/test/status',json={'status':'peak'}).status_code,404)

if __name__=='__main__':
    unittest.main()
