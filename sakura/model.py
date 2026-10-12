"""Auditable ridge correction of JMA red-leaf city dates; never writes official tables."""
from datetime import date, datetime, timedelta
from statistics import mean, median
import hashlib
import json
import math
from .collect import now
from .regions import ordinal, to_date, quantile, MODEL_VERSION
from .sources import STATIONS, BASE
from .store import DEFAULT_DB, ROOT, connect, initialize
from .weather import load_weather

ALPHA=10.0
ISSUES=('10-01','10-15','11-01')

def monthly(weather, year):
    values=[]
    for month, days in ((8,31),(9,30),(10,31)):
        temps=[weather.get(f'{year}-{month:02d}-{d:02d}') for d in range(1,days+1)]
        if any(t is None for t in temps):return None
        values.append(mean(temps))
    return values

def solve(matrix, vector):
    """Partial pivot elimination for the four-parameter ridge normal equation."""
    rows=[list(row)+[value] for row,value in zip(matrix,vector)]
    n=len(rows)
    for col in range(n):
        pivot=max(range(col,n),key=lambda i:abs(rows[i][col]))
        rows[col],rows[pivot]=rows[pivot],rows[col]
        if abs(rows[col][col])<1e-12:raise ValueError('singular ridge system')
        scale=rows[col][col];rows[col]=[v/scale for v in rows[col]]
        for i in range(n):
            if i!=col:
                scale=rows[i][col];rows[i]=[a-scale*b for a,b in zip(rows[i],rows[col])]
    return [row[-1] for row in rows]

def fit(records, archives, target_year):
    stations={}; xs=[];ys=[]
    for station, history in records.items():
        if station not in archives or station not in STATIONS:continue
        candidates=[r for r in history if target_year-20<=r['year']<target_year]
        if not candidates:continue
        group=int(candidates[-1]['quality'])>=8
        # 6/7 can refer to several substitute species: no unverified same-species assumption.
        if not group:continue
        candidates=[r for r in candidates if (int(r['quality'])>=8)==group]
        pairs=[(r,monthly(archives[station],r['year'])) for r in candidates]
        pairs=[(r,t) for r,t in pairs if t is not None]
        if len(pairs)<15:continue
        norms=[mean([t[j] for _,t in pairs]) for j in range(3)]
        days=[ordinal(r['day'],True) for r,_ in pairs];base=median(days)
        for r,temps in pairs:
            xs.append([temps[j]-norms[j] for j in range(3)])
            ys.append(ordinal(r['day'],True)-base)
        stations[station]=dict(baseline=base,norms=norms,years=[r['year'] for r,_ in pairs],
            days=days,species='正規種目' if group else '替代種目',source_url=pairs[-1][0]['source_url'])
    if not xs:return None
    scales=[max(.1,math.sqrt(mean([x[j]**2 for x in xs]))) for j in range(3)]
    design=[[1]+[x[j]/scales[j] for j in range(3)] for x in xs]
    matrix=[[sum(x[i]*x[j] for x in design)+(ALPHA if i==j and i>0 else 0) for j in range(4)] for i in range(4)]
    beta=solve(matrix,[sum(x[i]*y for x,y in zip(design,ys)) for i in range(4)])
    return dict(stations=stations,beta=beta,scales=scales,alpha=ALPHA,training_cases=len(xs),training_max_year=target_year-1)

def scenario_dates(model, station, archive, forecast, cutoff):
    info=model['stations'][station];year=cutoff.year;values=[]
    # ERA5 is treated as available only five days behind issue date, even in retrospective evaluation.
    actual_end=cutoff-timedelta(days=5)
    for scenario_year in info['years']:
        months=[]
        for month, days in ((8,31),(9,30),(10,31)):
            temps=[]
            for d in range(1,days+1):
                current=date(year,month,d);key=current.isoformat()
                value=archive.get(key) if current<=actual_end else None
                if value is None:value=forecast.get(key)
                if value is None:value=archive.get(f'{scenario_year}-{month:02d}-{d:02d}')
                if value is None:return []
                temps.append(value)
            months.append(mean(temps))
        x=[1]+[(months[j]-info['norms'][j])/model['scales'][j] for j in range(3)]
        pred=info['baseline']+sum(a*b for a,b in zip(x,model['beta']))
        # Autumn dates may extend into the following January; bound extreme extrapolation to Aug–June.
        values.append(min(547,max(213,pred)))
    return values

