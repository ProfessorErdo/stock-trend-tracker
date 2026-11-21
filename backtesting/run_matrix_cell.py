#!/usr/bin/env python3
"""按统一 spec 列表跑一个 2x2 格子，保存 M3b 与逐年收益。"""
import argparse, os, sys, time
sys.path.insert(0,'.')
import pandas as pd
import config
SNAP='/tmp/bt_snapshot_20261120'
if os.path.exists(os.path.join(SNAP,'price')):
    config.PRICE_DATA_DIR=os.path.join(SNAP,'price')
    config.FINANCIAL_DATA_DIR=os.path.join(SNAP,'financial')
import universe_compare as uc
from backtest_engine import run_backtest
from performance import calculate_performance

p=argparse.ArgumentParser()
p.add_argument('--pool',choices=['union','legacy'],required=True)
p.add_argument('--mode',choices=['nodiv','div'],required=True)
p.add_argument('--specs',default='../data/processed/backtesting/matrix_20261121/specs.csv')
p.add_argument('--out',required=True)
a=p.parse_args()
os.makedirs(a.out,exist_ok=True)
specs=pd.read_csv(a.specs,dtype={'trim':str})
summary=[]; annual=[]
for i,row in specs.iterrows():
    uc.set_pool(a.pool)
    filters=[x for x in str(row['filters']).split('+') if x]
    config.FILTER_INDICATORS=filters
    config.PE_THRESHOLD=float(row['pe_thr']); config.PB_THRESHOLD=float(row['pb_thr']); config.PR_THRESHOLD=float(row['pr_thr'])
    config.ROE_THRESHOLD=float(row['roe_thr']); config.MAX_POSITIONS=int(row['max_positions'])
    trim=str(row['trim']); config.WINSORIZE_ENABLED=(trim!='raw')
    config.THRESHOLD_TRIM_RATIO=float(trim) if trim!='raw' else 0.01
    config.DIVIDEND_MODE='declared'
    ranking='div' if a.mode=='div' else row['ranking']
    try:
        r=run_backtest('2015-01-01','2026-11-06',frequency='annual',ranking_method=ranking,
                       filter_indicators=filters, ignore_first_cutoff_new_stock=True)
        perf=calculate_performance(r['equity_curve'],r['cutoff_dates'],r['trade_records'])
        ar=perf['annual_returns']
        summary.append(dict(spec_id=row['spec_id'],filters=row['filters'],ranking=ranking,trim=trim,
                            max_positions=int(row['max_positions']),pe_thr=row['pe_thr'],pb_thr=row['pb_thr'],
                            pr_thr=row['pr_thr'],roe_thr=row['roe_thr'],
                            M3b=perf['annual_return_since_first_investment'],M1=perf['annual_return'],
                            sharpe=perf['sharpe_ratio'],mdd=perf['max_drawdown']))
        for _,x in ar.iterrows(): annual.append(dict(spec_id=row['spec_id'],year=int(x['year']),return_=float(x['strategy_return'])))
    except Exception as e:
        print('ERR',row['spec_id'],type(e).__name__,str(e)[:120],flush=True)
    if (i+1)%10==0:
        pd.DataFrame(summary).to_csv(os.path.join(a.out,'summary.csv'),index=False)
        pd.DataFrame(annual).to_csv(os.path.join(a.out,'annual.csv'),index=False)
        print(a.pool,a.mode,i+1,'/',len(specs),flush=True)
pd.DataFrame(summary).to_csv(os.path.join(a.out,'summary.csv'),index=False)
pd.DataFrame(annual).to_csv(os.path.join(a.out,'annual.csv'),index=False)
print('DONE',a.pool,a.mode,len(summary),flush=True)
