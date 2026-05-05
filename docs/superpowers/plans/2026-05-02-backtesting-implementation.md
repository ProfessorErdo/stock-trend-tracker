# 选股策略回测系统实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建完整的周频低估值高ROE选股策略回测系统，支持数据拉取、选股、调仓、绩效计算和可视化输出。

**Architecture:** 模块化设计，9个独立模块通过清晰接口协作。数据层与业务逻辑分离，回测引擎驱动整个流程。

**Tech Stack:** Python 3.x, pandas, numpy, akshare, matplotlib, seaborn

---

## 文件结构映射

### 新建文件清单

| 文件路径 | 职责 |
|----------|------|
| `backtesting/config.py` | 全局参数配置 |
| `backtesting/data_loader.py` | 数据拉取与存储 |
| `backtesting/trading_calendar.py` | 交易日历管理 |
| `backtesting/stock_selector.py` | 选股逻辑执行 |
| `backtesting/portfolio.py` | 持仓状态管理 |
| `backtesting/backtest_engine.py` | 回测核心引擎 |
| `backtesting/performance.py` | 绩效指标计算 |
| `backtesting/visualizer.py` | 可视化输出 |
| `backtesting/run_backtest.py` | 主运行入口 |

### 新建数据目录

| 目录路径 | 用途 |
|----------|------|
| `data/input/backtesting/` | 回测专用输入数据 |
| `data/input/backtesting/price/` | 后复权价格CSV |
| `data/input/backtesting/financial/` | 财务数据CSV |
| `data/input/backtesting/stock_pool/` | 股票池列表CSV |
| `data/processed/backtesting/` | 回测输出结果 |
| `data/processed/backtesting/holdings/` | 持仓明细CSV |
| `data/processed/backtesting/trades/` | 交易记录CSV |
| `data/processed/backtesting/performance/` | 绩效指标CSV |
| `data/processed/backtesting/charts/` | 图表PNG |

---

## Phase 1: 项目初始化与配置模块

### Task 1.1: 创建目录结构

**Files:**
- Create: `backtesting/` 目录
- Create: `data/input/backtesting/` 目录
- Create: `data/processed/backtesting/` 目录

- [ ] **Step 1: 创建回测模块目录**

```bash
mkdir -p backtesting
```

- [ ] **Step 2: 创建回测数据输入目录**

```bash
mkdir -p data/input/backtesting/price
mkdir -p data/input/backtesting/financial
mkdir -p data/input/backtesting/stock_pool
```

- [ ] **Step 3: 创建回测结果输出目录**

```bash
mkdir -p data/processed/backtesting/holdings
mkdir -p data/processed/backtesting/trades
mkdir -p data/processed/backtesting/performance
mkdir -p data/processed/backtesting/charts
```

- [ ] **Step 4: 验证目录创建成功**

```bash
ls -la backtesting/
ls -la data/input/backtesting/
ls -la data/processed/backtesting/
```
Expected: 所有目录存在

---

### Task 1.2: 编写配置模块 config.py

**Files:**
- Create: `backtesting/config.py`

- [ ] **Step 1: 创建 config.py 文件**

```python
"""
回测系统全局配置模块
定义所有可配置参数，便于后续调整
"""

from datetime import datetime
import os

# ============== 基础路径配置 ==============
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_INPUT_DIR = os.path.join(BASE_DIR, "data", "input", "backtesting")
DATA_OUTPUT_DIR = os.path.join(BASE_DIR, "data", "processed", "backtesting")

# 价格数据目录
PRICE_DATA_DIR = os.path.join(DATA_INPUT_DIR, "price")
# 财务数据目录
FINANCIAL_DATA_DIR = os.path.join(DATA_INPUT_DIR, "financial")
# 股票池目录
STOCK_POOL_DIR = os.path.join(DATA_INPUT_DIR, "stock_pool")

# 输出目录
HOLDINGS_DIR = os.path.join(DATA_OUTPUT_DIR, "holdings")
TRADES_DIR = os.path.join(DATA_OUTPUT_DIR, "trades")
PERFORMANCE_DIR = os.path.join(DATA_OUTPUT_DIR, "performance")
CHARTS_DIR = os.path.join(DATA_OUTPUT_DIR, "charts")


# ============== 回测全局参数 ==============
INITIAL_CAPITAL = 1_000_000  # 初始资金（元）
START_DATE = "2015-01-01"   # 回测起始日期
END_DATE = None              # 回测结束日期（None表示使用最新交易日）
RISK_FREE_RATE = 0.02        # 无风险利率（用于夏普比率）


# ============== 选股参数 ==============
# 分位数阈值
PE_THRESHOLD = 0.25          # PE分位数阈值（保留最低25%）
PB_THRESHOLD = 0.25          # PB分位数阈值（保留最低25%）
PR_THRESHOLD = 0.25          # PR分位数阈值（保留最低25%）
ROE_THRESHOLD = 0.75         # ROE分位数阈值（保留最高75%分位以上）

# 极值处理
WINSORIZE_LOWER = 0.01       # 极值截尾下限（1%）
WINSORIZE_UPPER = 0.99       # 极值截尾上限（99%）

# 新股排除
NEW_STOCK_EXCLUDE_DAYS = 120  # 排除上市不足120天的股票


# ============== 调仓参数 ==============
MIN_FULL_POSITION_STOCKS = 5  # N>=5时满仓，N<5启用集中度控制
MAX_SINGLE_POSITION = 0.20    # 单股最大仓位（20%）
LOT_SIZE = 100                # 每手股数（A股100股/手）


# ============== 交易成本参数 ==============
COMMISSION_RATE = 0.0003      # 佣金率（0.03%）
COMMISSION_MIN = 5            # 最低佣金（元）
STAMP_TAX_RATE = 0.001        # 印花税率（卖出0.1%）


# ============== 涨跌停参数 ==============
LIMIT_TOLERANCE = 0.001       # 涨跌停判断容差（0.1%）
DEFAULT_LIMIT_RATIO = 0.10    # 默认涨跌幅（10%）

# 涨跌幅规则映射表
# 格式: (代码前缀列表, 涨跌幅, 开始日期, 结束日期)
# None表示全期适用
LIMIT_RATIO_RULES = [
    # 主板（上海）
    (["600", "601", "603", "605"], 0.10, None, None),
    # 主板（深圳）
    (["000", "001", "002", "003"], 0.10, None, None),
    # 科创板（20%，全期）
    (["688"], 0.20, None, None),
    # 创业板（10%，2020-08-23及之前）
    (["300"], 0.10, None, "2020-08-23"),
    # 创业板（20%，2020-08-24及之后）
    (["300"], 0.20, "2020-08-24", None),
    # 北交所（30%，全期）
    (["830", "831", "832", "833", "834", "835", "836", "837", "838", "839",
      "870", "871", "872", "873", "874", "875", "876", "877", "878", "879",
      "920"], 0.30, None, None),
]


# ============== 股票池配置 ==============
STOCK_POOLS = [
    "hs300",       # 沪深300
    "zz500",       # 中证500
    "hongli",      # 红利
    "honglidibo",  # 红利低波
    "gz100",       # 国证2000（项目现有命名）
    "gzfc",        # 国证自由现金流
    "zzfc",        # 中证自由现金流
]

# 现有股票池文件映射（使用data/input/下的现有文件）
EXISTING_STOCK_POOL_FILES = {
    "hs300": os.path.join(BASE_DIR, "data", "input", "hs300_list_20251213.csv"),
    "zz500": os.path.join(BASE_DIR, "data", "input", "zz500_list_20251216.csv"),
    "hongli": os.path.join(BASE_DIR, "data", "input", "hongli_list_20251213.csv"),
    "honglidibo": os.path.join(BASE_DIR, "data", "input", "honglidibo_list_20251213.csv"),
    "gz100": os.path.join(BASE_DIR, "data", "input", "gz100_list_20260227.csv"),
    "gzfc": os.path.join(BASE_DIR, "data", "input", "gzfc_list_20260227.csv"),
    "zzfc": os.path.join(BASE_DIR, "data", "input", "zzfc_list_20260316.csv"),
}


# ============== 财报披露延迟规则 ==============
# 根据报告期月份判断可用日期
REPORT_AVAILABLE_MONTHS = {
    3: 1,   # 一季报：报告期+1个月（4月底可用）
    6: 2,   # 半年报：报告期+2个月（8月底可用）
    9: 1,   # 三季报：报告期+1个月（10月底可用）
    12: 4,  # 年报：报告期+4个月（次年4月底可用）
}


# ============== 辅助函数 ==============
def get_limit_ratio(stock_code: str, trade_date: str) -> float:
    """
    根据股票代码和交易日期获取涨跌幅限制
    
    Args:
        stock_code: 股票代码（如 600519）
        trade_date: 交易日期（如 2024-01-15）
    
    Returns:
        涨跌幅比例（如 0.10 表示10%）
    """
    prefix = stock_code[:3]
    trade_dt = datetime.strptime(trade_date, "%Y-%m-%d") if isinstance(trade_date, str) else trade_date
    
    # 查找匹配规则
    for prefixes, ratio, start, end in LIMIT_RATIO_RULES:
        if prefix in prefixes:
            # 检查日期范围
            if start is None or trade_dt >= datetime.strptime(start, "%Y-%m-%d"):
                if end is None or trade_dt <= datetime.strptime(end, "%Y-%m-%d"):
                    return ratio
    
    # 默认返回10%
    return DEFAULT_LIMIT_RATIO


def ensure_dirs():
    """确保所有必要目录存在"""
    dirs = [
        PRICE_DATA_DIR, FINANCIAL_DATA_DIR, STOCK_POOL_DIR,
        HOLDINGS_DIR, TRADES_DIR, PERFORMANCE_DIR, CHARTS_DIR
    ]
    for d in dirs:
        os.makedirs(d, exist_ok=True)
    print("All directories ensured.")


if __name__ == "__main__":
    # 测试配置模块
    ensure_dirs()
    
    # 测试涨跌幅获取
    print(f"600519 在 2020-08-20 涨跌幅: {get_limit_ratio('600519', '2020-08-20')}")
    print(f"300001 在 2020-08-20 涨跌幅: {get_limit_ratio('300001', '2020-08-20')}")
    print(f"300001 在 2020-08-24 涨跌幅: {get_limit_ratio('300001', '2020-08-24')}")
    ---

## Phase 2: 数据拉取模块

### Task 2.1: 编写数据加载模块 data_loader.py

**Files:**
- Create: `backtesting/data_loader.py`

- [ ] **Step 1: 创建 data_loader.py 文件**

```python
"""
回测数据拉取模块
从 AkShare API 获取后复权价格数据和财务数据，存储到指定目录
"""