def backtest(records, archives, latest_complete_year):
    cases=[];folds=[];models={}
    for year in range(latest_complete_year-4,latest_complete_year+1):
        model=fit(records,archives,year)
        if not model:continue
        models[year]=dict(beta=model['beta'],scales=model['scales'],training_cases=model['training_cases'],training_max_year=model['training_max_year'])
        for issue in ISSUES:
            cutoff=date.fromisoformat(f'{year}-{issue}')
            for station,info in model['stations'].items():
                truth=next((r for r in records[station] if r['year']==year and (int(r['quality'])>=8)==(info['species']=='正規種目')),None)
                if truth is None:continue
                archive=archives[station]
                # Require all days deemed available; no climate fill for missing historical observations.
                actual_end=cutoff-timedelta(days=5)
                expected=[date(year,8,1)+timedelta(days=i) for i in range(92)]
                if any(d<=actual_end and d.isoformat() not in archive for d in expected):continue
                # No current/future forecast snapshots in backtest. Unknown weather uses training-year scenarios only.
                predictions=scenario_dates(model,station,archive,{},cutoff)
                if not predictions:continue
                observed=ordinal(truth['day'],True);pred=median(predictions)
                cases.append(dict(station=station,year=year,issue=cutoff.isoformat(),actual_weather_through=actual_end.isoformat(),
                    training_years=info['years'],observed=truth['day'],baseline=to_date(year,info['baseline']),
                    predicted=to_date(year,pred),model_error=abs(pred-observed),baseline_error=abs(info['baseline']-observed)))
        subset=[c for c in cases if c['year']==year]
        if subset:folds.append(dict(year=year,cases=len(subset),model_mae=mean(c['model_error'] for c in subset),baseline_mae=mean(c['baseline_error'] for c in subset)))
    model_mae=mean(c['model_error'] for c in cases) if cases else None
    baseline_mae=mean(c['baseline_error'] for c in cases) if cases else None
    improvement=(baseline_mae-model_mae)/baseline_mae if baseline_mae else 0
    enabled=len(cases)>=100 and improvement>=.10 and len(folds)==5
    failures=[]
    if len(cases)<100:failures.append(f'有效案例{len(cases)}個，未達100個')
    if len(folds)<5:failures.append('不足五個完整年度')
    if improvement<.10:failures.append(f'平均誤差改善{improvement:.1%}，未達10%')
    return dict(version=MODEL_VERSION,enabled=enabled,cases=len(cases),model_mae=model_mae,baseline_mae=baseline_mae,
        improvement=improvement,reason='通過100案例與10%改善門檻' if enabled else '；'.join(failures)+'，前台使用歷年基準',
        folds=folds,fold_models=models,case_details=cases,
        evaluation='逐年向前留出最近五個完整年度，發布日10/1、10/15、11/1；訓練只取目標年前最多20年同樹種、至少15年。固定alpha=10，不以測試年度調參。',
        availability='以ERA5至少5日延遲模擬可取得的歷史天氣；未完成資料只用訓練年份氣候情境，未使用發布日以後的實際天氣。回測未引入當時的短期預報。ERA5為目前重分析版本，非原始發布版本重播。',
        range='情境分布10–90百分位，不是校準信心區間；區域再匯總城市分布。')

