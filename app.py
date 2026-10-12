"""Sakura Map v3. Read APIs never trigger remote collection or fabricate observations."""
import os
from datetime import date
from flask import Flask, jsonify, render_template, request
from sakura.collect import now
from sakura.service import get_places, decorate_observation, source_status
from sakura.regions import get_regions
from sakura.store import DEFAULT_DB, initialize, connect


def create_app(db_path=None):
    app = Flask(__name__)
    app.config['DATABASE'] = db_path or os.environ.get('SAKURA_DB', str(DEFAULT_DB))
    initialize(app.config['DATABASE'])

    @app.get('/')
    def index():
        return render_template('index.html', today=now().date().isoformat(),
                               default_season='momiji' if now().month >= 7 else 'sakura')

    @app.get('/api/places')
    @app.get('/api/spots')
    def places():
        season = request.args.get('season', 'momiji')
        if season not in ('sakura', 'momiji'):
            return jsonify(error='無效的季節'), 400
        try:
            target = date.fromisoformat(request.args.get('date', now().date().isoformat()))
            if not 1953 <= target.year <= now().year+2:
                raise ValueError()
        except ValueError:
            return jsonify(error='日期不在支援範圍'), 400
        items = get_places(app.config['DATABASE'], season, target)
        kind = request.args.get('kind', 'all')
        if kind not in ('all', 'spot', 'station'):
            return jsonify(error='無效的圖層'), 400
        if kind != 'all':
            items = [p for p in items if p['kind'] == kind]
        query = request.args.get('q', '').casefold()
        if query:
            items = [p for p in items if query in ' '.join(str(p.get(k,'')) for k in
                     ('name','name_ja','name_en','prefecture','region_name')).casefold()]
        return jsonify(places=items, today=now().date().isoformat(), date=target.isoformat(), season=season)

    @app.get('/api/regions')
    def regions():
        season = request.args.get('season', 'momiji')
        if season not in ('sakura', 'momiji'):
            return jsonify(error='無效的季節'), 400
        try:
            target = date.fromisoformat(request.args.get('date', now().date().isoformat()))
            if not 1953 <= target.year <= now().year+2:
                raise ValueError()
        except ValueError:
            return jsonify(error='日期不在支援範圍'), 400
        return jsonify(get_regions(app.config['DATABASE'], season, target))

    @app.get('/api/places/<place_id>/history')
    def history(place_id):
        with connect(app.config['DATABASE']) as db:
            if not db.execute('SELECT 1 FROM places WHERE id=?', (place_id,)).fetchone():
                return jsonify(error='找不到景點'), 404
            rows = db.execute('SELECT * FROM observations WHERE place_id=? ORDER BY observed_on DESC,id DESC LIMIT 30',
                              (place_id,)).fetchall()
        return jsonify(observations=[decorate_observation(r) for r in rows])

    @app.get('/api/sources')
    def sources():
        return jsonify(sources=source_status(app.config['DATABASE']))

    @app.get('/api/health')
    def health():
        with connect(app.config['DATABASE']) as db:
            observations = db.execute('SELECT COUNT(*) FROM observations').fetchone()[0]
            history = db.execute('SELECT COUNT(*) FROM historical').fetchone()[0]
            latest = db.execute('SELECT finished_at FROM collection_runs ORDER BY id DESC LIMIT 1').fetchone()
        return jsonify(status='ok', observations=observations, historical_records=history,
                       last_collection_at=latest['finished_at'] if latest else None)

    return app

app = create_app()
if __name__ == '__main__':
    app.run(host='127.0.0.1', port=int(os.environ.get('PORT', 5001)), debug=False)