import akshare as ak
import pandas as pd
import numpy as np
import os
from datetime import datetime
from tqdm import tqdm
import argparse
import sys

# 添加父目录到路径以导入配置
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config


def format_symbol(code: str) -> str:
    """将股票代码格式化为 AkShare 要求的格式"""
    code = str(code).zfill(6)
    if code.startswith('6'):
        return f'sh{code}'
    elif code.startswith('4') or code.startswith('8') or code.startswith('9'):
        return f'bj{code}'
    else:
        return f'sz{code}'


def load_stock_pool() -> pd.DataFrame:
    """
    加载并合并所有股票池，去重后返回
    
    Returns:
        DataFrame with columns: ['code']
    """
    all_codes = set()
    
    for pool_name in config.STOCK_POOLS:
        pool_file = config.EXISTING_STOCK_POOL_FILES.get(pool_name)
        if not pool_file or not os.path.exists(pool_file):
            print(f"Warning: Stock pool file not found: {pool_file}")
            continue
        
        try:
            # 判断分隔符
            sep = '\t' if pool_name == 'zz500' else ','
            df = pd.read_csv(pool_file, sep=sep)
            codes = df['code'].astype(str).str.zfill(6).tolist()
            all_codes.update(codes)
            print(f"Loaded {pool_name}: {len(codes)} stocks")
        except Exception as e:
            print(f"Warning: Failed to load {pool_name}: {e}")
    
    result = pd.DataFrame({'code': sorted(all_codes)})
    print(f"Combined stock pool: {len(result)} unique stocks")
    return result


