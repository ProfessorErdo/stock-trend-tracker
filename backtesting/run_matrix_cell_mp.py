#!/usr/bin/env python3
"""多进程版：按统一 spec 列表跑一个 2x2 格子。"""
import argparse, os, sys
sys.path.insert(0,'.')
import pandas as pd

def work(task):
    import config
    SNAP='/tmp/bt_snapshot_20261120'
    if os.path.exists(os.path.join(SNAP,'price')):
        config.PRICE_DATA_DIR=os.path.join(SNAP,'price')
        config.FINANCIAL_DATA_DIR=os.path.join(SNAP,'financial')
    import universe_compare as uc
    from backtest_engine import run_backtest
    from performance import calculate_performance
    row,pool,mode=task
    uc.set_pool(pool)
    filters=[x for x in str(row['filters']).split('+') if x]
    config.FILTER_INDICATORS=filters
    config.PE_THRESHOLD=float(row['pe_thr']); config.PB_THRESHOLD=float(row['pb_thr']); config.PR_THRESHOLD=float(row['pr_thr'])
    config.ROE_THRESHOLD=float(row['roe_thr']); config.MAX_POSITIONS=int(row['max_positions'])
    trim=str(row['trim']); config.WINSORIZE_ENABLED=(trim!='raw')
    config.THRESHOLD_TRIM_RATIO=float(trim) if trim!='raw' else 0.01
    config.DIVIDEND_MODE='declared'
    ranking='div' if mode=='div' else row['ranking']
    try:
        r=run_backtest('2015-01-01','2026-11-06',frequency='annual',ranking_method=ranking,
                       filter_indicators=filters, ignore_first_cutoff_new_stock=True)
        p=calculate_performance(r['equity_curve'],r['cutoff_dates'],r['trade_records'])
        s=dict(spec_id=row['spec_id'],filters=row['filters'],ranking=ranking,trim=trim,
               max_positions=int(row['max_positions']),pe_thr=float(row['pe_thr']),pb_thr=float(row['pb_thr']),
               pr_thr=float(row['pr_thr']),roe_thr=float(row['roe_thr']),
               M3b=float(p['annual_return_since_first_investment']),M1=float(p['annual_return']),
               sharpe=float(p['sharpe_ratio']),mdd=float(p['max_drawdown']))
        a=[dict(spec_id=row['spec_id'],year=int(x['year']),return_=float(x['strategy_return'])) for _,x in p['annual_returns'].iterrows()]
        return s,a
    except Exception as e:
        print('ERR',row['spec_id'],type(e).__name__,str(e)[:150],flush=True)
        return None,[]

if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--pool',choices=['union','legacy'],required=True)
    ap.add_argument('--mode',choices=['nodiv','div'],required=True)
    ap.add_argument('--specs',default='../data/processed/backtesting/matrix_20261121/specs.csv')
    ap.add_argument('--out',required=True)
    ap.add_argument('--workers',type=int,default=4)
    a=ap.parse_args()
    os.makedirs(a.out,exist_ok=True)
    specs=pd.read_csv(a.specs,dtype={'trim':str})
    tasks=[(row,a.pool,a.mode) for _,row in specs.iterrows()]
    import multiprocessing as mp
    with mp.Pool(a.workers) as pool:
        results=pool.map(work,tasks)
    summary=[s for s,_ in results if s]; annual=[x for _,aa in results for x in aa]
    pd.DataFrame(summary).to_csv(os.path.join(a.out,'summary.csv'),index=False)
    pd.DataFrame(annual).to_csv(os.path.join(a.out,'annual.csv'),index=False)
    print('DONE',a.pool,a.mode,len(summary),'/',len(specs),flush=True)
