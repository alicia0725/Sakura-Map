from contextlib import contextmanager
from pathlib import Path
import json
import sqlite3

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / 'data' / 'observations.sqlite3'

@contextmanager
def connect(path=DEFAULT_DB):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=20)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def initialize(path=DEFAULT_DB):
    with connect(path) as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS places (
          id TEXT PRIMARY KEY, season TEXT NOT NULL, kind TEXT NOT NULL,
          name TEXT NOT NULL, lat REAL, lng REAL, metadata TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS observations (
          id INTEGER PRIMARY KEY, place_id TEXT NOT NULL REFERENCES places(id),
          season TEXT NOT NULL, stage TEXT NOT NULL, observed_on TEXT NOT NULL,
          date_basis TEXT NOT NULL, source_id TEXT NOT NULL, source_url TEXT NOT NULL,
          fetched_at TEXT NOT NULL, raw_path TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
          fingerprint TEXT NOT NULL UNIQUE);
        CREATE INDEX IF NOT EXISTS observation_latest ON observations(place_id, observed_on DESC);
        CREATE TABLE IF NOT EXISTS historical (
          station TEXT NOT NULL, season TEXT NOT NULL, event TEXT NOT NULL,
          year INTEGER NOT NULL, day TEXT NOT NULL, quality TEXT NOT NULL,
          source_url TEXT NOT NULL, PRIMARY KEY(station, event, year));
        CREATE TABLE IF NOT EXISTS outlooks (
          place_id TEXT NOT NULL REFERENCES places(id), source_id TEXT NOT NULL,
          season TEXT NOT NULL, target_year INTEGER NOT NULL, period TEXT NOT NULL,
          issued_on TEXT NOT NULL, source_url TEXT NOT NULL, fetched_at TEXT NOT NULL,
          raw_path TEXT NOT NULL, PRIMARY KEY(place_id, source_id, target_year));
        CREATE TABLE IF NOT EXISTS collection_runs (
          id INTEGER PRIMARY KEY, source_id TEXT NOT NULL, started_at TEXT NOT NULL,
          finished_at TEXT NOT NULL, status TEXT NOT NULL, records INTEGER NOT NULL,
          error TEXT, raw_path TEXT);
        CREATE TABLE IF NOT EXISTS weather_fetches (
          id INTEGER PRIMARY KEY, station TEXT NOT NULL, kind TEXT NOT NULL,
          provider TEXT NOT NULL, model TEXT NOT NULL, latitude REAL, longitude REAL,
          fetched_at TEXT NOT NULL, start_date TEXT, end_date TEXT, url TEXT NOT NULL,
          raw_path TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS weather_station ON weather_fetches(station,kind,id);
        CREATE TABLE IF NOT EXISTS weather_attempts (
          id INTEGER PRIMARY KEY, finished_at TEXT NOT NULL, status TEXT NOT NULL,
          records INTEGER NOT NULL, error TEXT);
        CREATE TABLE IF NOT EXISTS model_runs (
          id INTEGER PRIMARY KEY, target_year INTEGER NOT NULL, published_at TEXT NOT NULL,
          cutoff TEXT NOT NULL, model_version TEXT NOT NULL, sources TEXT NOT NULL,
          report TEXT NOT NULL, estimates TEXT NOT NULL);
        ''')
        # Import only identity and descriptive fields. Legacy statuses/photos are not observations.
        for spot in json.loads((ROOT / 'data' / 'spots.json').read_text()):
            fields = {k: spot[k] for k in ('name_ja', 'name_en', 'prefecture', 'region', 'region_name',
                      'address', 'description', 'tree_types', 'sakura_types', 'best_period') if k in spot}
            fields['catalog_verified'] = False
            db.execute('INSERT OR IGNORE INTO places VALUES (?,?,?,?,?,?,?)',
                       (spot['id'], spot['season'], 'spot', spot['name'], spot['lat'], spot['lng'],
                        json.dumps(fields, ensure_ascii=False)))

def upsert_place(db, place):
    db.execute('INSERT INTO places VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET '
               'name=excluded.name,lat=excluded.lat,lng=excluded.lng,metadata=excluded.metadata',
               (place['id'], place['season'], place['kind'], place['name'], place.get('lat'),
                place.get('lng'), json.dumps(place.get('metadata', {}), ensure_ascii=False)))

def place_dict(row):
    item = dict(row)
    item.update(json.loads(item.pop('metadata')))
    return item
