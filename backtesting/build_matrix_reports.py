#!/usr/bin/env python3
"""生成 2x2 四份子报告 + 一份汇总。"""
import os, sys
sys.path.insert(0,'.')
import numpy as np, pandas as pd
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
import config
SNAP='/tmp/bt_snapshot_20261120'
if os.path.exists(os.path.join(SNAP,'price')):
    config.PRICE_DATA_DIR=os.path.join(SNAP,'price'); config.FINANCIAL_DATA_DIR=os.path.join(SNAP,'financial')
import universe_compare as uc
from backtest_engine import run_backtest
from performance import calculate_performance

BASE='../data/processed/backtesting/matrix_20261121'
IMG='../docs/img/matrix-2026-11'; os.makedirs(IMG,exist_ok=True)
names=pd.read_csv('../data/input/stock_names_full.csv',dtype={'code':str}).set_index('code')['name'].to_dict()

def norm(df):
    df=df.copy()
    if 'spec_id' not in df.columns: df['spec_id']=df['key']
    for c in ['filters','ranking','trim','max_positions','pe_thr','pb_thr','pr_thr','roe_thr']:
        if c not in df.columns: df[c]=np.nan
    if 'M3b' not in df.columns:
        df['M3b']=df['annual_return_since_first_investment']; df['M1']=df['annual_return']
    if 'sharpe' not in df.columns:
        df['sharpe']=df['M3_sharpe'] if 'M3_sharpe' in df.columns else np.nan
    if 'mdd' not in df.columns:
        df['mdd']=df['M3_mdd'] if 'M3_mdd' in df.columns else np.nan
    return df

def load_cell(cell):
    if cell in ('1052_nodiv','932_nodiv'):
        df=pd.read_csv('../data/processed/backtesting/m3b_20261120/m3b_annual.csv',dtype={'pool':str})
        pool='1052' if cell=='1052_nodiv' else '932'
        df=df[(df.pool==pool)&(df.phase!='special')]
        return norm(df)
    return norm(pd.read_csv(f'{BASE}/{cell}/summary.csv'))

def short(r):
    trim='raw' if str(r['trim'])=='raw' else f"{float(r['trim'])*100:g}%"
    filt=str(r['filters']); parts=[]
    if 'pe' in filt.split('+'): parts.append(f"PE{int(float(r['pe_thr'])*100)}")
    if 'pb' in filt.split('+'): parts.append(f"PB{int(float(r['pb_thr'])*100)}")
    if 'pr' in filt.split('+'): parts.append(f"PR{int(float(r['pr_thr'])*100)}")
    return f"{filt} {'/'.join(parts)}/ROE{int(float(r['roe_thr'])*100)} {r['ranking']} {trim} N{int(r['max_positions'])}"

def annual_matrix(cell, top):
    ids=list(top['spec_id'])
    if cell in ('1052_nodiv','932_nodiv'):
        root='../data/processed/backtesting/universe_compare_2015start_20261120' if cell=='1052_nodiv' else '../data/processed/backtesting/universe_compare_legacy932_2015start_20261120'
        rows={}
        for sid in ids:
            p=f'{root}/runs/{sid}_2015start/annual_returns.csv'
            if os.path.exists(p):
                rows[sid]=pd.read_csv(p).set_index('year')['strategy_return']
        return pd.DataFrame(rows).T
    p=f'{BASE}/{cell}/annual.csv'
    a=pd.read_csv(p)
    a=a[a.spec_id.isin(ids)]
    return a.pivot(index='spec_id',columns='year',values='return_')