def save_stock_pool(stock_codes: list):
    """保存股票池列表到回测专用目录"""
    os.makedirs(config.STOCK_POOL_DIR, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    filepath = os.path.join(config.STOCK_POOL_DIR, f"stock_pool_{today}.csv")
    
    df = pd.DataFrame({'code': [str(c).zfill(6) for c in stock_codes]})
    df.to_csv(filepath, index=False)
    print(f"Saved stock pool to {filepath}")


def query_price_data(stock_codes: list, start_date: str = "20150101", 
                     end_date: str = None, adjust: str = "hfq") -> int:
    """
    从 AkShare 获取后复权价格数据
    
    Args:
        stock_codes: 股票代码列表
        start_date: 起始日期，格式 YYYYMMDD
        end_date: 结束日期，格式 YYYYMMDD（None 表示今天）
        adjust: 复权方式，默认 hfq（后复权）
    
    Returns:
        成功获取数据的股票数量
    """
    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")
    
    os.makedirs(config.PRICE_DATA_DIR, exist_ok=True)
    
    # 检查已下载的股票
    existing_files = os.listdir(config.PRICE_DATA_DIR)
    existing_codes = set()
    for f in existing_files:
        if f.endswith('.csv'):
            # 文件名格式: price_{code}.csv
            parts = f.replace('price_', '').replace('.csv', '').split('_')
            existing_codes.add(parts[0])
    
    codes_to_download = [c for c in stock_codes if c not in existing_codes]
    print(f"Already have {len(existing_codes)} stocks, need to download {len(codes_to_download)}")
    
    success_count = len(existing_codes)
    
    for code in tqdm(codes_to_download, desc="Downloading price data"):
        try:
            symbol = format_symbol(code)
            df = ak.stock_zh_a_daily(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                adjust=adjust
            )
            
            if df.empty:
                continue
            
            # 选择需要的列
            df = df[['date', 'open', 'high', 'low', 'close', 'volume']]
            df.columns = ['trade_date', 'open', 'high', 'low', 'close', 'volume']
            df['trade_date'] = pd.to_datetime(df['trade_date'])
            df['stock_code'] = code
            
            # 数据类型转换和校验
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # 删除无效数据
            df = df.dropna(subset=['open', 'high', 'low', 'close', 'volume'])
            df = df[df['open'] > 0]
            
            # 保存到文件
            filepath = os.path.join(config.PRICE_DATA_DIR, f"price_{code}.csv")
            df.to_csv(filepath, index=False)
            success_count += 1
            
        except Exception as e:
            print(f"\nWarning: Failed to download {code}: {e}")
            continue
    
    print(f"Price data download complete: {success_count}/{len(stock_codes)} stocks")
    return success_count


def query_financial_data(stock_codes: list, season_end: str = "2026-04-30") -> int:
    """
    从 AkShare 获取财务数据，计算 TTM 指标
    
    Args:
        stock_codes: 股票代码列表
        season_end: 财务数据截止季度
    
    Returns:
        成功获取数据的股票数量
    """
    os.makedirs(config.FINANCIAL_DATA_DIR, exist_ok=True)
    
    # 检查已下载的股票
    existing_files = os.listdir(config.FINANCIAL_DATA_DIR)
    existing_codes = set()
    for f in existing_files:
        if f.endswith('.csv') and f.startswith('financial_'):
            code = f.replace('financial_', '').replace('.csv', '')
            existing_codes.add(code)
    
    codes_to_download = [c for c in stock_codes if c not in existing_codes]
    print(f"Already have {len(existing_codes)} stocks, need to download {len(codes_to_download)}")
    
    success_count = len(existing_codes)
    
    for code in tqdm(codes_to_download, desc="Downloading financial data"):
        try:
            # 获取财务摘要数据（按单季度）
            df = ak.stock_financial_abstract_ths(symbol=code, indicator="按单季度")
            
            if df.empty:
                continue
            
            # 选择需要的列
            df = df[['报告期', '每股净资产', '基本每股收益', '净资产收益率']]
            df.columns = ['report_date', 'bps', 'eps', 'roe']
            
            # 日期转换
            df['report_date'] = pd.to_datetime(df['report_date'])
            df = df[df['report_date'] >= '2010-01-01']
            
            # 数据类型转换
            df['eps'] = pd.to_numeric(df['eps'], errors='coerce')
            df['roe'] = df['roe'].astype(str).str.replace('%', '').astype(float)
            df['bps'] = pd.to_numeric(df['bps'], errors='coerce')
            
            # 计算 TTM 指标（4期滚动）
            df['bps_ttm'] = df['bps'].rolling(window=4).mean()
            df['eps_ttm'] = df['eps'].rolling(window=4).sum()
            df['roe_ttm'] = df['roe'].rolling(window=4).sum()
            
            # 删除 NaN
            df = df.dropna(subset=['eps_ttm', 'bps_ttm', 'roe_ttm'])
            
            if df.empty:
                continue
            
            # 计算财报可用日期
            df['ann_available_date'] = df['report_date'].apply(
                lambda d: _calc_ann_available_date(d)
            )
            
            # 保存到文件
            filepath = os.path.join(config.FINANCIAL_DATA_DIR, f"financial_{code}.csv")
            df.to_csv(filepath, index=False)
            success_count += 1
            
        except Exception as e:
            print(f"\nWarning: Failed to download financial data for {code}: {e}")
            continue
    
    print(f"Financial data download complete: {success_count}/{len(stock_codes)} stocks")
    return success_count


def _calc_ann_available_date(report_date: pd.Timestamp) -> pd.Timestamp:
    """根据报告期计算财报可用日期"""
    month = report_date.month
    
    if month == 12:
        # 年报：次年4月底
        return pd.Timestamp(year=report_date.year + 1, month=4, day=30)
    elif month == 6:
        # 半年报：8月底
        return pd.Timestamp(year=report_date.year, month=8, day=31)
    else:
        # 季报：+1个月
        year = report_date.year
        m = report_date.month + 1
        if m > 12:
            year += 1
            m = 1
        # 返回该月最后一天
        if m == 12:
            return pd.Timestamp(year=year, month=m, day=31)
        else:
            next_month = pd.Timestamp(year=year, month=m+1, day=1)
            return next_month - pd.Timedelta(days=1)


def load_price_data(stock_code: str) -> pd.DataFrame:
    """
    加载单只股票的后复权价格数据
    
    Args:
        stock_code: 股票代码
    
    Returns:
        DataFrame with columns [trade_date, open, high, low, close, volume]
    """
    filepath = os.path.join(config.PRICE_DATA_DIR, f"price_{stock_code}.csv")
    if not os.path.exists(filepath):
        return pd.DataFrame()
    
    df = pd.read_csv(filepath, parse_dates=['trade_date'])
    return df


def load_financial_data(stock_code: str) -> pd.DataFrame:
    """
    加载单只股票的财务数据
    
    Args:
        stock_code: 股票代码
    
    Returns:
        DataFrame with columns [report_date, bps_ttm, eps_ttm, roe_ttm, ann_available_date]
    """
    filepath = os.path.join(config.FINANCIAL_DATA_DIR, f"financial_{stock_code}.csv")
    if not os.path.exists(filepath):
        return pd.DataFrame()
    
    df = pd.read_csv(filepath, parse_dates=['report_date', 'ann_available_date'])
    return df


def main():
    """主函数：下载所有数据"""
    parser = argparse.ArgumentParser(description="回测数据拉取工具")
    parser.add_argument("--start_date", type=str, default="20150101", 
                        help="起始日期，格式 YYYYMMDD")
    parser.add_argument("--end_date", type=str, default=None,
                        help="结束日期，格式 YYYYMMDD")
    parser.add_argument("--price_only", action="store_true", help="仅下载价格数据")
    parser.add_argument("--financial_only", action="store_true", help="仅下载财务数据")
    
    args = parser.parse_args()
    
    # 确保目录存在
    config.ensure_dirs()
    
    # 加载股票池
    stock_df = load_stock_pool()
    stock_codes = stock_df['code'].tolist()
    
    # 保存股票池
    save_stock_pool(stock_codes)
    
    end_date = args.end_date or datetime.now().strftime("%Y%m%d")
    
    if not args.financial_only:
        query_price_data(stock_codes, start_date=args.start_date, end_date=end_date)
    
    if not args.price_only:
        query_financial_data(stock_codes)
    
    print("\nAll data downloading completed!")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 测试数据加载模块（先不执行下载）**

```bash
cd backtesting
python data_loader.py --help
```
Expected: 显示命令行帮助信息

---

## Phase 3: 交易日历模块

### Task 3.1: 编写交易日历模块 trading_calendar.py

**Files:**
- Create: `backtesting/trading_calendar.py`

- [ ] **Step 1: 创建 trading_calendar.py 文件**

```python
"""
交易日历管理模块
构建交易日列表，确定每周截面日和调仓日
"""

import pandas as pd
import numpy as np
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config


def build_trading_calendar(start_date: str = "2015-01-01", 
                           end_date: str = None) -> list:
    """
    从价格数据中构建交易日历
    
    交易日定义为：至少有一只股票有行情数据的日期（剔除周末和节假日）
    
    Args:
        start_date: 起始日期
        end_date: 结束日期（None 表示从数据中获取最晚日期）
    
    Returns:
        交易日列表，按日期升序排列
    """
    price_dir = config.PRICE_DATA_DIR
    if not os.path.exists(price_dir):
        raise FileNotFoundError(f"Price data directory not found: {price_dir}")
    
    # 从所有价格文件中提取日期
    all_dates = set()
    
    files = os.listdir(price_dir)
    sample_files = files[:min(10, len(files))]  # 取前10个文件作为样本
    
    for filename in sample_files:
        if filename.endswith('.csv') and filename.startswith('price_'):
            filepath = os.path.join(price_dir, filename)
            df = pd.read_csv(filepath, usecols=['trade_date'], parse_dates=['trade_date'])
            all_dates.update(df['trade_date'].tolist())
    
    # 如果样本文件太少，尝试读取全部
    if len(all_dates) < 10:
        for filename in files:
            if filename.endswith('.csv') and filename.startswith('price_'):
                filepath = os.path.join(price_dir, filename)
                df = pd.read_csv(filepath, usecols=['trade_date'], parse_dates=['trade_date'])
                all_dates.update(df['trade_date'].tolist())
    
    # 转为 DataFrame 并排序
    trading_days = sorted([d for d in all_dates 
                          if d >= pd.Timestamp(start_date)])
    
    if end_date:
        end_ts = pd.Timestamp(end_date)
        trading_days = [d for d in trading_days if d <= end_ts]
    
    print(f"Trading calendar: {len(trading_days)} days from {trading_days[0]} to {trading_days[-1]}")
    return trading_days


def get_weekly_cutoff_dates(trading_days: list) -> list:
    """
    确定每周截面日和对应的调仓日
    
    截面日 = 该周最后一个交易日
    调仓日 = 截面日之后的下一个交易日
    
    Returns:
        list of tuples: (截面日, 调仓日)
    """
    cutoffs = []
    
    # 将交易日按周分组
    df = pd.DataFrame({'date': trading_days})
    df['year'] = df['date'].dt.isocalendar().year
    df['week'] = df['date'].dt.isocalendar().week
    
    # 每周取最后一个交易日
    weekly_last = df.groupby(['year', 'week'])['date'].max().reset_index()
    weekly_last = weekly_last.sort_values('date').reset_index(drop=True)
    
    # 为每个截面日找下一个交易日作为调仓日
    for i in range(len(weekly_last)):
        cutoff_date = weekly_last.iloc[i]['date']
        
        # 找下一个交易日
        if i < len(weekly_last) - 1:
            rebalance_date = weekly_last.iloc[i + 1]['date']
        else:
            # 如果是最后一天，尝试从原始交易日找
            cutoff_idx = trading_days.index(cutoff_date) if cutoff_date in trading_days else -1
            if cutoff_idx >= 0 and cutoff_idx < len(trading_days) - 1:
                rebalance_date = trading_days[cutoff_idx + 1]
            else:
                continue  # 无后续交易日
        
        cutoffs.append((cutoff_date, rebalance_date))
    
    print(f"Found {len(cutoffs)} weekly cutoff dates")
    return cutoffs


def get_cutoff_date_for_trade_date(trade_date: pd.Timestamp, 
                                    cutoffs: list) -> pd.Timestamp:
    """
    获取某个调仓日对应的截面日
    
    Args:
        trade_date: 调仓日
        cutoffs: 截面日/调仓日列表
    
    Returns:
        对应的截面日
    """
    for cutoff, rebalance in cutoffs:
        if rebalance == trade_date:
            return cutoff
    return None


def main():
    """测试交易日历"""
    # 构建交易日历
    trading_days = build_trading_calendar()
    
    # 获取周截面日期
    cutoffs = get_weekly_cutoff_dates(trading_days)
    
    # 打印前10个
    print("\nFirst 10 cutoff dates:")
    for cutoff, rebalance in cutoffs[:10]:
        print(f"  Cutoff: {cutoff.strftime('%Y-%m-%d')} -> Rebalance: {rebalance.strftime('%Y-%m-%d')}")
    
    print(f"\nTotal cutoff periods: {len(cutoffs)}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 测试交易日历模块**

```bash
cd backtesting
python trading_calendar.py
```
Expected: 显示交易日历信息和前10个截面日

---

## Phase 4: 选股模块

### Task 4.1: 编写选股模块 stock_selector.py

**Files:**
- Create: `backtesting/stock_selector.py`

- [ ] **Step 1: 创建 stock_selector.py 文件**

```python
"""
选股逻辑模块
执行四步筛选流程：基础过滤 -> 估值分位数筛选 -> ROE筛选 -> 结果处理
"""

import pandas as pd
import numpy as np
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from data_loader import load_price_data, load_financial_data


def get_latest_financial_data(stock_code: str, as_of_date: pd.Timestamp) -> dict:
    """
    获取某股票在某日期之前可用的最新财务数据
    
    Args:
        stock_code: 股票代码
        as_of_date: 查询日期
    
    Returns:
        dict with keys: eps_ttm, bps_ttm, roe_ttm 或 None（无可用数据）
    """
    fin_df = load_financial_data(stock_code)
    if fin_df.empty:
        return None
    
    # 过滤出在该日期之前可用的财报
    available = fin_df[fin_df['ann_available_date'] <= as_of_date]
    
    if available.empty:
        return None
    
    # 取最新的可用财报
    latest = available.sort_values('report_date', ascending=False).iloc[0]
    
    return {
        'eps_ttm': latest['eps_ttm'],
        'bps_ttm': latest['bps_ttm'],
        'roe_ttm': latest['roe_ttm'],
    }


def calculate_valuation(price_df: pd.DataFrame, trade_date: pd.Timestamp,
                        financial_data: dict) -> dict:
    """
    计算某股票在某日的估值指标
    
    Args:
        price_df: 价格数据 DataFrame
        trade_date: 交易日期
        financial_data: 财务数据 dict
    
    Returns:
        dict with keys: pe_ttm, pb_ttm, pr_ttm 或 None
    """
    if financial_data is None:
        return None
    
    # 获取当日收盘价
    day_data = price_df[price_df['trade_date'] == trade_date]
    if day_data.empty:
        return None
    
    close_price = day_data.iloc[0]['close']
    
    eps_ttm = financial_data['eps_ttm']
    bps_ttm = financial_data['bps_ttm']
    roe_ttm = financial_data['roe_ttm']
    
    # 计算估值指标
    pe = close_price / eps_ttm if eps_ttm != 0 and not np.isnan(eps_ttm) else np.nan
    pb = close_price / bps_ttm if bps_ttm != 0 and not np.isnan(bps_ttm) else np.nan
    pr = pe / roe_ttm if roe_ttm != 0 and not np.isnan(roe_ttm) else np.nan
    
    return {
        'pe_ttm': pe,
        'pb_ttm': pb,
        'pr_ttm': pr,
        'roe_ttm': roe_ttm,
    }


def winsorize(series: pd.Series, lower: float = 0.01, upper: float = 0.99) -> pd.Series:
    """
    对数据进行 winsorize 处理（极值截尾）
    
    Args:
        series: 输入数据
        lower: 下限分位数
        upper: 上限分位数
    
    Returns:
        截尾后的数据
    """
    lower_bound = series.quantile(lower)
    upper_bound = series.quantile(upper)
    return series.clip(lower=lower_bound, upper=upper_bound)


def select_stocks(stock_codes: list, trade_date: pd.Timestamp,
                  price_cache: dict = None) -> list:
    """
    执行选股流程，返回入选股票代码列表和估值数据
    
    Args:
        stock_codes: 候选股票池
        trade_date: 截面日
        price_cache: 价格数据缓存（可选）
    
    Returns:
        tuple: (入选股票代码列表, 所有股票的估值数据 DataFrame)
    """
    valuations = []
    
    for code in stock_codes:
        try:
            # 加载价格数据
            if price_cache and code in price_cache:
                price_df = price_cache[code]
            else:
                price_df = load_price_data(code)
            
            if price_df.empty:
                continue
            
            # 检查当日是否有行情（停牌判断）
            day_data = price_df[price_df['trade_date'] == trade_date]
            if day_data.empty:
                continue  # 停牌，跳过
            
            # 获取最新可用财务数据
            fin_data = get_latest_financial_data(code, trade_date)
            if fin_data is None:
                continue
            
            # 计算估值指标
            val = calculate_valuation(price_df, trade_date, fin_data)
            if val is None:
                continue
            
            # 基础过滤：PE/PB/PR/ROE 必须为正
            if val['pe_ttm'] <= 0 or val['pb_ttm'] <= 0 or val['pr_ttm'] <= 0 or val['roe_ttm'] <= 0:
                continue
            
            # 新股排除：上市不足120天的股票
            if price_cache and code in price_cache:
                if is_new_stock(code, price_cache[code], trade_date):
                    continue
            
            val['code'] = code
            valuations.append(val)
            
        except Exception as e:
            continue
    
    if not valuations:
        return [], pd.DataFrame()
    
    val_df = pd.DataFrame(valuations)
    
    # 步骤2: 估值分位数筛选（先进行 winsorize）
    val_df['pe_w'] = winsorize(val_df['pe_ttm'], config.WINSORIZE_LOWER, config.WINSORIZE_UPPER)
    val_df['pb_w'] = winsorize(val_df['pb_ttm'], config.WINSORIZE_LOWER, config.WINSORIZE_UPPER)
    val_df['pr_w'] = winsorize(val_df['pr_ttm'], config.WINSORIZE_LOWER, config.WINSORIZE_UPPER)
    
    # 计算分位数阈值
    pe_threshold = val_df['pe_w'].quantile(config.PE_THRESHOLD)
    pb_threshold = val_df['pb_w'].quantile(config.PB_THRESHOLD)
    pr_threshold = val_df['pr_w'].quantile(config.PR_THRESHOLD)
    
    # 应用筛选
    filtered = val_df[
        (val_df['pe_ttm'] <= pe_threshold) &
        (val_df['pb_ttm'] <= pb_threshold) &
        (val_df['pr_ttm'] <= pr_threshold)
    ].copy()
    
    # 步骤3: ROE筛选
    if filtered.empty:
        return [], val_df
    
    roe_threshold = filtered['roe_ttm'].quantile(config.ROE_THRESHOLD)
    final = filtered[filtered['roe_ttm'] >= roe_threshold].copy()
    
    selected_codes = final['code'].tolist()
    
    return selected_codes, val_df


def main():
    """测试选股模块"""
    from data_loader import load_stock_pool
    
    # 加载股票池
    stock_df = load_stock_pool()
    stock_codes = stock_df['code'].tolist()
    
    # 取最近一个交易日测试
    trading_days = []
    price_dir = config.PRICE_DATA_DIR
    for f in os.listdir(price_dir)[:3]:
        if f.endswith('.csv') and f.startswith('price_'):
            df = pd.read_csv(os.path.join(price_dir, f), parse_dates=['trade_date'])
            trading_days.extend(df['trade_date'].tolist())
    
    test_date = max(trading_days)
    print(f"Testing selection on: {test_date.strftime('%Y-%m-%d')}")
    
    selected, val_df = select_stocks(stock_codes[:100], test_date)  # 测试前100只
    print(f"Selected {len(selected)} stocks: {selected}")


if __name__ == "__main__":
    main()
```

---

## Phase 5: 持仓管理模块

### Task 5.1: 编写持仓管理模块 portfolio.py

**Files:**
- Create: `backtesting/portfolio.py`

- [ ] **Step 1: 创建 portfolio.py 文件**

```python
"""
持仓状态管理模块
维护当前持仓、现金余额，计算总权益，处理集中度控制
"""

import pandas as pd
import numpy as np
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config


class Portfolio:
    """
    持仓管理类
    
    维护：
    - 现金余额
    - 持仓字典 {stock_code: {'shares': int, 'cost_price': float}}
    """
    
    def __init__(self, initial_capital: float = config.INITIAL_CAPITAL):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions = {}  # {code: {'shares': int, 'cost_price': float}}
        self.trade_history = []  # 交易记录
        self.holding_history = []  # 持仓快照
    
    def get_total_equity(self, prices: dict) -> float:
        """
        计算总权益（现金 + 持仓市值）
        
        Args:
            prices: {stock_code: current_price} 当前价格字典
        
        Returns:
            总权益
        """
        market_value = sum(
            pos['shares'] * prices.get(code, 0)
            for code, pos in self.positions.items()
        )
        return self.cash + market_value
    
    def sell_shares(self, stock_code: str, shares: int, price: float, 
                    reason: str = "调仓卖出") -> dict:
        """
        卖出股票
        
        Args:
            stock_code: 股票代码
            shares: 卖出股数
            price: 卖出价格
            reason: 卖出原因
        
        Returns:
            交易记录 dict
        """
        if stock_code not in self.positions:
            return None
        
        actual_shares = min(shares, self.positions[stock_code]['shares'])
        if actual_shares <= 0:
            return None
        
        # 计算费用
        amount = actual_shares * price
        commission = max(amount * config.COMMISSION_RATE, config.COMMISSION_MIN)
        stamp_tax = amount * config.STAMP_TAX_RATE
        
        # 更新现金和持仓
        self.cash += amount - commission - stamp_tax
        self.positions[stock_code]['shares'] -= actual_shares
        
        # 清仓如果全部卖出
        if self.positions[stock_code]['shares'] <= 0:
            del self.positions[stock_code]
        
        trade_record = {
            'trade_date': None,  # 由外部设置
            'stock_code': stock_code,
            'direction': '卖出',
            'shares': actual_shares,
            'price': price,
            'amount': amount,
            'commission': commission,
            'stamp_tax': stamp_tax,
            'reason': reason,
        }
        self.trade_history.append(trade_record)
        return trade_record
    
    def buy_shares(self, stock_code: str, shares: int, price: float,
                   reason: str = "调仓买入") -> dict:
        """
        买入股票（整手取整）
        
        Args:
            stock_code: 股票代码
            shares: 买入股数
            price: 买入价格
            reason: 买入原因
        
        Returns:
            交易记录 dict 或 None（资金不足）
        """
        if shares <= 0:
            return None
        
        # 计算费用
        amount = shares * price
        commission = max(amount * config.COMMISSION_RATE, config.COMMISSION_MIN)
        total_cost = amount + commission
        
        if total_cost > self.cash:
            # 资金不足，计算最大可买股数
            available = self.cash - config.COMMISSION_MIN
            max_shares = int(available / price / config.LOT_SIZE) * config.LOT_SIZE
            if max_shares <= 0:
                return None
            shares = max_shares
            amount = shares * price
            commission = max(amount * config.COMMISSION_RATE, config.COMMISSION_MIN)
            total_cost = amount + commission
        
        # 更新持仓和现金
        self.cash -= total_cost
        
        if stock_code in self.positions:
            # 加仓：更新加权平均成本
            old_shares = self.positions[stock_code]['shares']
            old_cost = self.positions[stock_code]['cost_price']
            new_shares = old_shares + shares
            new_cost = (old_shares * old_cost + amount) / new_shares
            self.positions[stock_code]['shares'] = new_shares
            self.positions[stock_code]['cost_price'] = new_cost
        else:
            # 新建仓
            self.positions[stock_code] = {
                'shares': shares,
                'cost_price': price,
            }
        
        trade_record = {
            'trade_date': None,
            'stock_code': stock_code,
            'direction': '买入',
            'shares': shares,
            'price': price,
            'amount': amount,
            'commission': commission,
            'stamp_tax': 0.0,
            'reason': reason,
        }
        self.trade_history.append(trade_record)
        return trade_record
    
    def calculate_target_positions(self, target_codes: list, total_equity: float,
                                    prices: dict, can_buy: dict, can_sell: dict) -> dict:
        """
        计算目标调仓方案
        
        Args:
            target_codes: 目标持仓股票代码列表
            total_equity: 调仓前总权益
            prices: 当前价格 {code: price}
            can_buy: {code: bool} 是否可以买入
            can_sell: {code: bool} 是否可以卖出
        
        Returns:
            dict with keys:
            - 'sell_orders': [(code, shares)] 卖出订单
            - 'buy_orders': [(code, target_shares)] 买入订单
        """
        n = len(target_codes)
        sell_orders = []
        buy_orders = []
        
        if n == 0:
            # 空仓：清仓所有可卖出的股票
            for code in list(self.positions.keys()):
                if can_sell.get(code, True):
                    sell_orders.append((code, self.positions[code]['shares']))
            return {'sell_orders': sell_orders, 'buy_orders': buy_orders}
        
        # 步骤1: 生成卖出订单（清仓不在目标池中的股票）
        for code in list(self.positions.keys()):
            if code not in target_codes:
                if can_sell.get(code, True):
                    sell_orders.append((code, self.positions[code]['shares']))
            elif self.positions[code]['shares'] > 0 and not can_sell.get(code, True):
                # 需要卖出但无法卖出（跌停），保留
                pass
        
        # 步骤2: 计算集中度规则下的目标市值
        if n >= config.MIN_FULL_POSITION_STOCKS:
            # 满仓：等分可用资金
            target_value_per_stock = total_equity / n
        else:
            # 集中度控制：单股最大20%，强制保留现金
            target_value_per_stock = config.MAX_SINGLE_POSITION * total_equity
            # 强制保留现金 = (1 - 0.2*N) * total_equity
        
        # 步骤3: 生成买入订单
        for code in target_codes:
            if not can_buy.get(code, True):
                continue  # 无法买入（涨停/停牌）
            
            target_shares = int(target_value_per_stock / prices.get(code, 1) / config.LOT_SIZE) * config.LOT_SIZE
            if target_shares <= 0:
                continue
            
            # 如果已有持仓，只买差额
            current_shares = self.positions.get(code, {}).get('shares', 0)
            needed = target_shares - current_shares
            if needed > 0:
                buy_orders.append((code, needed))
        
        return {'sell_orders': sell_orders, 'buy_orders': buy_orders}
    
    def snapshot_holdings(self, trade_date: pd.Timestamp, prices: dict) -> pd.DataFrame:
        """
        生成当前持仓快照
        
        Args:
            trade_date: 日期
            prices: 当前价格
        
        Returns:
            DataFrame
        """
        total_equity = self.get_total_equity(prices)
        records = []
        
        for code, pos in self.positions.items():
            if pos['shares'] <= 0:
                continue
            
            current_price = prices.get(code, pos['cost_price'])
            market_value = pos['shares'] * current_price
            
            records.append({
                'rebalance_date': trade_date,
                'stock_code': code,
                'shares': pos['shares'],
                'cost_price': pos['cost_price'],
                'current_price': current_price,
                'market_value': market_value,
                'weight': market_value / total_equity if total_equity > 0 else 0,
            })
        
        return pd.DataFrame(records)
    
    def get_daily_equity(self, prices: dict) -> float:
        """获取当日总权益"""
        return self.get_total_equity(prices)
```

---

## Phase 6: 回测引擎模块

### Task 6.1: 编写回测引擎 backtest_engine.py

**Files:**
- Create: `backtesting/backtest_engine.py`

- [ ] **Step 1: 创建 backtest_engine.py 文件（核心逻辑，较长）**

```python
"""
回测核心引擎
遍历交易日历，调用选股模块，执行调仓，记录持仓和交易
"""

import pandas as pd
import numpy as np
import os
import sys
from datetime import datetime
from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from data_loader import load_price_data, load_stock_pool
from trading_calendar import build_trading_calendar, get_weekly_cutoff_dates
from stock_selector import select_stocks
from portfolio import Portfolio


def get_new_stock_listing_dates(stock_code: str, price_df: pd.DataFrame) -> pd.Timestamp:
    """获取股票上市日期（价格数据第一条日期）"""
    if price_df.empty:
        return pd.Timestamp.min
    return price_df['trade_date'].min()


def is_new_stock(stock_code: str, price_df: pd.DataFrame, as_of_date: pd.Timestamp,
                 exclude_days: int = config.NEW_STOCK_EXCLUDE_DAYS) -> bool:
    """检查是否为新股（上市不足 exclude_days 天）"""
    listing_date = get_new_stock_listing_dates(stock_code, price_df)
    days_listed = (as_of_date - listing_date).days
    
    # 估算交易日数量（约 252 天/年）
    trading_days_listed = days_listed * 252 / 365
    return trading_days_listed < exclude_days


def check_limit_up_down(code: str, trade_date: pd.Timestamp, price_df: pd.DataFrame,
                        prev_close: float) -> dict:
    """
    检查股票在调仓日是否涨跌停封死
    
    Args:
        code: 股票代码
        trade_date: 调仓日
        price_df: 该股票价格数据
        prev_close: 前一日收盘价
    
    Returns:
        dict: {'can_buy': bool, 'can_sell': bool}
    """
    limit_ratio = config.get_limit_ratio(code, trade_date.strftime("%Y-%m-%d"))
    tolerance = config.LIMIT_TOLERANCE
    
    day_data = price_df[price_df['trade_date'] == trade_date]
    if day_data.empty:
        return {'can_buy': False, 'can_sell': False}  # 停牌
    
    open_price = day_data.iloc[0]['open']
    high_price = day_data.iloc[0]['high']
    low_price = day_data.iloc[0]['low']
    
    # 涨停判断：开盘价和最低价都封死涨停
    limit_up_price = prev_close * (1 + limit_ratio - tolerance)
    can_buy = not (open_price >= limit_up_price and low_price >= limit_up_price)
    
    # 跌停判断：开盘价和最高价都封死跌停
    limit_down_price = prev_close * (1 - limit_ratio + tolerance)
    can_sell = not (open_price <= limit_down_price and high_price <= limit_down_price)
    
    return {'can_buy': can_buy, 'can_sell': can_sell}


def get_new_stock_listing_dates(stock_code: str, price_df: pd.DataFrame) -> pd.Timestamp:
    """获取股票上市日期（价格数据第一条日期）"""
    if price_df.empty:
        return pd.Timestamp.min
    return price_df['trade_date'].min()


def is_new_stock(stock_code: str, price_df: pd.DataFrame, as_of_date: pd.Timestamp,
                 exclude_days: int = config.NEW_STOCK_EXCLUDE_DAYS) -> bool:
    """检查是否为新股（上市不足 exclude_days 天）"""
    listing_date = get_new_stock_listing_dates(stock_code, price_df)
    days_listed = (as_of_date - listing_date).days
    
    # 估算交易日数量（约 252 天/年）
    trading_days_listed = days_listed * 252 / 365
    return trading_days_listed < exclude_days


def run_backtest(start_date: str = config.START_DATE,
                 end_date: str = None) -> dict:
    """
    执行完整回测
    
    Args:
        start_date: 回测起始日期
        end_date: 回测结束日期
    
    Returns:
        dict with keys:
        - 'portfolio': Portfolio 对象
        - 'equity_curve': DataFrame (date, strategy_equity, benchmark_equity)
        - 'trade_records': list
        - 'holding_snapshots': list
        - 'cutoff_dates': list
    """
    print("=" * 60)
    print("Starting backtest...")
    print("=" * 60)
    
    # 1. 加载股票池
    print("\n[1/5] Loading stock pool...")
    stock_df = load_stock_pool()
    stock_codes = stock_df['code'].tolist()
    print(f"Total stocks in pool: {len(stock_codes)}")
    
    # 2. 构建交易日历
    print("\n[2/5] Building trading calendar...")
    trading_days = build_trading_calendar(start_date, end_date)
    cutoffs = get_weekly_cutoff_dates(trading_days)
    print(f"Trading days: {len(trading_days)}, Cutoff periods: {len(cutoffs)}")
    
    # 3. 预加载价格数据到缓存
    print("\n[3/5] Pre-loading price data...")
    price_cache = {}
    for code in tqdm(stock_codes, desc="Loading prices"):
        df = load_price_data(code)
        if not df.empty:
            price_cache[code] = df
    
    # 4. 计算基准（等权组合）
    print("\n[4/5] Calculating benchmark (equal-weight portfolio)...")
    benchmark_values = {}  # {date: value}
    
    # 基准：初始 100 万，等权分配到每只股票，每周再平衡
    # 简化计算：每天计算等权组合的净值
    initial_benchmark_value = config.INITIAL_CAPITAL
    if len(stock_codes) > 0:
        shares_per_stock = {}
        # 第一个交易日建仓
        first_day = cutoffs[0][0] if cutoffs else trading_days[0]
        for code in stock_codes:
            df = price_cache.get(code)
            if df is None or df.empty:
                continue
            day_data = df[df['trade_date'] == first_day]
            if day_data.empty:
                continue
            price = day_data.iloc[0]['close']
            invest_amount = initial_benchmark_value / len(stock_codes)
            shares_per_stock[code] = int(invest_amount / price / config.LOT_SIZE) * config.LOT_SIZE
        
        # 计算每日基准净值
        for day in trading_days:
            # 每周一再平衡（简化处理）
            week_num = day.isocalendar()[1]
            prev_day_num = (day - pd.Timedelta(days=1)).isocalendar()[1]
            if week_num != prev_day_num or day == trading_days[0]:
                # 再平衡
                total_value = sum(
                    shares * price_cache[code][price_cache[code]['trade_date'] <= day].iloc[-1]['close']
                    for code, shares in shares_per_stock.items()
                    if code in price_cache and not price_cache[code][price_cache[code]['trade_date'] <= day].empty
                )
                # 重新分配
                for code in stock_codes:
                    df = price_cache.get(code)
                    if df is None or df.empty:
                        continue
                    day_data = df[df['trade_date'] == day]
                    if day_data.empty:
                        continue
                    price = day_data.iloc[0]['close']
                    invest_amount = total_value / len(stock_codes) if len(stock_codes) > 0 else 0
                    shares_per_stock[code] = int(invest_amount / price / config.LOT_SIZE) * config.LOT_SIZE
            
            # 计算当日净值
            total_value = 0
            for code, shares in shares_per_stock.items():
                df = price_cache.get(code)
                if df is None or df.empty:
                    continue
                day_data = df[df['trade_date'] == day]
                if not day_data.empty:
                    total_value += shares * day_data.iloc[0]['close']
            
            benchmark_values[day] = total_value
    
    # 5. 执行回测
    print("\n[5/5] Running backtest engine...")
    portfolio = Portfolio(initial_capital=config.INITIAL_CAPITAL)
    equity_curve = []  # [(date, strategy_equity, benchmark_value)]
    trade_records = []
    holding_snapshots = []
    
    # 截面日选股缓存
    cutoff_stock_pools = {}  # {cutoff_date: selected_codes}
    
    # 先执行选股（所有截面日）
    print("  Running stock selection for each cutoff date...")
    for cutoff_date, _ in tqdm(cutoffs, desc="Selecting stocks"):
        selected, _ = select_stocks(stock_codes, cutoff_date, price_cache)
        cutoff_stock_pools[cutoff_date] = selected
    
    # 执行调仓
    print("  Executing rebalances...")
    for cutoff_date, rebalance_date in tqdm(cutoffs, desc="Rebalancing"):
        target_codes = cutoff_stock_pools.get(cutoff_date, [])
        
        # 获取当前价格
        prices = {}
        can_buy = {}
        can_sell = {}
        prev_closes = {}
        
        for code in stock_codes:
            df = price_cache.get(code)
            if df is None or df.empty:
                continue
            
            # 当前日价格
            day_data = df[df['trade_date'] == rebalance_date]
            if day_data.empty:
                continue
            
            prices[code] = day_data.iloc[0]['open']
            
            # 前一日收盘价（用于涨跌停判断）
            prev_data = df[df['trade_date'] < rebalance_date]
            if not prev_data.empty:
                prev_closes[code] = prev_data.iloc[-1]['close']
            else:
                prev_closes[code] = prices[code]
            
            # 检查可交易性
            limit_status = check_limit_up_down(code, rebalance_date, df, prev_closes.get(code, prices[code]))
            can_buy[code] = limit_status['can_buy']
            can_sell[code] = limit_status['can_sell']
        
        # 计算总权益
        total_equity = portfolio.get_total_equity(prices)
        
        # 计算目标调仓方案
        target_plan = portfolio.calculate_target_positions(
            target_codes, total_equity, prices, can_buy, can_sell
        )
        
        # 执行卖出
        for code, shares in target_plan['sell_orders']:
            if code in prices:
                trade = portfolio.sell_shares(code, shares, prices[code], reason="调仓卖出")
                if trade:
                    trade['trade_date'] = rebalance_date
                    trade_records.append(trade)
        
        # 执行买入
        for code, shares in target_plan['buy_orders']:
            if code in prices:
                trade = portfolio.buy_shares(code, shares, prices[code], reason="调仓买入")
                if trade:
                    trade['trade_date'] = rebalance_date
                    trade_records.append(trade)
        
        # 记录持仓快照
        snapshot = portfolio.snapshot_holdings(rebalance_date, prices)
        if not snapshot.empty:
            holding_snapshots.append(snapshot)
    
    # 计算每日权益曲线
    print("  Calculating equity curve...")
    for day in tqdm(trading_days, desc="Computing daily equity"):
        prices = {}
        for code in stock_codes:
            df = price_cache.get(code)
            if df is None or df.empty:
                continue
            day_data = df[df['trade_date'] == day]
            if not day_data.empty:
                prices[code] = day_data.iloc[0]['close']
        
        strategy_equity = portfolio.get_daily_equity(prices)
        benchmark_value = benchmark_values.get(day, config.INITIAL_CAPITAL)
        
        equity_curve.append({
            'date': day,
            'strategy_equity': strategy_equity,
            'benchmark_equity': benchmark_value,
        })
    
    equity_df = pd.DataFrame(equity_curve)
    
    return {
        'portfolio': portfolio,
        'equity_curve': equity_df,
        'trade_records': trade_records,
        'holding_snapshots': holding_snapshots,
        'cutoff_dates': cutoffs,
    }


def main():
    """主函数：执行回测"""
    import argparse
    parser = argparse.ArgumentParser(description="执行回测")
    parser.add_argument("--start_date", type=str, default=config.START_DATE,
                        help="回测起始日期，格式 YYYY-MM-DD")
    parser.add_argument("--end_date", type=str, default=None,
                        help="回测结束日期，格式 YYYY-MM-DD")
    
    args = parser.parse_args()
    
    result = run_backtest(args.start_date, args.end_date)
    
    # 保存结果
    save_results(result)
    
    # 计算最终权益
    equity_df = result['equity_curve']
    final_equity = equity_df.iloc[-1]['strategy_equity'] if not equity_df.empty else config.INITIAL_CAPITAL
    
    print("\nBacktest completed!")
    print(f"Initial capital: {config.INITIAL_CAPITAL:,.0f}")
    print(f"Final equity: {final_equity:,.0f}")
    print(f"Cumulative return: {final_equity/config.INITIAL_CAPITAL - 1:.2%}")


def save_results(result: dict):
    """保存回测结果到文件"""
    # 保存持仓明细
    if result['holding_snapshots']:
        all_holdings = pd.concat(result['holding_snapshots'], ignore_index=True)
        all_holdings.to_csv(os.path.join(config.HOLDINGS_DIR, "holdings_summary.csv"), index=False)
        print(f"Saved holdings to {config.HOLDINGS_DIR}/holdings_summary.csv")
    
    # 保存交易记录
    if result['trade_records']:
        trades_df = pd.DataFrame(result['trade_records'])
        trades_df.to_csv(os.path.join(config.TRADES_DIR, "trades_record.csv"), index=False)
        print(f"Saved trades to {config.TRADES_DIR}/trades_record.csv")
    
    # 保存权益曲线
    if not result['equity_curve'].empty:
        result['equity_curve'].to_csv(os.path.join(config.PERFORMANCE_DIR, "equity_curve.csv"), index=False)
        print(f"Saved equity curve to {config.PERFORMANCE_DIR}/equity_curve.csv")


if __name__ == "__main__":
    import argparse
    main()
```

---

## Phase 7: 绩效计算模块

### Task 7.1: 编写绩效计算模块 performance.py

**Files:**
- Create: `backtesting/performance.py`

- [ ] **Step 1: 创建 performance.py 文件**

```python
"""
绩效指标计算模块
计算累计收益、年化收益、夏普比率、最大回撤、胜率、换手率等指标
"""

import pandas as pd
import numpy as np
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config


def calculate_performance(equity_df: pd.DataFrame, 
                          cutoffs: list = None,
                          trade_records: list = None) -> dict:
    """
    计算回测绩效指标
    
    Args:
        equity_df: DataFrame with columns [date, strategy_equity, benchmark_equity]
        cutoffs: 截面日列表（用于计算胜率）
    
    Returns:
        dict of performance metrics
    """
    if equity_df.empty:
        return {}
    
    df = equity_df.copy()
    df['strategy_return'] = df['strategy_equity'].pct_change()
    df['benchmark_return'] = df['benchmark_equity'].pct_change()
    df['excess_return'] = df['strategy_return'] - df['benchmark_return']
    
    # 累计收益
    initial = df.iloc[0]['strategy_equity']
    final = df.iloc[-1]['strategy_equity']
    cumulative_return = final / initial - 1
    
    # 年化收益
    trading_days = len(df)
    annual_return = (1 + cumulative_return) ** (252 / trading_days) - 1
    
    # 年化波动率
    daily_vol = df['strategy_return'].std()
    annual_vol = daily_vol * np.sqrt(252)
    
    # 夏普比率
    sharpe = (annual_return - config.RISK_FREE_RATE) / annual_vol if annual_vol > 0 else 0
    
    # 最大回撤
    df['strategy_peak'] = df['strategy_equity'].cummax()
    df['drawdown'] = (df['strategy_equity'] - df['strategy_peak']) / df['strategy_peak']
    max_drawdown = df['drawdown'].min()
    
    # 回撤持续时间
    max_dd_end_idx = df['drawdown'].idxmin()
    peak_idx = df.loc[:max_dd_end_idx]['strategy_equity'].idxmax()
    recovery_idx = df.loc[max_dd_end_idx:]['strategy_equity'][
        df.loc[max_dd_end_idx:]['strategy_equity'] >= df.loc[peak_idx]['strategy_equity']
    ].index.min()
    
    dd_duration = (df.loc[max_dd_end_idx, 'date'] - df.loc[peak_idx, 'date']).days
    recovery_duration = (df.loc[recovery_idx, 'date'] - df.loc[max_dd_end_idx, 'date']).days if pd.notna(recovery_idx) else None
    
    # 基准指标
    benchmark_cumulative = df.iloc[-1]['benchmark_equity'] / df.iloc[0]['benchmark_equity'] - 1
    benchmark_annual = (1 + benchmark_cumulative) ** (252 / trading_days) - 1
    
    # 超额收益
    excess_return = cumulative_return - benchmark_cumulative
    excess_daily = df['excess_return'].dropna()
    tracking_error = excess_daily.std() * np.sqrt(252)
    information_ratio = (excess_return * 252 / trading_days) / tracking_error if tracking_error > 0 else 0
    
    # 胜率（按调仓周期）
    win_rate, profit_loss_ratio = 0, 0
    avg_turnover = 0
    if cutoffs and len(cutoffs) > 0:
        win_rate, profit_loss_ratio = _calculate_win_rate(df, cutoffs)
    if trade_records:
        avg_turnover = _calculate_turnover_from_trades(trade_records, equity_df)
    
    # 分年度收益
    df['year'] = df['date'].dt.year
    annual_returns = df.groupby('year').agg(
        strategy_return=('strategy_equity', lambda x: x.iloc[-1] / x.iloc[0] - 1),
        benchmark_return=('benchmark_equity', lambda x: x.iloc[-1] / x.iloc[0] - 1),
    ).reset_index()
    annual_returns['excess_return'] = annual_returns['strategy_return'] - annual_returns['benchmark_return']
    
    return {
        'cumulative_return': cumulative_return,
        'annual_return': annual_return,
        'annual_volatility': annual_vol,
        'sharpe_ratio': sharpe,
        'max_drawdown': max_drawdown,
        'max_drawdown_duration_days': dd_duration,
        'recovery_days': recovery_duration,
        'win_rate': win_rate,
        'profit_loss_ratio': profit_loss_ratio,
        'avg_weekly_turnover': avg_turnover,
        'benchmark_cumulative_return': benchmark_cumulative,
        'benchmark_annual_return': benchmark_annual,
        'excess_return': excess_return,
        'tracking_error': tracking_error,
        'information_ratio': information_ratio,
        'annual_returns': annual_returns,
        'trading_days': trading_days,
        'initial_capital': initial,
        'final_equity': final,
    }


def _calculate_win_rate(equity_df: pd.DataFrame, cutoffs: list) -> tuple:
    """计算胜率"""
    winning_periods = 0
    losing_periods = 0
    avg_win = 0
    avg_loss = 0
    
    prev_equity = equity_df.iloc[0]['strategy_equity']
    returns = []
    
    for _, rebalance_date in cutoffs:
        day_data = equity_df[equity_df['date'] == rebalance_date]
        if day_data.empty:
            continue
        
        current_equity = day_data.iloc[0]['strategy_equity']
        period_return = (current_equity - prev_equity) / prev_equity
        returns.append(period_return)
        
        if period_return > 0:
            winning_periods += 1
            avg_win += period_return
        elif period_return < 0:
            losing_periods += 1
            avg_loss += abs(period_return)
        
        prev_equity = current_equity
    
    total = winning_periods + losing_periods
    win_rate = winning_periods / total if total > 0 else 0
    profit_loss_ratio = (avg_win / winning_periods) / (avg_loss / losing_periods) if winning_periods > 0 and losing_periods > 0 else 0
    
    return win_rate, profit_loss_ratio


def _calculate_turnover_from_trades(trade_records: list, equity_df: pd.DataFrame) -> float:
    """从交易记录计算平均换手率"""
    if not trade_records:
        return 0
    
    # 按日期分组
    df = pd.DataFrame(trade_records)
    if 'trade_date' not in df.columns or df['trade_date'].isna().all():
        return 0
    
    turnovers = []
    for date, group in df.groupby('trade_date'):
        # 获取调仓前总权益
        day_data = equity_df[equity_df['date'] == date]
        if day_data.empty:
            continue
        prev_equity = day_data.iloc[0]['strategy_equity']
        if prev_equity <= 0:
            continue
        
        # 换手率 = (买入额 + 卖出额) / 2 / 调仓前总权益
        total_amount = group['amount'].sum()
        turnover = total_amount / 2 / prev_equity
        turnovers.append(turnover)
    
    return np.mean(turnovers) if turnovers else 0


def save_performance_summary(performance: dict, filepath: str):
    """保存绩效汇总到 CSV"""
    records = [
        ('累计收益率', f"{performance['cumulative_return']*100:.2f}%"),
        ('年化收益率', f"{performance['annual_return']*100:.2f}%"),
        ('年化波动率', f"{performance['annual_volatility']*100:.2f}%"),
        ('夏普比率', f"{performance['sharpe_ratio']:.3f}"),
        ('最大回撤', f"{performance['max_drawdown']*100:.2f}%"),
        ('最大回撤持续天数', f"{performance['max_drawdown_duration_days']}天"),
        ('胜率', f"{performance['win_rate']*100:.2f}%"),
        ('盈亏比', f"{performance['profit_loss_ratio']:.2f}"),
        ('平均周换手率', f"{performance['avg_weekly_turnover']*100:.2f}%"),
        ('基准累计收益率', f"{performance['benchmark_cumulative_return']*100:.2f}%"),
        ('基准年化收益率', f"{performance['benchmark_annual_return']*100:.2f}%"),
        ('超额收益率', f"{performance['excess_return']*100:.2f}%"),
        ('跟踪误差', f"{performance['tracking_error']*100:.2f}%"),
        ('信息比率', f"{performance['information_ratio']:.3f}"),
    ]
    
    summary_df = pd.DataFrame(records, columns=['指标', '值'])
    summary_df.to_csv(filepath, index=False)
    print(f"Performance summary saved to {filepath}")
```

---

## Phase 8: 可视化模块

### Task 8.1: 编写可视化模块 visualizer.py

**Files:**
- Create: `backtesting/visualizer.py`

- [ ] **Step 1: 创建 visualizer.py 文件**

```python
"""
可视化输出模块
绘制净值曲线图、回撤图、分年度收益热图
"""

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import seaborn as sns
import pandas as pd
import numpy as np
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config


def plot_equity_curve(equity_df: pd.DataFrame, save_path: str = None):
    """
    绘制净值曲线图（含回撤阴影）
    
    Args:
        equity_df: DataFrame with columns [date, strategy_equity, benchmark_equity]
        save_path: 保存路径
    """
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), gridspec_kw={'height_ratios': [3, 1]})
    
    # 净值曲线
    ax1.plot(equity_df['date'], equity_df['strategy_equity'] / config.INITIAL_CAPITAL,
             label='策略净值', color='#eeb908', linewidth=1.5)
    ax1.plot(equity_df['date'], equity_df['benchmark_equity'] / config.INITIAL_CAPITAL,
             label='基准净值', color='gray', linewidth=1.0, linestyle='--')
    
    ax1.set_title('策略净值曲线 vs 基准', fontsize=14, fontweight='bold')
    ax1.set_ylabel('净值倍数')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax1.xaxis.set_major_locator(mdates.YearLocator())
    
    # 回撤图
    df = equity_df.copy()
    df['peak'] = df['strategy_equity'].cummax()
    df['drawdown'] = (df['strategy_equity'] - df['peak']) / df['peak'] * 100
    
    ax2.fill_between(df['date'], df['drawdown'], 0, color='red', alpha=0.3)
    ax2.set_title('回撤', fontsize=12)
    ax2.set_ylabel('回撤 %')
    ax2.grid(True, alpha=0.3)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=200, bbox_inches='tight')
        print(f"Equity curve saved to {save_path}")
    
    plt.close()


