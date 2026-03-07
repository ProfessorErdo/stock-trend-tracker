# Stock Trend Tracker

A Python-based stock analysis tool that queries financial and price data, calculates valuation metrics, and identifies undervalued stocks based on PE, PB, PR, and ROE indicators.

## Features

- **Incremental Data Query**: Only fetches new data since last update, significantly reducing query time
- **Multi-Source Support**: Query data for different stock lists (HS300, ZZ500, Hongli, Honglidibo, Portfolio)
- **Valuation Analysis**: Calculate PE-TTM, PB-TTM, PR-TTM, and ROE-TTM metrics
- **Stock Screening**: Filter stocks based on quantile thresholds
- **Visualization**: Generate distribution plots for selected stocks
- **Email Reports**: Send analysis results with inline charts via email

## Project Structure

```
stock-trend-tracker/
├── data/
│   ├── input/
│   │   ├── financial-indicators/all/    # Financial data (EPS, BPS, ROE)
│   │   ├── price-data/all/              # Daily price data (OHLC)
│   │   ├── query_metadata.json          # Tracks last update times
│   │   └── *.csv                        # Stock lists
│   └── processed/
│       └── stock-valuation/all/         # Calculated valuations
├── img/                                  # Generated visualization plots
├── notebooks/                            # Jupyter notebooks for analysis
├── src/
│   ├── query_data_new.py                # Incremental data query
│   ├── calculation_and_visualization_new.py  # Valuation calculation
│   ├── send_emails_new.py               # Email reporting
│   └── run_new.sh                       # Pipeline runner
├── pyproject.toml
└── README.md
```

## Installation

### Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) package manager

### Setup

```bash
# Clone the repository
git clone https://github.com/yourusername/stock-trend-tracker.git
cd stock-trend-tracker

# Install dependencies
uv sync
```

### Environment Variables

Create a `.env` file in the project root for email functionality:

```env
SMTP_SERVER=smtp.example.com
SENDER_EMAIL=your_email@example.com
EMAIL_AUTH_CODE=your_auth_code
RECEIVER_EMAIL=recipient@example.com
```

## Usage

### Quick Start

Run the complete pipeline:

```bash
cd src
chmod +x run_new.sh
./run_new.sh
```

### Individual Scripts

#### 1. Query Data

```bash
# Query price data (daily incremental)
python query_data_new.py --data_type price --stock_type hs300

# Query financial data (monthly incremental)
python query_data_new.py --data_type financial --stock_type hs300

# Force query all stocks
python query_data_new.py --data_type price --stock_type hs300 --force

# Query with price adjustment (for backtesting)
python query_data_new.py --data_type price --stock_type hs300 --adjust hfq
```

**Parameters:**

| Parameter | Values | Description |
|-----------|--------|-------------|
| `--data_type` | `financial`, `price` | Type of data to query |
| `--stock_type` | `hs300`, `zz500`, `hongli`, `honglidibo`, `portfolio`, `all` | Stock list to query |
| `--force` | - | Force query all stocks |
| `--season_end` | `YYYY-MM-DD` | End date for financial data (default: `2025-12-31`) |
| `--adjust` | `''`, `qfq`, `hfq` | Price adjustment method |

#### 2. Calculate Valuations & Visualize

```bash
# Run both calculation and visualization
python calculation_and_visualization_new.py --step all --threshold 0.26

# Run only calculation
python calculation_and_visualization_new.py --step value

# Run only visualization
python calculation_and_visualization_new.py --step visualize --threshold 0.26
```

**Parameters:**

| Parameter | Values | Description |
|-----------|--------|-------------|
| `--step` | `value`, `visualize`, `all` | Which step to run |
| `--threshold` | `0.0` - `1.0` | Quantile threshold for filtering (default: `0.26`) |

#### 3. Send Email Report

```bash
# Send today's results
python send_emails_new.py

# Send results for a specific date
python send_emails_new.py --date 20250307
```

## Incremental Query Logic

The new incremental query system significantly reduces data fetching time:

### Financial Data (Monthly)
- Only queries stocks not updated in 30+ days
- Metadata tracked in `query_metadata.json`

### Price Data (Daily)
- Only queries stocks not updated today
- New data is appended to existing files
- No need to re-download historical data

### Performance Comparison

| Scenario | Stocks | Time |
|----------|--------|------|
| First run (full query) | 300 stocks | ~7 minutes |
| Subsequent run (incremental) | 0-1 stocks | ~2 seconds |

## Stock Screening Criteria

Stocks are filtered based on the following criteria:

- **PE-TTM** < threshold percentile (default: 26th)
- **PB-TTM** < threshold percentile (default: 26th)
- **PR-TTM** < threshold percentile (default: 26th)
- **ROE-TTM** > (1 - threshold) percentile (default: 74th)

Lower threshold = stricter filtering = fewer stocks selected.

## Data Sources

- **Financial Data**: [Akshare](https://github.com/akfamily/akshare) - Tushare financial indicators
- **Price Data**: [Akshare](https://github.com/akfamily/akshare) - Sina finance daily prices

## License

MIT License

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.