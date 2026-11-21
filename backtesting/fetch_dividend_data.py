#!/usr/bin/env python3
"""拉取全市场分红方案（年报 + 中期），保存为本地面板。"""
import os, time
import pandas as pd
import akshare as ak

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, '..', 'data', 'input', 'backtesting', 'dividend')
os.makedirs(OUT, exist_ok=True)

frames=[]
for year in range(2014, 2026):
    for md in ['0630', '0930', '1231']:
        date=f'{year}{md}'
        try:
            df=ak.stock_fhps_em(date=date)
            if len(df):
                df['报告期']=pd.Timestamp(f'{year}-{md[:2]}-{md[2:]}')
                frames.append(df)
            print(date, len(df), flush=True)
        except Exception as e:
            print(date, 'ERR', type(e).__name__, str(e)[:120], flush=True)
        time.sleep(0.5)

all_df=pd.concat(frames, ignore_index=True)
out=pd.DataFrame({
    'code': all_df['代码'].astype(str).str.zfill(6),
    'name': all_df['名称'],
    'report_date': all_df['报告期'],
    'cash_div_per_10': pd.to_numeric(all_df['现金分红-现金分红比例'], errors='coerce'),
    'plan_date': pd.to_datetime(all_df['预案公告日'], errors='coerce'),
    'latest_date': pd.to_datetime(all_df['最新公告日期'], errors='coerce'),
    'ex_date': pd.to_datetime(all_df['除权除息日'], errors='coerce'),
    'progress': all_df['方案进度'],
})
out=out.dropna(subset=['cash_div_per_10'])
out=out[out['cash_div_per_10']>0]
out=out.sort_values(['code','report_date','latest_date']).drop_duplicates(['code','report_date'], keep='last')
out.to_csv(os.path.join(OUT,'fhps_all.csv'), index=False)
out[out.report_date.dt.month==12].to_csv(os.path.join(OUT,'fhps_annual.csv'), index=False)
print('saved', len(out), 'rows ->', os.path.join(OUT,'fhps_all.csv'))