def plot_annual_heatmap(annual_returns_df: pd.DataFrame, save_path: str = None):
    """
    绘制分年度收益热图
    
    Args:
        annual_returns_df: DataFrame with columns [year, strategy_return, benchmark_return, excess_return]
        save_path: 保存路径
    """
    fig, ax = plt.subplots(figsize=(10, len(annual_returns_df) * 0.5 + 2))
    
    # 准备数据
    data = annual_returns_df[['strategy_return', 'benchmark_return', 'excess_return']].values
    labels = ['策略收益', '基准收益', '超额收益']
    
    # 绘制热图
    im = ax.imshow(data, cmap='RdYlGn', aspect='auto', vmin=-0.3, vmax=0.5)
    
    # 设置标签
    ax.set_yticks(range(len(annual_returns_df)))
    ax.set_yticklabels(annual_returns_df['year'].astype(str))
    ax.set_xticks(range(3))
    ax.set_xticklabels(labels, fontsize=10)
    
    # 添加数值标签
    for i in range(len(annual_returns_df)):
        for j in range(3):
            val = data[i, j]
            color = 'white' if abs(val) > 0.2 else 'black'
            ax.text(j, i, f'{val*100:.1f}%', ha='center', va='center', color=color, fontweight='bold')
    
    ax.set_title('分年度收益热图', fontsize=14, fontweight='bold')
    
    plt.colorbar(im, ax=ax, label='收益率')
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=200, bbox_inches='tight')
        print(f"Annual heatmap saved to {save_path}")
    
    plt.close()


