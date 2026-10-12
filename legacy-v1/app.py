# -*- coding: utf-8 -*-
"""
Sakura & Momiji Map - 日本即時櫻花與紅葉花況地圖
支援【春季賞櫻 🌸】與【秋季賞楓 🍁】雙季節模式切換
"""

import os
import json
import random
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.error import URLError
from flask import Flask, render_template, request, jsonify

app = Flask(__name__, static_folder='static', template_folder='templates')

DATA_PATH = os.path.join(os.path.dirname(__file__), 'data', 'spots.json')

def load_spots(season='momiji'):
    """載入景點資料庫（單一檔案整合春櫻與秋楓，零丟檔風險）"""
    if not os.path.exists(DATA_PATH):
        return []
    with open(DATA_PATH, 'r', encoding='utf-8') as f:
        all_spots = json.load(f)
    if season and season != 'all':
        matched = [s for s in all_spots if s.get('season') == season]
        return matched if matched else all_spots
    return all_spots

def save_spots(spots, season='momiji'):
    """持久化儲存景點資料"""
    if not os.path.exists(DATA_PATH):
        return
    with open(DATA_PATH, 'r', encoding='utf-8') as f:
        all_spots = json.load(f)
    # 更新特定季節景點
    updated_dict = {s['id']: s for s in spots}
    final_spots = []
    for s in all_spots:
        if s['id'] in updated_dict:
            final_spots.append(updated_dict[s['id']])
        else:
            final_spots.append(s)
    with open(DATA_PATH, 'w', encoding='utf-8') as f:
        json.dump(final_spots, f, ensure_ascii=False, indent=2)

# end of save

STATUS_MAP_SAKURA = {
    'budding': {'label': '花苞 (蕾)', 'color': '#4caf50', 'default_pct': 10},
    'early_bloom': {'label': '開花 (30%)', 'color': '#ffb7b2', 'default_pct': 30},
    'half_bloom': {'label': '五分咲 (50%)', 'color': '#ff85a2', 'default_pct': 50},
    'full_bloom': {'label': '滿開 (100%)', 'color': '#e91e63', 'default_pct': 100},
    'petal_fall': {'label': '櫻吹雪 (落花)', 'color': '#ba68c8', 'default_pct': 75}
}

STATUS_MAP_MOMIJI = {
    'budding': {'label': '青葉 (綠葉 10%)', 'color': '#4caf50', 'default_pct': 10},
    'early_bloom': {'label': '色づき始め (開始著色 30%)', 'color': '#e9c46a', 'default_pct': 30},
    'half_bloom': {'label': '見頃間近 (50%)', 'color': '#f4a261', 'default_pct': 50},
    'full_bloom': {'label': '見頃 (滿紅 100%)', 'color': '#d90429', 'default_pct': 100},
    'petal_fall': {'label': '落葉 (枯紅)', 'color': '#8d6e63', 'default_pct': 80}
}

@app.route('/')
def index():
    """首頁：渲染互動地圖介面，預設偵測當前月份切換季節（9-12月預設紅葉）"""
    current_month = datetime.now().month
    default_season = 'momiji' if current_month in [9, 10, 11, 12] else 'sakura'
    spots = load_spots(default_season)
    return render_template('index.html', initial_spots=spots, default_season=default_season)

@app.route('/api/spots', methods=['GET'])
def get_spots():
    """景點列表 API：支援季節、地區、花況/楓況狀態及關鍵字搜尋過濾"""
    season = request.args.get('season', 'momiji').strip().lower()
    spots = load_spots(season)
    region = request.args.get('region', '').strip().lower()
    status = request.args.get('status', '').strip().lower()
    keyword = request.args.get('q', '').strip().lower()

    filtered = spots
    if region and region != 'all':
        filtered = [s for s in filtered if s.get('region', '').lower() == region]

    if status and status != 'all':
        filtered = [s for s in filtered if s.get('status', '').lower() == status]

    if keyword:
        filtered = [
            s for s in filtered
            if keyword in s.get('name', '').lower()
            or keyword in s.get('name_ja', '').lower()
            or keyword in s.get('name_en', '').lower()
            or keyword in s.get('prefecture', '').lower()
            or keyword in s.get('address', '').lower()
            or keyword in s.get('tree_types', s.get('sakura_types', '')).lower()
        ]

    return jsonify({
        'success': True,
        'season': season,
        'count': len(filtered),
        'spots': filtered
    })

