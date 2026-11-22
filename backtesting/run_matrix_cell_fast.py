#!/usr/bin/env python3
"""缓存价格/财务后的多进程版：每个 worker 只加载一次数据。"""
import argparse, os, sys
sys.path.insert(0,'.')
import pandas as pd

def init(pool):
    import config
    SNAP='/tmp/bt_snapshot_20261120'
    if os.path.exists(os.path.join(SNAP,'price')):
        config.PRICE_DATA_DIR=os.path.join(SNAP,'price')
        config.FINANCIAL_DATA_DIR=os.path.join(SNAP,'financial')
    import data_loader, stock_selector, backtest_engine
    import universe_compare as uc
    uc.set_pool(pool)
    codes=data_loader.load_stock_pool()['code'].tolist()
    price={c:data_loader.load_price_data(c) for c in codes}
    fin={c:data_loader.load_financial_data(c) for c in codes}
    pool_df=data_loader.load_stock_pool()
    def lp(c): return price.get(c, pd.DataFrame())
    def lf(c): return fin.get(c, pd.DataFrame())
    def lsp(): return pool_df
    data_loader.load_price_data=lp; data_loader.load_financial_data=lf; data_loader.load_stock_pool=lsp
    stock_selector.load_price_data=lp; stock_selector.load_financial_data=lf
    backtest_engine.load_price_data=lp; backtest_engine.load_financial_data=lf; backtest_engine.load_stock_pool=lsp
    print('worker ready',pool,len(codes),flush=True)

def work(task):
    import config
    import universe_compare as uc
    from backtest_engine import run_backtest
    from performance import calculate_performance
    row,pool,mode,div_tax=task
    uc.set_pool(pool)
    filters=[x for x in str(row['filters']).split('+') if x]
    config.FILTER_INDICATORS=filters
    config.PE_THRESHOLD=float(row['pe_thr']); config.PB_THRESHOLD=float(row['pb_thr']); config.PR_THRESHOLD=float(row['pr_thr'])
    config.ROE_THRESHOLD=float(row['roe_thr']); config.MAX_POSITIONS=int(row['max_positions'])
    trim=str(row['trim']); config.WINSORIZE_ENABLED=(trim!='raw')
    config.THRESHOLD_TRIM_RATIO=float(trim) if trim!='raw' else 0.01
    config.DIVIDEND_MODE='declared'
    config.DIVIDEND_TAX_ENABLED=bool(div_tax)
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
    ap.add_argument('--dividend_tax',action='store_true',help='兼容旧命令；默认已开启')
    ap.add_argument('--no_dividend_tax',action='store_true',help='关闭红利税')
    a=ap.parse_args()
    os.makedirs(a.out,exist_ok=True)
    specs=pd.read_csv(a.specs,dtype={'trim':str})
    tasks=[(row,a.pool,a.mode,not a.no_dividend_tax) for _,row in specs.iterrows()]
    import multiprocessing as mp
    with mp.Pool(a.workers,initializer=init,initargs=(a.pool,)) as pool:
        results=pool.map(work,tasks)
    summary=[s for s,_ in results if s]; annual=[x for _,aa in results for x in aa]
    pd.DataFrame(summary).to_csv(os.path.join(a.out,'summary.csv'),index=False)
    pd.DataFrame(annual).to_csv(os.path.join(a.out,'annual.csv'),index=False)
    print('DONE',a.pool,a.mode,len(summary),'/',len(specs),flush=True)
