# 季見 Kisetsu · 日本櫻花／紅葉分區地圖

拖動日期，九個日本分區立即變色；點分區查全部景點。官方實況、官方見頃預測與介紹中的通常觀賞期同時顯示，日期拖動不改實況或排序。桌面左右並排，手機依序顯示日期、分區圖、景點。

## 本機啟動

Python 3.10+：

```bash
python3 -m pip install -r requirements.txt
python3 -m sakura.collect --once
python3 -m sakura.weather --once
python3 run.py
```

開啟 [本機版本](http://127.0.0.1:5001/)。`run.py` 同時啟動 Flask、官方蒐集 worker、氣象／模型 worker；Ctrl+C 停止三者。本輪沒有公開部署或系統排程。首次歷史氣象初始化要取得約25年城市日資料，需數分鐘，會遵守限流並保留中途成功快照。初始化25年是為了讓最近五個留出年度各自擁有最多20個訓練年；單次模型不使用超過20年。

- 僅開網頁：`python3 app.py`。
- 官方背景更新：`python3 -m sakura.collect --watch`。
- 氣象與模型背景更新：`python3 -m sakura.weather --watch`。每日更新，失敗一小時後重試。
- 強制氣象更新：`python3 -m sakura.weather --once --force`。
- 只重試最近失敗／尚未完成的氣象城市：`python3 -m sakura.weather --once --retry-failed`。
- 只使用已快取資料回測／發布：`python3 -m sakura.weather --once --offline`。
- 自訂 SQLite 路徑用網頁的 `SAKURA_DB`；worker 目前 CLI 使用專案預設資料庫。測試可直接傳入函式 `db_path`。

網頁 API 完全唯讀，不發送遠端蒐集請求、不訓練。電腦休眠或 worker 停止期間不會更新。來源取得時間不代替現場日期。

## 已保留的資料與操作

原106個景點 ID 全數保留，另有日光官方景點，合計129個景點：紅葉75、櫻花54。來源沿用日光市觀光協會、氣象廳事件表與累年CSV。官方未提供的景點實況保持未知，介紹日期不是今年官方預測。點景點卡展開介绍、位置、官方連結及觀測歷史。

列表固定以今天判斷近7日官方紀錄／較舊紀錄／尚無紀錄，組内按日期降序、名稱排序；拖旅行日期不重排，也不會關閉已展開的卡片。單一搜尋入口查全日本景點，點分區回到區域清單。景點卡右上角♡可收藏／取消收藏；清單上方「我的收藏」列出本季跨地區收藏，仍顯示最新官方資料。收藏、收藏檢視與所選季節存在此瀏覽器localStorage，重新開啟仍保留；不同裝置／瀏覽器不會同步，清除網站資料會移除收藏。九區是方位示意圖，不是行政邊界或道路地圖；沖繩獨立呈現。

## 模型與資料誠實性

紅葉預測目標為氣象廳城市標本木的轉紅日期，**不等於景點見頃或落葉紀錄**。8–10月均溫偏差的 ridge 校正與最近五年逐年回測已實作；至少100案例、MAE改善10%及五個完整年度才啟用。未達門檻前台使用歷年基準，同樹種至少15年、最多20年；不足則灰色。

紅葉 `rm=8/9` 正規種目可確認為いろはかえで；`6/7`只標明替代種目，沒有逐年完整種名，因此目前保留官方紀錄，但不參與新紅葉模型與分區基準。北海道可能因此灰色，景點仍完整列出。櫻花保留按正規／替代種目區分的滿開基準，尚無櫻花氣象模型。

氣象採 Open-Meteo ERA5 歷史服務與明確指定 GFS Seamless 的近期預報。使用實際回傳非空日期範圍，沒有資料的更遠日子用訓練年份氣候情境。範圍是情境與城市分布，**不是校準信心區間**。氣象快照、原始回應、模型結果不覆寫官方 observations、outlooks、historical。

回測只使用發布日以前的舊年紅葉結果及至少5日延遲的歷史氣象；未完成月份以訓練年份情境補齊，不使用未來實際天氣。沒有重播當時的短期預報。ERA5為目前修訂後重分析版本，不能宣稱完全還原當時資料版本。

閱讀 [回測報告](docs/model-backtest.md)、[逐案例與係數](docs/model-backtest.json)、[來源與模型說明](docs/architecture.md)、[驗收紀錄](docs/acceptance.md)。

## API

- `GET /api/regions?season=momiji&date=2026-11-25`：區域分段、上下界、中位日期、類型、有效城市／年份、來源、發布／截止日、模型版本、回測狀態、氣象失敗與過期標記。
- `GET /api/places?season=momiji&date=2026-10-20&kind=spot`（`/api/spots`別名保留）：景點實況與所選年度官方預測。`usual_period`獨立返回介紹參考。
- `GET /api/places/{id}/history`、`GET /api/sources`、`GET /api/health` 保留。

## 驗證

```bash
python3 -m unittest discover -s tests -v
node --check static/js/app.js
```

測試涵蓋官方年份與跨年、品質碼、去重、缺測、資料來源失敗、過期保留、模型隔離、回測防洩漏、分區邊界和唯讀API。介面操作使用真實本機頁面驗收，預覽在 `docs/preview-regions-desktop.png` 與 `docs/preview-regions-mobile.png`。

歷史版本保存在 `legacy-v1/`。舊 Leaflet 與 Natural Earth 底圖資產保留，但新主介面不載入地圖圖磚或外部字體。
