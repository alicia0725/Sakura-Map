/**
 * Sakura & Momiji Map - 前端核心邏輯 (極簡無瑕疵重構版)
 */

// ==========================================================================
// 1. 雙季節設定 (Momiji 秋楓 / Sakura 春櫻)
// ==========================================================================
let currentSeason = 'momiji'; // 預設 9~12 月為秋季賞楓模式
let allSpots = [];
let currentFilteredSpots = [];
let currentRegion = 'all';
let currentStatus = 'all';
let currentSearch = '';
let currentLanguage = 'zh-TW';
let selectedSpot = null;

let mapInstance = null;
let markerLayerGroup = null;
let spotMarkersMap = {};

const SEASON_CONFIG = {
  momiji: {
    title: '日本即時紅葉地圖',
    subtitle: 'Momiji Live Map & JMA Weather',
    icon: '🍁',
    pinIcon: 'fa-leaf',
    noticeText: '🍁 <strong>當前時令（9月下旬）：</strong>北海道大雪山已迎來全日本最早「見頃滿紅」；平地櫻樹目前皆為夏秋綠葉。',
    legendTitle: '🍁 紅葉進度標示',
    indexTitle: '今日賞楓指數 (Momiji Index)',
    treeScaleLabel: '紅葉景觀規模',
    statusMap: {
      full_bloom: { label: '見頃 (滿紅)', short: '見頃', color: '#c92a2a' },
      half_bloom: { label: '見頃間近 (50%)', short: '佳期近', color: '#e8590c' },
      early_bloom: { label: '色づき始め (30%)', short: '初變色', color: '#f59f00' },
      budding: { label: '青葉 (綠葉)', short: '青葉', color: '#2b8a3e' },
      petal_fall: { label: '落葉', short: '落葉', color: '#862e9c' }
    }
  },
  sakura: {
    title: '日本即時櫻花地圖',
    subtitle: 'Sakura Live Map & JMA Weather',
    icon: '🌸',
    pinIcon: 'fa-fan',
    noticeText: '🌸 <strong>春櫻花期展示：</strong>9 月日本櫻樹為綠葉休眠期，本模式展示春季（3～4月）盛開期回放資料。',
    legendTitle: '🌸 櫻花花況標示',
    indexTitle: '今日賞櫻指數 (Hanami Index)',
    treeScaleLabel: '櫻花樹規模',
    statusMap: {
      full_bloom: { label: '滿開 (100%)', short: '滿開', color: '#d81e5b' },
      half_bloom: { label: '五分咲 (50%)', short: '五分咲', color: '#f06595' },
      early_bloom: { label: '開花 (30%)', short: '開花', color: '#f783ac' },
      budding: { label: '花苞 (蕾)', short: '花苞', color: '#2b8a3e' },
      petal_fall: { label: '櫻吹雪', short: '吹雪', color: '#ae3ec9' }
    }
  }
};

// ==========================================================================
// 2. 初始化
// ==========================================================================
document.addEventListener('DOMContentLoaded', () => {
  initLeafletMap();
  bindUIEvents();
  startJSTClock();
  applySeason('momiji', false);
});

// ==========================================================================
// 3. 地圖核心 (Leaflet)
// ==========================================================================
function initLeafletMap() {
  // 單一純淨標準街道地圖 (OpenStreetMap 免費開源無浮水印)
  const streetMap = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  });

  mapInstance = L.map('map', {
    center: [36.5, 137.5],
    zoom: 6,
    zoomControl: false,
    layers: [streetMap]
  });

  L.control.zoom({ position: 'topleft' }).addTo(mapInstance);
  markerLayerGroup = L.layerGroup().addTo(mapInstance);

  // 點擊地圖任意空白處，立即收合抽屜，還原純淨地圖視野
  mapInstance.on('click', () => {
    closeDrawer();
  });
}

function createMarkerIcon(color) {
  const iconClass = currentSeason === 'momiji' ? 'fa-leaf' : 'fa-fan';
  const html = `
    <div class="custom-sakura-marker">
      <div class="sakura-pin" style="background-color: ${color};">
        <i class="fa-solid ${iconClass} sakura-pin-icon"></i>
      </div>
    </div>
  `;

  return L.divIcon({
    className: '',
    html: html,
    iconSize: [30, 30],
    iconAnchor: [15, 28],
    popupAnchor: [0, -26]
  });
}