@app.route('/api/spots/<spot_id>', methods=['GET'])
def get_spot_detail(spot_id):
    """單一景點詳細資訊 API"""
    season = request.args.get('season', 'momiji').strip().lower()
    spots = load_spots(season)
    spot = next((s for s in spots if s.get('id') == spot_id), None)
    if not spot:
        # 跨季節搜尋
        other_season = 'sakura' if season == 'momiji' else 'momiji'
        spot = next((s for s in load_spots(other_season) if s.get('id') == spot_id), None)

    if not spot:
        return jsonify({'success': False, 'message': '找不到該景點'}), 404
    return jsonify({'success': True, 'spot': spot})

@app.route('/api/spots/<spot_id>/status', methods=['POST'])
def update_spot_status(spot_id):
    """即時花況/紅葉進度通報 API"""
    data = request.get_json() or {}
    season = data.get('season', 'momiji').strip().lower()
    new_status = data.get('status')
    note = data.get('note', '').strip()
    reporter = data.get('reporter', '熱心旅人').strip()

    status_map = STATUS_MAP_MOMIJI if season == 'momiji' else STATUS_MAP_SAKURA

    if not new_status or new_status not in status_map:
        return jsonify({'success': False, 'message': '無效的狀態代碼'}), 400

    spots = load_spots(season)
    target = next((s for s in spots if s.get('id') == spot_id), None)
    if not target:
        return jsonify({'success': False, 'message': '找不到該景點'}), 404

    status_meta = status_map[new_status]
    target['status'] = new_status
    target['status_label'] = status_meta['label']
    target['status_color'] = status_meta['color']
    target['bloom_percentage'] = status_meta['default_pct']
    target['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M')

    if 'updates_log' not in target:
        target['updates_log'] = []

    item_name = '紅葉進度' if season == 'momiji' else '花況'
    target['updates_log'].insert(0, {
        'reporter': reporter,
        'status_label': status_meta['label'],
        'note': note if note else f'更新了現場即時{item_name}',
        'timestamp': target['last_updated']
    })
    target['updates_log'] = target['updates_log'][:10]

    save_spots(spots, season)
    return jsonify({
        'success': True,
        'message': f"成功更新【{target['name']}】為 {status_meta['label']}！",
        'spot': target
    })

@app.route('/api/weather', methods=['GET'])
def get_weather():
    """即時天氣 API 代理 (Open-Meteo)"""
    try:
        lat = float(request.args.get('lat', 35.6852))
        lng = float(request.args.get('lng', 139.7100))
    except ValueError:
        return jsonify({'success': False, 'message': '經緯度參數錯誤'}), 400

    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lng}"
        f"&current=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m,wind_direction_10m"
        f"&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
        f"&timezone=Asia%2FTokyo"
    )

    weather_desc = {
        0: '晴朗無雲 ☀️', 1: '大致晴朗 🌤️', 2: '局部多雲 ⛅', 3: '陰天 ☁️',
        45: '晨霧瀰漫 🌫️', 48: '濃霧 🌫️', 51: '毛毛細雨 🌦️', 61: '小雨 🌧️',
        63: '中雨 🌧️', 65: '大雨 ⛈️', 71: '輕微飄雪 🌨️', 80: '局部陣雨 🌦️', 95: '雷陣雨 ⚡'
    }

    try:
        req = Request(url, headers={'User-Agent': 'SakuraMomijiMap/2.0'})
        with urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            current = data.get('current', {})
            daily = data.get('daily', {})
            code = current.get('weather_code', 0)

            forecast = []
            dates = daily.get('time', [])
            max_temps = daily.get('temperature_2m_max', [])
            min_temps = daily.get('temperature_2m_min', [])
            rain_probs = daily.get('precipitation_probability_max', [])
            codes = daily.get('weather_code', [])

            for i in range(min(4, len(dates))):
                forecast.append({
                    'date': dates[i],
                    'condition': weather_desc.get(codes[i] if i < len(codes) else 0, '晴時多雲 ⛅'),
                    'max_temp': round(max_temps[i]) if i < len(max_temps) else 20,
                    'min_temp': round(min_temps[i]) if i < len(min_temps) else 12,
                    'rain_prob': rain_probs[i] if i < len(rain_probs) else 10
                })

            return jsonify({
                'success': True,
                'source': 'live_open_meteo',
                'current': {
                    'temperature': round(current.get('temperature_2m', 18.5), 1),
                    'apparent_temperature': round(current.get('apparent_temperature', 18.5), 1),
                    'humidity': current.get('relative_humidity_2m', 55),
                    'wind_speed': current.get('wind_speed_10m', 2.8),
                    'wind_direction': current.get('wind_direction_10m', 45),
                    'condition': weather_desc.get(code, '舒適晴朗 🍁'),
                    'precipitation': current.get('precipitation', 0.0)
                },
                'forecast': forecast
            })
    except Exception:
        # 擬真降備
        random.seed(int(lat * 100 + lng * 100))
        temp = round(random.uniform(14.0, 21.0), 1)
        rain_prob = random.choice([5, 10, 15, 20])
        return jsonify({
            'success': True,
            'source': 'simulated_fallback',
            'current': {
                'temperature': temp,
                'apparent_temperature': temp,
                'humidity': random.randint(50, 65),
                'wind_speed': round(random.uniform(2.0, 3.8), 1),
                'wind_direction': 60,
                'condition': '秋高氣爽，微風宜人 🍁',
                'precipitation': 0.0
            },
            'forecast': [
                {'date': '今日', 'condition': '秋晴舒適 ☀️', 'max_temp': 20, 'min_temp': 11, 'rain_prob': rain_prob},
                {'date': '明日', 'condition': '晴時多雲 🌤️', 'max_temp': 21, 'min_temp': 12, 'rain_prob': 10},
                {'date': '後日', 'condition': '多雲轉涼 ☁️', 'max_temp': 18, 'min_temp': 9, 'rain_prob': 20}
            ]
        })

