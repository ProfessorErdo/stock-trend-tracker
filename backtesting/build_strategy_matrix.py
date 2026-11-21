#!/usr/bin/env python3
"""跑 2x2 四宫格：1052/932 × 股息率/非股息率，并保存净值与逐年收益。"""
import os, sys, json
sys.path.insert(0, '.')
import pandas as pd
import config
SNAP='/tmp/bt_snapshot_20261120'
if os.path.exists(os.path.join(SNAP,'price')):
    config.PRICE_DATA_DIR=os.path.join(SNAP,'price')
    config.FINANCIAL_DATA_DIR=os.path.join(SNAP,'financial')
import universe_compare as uc
from backtest_engine import run_backtest
from performance import calculate_performance

OUT='../data/processed/backtesting/strategy_matrix_20261121'
os.makedirs(OUT,exist_ok=True); os.makedirs(os.path.join(OUT,'equity'),exist_ok=True)

specs=[
 dict(id='1052_nodiv', pool='union', filters=['pb'], pb=0.15, roe=0.70, rank='pe', div=False, first2015=False),
 dict(id='1052_div',   pool='union', filters=['pb'], pb=0.10, roe=0.65, rank='div', div=True,  first2015=True),
 dict(id='932_nodiv',  pool='legacy', filters=['pe'], pb=0.25, roe=0.75, rank='pb', div=False, first2015=True),
 dict(id='932_div',    pool='legacy', filters=['pb'], pb=0.10, roe=0.65, rank='div', div=True,  first2015=True),
]
summary=[]; annual_rows=[]
for s in specs:
    uc.set_pool(s['pool'])
    config.FILTER_INDICATORS=s['filters']
    config.PB_THRESHOLD=s['pb']; config.PE_THRESHOLD=0.25; config.PR_THRESHOLD=0.25
    config.ROE_THRESHOLD=s['roe']; config.WINSORIZE_ENABLED=True
    config.THRESHOLD_TRIM_RATIO=0.01; config.MAX_POSITIONS=5
    config.DIVIDEND_MODE='declared'
    r=run_backtest('2015-01-01','2026-11-06',frequency='annual',ranking_method=s['rank'],
                   filter_indicators=s['filters'], ignore_first_cutoff_new_stock=s['first2015'])
    p=calculate_performance(r['equity_curve'],r['cutoff_dates'],r['trade_records'])
    ar=p['annual_returns']
    eq=r['equity_curve'].copy(); eq.to_csv(os.path.join(OUT,'equity',f"{s['id']}.csv"),index=False)
    for _,row in ar.iterrows():
        annual_rows.append({'id':s['id'],'year':int(row['year']),'return':float(row['strategy_return'])})
    hold=None
    for x in r['holding_snapshots']:
        if len(x) and pd.Timestamp(x.rebalance_date.iloc[0])==pd.Timestamp('2026-05-06'):
            hold=x.copy()
    if hold is not None: hold.to_csv(os.path.join(OUT,f"holdings_{s['id']}_2026.csv"),index=False)
    summary.append(dict(
        id=s['id'], pool=s['pool'], dividend=s['div'],
        M1=float(p['annual_return']), M2=float(p['annual_return_since_first_investment']),
        sharpe=float(p['sharpe_ratio']), mdd=float(p['max_drawdown']),
        first_date=str(p['first_investment_date']),
        holdings=','.join(hold['stock_code'].astype(str).str.zfill(6)) if hold is not None else '',
    ))
    print(s['id'], 'M1',round(p['annual_return']*100,2),'M2',round(p['annual_return_since_first_investment']*100,2),
          'sharpe',round(p['sharpe_ratio'],3),'mdd',round(p['max_drawdown']*100,1), flush=True)

pd.DataFrame(summary).to_csv(os.path.join(OUT,'summary.csv'),index=False)
pd.DataFrame(annual_rows).to_csv(os.path.join(OUT,'annual.csv'),index=False)
print('saved',OUT)