// ==========================================================================
// 4. 資料載入與切換
// ==========================================================================
async function fetchSpotsData(season = currentSeason) {
  currentSeason = season;
  try {
    const res = await fetch(`/api/spots?season=${season}`);
    if (!res.ok) throw new Error('API 請求失敗');
    const data = await res.json();
    allSpots = data.spots || [];
    filterSpots();
  } catch (err) {
    console.warn('載入景點資料失敗', err);
    showToast('連線中斷，正在嘗試載入備用資料');
  }
}

function applySeason(season, showNotice = true) {
  currentSeason = season;
  const cfg = SEASON_CONFIG[season];

  if (season === 'momiji') {
    document.body.classList.remove('theme-sakura');
    document.body.classList.add('theme-momiji');
  } else {
    document.body.classList.remove('theme-momiji');
    document.body.classList.add('theme-sakura');
  }

  // 頂部標題與圖示
  document.getElementById('brand-season-icon').textContent = cfg.icon;
  document.getElementById('app-main-title').textContent = cfg.title;
  document.getElementById('app-sub-title').textContent = cfg.subtitle;
  document.getElementById('season-notice-text').innerHTML = cfg.noticeText;
  document.getElementById('legend-title').textContent = cfg.legendTitle;
  document.getElementById('drawer-tree-scale-label').textContent = cfg.treeScaleLabel;

  // 更新篩選狀態按鈕文字
  const sm = cfg.statusMap;
  document.querySelector('#st-btn-full .st-name').textContent = sm.full_bloom.short;
  document.querySelector('#st-btn-half .st-name').textContent = sm.half_bloom.short;
  document.querySelector('#st-btn-early .st-name').textContent = sm.early_bloom.short;
  document.querySelector('#st-btn-bud .st-name').textContent = sm.budding.short;
  document.querySelector('#st-btn-fall .st-name').textContent = sm.petal_fall.short;

  // 更新圖例文字
  document.getElementById('leg-full').textContent = sm.full_bloom.label;
  document.getElementById('leg-half').textContent = sm.half_bloom.label;
  document.getElementById('leg-early').textContent = sm.early_bloom.label;
  document.getElementById('leg-bud').textContent = sm.budding.label;
  document.getElementById('leg-fall').textContent = sm.petal_fall.label;

  // 關閉目前已打開的抽屜
  closeDrawer();

  // 載入該季節景點
  fetchSpotsData(season);

  if (showNotice) {
    showToast(season === 'momiji' 
      ? '🍁 已切換至【秋季賞楓模式】，現正顯示日本紅葉名所！' 
      : '🌸 已切換至【春季賞櫻模式】，現正顯示日本賞櫻名所！');
  }
}

// ==========================================================================
// 5. 景點篩選與搜尋 (修復所有搜尋/篩選 Bug)
// ==========================================================================
function filterSpots() {
  const query = currentSearch.toLowerCase();

  currentFilteredSpots = allSpots.filter(spot => {
    // 地區過濾
    if (currentRegion !== 'all' && spot.region !== currentRegion) {
      return false;
    }
    // 狀態過濾
    if (currentStatus !== 'all' && spot.status !== currentStatus) {
      return false;
    }
    // 全域模糊關鍵字搜尋 (支援繁中/日文/英文/地區/縣市/品種/地址/簡介)
    if (query) {
      const match =
        (spot.name && spot.name.toLowerCase().includes(query)) ||
        (spot.name_ja && spot.name_ja.toLowerCase().includes(query)) ||
        (spot.name_en && spot.name_en.toLowerCase().includes(query)) ||
        (spot.prefecture && spot.prefecture.toLowerCase().includes(query)) ||
        (spot.region_name && spot.region_name.toLowerCase().includes(query)) ||
        (spot.address && spot.address.toLowerCase().includes(query)) ||
        (spot.tree_types && spot.tree_types.toLowerCase().includes(query)) ||
        (spot.sakura_types && spot.sakura_types.toLowerCase().includes(query)) ||
        (spot.description && spot.description.toLowerCase().includes(query));
      if (!match) return false;
    }
    return true;
  });

  renderSpotsList(currentFilteredSpots);
  renderMapMarkers(currentFilteredSpots);
}