def generate_all_visualizations(performance: dict, equity_df: pd.DataFrame):
    """
    生成所有可视化图表
    
    Args:
        performance: 绩效指标 dict
        equity_df: 权益曲线 DataFrame
    """
    # 净值曲线
    equity_curve_path = os.path.join(config.CHARTS_DIR, "equity_curve.png")
    plot_equity_curve(equity_df, equity_curve_path)
    
    # 分年度收益热图
    if 'annual_returns' in performance and not performance['annual_returns'].empty:
        heatmap_path = os.path.join(config.CHARTS_DIR, "annual_heatmap.png")
        plot_annual_heatmap(performance['annual_returns'], heatmap_path)
    
    # 打印绩效汇总
    print("\n" + "=" * 60)
    print("回测绩效汇总")
    print("=" * 60)
    print(f"累计收益率: {performance['cumulative_return']*100:.2f}%")
    print(f"年化收益率: {performance['annual_return']*100:.2f}%")
    print(f"年化波动率: {performance['annual_volatility']*100:.2f}%")
    print(f"夏普比率: {performance['sharpe_ratio']:.3f}")
    print(f"最大回撤: {performance['max_drawdown']*100:.2f}%")
    print(f"胜率: {performance['win_rate']*100:.2f}%")
    print(f"盈亏比: {performance['profit_loss_ratio']:.2f}")
    print(f"超额收益率: {performance['excess_return']*100:.2f}%")
    print(f"信息比率: {performance['information_ratio']:.3f}")
    print("=" * 60)
    
    # 保存绩效汇总
    perf_path = os.path.join(config.PERFORMANCE_DIR, "performance_summary.csv")
    from performance import save_performance_summary
    save_performance_summary(performance, perf_path)
    
    # 保存分年度收益
    if 'annual_returns' in performance:
        annual_path = os.path.join(config.PERFORMANCE_DIR, "annual_returns.csv")
        performance['annual_returns'].to_csv(annual_path, index=False)
        print(f"Annual returns saved to {annual_path}")
