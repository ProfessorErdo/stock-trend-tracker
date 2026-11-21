# grid_v1（2026-11）

固定实验网格，四格共用。

| 文件 | 行数 | distinct | 用途 |
|---|---:|---:|---|
| `grid_v1_div.csv` | 139 | 138 | 股息格 |
| `grid_v1_nodiv.csv` | 91 | 87 | 非股息格 |

- 股息：PB-only 120 + 过滤 core 6 + 组合补充 12 = 138。
- 非股息：核心 35 + 阈值面 44 + trim/N 8 = 87。
- 两池合计 450 distinct。

运行：

```bash
cd backtesting
../.venv/bin/python run_matrix_cell_fast.py --pool union  --mode div   --workers 2 --specs grids/grid_v1_div.csv   --out ../data/processed/backtesting/grid_v1_20261121/1052_div
../.venv/bin/python run_matrix_cell_fast.py --pool legacy --mode div   --workers 2 --specs grids/grid_v1_div.csv   --out ../data/processed/backtesting/grid_v1_20261121/932_div
../.venv/bin/python run_matrix_cell_fast.py --pool union  --mode nodiv --workers 2 --specs grids/grid_v1_nodiv.csv --out ../data/processed/backtesting/grid_v1_20261121/1052_nodiv
../.venv/bin/python run_matrix_cell_fast.py --pool legacy --mode nodiv --workers 2 --specs grids/grid_v1_nodiv.csv --out ../data/processed/backtesting/grid_v1_20261121/932_nodiv
```

去重签名：`(pool, ranking, 激活过滤器, 激活阈值, ROE, N, trim)`；未激活阈值不参与比较。
