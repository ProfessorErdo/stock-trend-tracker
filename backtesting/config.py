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
WINSORIZE_ENABLED = True     # 是否启用1%/99%截尾（True=启用，False=跳过）
WINSORIZE_LOWER = 0.01       # 极值截尾下限（1%）
WINSORIZE_UPPER = 0.99       # 极值截尾上限（99%）

# 新股排除
NEW_STOCK_EXCLUDE_DAYS = 120  # 排除上市不足120天的股票
MAX_POSITIONS = 5             # 最大持仓股票数量


# ============== 调仓参数 ==============
REBALANCE_FREQUENCY = "weekly"   # 调仓频率: "weekly", "monthly", or "quarterly"
MIN_FULL_POSITION_STOCKS = 5  # N>=5时满仓，N<5启用集中度控制
MAX_SINGLE_POSITION = 0.20    # 单股最大仓位（20%）
LOT_SIZE = 100                # 每手股数（A股100股/手）


# ============== 交易成本参数 ==============
COMMISSION_RATE = 0.0003      # 佣金率（0.03%）
COMMISSION_MIN = 5            # 最低佣金（元）
STAMP_TAX_RATE = 0.001        # 印花税率（卖出0.1%）
SLIPPAGE_RATE = 0.001         # 滑点率（0.1%，买入加价、卖出减价）


# ============== 止损参数 ==============
STOP_LOSS_ENABLED = False       # 是否启用止损
STOP_LOSS_HALF_DRAWDOWN = 0.15  # 回撤15%，减半仓位
STOP_LOSS_FULL_DRAWDOWN = 0.25  # 回撤25%，清仓离场


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
    trade_dt = datetime.strptime(trade_date, "%Y-%m-%d") if isinstance(trade_date, str) else trade_dt

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


if __name__ == "__main__":
    # 测试配置模块
    ensure_dirs()

    # 测试涨跌幅获取
    print(f"600519 在 2020-08-20 涨跌幅: {get_limit_ratio('600519', '2020-08-20')}")
    print(f"300001 在 2020-08-20 涨跌幅: {get_limit_ratio('300001', '2020-08-20')}")
    print(f"300001 在 2020-08-24 涨跌幅: {get_limit_ratio('300001', '2020-08-24')}")
    print(f"688001 在 2024-01-15 涨跌幅: {get_limit_ratio('688001', '2024-01-15')}")