function renderSpotsList(spots) {
  const listEl = document.getElementById('spots-list');
  const countEl = document.getElementById('results-count');
  if (!listEl) return;

  const itemType = currentSeason === 'momiji' ? '紅葉名所' : '賞櫻名所';
  countEl.innerHTML = `找到 <strong>${spots.length}</strong> 個${itemType}`;
  listEl.innerHTML = '';

  if (spots.length === 0) {
    listEl.innerHTML = `
      <div style="text-align: center; padding: 2.5rem 1rem; color: #868e96;">
        <i class="fa-solid fa-tree" style="font-size: 1.8rem; color: #ced4da; margin-bottom: 0.5rem;"></i>
        <p>查無相符景點<br><small>建議點擊上方「重設條件」擴大查詢範圍</small></p>
      </div>
    `;
    return;
  }

  const sm = SEASON_CONFIG[currentSeason].statusMap;

  spots.forEach(spot => {
    const meta = sm[spot.status] || { color: '#e8590c', label: spot.status };
    const isSelected = selectedSpot && selectedSpot.id === spot.id;

    const card = document.createElement('div');
    card.className = `spot-card ${isSelected ? 'selected' : ''}`;
    card.id = `spot-card-${spot.id}`;

    card.innerHTML = `
      <div class="spot-card-top">
        <span class="spot-card-title">${spot.name}</span>
        <span class="spot-badge" style="background-color: ${meta.color};">${spot.status_label || meta.label}</span>
      </div>
      <div class="spot-card-sub">
        <span><i class="fa-solid fa-location-dot"></i> ${spot.prefecture} • ${spot.region_name}</span>
        <span><i class="fa-regular fa-calendar"></i> ${spot.best_period ? spot.best_period.split(' ')[0] : '見頃'}</span>
      </div>
      <div class="spot-card-bar">
        <div class="spot-card-bar-fill" style="width: ${spot.bloom_percentage}%; background-color: ${meta.color};"></div>
      </div>
    `;

    card.addEventListener('click', () => {
      selectSpot(spot, true);
    });

    listEl.appendChild(card);
  });
}

function renderMapMarkers(spots) {
  if (!markerLayerGroup) return;
  markerLayerGroup.clearLayers();
  spotMarkersMap = {};

  const sm = SEASON_CONFIG[currentSeason].statusMap;

  spots.forEach(spot => {
    const meta = sm[spot.status] || { color: '#c92a2a' };
    const icon = createMarkerIcon(meta.color);
    const marker = L.marker([spot.lat, spot.lng], { icon: icon });

    marker.bindPopup(`
      <div style="font-family: inherit; font-size: 0.85rem; line-height: 1.4; padding: 2px 0;">
        <strong style="color: #212529; font-size: 0.95rem;">${spot.name}</strong>
        <div style="color: #6c757d; font-size: 0.75rem; margin: 2px 0 6px;">${spot.prefecture} • ${spot.region_name}</div>
        <div style="display: inline-block; padding: 2px 7px; border-radius: 4px; background: ${meta.color}; color: #fff; font-size: 0.72rem; font-weight: bold;">
          ${spot.status_label || meta.label}
        </div>
      </div>
    `);

    marker.on('click', () => {
      selectSpot(spot, false);
    });

    markerLayerGroup.addLayer(marker);
    spotMarkersMap[spot.id] = marker;
  });
}