```

---

## Phase 9: 主运行脚本

### Task 9.1: 编写主运行脚本 run_backtest.py

**Files:**
- Create: `backtesting/run_backtest.py`

- [ ] **Step 1: 创建 run_backtest.py 文件**

```python
"""
回测主运行入口
整合各模块，执行完整回测流程
"""

import sys
import os
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from data_loader import load_stock_pool, query_price_data, query_financial_data
from backtest_engine import run_backtest
from performance import calculate_performance, save_performance_summary
from visualizer import generate_all_visualizations


def main():
    parser = argparse.ArgumentParser(description="选股策略回测系统")
    parser.add_argument("--fetch_data", action="store_true", help="先拉取数据再执行回测")
    parser.add_argument("--start_date", type=str, default=config.START_DATE,
                        help="回测起始日期，格式 YYYY-MM-DD")
    parser.add_argument("--end_date", type=str, default=None,
                        help="回测结束日期，格式 YYYY-MM-DD")
    parser.add_argument("--price_start", type=str, default="20150101",
                        help="价格数据起始日期，格式 YYYYMMDD")
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("  选股策略回测系统 v1.0")
    print("=" * 60)
    print(f"  回测区间: {args.start_date} ~ {args.end_date or '最新'}")
    print(f"  初始资金: {config.INITIAL_CAPITAL:,.0f} 元")
    print(f"  股票池: {len(config.STOCK_POOLS)} 个列表")
    print("=" * 60)
    
    # 确保目录存在
    config.ensure_dirs()
    
    # 如果需要，先拉取数据
    if args.fetch_data:
        print("\n>>> Phase 1: 拉取数据")
        stock_df = load_stock_pool()
        stock_codes = stock_df['code'].tolist()
        
        print("\n[1a] 下载价格数据...")
        query_price_data(stock_codes, start_date=args.price_start)
        
        print("\n[1b] 下载财务数据...")
        query_financial_data(stock_codes)
    
    # 执行回测
    print("\n>>> Phase 2: 执行回测")
    result = run_backtest(args.start_date, args.end_date)
    
    # 计算绩效
    print("\n>>> Phase 3: 计算绩效")
    performance = calculate_performance(
        result['equity_curve'], 
        result['cutoff_dates'],
        result['trade_records']
    )
    
    # 生成可视化
    print("\n>>> Phase 4: 生成可视化报告")
    generate_all_visualizations(performance, result['equity_curve'])
    
    print("\n" + "=" * 60)
    print("  回测完成！")
    print("=" * 60)
    print(f"\n结果保存在:")
    print(f"  持仓明细: {config.HOLDINGS_DIR}/")
    print(f"  交易记录: {config.TRADES_DIR}/")
    print(f"  绩效指标: {config.PERFORMANCE_DIR}/")
    print(f"  图表输出: {config.CHARTS_DIR}/")