def chart_cell(cell, top, ann):
    labels=[short(r) for _,r in top.iterrows()]
    data=ann.loc[top['spec_id'].tolist()].values*100
    fig,ax=plt.subplots(figsize=(12,0.55*len(labels)+1.8))
    im=ax.imshow(data,cmap='RdYlGn',aspect='auto',vmin=-40,vmax=60)
    ax.set_xticks(range(ann.shape[1]),ann.columns,rotation=45); ax.set_yticks(range(len(labels)),labels,fontsize=7)
    for i in range(data.shape[0]):
        for j in range(data.shape[1]): ax.text(j,i,f'{data[i,j]:.0f}',ha='center',va='center',fontsize=7)
    ax.set_title(f'{cell}: top5 annual returns (%)'); fig.colorbar(im,ax=ax,shrink=0.8)
    fig.tight_layout(); fig.savefig(f'{IMG}/{cell}_annual_top5.png',dpi=160); plt.close(fig)
    # top15 bar
    t=top.head(15).iloc[::-1]
    fig,ax=plt.subplots(figsize=(10,0.45*len(t)+1.6))
    ax.barh([short(r) for _,r in t.iterrows()],t['M3b']*100,color='#4C72B0')
    for i,v in enumerate(t['M3b']*100): ax.text(v+0.05,i,f'{v:.2f}',va='center',fontsize=7)
    ax.set_xlabel('M3b (%)'); ax.set_title(f'{cell}: top15 by M3b'); fig.tight_layout()
    fig.savefig(f'{IMG}/{cell}_top15.png',dpi=160); plt.close(fig)

def holdings(best):
    uc.set_pool('union' if str(best.get('pool',''))=='1052' else 'legacy')
    filters=[x for x in str(best['filters']).split('+') if x]
    config.FILTER_INDICATORS=filters
    config.PE_THRESHOLD=float(best['pe_thr']); config.PB_THRESHOLD=float(best['pb_thr']); config.PR_THRESHOLD=float(best['pr_thr'])
    config.ROE_THRESHOLD=float(best['roe_thr']); config.MAX_POSITIONS=int(best['max_positions'])
    trim=str(best['trim']); config.WINSORIZE_ENABLED=(trim!='raw'); config.THRESHOLD_TRIM_RATIO=float(trim) if trim!='raw' else 0.01
    config.DIVIDEND_MODE='declared'
    r=run_backtest('2015-01-01','2026-11-06',frequency='annual',ranking_method=best['ranking'],
                   filter_indicators=filters, ignore_first_cutoff_new_stock=True)
    for x in r['holding_snapshots']:
        if len(x) and pd.Timestamp(x.rebalance_date.iloc[0])==pd.Timestamp('2026-05-06'):
            return [f"{c}{names.get(c,'')}" for c in x.stock_code]
    return []

CELLS={
 '1052_nodiv': dict(title='1052 × 非股息', pool='1052', start='2015-05', note='union 池；非股息排名'),
 '1052_div': dict(title='1052 × 股息', pool='1052', start='2015-05', note='union 池；股息率 TTM 排名'),
 '932_nodiv': dict(title='932 × 非股息', pool='932', start='2015-05', note='legacy 单期清单；非股息排名'),
 '932_div': dict(title='932 × 股息', pool='932', start='2015-05', note='legacy 单期清单；股息率 TTM 排名'),
}
CAVEAT={
 '1052_nodiv':['union 池含历史清单，仍有成分股回推偏差；','银行/钢铁集中度高，2015 银行股灾、2019/2022 钢铁是主要亏损来源；','非股息版没有分红信息，2026 持仓含 5 只银行。'],
 '1052_div':['股息率 TTM 用“预案公告日 + 最终实施金额”，隐含“预案≈实施”假设；','paid 口径（只算已派息）为 11.85%（M1）/12.21%（M3b），仍高于同起点无股息；','2023-2026 无股息版反超，因子阶段性失效；','2026 持仓为江苏/南京/齐鲁/招商/成都，仍是银行。'],
 '932_nodiv':['legacy 是单期旧清单，幸存者偏差最重；','2021 年 +56%（妖股/周期）与 2022 年 -22.9% 是同一批高波动持仓；','2026 持仓含成都/杭州/常熟/人保/太保，银行+保险。'],
 '932_div':['同样有 legacy 单期清单的幸存者偏差；','股息率 TTM 同样隐含“预案≈实施”；','paid 口径 11.48%（M1）/11.83%（M3b），仍高于无股息 10.73%/11.05%；','2021 从 56% 降到 28%，2022 从 -22.9% 升到 +7.4%，波动明显下降；','2026 持仓为江苏/南京/齐鲁/招商/常熟。'],
}