@app.route('/api/ai-analyze', methods=['POST'])
def ai_analyze():
    """AI 視覺辨識 Demo API (依季節支援櫻花與紅葉分析)"""
    data = request.get_json() or {}
    season = data.get('season', 'momiji')

    if season == 'momiji':
        return jsonify({
            'success': True,
            'season': 'momiji',
            'analysis': {
                'status': 'full_bloom',
                'status_label': '見頃 (滿紅巔峰期)',
                'bloom_percentage': 95,
                'confidence': 0.978,
                'detected_features': ['槭樹科山紅葉原生葉型', '葉綠素全面降解，花青素深紅覆蓋率 95%', '紅金雙色層次鮮明', '無明顯落葉枯褐邊緣'],
                'stage_evaluation': '目前處於全山滿紅的最佳觀賞期（見頃），楓紅飽和度達到年度最高峰！',
                'trip_recommendation': '絕佳朝聖時刻！大雪山與高海拔山谷此時層次最美，建議把握晴朗上午前往順光拍攝。'
            }
        })
    else:
        return jsonify({
            'success': True,
            'season': 'sakura',
            'analysis': {
                'status': 'full_bloom',
                'status_label': '滿開 (盛開期)',
                'bloom_percentage': 96,
                'confidence': 0.962,
                'detected_features': ['染井吉野櫻品種特徵', '淡粉花瓣覆蓋率 > 90%', '花蕊深粉色成熟度高', '枝條花簇飽滿密集'],
                'stage_evaluation': '目前處於花期頂峰（満開），約有 95% 以上花蕾均已綻放。',
                'trip_recommendation': '強烈推薦！未來 3~5 天為絕美觀賞與攝影期，若遇微風將開始欣賞櫻吹雪景觀。'
            }
        })

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """景點統計指標 API"""
    season = request.args.get('season', 'momiji').strip().lower()
    spots = load_spots(season)
    total = len(spots)
    status_counts = {}
    for s in spots:
        st = s.get('status', 'budding')
        status_counts[st] = status_counts.get(st, 0) + 1

    avg_bloom = round(sum(s.get('bloom_percentage', 0) for s in spots) / max(1, total), 1)

    return jsonify({
        'success': True,
        'season': season,
        'total_spots': total,
        'full_bloom_count': status_counts.get('full_bloom', 0),
        'half_bloom_count': status_counts.get('half_bloom', 0),
        'early_bloom_count': status_counts.get('early_bloom', 0),
        'budding_count': status_counts.get('budding', 0),
        'petal_fall_count': status_counts.get('petal_fall', 0),
        'avg_bloom_percentage': avg_bloom
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    print(f"🌸🍁 Sakura & Momiji Map 伺服器啟動於 http://127.0.0.1:{port}")
    app.run(host='0.0.0.0', port=port, debug=True)