def render_report(report, metadata, path):
    def fmt(value):return f'{value:.2f}' if value is not None else '—'
    lines=['# 紅葉氣象模型回測報告','',f"產生時間：{report['published_at']}；資料截止：{report['cutoff']}。",'',
        f"**前台：{'天氣校正模型' if report['enabled'] else '歷年基準'}**。{report['reason']}。",'',
        f"有效案例 {report['cases']}；基準 MAE {fmt(report['baseline_mae'])} 天；模型 MAE {fmt(report['model_mae'])} 天；改善 {report['improvement']:.1%}。",'',
        '| 留出年度 | 案例 | 歷年基準 MAE（天） | 氣象模型 MAE（天） |','|---|---:|---:|---:|']
    lines += [f"| {r['year']} | {r['cases']} | {fmt(r['baseline_mae'])} | {fmt(r['model_mae'])} |" for r in report['folds']]
    lines += ['',report['evaluation'],'',report['availability'],'',report['range'],'',
        '完整逐案例結果、每折係數及訓練年清單見 `model-backtest.json`。採8–10月均溫對各站訓練期正常值的偏差，以站點紅葉中位日期為基準， pooled ridge 校正（標準化特徵、alpha=10、截距不懲罰）。此門檻只評估城市日期，不驗證景點見頃。',
        '',f'氣象已收錄城市：{len(metadata)}。供應商 Open-Meteo；歷史模型 ERA5；近期預報 GFS Seamless。原始回應、請求網址、座標、取得時間保存在 SQLite weather_fetches 與 data/raw/open-meteo。',
        '', '來源：[氣象廳紅葉歷年 CSV](https://www.data.jma.go.jp/sakura/data/ruinenchi/015.csv)、[Open-Meteo 歷史服務](https://open-meteo.com/en/docs/historical-weather-api)、[Open-Meteo 預報服務](https://open-meteo.com/en/docs)。',
        '', '限制：城市中心氣象格點與標本木不完全重合；紅葉僅採8/9正規種目（いろはかえで）；6/7替代種目未能逐年確認樹種，暂不參與模型與分區基準；不含海拔模型。歷史氣象是修訂後重分析，資料可用日採保守延遲假設，沒有當時的預報版本。官方歷年CSV並非每年發布快照；訓練只用完整舊年，未用留出年紅葉結果。']
    path.write_text('\n'.join(lines)+'\n')

def publish(db_path=DEFAULT_DB, report_dir=None):
    initialize(db_path);cutoff=now().date();archives,forecasts,metadata=load_weather(db_path)
    with connect(db_path) as db:
        rows=[dict(r) for r in db.execute("SELECT * FROM historical WHERE event='red_leaves' ORDER BY station,year")]
        # Re-publish only after new inputs or day changes; prevent training on page reads and worker loops.
        signatures=[tuple(r) for r in db.execute('SELECT station,kind,MAX(id) FROM weather_fetches GROUP BY station,kind')]
        digest=hashlib.sha256(json.dumps([MODEL_VERSION,'regular-species-autumn-rollover',cutoff.isoformat(),rows,signatures],sort_keys=True).encode()).hexdigest()
        previous=db.execute('SELECT * FROM model_runs ORDER BY id DESC LIMIT 1').fetchone()
        if previous and json.loads(previous['report']).get('input_digest')==digest:return json.loads(previous['report'])
    records={}
    for row in rows:records.setdefault(row['station'],[]).append(row)
    report=backtest(records,archives,cutoff.year-1)
    report.update(published_at=now().isoformat(timespec='seconds'),cutoff=cutoff.isoformat(),input_digest=digest)
    model=fit(records,archives,cutoff.year);estimates={}
    if model:
        report['fit']={k:v for k,v in model.items() if k!='stations'}
        for station,info in model['stations'].items():
            meta=metadata.get(station,{}).get('forecast',{})
            forecast=forecasts.get(station,{}) if meta and now()-datetime.fromisoformat(meta['fetched_at'])<timedelta(hours=48) else {}
            predictions=scenario_dates(model,station,archives[station],forecast,cutoff)
            if not predictions:continue
            estimates[station]=dict(station=station,median=to_date(cutoff.year,median(predictions)),
                start=to_date(cutoff.year,quantile(predictions,.1)),end=to_date(cutoff.year,quantile(predictions,.9)),
                sample_count=len(info['years']),sample_years=info['years'],species=info['species'],source_url=info['source_url'],
                scenario_years=info['years'],weather=metadata.get(station,{}),
                forecast_through=max(forecast) if forecast else None,climate_scenario=True)
    directory=report_dir or ROOT/'docs';directory.mkdir(parents=True,exist_ok=True)
    (directory/'model-backtest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    render_report(report,metadata,directory/'model-backtest.md')
    with connect(db_path) as db:
        weather=db.execute('SELECT * FROM weather_attempts ORDER BY id DESC LIMIT 1').fetchone()
        # A failed refresh must not replace a previously successful live model with a new partial run.
        if previous and json.loads(previous['report']).get('enabled') and weather and weather['status']=='error':
            return report
        db.execute('INSERT INTO model_runs(target_year,published_at,cutoff,model_version,sources,report,estimates) VALUES (?,?,?,?,?,?,?)',
            (cutoff.year,report['published_at'],cutoff.isoformat(),MODEL_VERSION,json.dumps(metadata,ensure_ascii=False),json.dumps(report,ensure_ascii=False),json.dumps(estimates,ensure_ascii=False)))
    print(f"model {report['cases']} cases: {report['reason']}",flush=True)
    return report