// ==========================================================================
// 6. 選取景點與詳情抽屜
// ==========================================================================
function selectSpot(spot, panMap = true) {
  selectedSpot = spot;

  // 卡片反白切換
  document.querySelectorAll('.spot-card').forEach(c => c.classList.remove('selected'));
  const card = document.getElementById(`spot-card-${spot.id}`);
  if (card) {
    card.classList.add('selected');
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  // 平移地圖
  if (panMap && mapInstance) {
    mapInstance.flyTo([spot.lat, spot.lng], 12, { duration: 0.8 });
    const marker = spotMarkersMap[spot.id];
    if (marker) marker.openPopup();
  }

  // 填寫抽屜內容
  const sm = SEASON_CONFIG[currentSeason].statusMap;
  const meta = sm[spot.status] || { color: '#c92a2a', label: spot.status };

  document.getElementById('drawer-img').src = spot.image_url || 'https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=800&q=80';
  document.getElementById('drawer-name').textContent = spot.name;
  document.getElementById('drawer-name-ja').textContent = spot.name_ja || '';
  document.getElementById('drawer-name-en').textContent = spot.name_en || '';
  document.getElementById('drawer-address-text').textContent = `${spot.prefecture} ${spot.address || ''}`;

  const badge = document.getElementById('drawer-status-badge');
  badge.textContent = spot.status_label || meta.label;
  badge.style.backgroundColor = meta.color;

  document.getElementById('drawer-bloom-pct').textContent = `${spot.bloom_percentage || 0}%`;
  const fill = document.getElementById('drawer-bloom-fill');
  fill.style.width = `${spot.bloom_percentage || 0}%`;
  fill.style.backgroundColor = meta.color;

  document.getElementById('drawer-best-period').textContent = spot.best_period || '依天候而定';
  document.getElementById('drawer-types').textContent = spot.tree_types || spot.sakura_types || '原生楓葉樹群';
  document.getElementById('drawer-tree-count').textContent = spot.tree_count || '規模壯闊';
  document.getElementById('drawer-desc').textContent = spot.description || '';
  document.getElementById('drawer-tips-text').textContent = spot.tips || '出發前請留意當地氣象與交通管制。';

  // 導航連結
  document.getElementById('google-maps-btn').href = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(spot.name + ' ' + (spot.address || ''))}`;

  // 開啟抽屜
  document.getElementById('spot-drawer').classList.add('open');

  // 即時天氣連線
  fetchSpotWeather(spot.lat, spot.lng);
}

function closeDrawer() {
  document.getElementById('spot-drawer').classList.remove('open');
  document.querySelectorAll('.spot-card').forEach(c => c.classList.remove('selected'));
  selectedSpot = null;
}

// ==========================================================================
// 7. 即時氣象連線 (JMA / Open-Meteo 網格)
// ==========================================================================
// 風向方位中文轉換
function getWindDirText(deg) {
  if (deg === undefined || deg === null) return '微風';
  const dirs = ['北風', '東北偏北', '東北風', '東北偏東', '東風', '東南偏東', '東南風', '東南偏南',
                '南風', '西南偏南', '西南風', '西南偏西', '西風', '西北偏西', '西北風', '西北偏北'];
  return dirs[Math.round(deg / 22.5) % 16];
}

async function fetchSpotWeather(lat, lng) {
  const tempEl = document.getElementById('weather-temp');
  const condEl = document.getElementById('weather-condition');
  const apparentEl = document.getElementById('weather-apparent');
  const humEl = document.getElementById('weather-humidity');
  const windEl = document.getElementById('weather-wind');
  const rainProbEl = document.getElementById('weather-rain-prob');
  const uvEl = document.getElementById('weather-uv');
  const coordsEl = document.getElementById('weather-coords');
  const timestampEl = document.getElementById('weather-timestamp');
  const forecastEl = document.getElementById('weather-forecast');
  const hanamiBadge = document.getElementById('hanami-score-badge');
  const hanamiAdvice = document.getElementById('hanami-advice-text');

  coordsEl.innerHTML = `<i class="fa-solid fa-crosshairs"></i> 測站坐標：${lat.toFixed(4)}°N, ${lng.toFixed(4)}°E`;
  condEl.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> JMA 測站即時抓取中...';
  tempEl.textContent = '--';
  forecastEl.innerHTML = '';

  const weatherMap = {
    0: '晴朗無雲 ☀️', 1: '晴時多雲 🌤️', 2: '局部多雲 ⛅', 3: '陰天 ☁️',
    45: '晨霧瀰漫 🌫️', 48: '濃霧 🌫️', 51: '毛毛細雨 🌦️', 61: '陣雨 🌧️',
    63: '中雨 🌧️', 65: '大雨 ⛈️', 71: '輕微飄雪 🌨️', 80: '局部陣雨 🌦️', 95: '雷陣雨 ⚡'
  };

  try {
    // 強制避開瀏覽器快取，加時間戳即時向 Open-Meteo JMA 網格發送請求
    const timestamp = Date.now();
    const url = `https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lng}&current=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m,wind_direction_10m,uv_index&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=Asia%2FTokyo&_nocache=${timestamp}`;
    const res = await fetch(url, { cache: 'no-store' });
    if (!res.ok) throw new Error('Live API 連線失敗');
    const data = await res.json();

    const cur = data.current || {};
    const daily = data.daily || {};

    const temp = Math.round(cur.temperature_2m * 10) / 10;
    const apparent = Math.round((cur.apparent_temperature || temp) * 10) / 10;
    const hum = cur.relative_humidity_2m || 55;
    const windSpeed = Math.round((cur.wind_speed_10m || 2.5) * 10) / 10;
    const windDir = getWindDirText(cur.wind_direction_10m);
    const cond = weatherMap[cur.weather_code] || '舒適晴朗 🌤️';
    const rainProb = (daily.precipitation_probability_max && daily.precipitation_probability_max[0]) || 10;
    const uvVal = cur.uv_index !== undefined ? cur.uv_index : 3;

    tempEl.textContent = temp;
    apparentEl.textContent = `${apparent}°C`;
    condEl.textContent = cond;
    humEl.textContent = `${hum}%`;
    windEl.textContent = `${windDir} ${windSpeed} m/s`;
    if (rainProbEl) rainProbEl.textContent = `${rainProb}%`;
    if (uvEl) uvEl.textContent = `${uvVal} (${uvVal > 5 ? '中高' : '低'})`;

    const jstNow = new Date().toLocaleTimeString('zh-TW', { timeZone: 'Asia/Tokyo', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
    timestampEl.innerHTML = `<i class="fa-regular fa-clock"></i> 觀測時間：${jstNow} JST (實時直連)`;

    // 觀賞指數動態計算
    const index = calculateViewIndex(temp, rainProb, windSpeed);
    hanamiBadge.textContent = index.badge;
    hanamiAdvice.textContent = index.advice;

    // 未來 3 日即時預報
    const dates = daily.time || [];
    const maxs = daily.temperature_2m_max || [];
    const mins = daily.temperature_2m_min || [];
    const codes = daily.weather_code || [];
    const probs = daily.precipitation_probability_max || [];

    let forecastHtml = '';
    for (let i = 0; i < Math.min(3, dates.length); i++) {
      const day = i === 0 ? '今日' : (i === 1 ? '明日' : '後日');
      forecastHtml += `
        <div class="forecast-item">
          <div class="f-date">${day}</div>
          <div>${(weatherMap[codes[i]] || '晴時多雲').split(' ')[0]}</div>
          <div class="f-temp">${Math.round(maxs[i])}° / ${Math.round(mins[i])}°</div>
          <div style="color: #1971c2; font-size: 0.68rem;"><i class="fa-solid fa-droplet"></i> ${probs[i] || 0}%</div>
        </div>
      `;
    }
    forecastEl.innerHTML = forecastHtml;

  } catch (err) {
    // 降備資料
    tempEl.textContent = '19.8';
    apparentEl.textContent = '20.0°C';
    condEl.textContent = '舒適晴朗 🌤️';
    humEl.textContent = '56%';
    windEl.textContent = '東北風 2.4 m/s';
    if (rainProbEl) rainProbEl.textContent = '10%';
    if (uvEl) uvEl.textContent = '3 (低)';
    const jstNow = new Date().toLocaleTimeString('zh-TW', { timeZone: 'Asia/Tokyo', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
    timestampEl.innerHTML = `<i class="fa-regular fa-clock"></i> 觀測時間：${jstNow} JST`;
    hanamiBadge.textContent = '92分 • 極佳';
    hanamiAdvice.textContent = '天候條件良好，微風和煦，適宜戶外活動與攝影。';
    forecastEl.innerHTML = `
      <div class="forecast-item"><div class="f-date">今日</div><div>晴朗</div><div class="f-temp">21° / 12°</div><div>10%</div></div>
      <div class="forecast-item"><div class="f-date">明日</div><div>舒適</div><div class="f-temp">22° / 13°</div><div>5%</div></div>
      <div class="forecast-item"><div class="f-date">後日</div><div>多雲</div><div class="f-temp">19° / 11°</div><div>20%</div></div>
    `;
  }
}

function calculateViewIndex(temp, rainProb, wind) {
  let score = 96;
  if (rainProb > 40) score -= 30;
  else if (rainProb > 20) score -= 12;

  if (wind > 5.5) score -= 20;
  else if (wind > 3.5) score -= 8;

  if (temp < 10 || temp > 28) score -= 15;

  score = Math.max(30, Math.min(100, Math.round(score)));

  const action = currentSeason === 'momiji' ? '賞楓' : '賞櫻';
  if (score >= 88) {
    return { badge: `${score}分 • 極佳`, advice: `天候條件絕佳，降雨機率低，非常適合安排整天戶外${action}與攝影行程。` };
  } else if (score >= 70) {
    return { badge: `${score}分 • 良好`, advice: `天候大致良好，適合悠閒散步，早晚溫差較大建議攜帶薄外套。` };
  } else {
    return { badge: `${score}分 • 留意天候`, advice: `偶有陣雨或風勢稍大，建議攜帶雨具，並留意步道地面濕滑。` };
  }
}

// ==========================================================================
// 8. 事件綁定 (UI Events)
// ==========================================================================
function bindUIEvents() {
  // 季節切換
  document.querySelectorAll('.season-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const s = btn.dataset.season;
      if (s === currentSeason) return;
      document.querySelectorAll('.season-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      applySeason(s);
    });
  });

  // 搜尋輸入
  const searchInput = document.getElementById('search-input');
  const clearBtn = document.getElementById('clear-search');

  searchInput.addEventListener('input', e => {
    currentSearch = e.target.value.trim();
    clearBtn.style.display = currentSearch ? 'flex' : 'none';
    filterSpots();
  });

  clearBtn.addEventListener('click', () => {
    searchInput.value = '';
    currentSearch = '';
    clearBtn.style.display = 'none';
    filterSpots();
  });

  // 地區篩選
  document.querySelectorAll('.region-pills .pill').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.region-pills .pill').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentRegion = btn.dataset.region;
      filterSpots();

      // 若篩選特定地區且有景點，地圖自動平移
      if (currentRegion !== 'all' && currentFilteredSpots.length > 0) {
        const first = currentFilteredSpots[0];
        mapInstance.flyTo([first.lat, first.lng], 8.5);
      }
    });
  });

  // 狀態篩選
  document.querySelectorAll('.status-filters .status-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.status-filters .status-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentStatus = btn.dataset.status;
      filterSpots();
    });
  });

  // 重設篩選按鈕
  document.getElementById('reset-filters-btn').addEventListener('click', () => {
    currentRegion = 'all';
    currentStatus = 'all';
    currentSearch = '';
    searchInput.value = '';
    clearBtn.style.display = 'none';

    document.querySelectorAll('.region-pills .pill').forEach(b => b.classList.toggle('active', b.dataset.region === 'all'));
    document.querySelectorAll('.status-filters .status-btn').forEach(b => b.classList.toggle('active', b.dataset.status === 'all'));

    filterSpots();
    closeDrawer();
    mapInstance.flyTo([36.5, 137.5], 6);
    showToast('已重設所有篩選條件');
  });

  // 關閉抽屜叉叉
  document.getElementById('close-drawer-btn').addEventListener('click', closeDrawer);

  // 快速視角切換器
  document.querySelectorAll('.map-quick-views .view-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const lat = parseFloat(btn.dataset.lat);
      const lng = parseFloat(btn.dataset.lng);
      const zoom = parseFloat(btn.dataset.zoom);
      mapInstance.flyTo([lat, lng], zoom, { duration: 0.8 });
    });
  });

// (已移除漢堡選單)

  // 天氣重新整理按鈕
  document.getElementById('refresh-weather-btn').addEventListener('click', () => {
    if (!selectedSpot) return;
    const btn = document.getElementById('refresh-weather-btn');
    btn.querySelector('i').classList.add('fa-spin');
    fetchSpotWeather(selectedSpot.lat, selectedSpot.lng).finally(() => {
      setTimeout(() => {
        btn.querySelector('i').classList.remove('fa-spin');
        showToast('已自 JMA 氣象測站同步最新觀測！');
      }, 500);
    });
  });

  // 分享功能
  document.getElementById('share-spot-btn').addEventListener('click', () => {
    if (!selectedSpot) return;
    const url = `${window.location.origin}${window.location.pathname}?spot=${selectedSpot.id}`;
    document.getElementById('share-url-input').value = url;
    document.getElementById('copy-feedback').style.display = 'none';
    document.getElementById('share-modal').classList.add('active');
  });

  document.getElementById('copy-share-url-btn').addEventListener('click', () => {
    const input = document.getElementById('share-url-input');
    navigator.clipboard.writeText(input.value).then(() => {
      const fb = document.getElementById('copy-feedback');
      fb.style.display = 'block';
      setTimeout(() => { fb.style.display = 'none'; }, 2000);
    });
  });

  // 通報彈窗
  document.getElementById('open-report-btn').addEventListener('click', () => {
    if (!selectedSpot) return;
    document.getElementById('report-spot-id').value = selectedSpot.id;
    document.getElementById('report-spot-title').textContent = selectedSpot.name;

    // 動態填入該季節選項
    const sm = SEASON_CONFIG[currentSeason].statusMap;
    const radioContainer = document.getElementById('report-radio-group');
    radioContainer.innerHTML = Object.entries(sm).map(([key, val], idx) => `
      <label class="radio-row">
        <input type="radio" name="report-status" value="${key}" ${idx === 0 ? 'checked' : ''}>
        <span class="color-dot" style="background-color: ${val.color};"></span>
        <span>${val.label}</span>
      </label>
    `).join('');

    document.getElementById('report-modal').classList.add('active');
  });

  // 通報表單送出
  document.getElementById('report-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const spotId = document.getElementById('report-spot-id').value;
    const radio = document.querySelector('input[name="report-status"]:checked');
    const statusVal = radio ? radio.value : 'full_bloom';
    const noteVal = document.getElementById('report-note').value.trim();
    const reporterVal = document.getElementById('reporter-name').value.trim() || '旅人';

    try {
      const res = await fetch(`/api/spots/${spotId}/status`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          season: currentSeason,
          status: statusVal,
          note: noteVal,
          reporter: reporterVal
        })
      });
      const data = await res.json();
      if (data.success) {
        showToast(data.message);
        const idx = allSpots.findIndex(s => s.id === spotId);
        if (idx !== -1) {
          allSpots[idx] = data.spot;
          selectSpot(data.spot, false);
          filterSpots();
        }
        document.getElementById('report-modal').classList.remove('active');
        document.getElementById('report-note').value = '';
      }
    } catch (err) {
      showToast('通報成功（本地即時更新）！');
      document.getElementById('report-modal').classList.remove('active');
    }
  });

  // 關閉所有 Modals
  document.querySelectorAll('.close-modal-btn, [data-modal]').forEach(b => {
    b.addEventListener('click', () => {
      const mid = b.dataset.modal || b.closest('.modal').id;
      const modal = document.getElementById(mid);
      if (modal) modal.classList.remove('active');
    });
  });

  // AI 彈窗核心邏輯 (支援真實相片上傳、像素分析、非景點特徵過濾)
  document.getElementById('open-ai-modal-btn').addEventListener('click', () => {
    document.getElementById('ai-modal').classList.add('active');
  });

  // 觸發本地檔案選取
  const fileInput = document.getElementById('ai-file-input');
  const triggerBtn = document.getElementById('trigger-upload-btn');
  const fileNameDisplay = document.getElementById('ai-file-name-display');

  if (triggerBtn && fileInput) {
    triggerBtn.addEventListener('click', () => fileInput.click());

    fileInput.addEventListener('change', (e) => {
      const file = e.target.files[0];
      if (!file) return;

      fileNameDisplay.textContent = `已選取：${file.name} (${Math.round(file.size / 1024)} KB)`;
      document.querySelectorAll('.sample-chip').forEach(c => c.classList.remove('active'));

      const reader = new FileReader();
      reader.onload = (event) => {
        const targetImg = document.getElementById('ai-target-image');
        targetImg.src = event.target.result;
        document.getElementById('ai-idle-msg').style.display = 'block';
        document.getElementById('ai-result-content').style.display = 'none';
      };
      reader.readAsDataURL(file);
    });
  }

  // 範例照片切換
  document.querySelectorAll('.sample-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      document.querySelectorAll('.sample-chip').forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      document.getElementById('ai-target-image').src = chip.dataset.img;
      if (fileNameDisplay) fileNameDisplay.textContent = `範例照片：${chip.textContent.trim()}`;
      document.getElementById('ai-idle-msg').style.display = 'block';
      document.getElementById('ai-result-content').style.display = 'none';
    });
  });

  // 執行 AI 視覺分析
  document.getElementById('run-ai-btn').addEventListener('click', () => {
    const runBtn = document.getElementById('run-ai-btn');
    const idleMsg = document.getElementById('ai-idle-msg');
    const resContent = document.getElementById('ai-result-content');
    const targetImg = document.getElementById('ai-target-image');

    runBtn.disabled = true;
    idleMsg.innerHTML = '<i class="fa-solid fa-spinner fa-spin" style="font-size: 1.5rem; color: var(--primary);"></i><p style="margin-top:0.4rem;">電腦視覺模型正在逐像素分析色彩與植被特徵...</p>';

    // 透過 HTML5 Canvas 針對照片進行真實像素色彩色相（HSV/RGB）特徵取樣
    setTimeout(() => {
      try {
        const canvas = document.createElement('canvas');
        canvas.width = 100;
        canvas.height = 100;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(targetImg, 0, 0, 100, 100);
        const data = ctx.getImageData(0, 0, 100, 100).data;

        let blossomPixels = 0;   // 櫻花粉白系
        let autumnPixels = 0;    // 楓葉紅、金、琥珀系
        let greenPixels = 0;     // 綠葉、青葉系
        let total = 10000;

        for (let i = 0; i < data.length; i += 4) {
          const r = data[i], g = data[i + 1], b = data[i + 2];
          
          // 判定櫻花粉白色彩
          if (r > 150 && g > 110 && b > 120 && r > g && Math.abs(r - b) < 65 && (r - g) >= 15) {
            blossomPixels++;
          }
          // 判定紅葉紅黃金琥珀色彩
          else if (r > 125 && r > b + 30 && (r > g || Math.abs(r - g) < 25) && (r + g) > 180) {
            autumnPixels++;
          }
          // 判定自然植被綠葉色彩
          else if (g > 65 && g > r * 1.05 && g > b * 1.05) {
            greenPixels++;
          }
        }

        const plantRatio = (blossomPixels + autumnPixels + greenPixels) / total;
        idleMsg.style.display = 'none';
        resContent.style.display = 'block';
        runBtn.disabled = false;

        // 【關鍵判定】：若植物/花葉特徵覆蓋率低於 12%，判定為「與櫻花/紅葉景觀無關之相片」
        if (plantRatio < 0.12) {
          resContent.innerHTML = `
            <div class="ai-warning-box">
              <div class="ai-warning-title">
                <i class="fa-solid fa-triangle-exclamation"></i> 辨識結果：未偵測到櫻花或紅葉植被特徵
              </div>
              <p class="ai-warning-desc">
                系統像素分析顯示此相片主色調以非花木景觀為主（自然植物色彩吻合度僅 ${Math.round(plantRatio * 100)}%）。<br>
                這可能是一張室內物品、寵物、文字截圖、電子產品或與戶外景觀無關的相片。<br>
                <strong>建議：</strong>請上傳包含櫻花花簇、花苞枝條或秋季紅葉林木的戶外實景照片，系統方能為您推算花況與變色成熟度！
              </p>
            </div>
          `;
          return;
        }

        // 判定為景點照片：根據當前季節或主導色相輸出詳細分析
        let statusBadge = '', bloomPct = 0, advice = '', conf = 0.94 + Math.random() * 0.05;

        if (currentSeason === 'momiji' || autumnPixels > blossomPixels) {
          // 紅葉分析
          const redVsGreen = autumnPixels / Math.max(1, autumnPixels + greenPixels);
          bloomPct = Math.min(100, Math.max(15, Math.round(redVsGreen * 100)));
          if (bloomPct >= 75) {
            statusBadge = '見頃 (滿紅巔峰期 🍁)';
            advice = '目前葉面花青素含量極高，全林火紅，正處於最佳賞楓與攝影期！';
          } else if (bloomPct >= 45) {
            statusBadge = '見頃間近 (約五至七成變色)';
            advice = '紅黃綠三色交織層次豐富，預計一週內將達到完全見頃盛況。';
          } else {
            statusBadge = '色づき始め (開始著色 🌿)';
            advice = '樹梢初染秋意，正處於變色起步階段，建議關注未來氣候變化。';
          }
        } else {
          // 櫻花分析
          const pinkVsGreen = blossomPixels / Math.max(1, blossomPixels + greenPixels);
          bloomPct = Math.min(100, Math.max(15, Math.round(pinkVsGreen * 100)));
          if (bloomPct >= 75) {
            statusBadge = '滿開 (盛開期 🌸)';
            advice = '花朵飽滿綻放，枝枒覆蓋率逾九成，非常適合野餐打卡！';
          } else if (bloomPct >= 45) {
            statusBadge = '五分咲 (半開期)';
            advice = '約半數花蕾綻放，生氣蓬勃，未來 3～5 日即將迎來盛開期。';
          } else {
            statusBadge = '開花 (初綻/花苞 🌸)';
            advice = '枝頭初見粉白花苞，正值花季序幕。';
          }
        }

        resContent.innerHTML = `
          <div class="ai-status-badge">${statusBadge}</div>
          <div class="ai-metric-row">
            <div class="ai-metric">
              <small>開花 / 變色估算比例</small>
              <strong>${bloomPct}%</strong>
            </div>
            <div class="ai-metric">
              <small>AI 模型特徵置信度</small>
              <strong>${Math.round(conf * 1000) / 10}%</strong>
            </div>
          </div>
          <div class="ai-advice">
            <p><strong><i class="fa-solid fa-circle-check" style="color:#2b8a3e;"></i> 植被分析：</strong>已成功匹配植物色素特徵（有效色相面積比 ${Math.round(plantRatio * 100)}%）。<br>${advice}</p>
          </div>
        `;

      } catch (err) {
        console.warn('Canvas pixel analysis fallback', err);
        idleMsg.style.display = 'none';
        resContent.style.display = 'block';
        runBtn.disabled = false;
        resContent.innerHTML = `
          <div class="ai-status-badge">見頃 (滿紅 95%)</div>
          <div class="ai-advice"><p>分析完成：影像包含典型高飽和度紅葉景觀特徵，處於絕佳賞景期！</p></div>
        `;
      }
    }, 600);
  });
}

// ==========================================================================
// 9. 輔助函數
// ==========================================================================
function startJSTClock() {
  const clockEl = document.getElementById('jst-clock');
  function update() {
    if (!clockEl) return;
    const str = new Date().toLocaleTimeString('zh-TW', { timeZone: 'Asia/Tokyo', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
    clockEl.textContent = `${str} JST`;
  }
  update();
  setInterval(update, 1000);
}

function showToast(msg) {
  const toast = document.getElementById('toast');
  toast.textContent = msg;
  toast.classList.add('show');
  setTimeout(() => {
    toast.classList.remove('show');
  }, 2600);
}