if __name__ == "__main__":
    main()
```

---

## Phase 10: 测试与验证

### Task 10.1: 验证模块可导入性

- [ ] **Step 1: 测试各模块导入**

```bash
cd backtesting
python -c "import config; print('config OK')"
python -c "import config; import data_loader; print('data_loader OK')"
python -c "import config; import trading_calendar; print('trading_calendar OK')"
python -c "import config; import stock_selector; print('stock_selector OK')"
python -c "import config; import portfolio; print('portfolio OK')"
python -c "import config; import backtest_engine; print('backtest_engine OK')"
python -c "import config; import performance; print('performance OK')"
python -c "import config; import visualizer; print('visualizer OK')"
```

- [ ] **Step 2: 测试配置模块**

```bash
cd backtesting
python config.py
```
Expected: 目录创建成功，涨跌幅测试输出正确

### Task 10.2: 运行完整回测

- [ ] **Step 1: 运行回测（首次需要先获取数据）**

```bash
cd backtesting
python run_backtest.py --fetch_data --start_date 2023-01-01 --end_date 2023-12-31
```
Note: 先用较短的测试区间（2023年）验证，成功后再跑全量。

Expected:
- 数据拉取完成
- 回测执行完成
- 输出绩效汇总
- 生成图表

- [ ] **Step 2: 验证输出文件**

```bash
ls -la data/processed/backtesting/holdings/
ls -la data/processed/backtesting/trades/
ls -la data/processed/backtesting/performance/
ls -la data/processed/backtesting/charts/
```
Expected: 所有输出文件存在且非空

- [ ] **Step 3: 运行完整回测（2015年至今）**

```bash
cd backtesting
python run_backtest.py --start_date 2015-01-01
```
Expected: 完整回测完成，输出所有图表和绩效指标