def main():
    summaries={c:load_cell(c) for c in CELLS}
    bests={}
    for c,df in summaries.items():
        df=df.sort_values('M3b',ascending=False).reset_index(drop=True)
        best=df.iloc[0].to_dict(); best['pool']=CELLS[c]['pool']; bests[c]=best
        top=df.head(10)
        ann=annual_matrix(c,df.head(5))
        chart_cell(c,df.head(5),ann)
        lines=[f"# {CELLS[c]['title']}：标准网格（2026-11）\n",f"> 池：{CELLS[c]['pool']}；首买：2015-05；主指标：M3b。\n"]
        lines.append('## 0. 结论\n')
        lines.append(f"- 最佳：`{short(best)}`")
        lines.append(f"- M3b **{best['M3b']*100:.2f}%**，M1 {best['M1']*100:.2f}%，夏普 {best['sharpe']:.3f}，回撤 {best['mdd']*100:.1f}%")
        if c.endswith('div') and float(best['roe_thr'])<=0.60:
            lines.append('- **注意：ROE60 是网格下边界**，M3b 最高但回撤更深；风险调整推荐 PB10/ROE65（1052 15.53% / -32.8%，932 13.80% / -32.8%）。')
        lines.append('')
        lines.append('## 1. 网格\n')
        grid_note='121 组标准网格' if c.endswith('nodiv') else '15 组股息 pilot 网格（PB10-20 × ROE60-80；全量 121 组待补）'
        pbv=', '.join(f'{x:g}' for x in sorted(df['pb_thr'].unique()))
        roev=', '.join(f'{x:g}' for x in sorted(df['roe_thr'].unique()))
        nv=', '.join(str(x) for x in sorted(df['max_positions'].unique()))
        lines.append(f"{grid_note}；过滤 {df['filters'].nunique()} 种、排名 {df['ranking'].nunique()} 种、PB {pbv}、ROE {roev}、裁尾 {sorted(df['trim'].astype(str).unique())}、N {nv}。\n")
        lines.append('## 2. Top 10\n')
        t=top.copy(); t['配置']=t.apply(short,axis=1)
        lines.append('| # | 配置 | M3b | M1 | 夏普 | 回撤 |')
        lines.append('|---:|---|---:|---:|---:|---:|')
        for i,r in t.iterrows():
            lines.append(f"| {i+1} | {r['配置']} | {r['M3b']*100:.2f}% | {r['M1']*100:.2f}% | {r['sharpe']:.3f} | {r['mdd']*100:.1f}% |")
        lines.append('')
        lines.append('## 3. Top5 年度收益\n')
        lines.append(f"![annual](img/matrix-2026-11/{c}_annual_top5.png)\n")
        lines.append(f"![top15](img/matrix-2026-11/{c}_top15.png)\n")
        lines.append('## 4. 2026 持仓\n')
        h=holdings(best); lines.append('、'.join(h) if h else '—'); lines.append('')
        lines.append('## 5. 本格子的特殊情况\n')
        for x in CAVEAT[c]: lines.append(f'- {x}')
        lines.append('')
        lines.append('## 6. 复现\n```bash\ncd backtesting\n../.venv/bin/python run_matrix_cell.py --pool '+('union' if CELLS[c]['pool']=='1052' else 'legacy')+f" --mode {'div' if c.endswith('div') else 'nodiv'} --out ../data/processed/backtesting/matrix_20261121/{c}\n```\n")
        open(f'../docs/matrix-{c.replace("_","-")}-2026-11.md','w').write('\n'.join(lines))

    # summary
    rows=[]
    for c,b in bests.items(): rows.append(dict(cell=c,M3b=b['M3b'],M1=b['M1'],sharpe=b['sharpe'],mdd=b['mdd'],config=short(b)))
    s=pd.DataFrame(rows)
    s.to_csv(f'{BASE}/summary_best.csv',index=False)
    # best4 annual
    anns=[]
    for c,b in bests.items():
        a=annual_matrix(c,pd.DataFrame([b]))
        a.index=[c]; anns.append(a)
    ann4=pd.concat(anns)
    fig,ax=plt.subplots(figsize=(12,4.2)); im=ax.imshow(ann4.values*100,cmap='RdYlGn',aspect='auto',vmin=-40,vmax=60)
    ax.set_xticks(range(ann4.shape[1]),ann4.columns,rotation=45)
    ax.set_yticks(range(4),['1052 no div','1052 div','932 no div','932 div'])
    for i in range(4):
        for j in range(ann4.shape[1]): ax.text(j,i,f'{ann4.values[i,j]*100:.0f}',ha='center',va='center',fontsize=8)
    ax.set_title('Best of each cell: annual returns (%)'); fig.colorbar(im,ax=ax,shrink=0.8)
    fig.tight_layout(); fig.savefig(f'{IMG}/summary_best4_annual.png',dpi=160); plt.close(fig)
    # 2x2 matrix
    m=np.array([[bests['1052_nodiv']['M3b'],bests['1052_div']['M3b']],[bests['932_nodiv']['M3b'],bests['932_div']['M3b']]])*100
    fig,ax=plt.subplots(figsize=(6,4.2)); im=ax.imshow(m,cmap='RdYlGn',vmin=8,vmax=17)
    ax.set_xticks([0,1],['no dividend','dividend']); ax.set_yticks([0,1],['1052','932'])
    for i in range(2):
        for j in range(2): ax.text(j,i,f'{m[i,j]:.2f}%',ha='center',va='center',fontsize=13)
    ax.set_title('M3b: 2x2 best'); fig.colorbar(im,ax=ax,shrink=0.8); fig.tight_layout()
    fig.savefig(f'{IMG}/summary_matrix.png',dpi=160); plt.close(fig)
    lines=['# 2×2 汇总：1052/932 × 股息/非股息（2026-11）\n', '> 主指标 M3b；非股息 121 组标准网格，股息 15 组 pilot；首买 2015-05。\n','## 0. 四宫格最佳\n']
    lines.append('| 格子 | 最佳配置 | M3b | M1 | 夏普 | 回撤 |')
    lines.append('|---|---|---:|---:|---:|---:|')
    for _,r in s.iterrows(): lines.append(f"| {CELLS[r['cell']]['title']} | {r['config']} | {r['M3b']*100:.2f}% | {r['M1']*100:.2f}% | {r['sharpe']:.3f} | {r['mdd']*100:.1f}% |")
    lines.append('')
    lines.append('![matrix](img/matrix-2026-11/summary_matrix.png)\n')
    lines.append('![annual](img/matrix-2026-11/summary_best4_annual.png)\n')
    lines.append('## 1. 子报告\n')
    for c in CELLS: lines.append(f"- [{CELLS[c]['title']}](matrix-{c.replace('_','-')}-2026-11.md)")
    lines.append('')
    lines.append('## 2. 跨格子观察\n')
    lines.append('- 股息率版在 1052 和 932 都提高了 M3b；但 2023-2026 无股息版反超，属于阶段性因子。')
    lines.append('- 932 的绝对收益更低、波动更大；legacy 单期清单的幸存者偏差最重。')
    lines.append('- 非股息格子是 121 组标准网格；股息格子目前是 15 组 pilot（覆盖 PB10-20/ROE60-80），全量 121 组可后续补齐。')
    lines.append('- 股息格的最高 M3b 落在 ROE60 边界，回撤更深；风险调整建议用 PB10/ROE65（1052 15.53% / 932 13.80%，回撤 -32.8%）。')
    lines.append('- 股息率版的“预案≈实施”假设需要持续监控；paid 口径是保守下界。')
    lines.append('')
    lines.append('## 3. 数据与口径\n')
    lines.append('- 价格/财务：2026-11-20 快照，统一截止 2026-11-06。')
    lines.append('- 股息率：AkShare 分红面板 2014-2025，TTM = 过去 365 天预案分红 / 4·30 close_na。')
    lines.append('- M3b = 2015-05-04 起算；M1/M2/M3 仅辅助。')
    open('../docs/matrix-summary-2026-11.md','w').write('\n'.join(lines))
    print('reports written')

if __name__=='__main__': main()
