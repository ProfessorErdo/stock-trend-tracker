const NS = "http://www.w3.org/2000/svg";

const $ = (selector) => document.querySelector(selector);

const METRIC_LABELS = ["PE", "PB", "PR", "ROE"];
const METRIC_CONFIG = {
  PE: { metric: "pe", threshold: "pe", direction: "max" },
  PB: { metric: "pb", threshold: "pb", direction: "max" },
  PR: { metric: "pr", threshold: "pr", direction: "max" },
  ROE: { metric: "roe", threshold: "roe", direction: "min" },
};

function percent(value, signed = true) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  const number = Number(value);
  const sign = signed && number > 0 ? "+" : "";
  return `${sign}${number.toFixed(2)}%`;
}

function metricText(label, value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return label === "ROE" ? `${Number(value).toFixed(2)}%` : Number(value).toFixed(2);
}

function metricPasses(label, value, thresholds) {
  const config = METRIC_CONFIG[label];
  const threshold = thresholds?.[config.threshold];
  if (value === null || value === undefined || threshold === null || threshold === undefined) {
    return null;
  }
  return config.direction === "max"
    ? Number(value) <= Number(threshold)
    : Number(value) >= Number(threshold);
}

function compareMetric(label, holding, thresholds, includeThresholdWord = true) {
  const config = METRIC_CONFIG[label];
  const value = holding.metrics?.[config.metric];
  const threshold = thresholds?.[config.threshold];
  const passes = metricPasses(label, value, thresholds);
  const operator = passes
    ? (config.direction === "max" ? "≤" : "≥")
    : (config.direction === "max" ? ">" : "<");
  const prefix = includeThresholdWord ? "阈值 " : "";
  return `${label} ${metricText(label, value)} ${operator} ${prefix}${metricText(label, threshold)}`;
}

function metricOperator(label, passes) {
  const direction = METRIC_CONFIG[label].direction;
  return passes
    ? (direction === "max" ? "≤" : "≥")
    : (direction === "max" ? ">" : "<");
}

function compactDate(isoDate) {
  if (!isoDate) return "—";
  const [, month, day] = isoDate.split("-");
  return `${month}/${day}`;
}

function formatGeneratedAt(isoDate) {
  if (!isoDate) return "—";
  const date = new Date(isoDate);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function createSvgElement(name, attributes = {}) {
  const element = document.createElementNS(NS, name);
  Object.entries(attributes).forEach(([key, value]) => {
    element.setAttribute(key, String(value));
  });
  return element;
}

function makePath(values, x, y) {
  return values
    .map((value, index) => `${index === 0 ? "M" : "L"}${x(index).toFixed(2)},${y(value).toFixed(2)}`)
    .join(" ");
}

function drawMainChart(history) {
  const svg = $("#trend-chart");
  if (!svg || !history?.length) return;

  const width = Math.max(280, Math.round(svg.getBoundingClientRect().width || 360));
  const height = 210;
  const margin = { top: 20, right: 12, bottom: 30, left: 42 };
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;
  const portfolio = history.map((point) => Number(point.portfolio));
  const benchmark = history.map((point) => Number(point.benchmark));
  const all = portfolio.concat(benchmark);
  const minValue = Math.floor((Math.min(...all) - 1) / 4) * 4;
  const maxValue = Math.ceil((Math.max(...all) + 1) / 4) * 4;

  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.querySelector(".chart-layer")?.remove();

  const layer = createSvgElement("g", { class: "chart-layer" });
  svg.appendChild(layer);
  const x = (index) => margin.left + (innerWidth * index) / Math.max(history.length - 1, 1);
  const y = (value) => margin.top + innerHeight * (1 - (value - minValue) / (maxValue - minValue));

  const gridValues = [minValue, Math.round((minValue + maxValue) / 2), maxValue];
  gridValues.forEach((value) => {
    layer.appendChild(createSvgElement("line", {
      x1: margin.left,
      y1: y(value),
      x2: width - margin.right,
      y2: y(value),
      stroke: "currentColor",
      "stroke-opacity": "0.12",
      "stroke-width": "1",
    }));
    const label = createSvgElement("text", {
      x: margin.left - 7,
      y: y(value) + 4,
      "text-anchor": "end",
    });
    label.textContent = String(value);
    layer.appendChild(label);
  });

  layer.appendChild(createSvgElement("path", {
    d: makePath(benchmark, x, y),
    fill: "none",
    stroke: "var(--benchmark)",
    "stroke-width": "1.6",
    "stroke-linecap": "round",
    "stroke-linejoin": "round",
  }));

  layer.appendChild(createSvgElement("path", {
    d: makePath(portfolio, x, y),
    fill: "none",
    stroke: "var(--green)",
    "stroke-width": "2.4",
    "stroke-linecap": "round",
    "stroke-linejoin": "round",
  }));

  layer.appendChild(createSvgElement("circle", {
    cx: x(portfolio.length - 1),
    cy: y(portfolio[portfolio.length - 1]),
    r: "3.6",
    fill: "var(--green)",
  }));

  const tickIndexes = [0, Math.floor((history.length - 1) / 2), history.length - 1];
  [...new Set(tickIndexes)].forEach((index, position) => {
    const label = createSvgElement("text", {
      x: x(index),
      y: height - 6,
      "text-anchor": position === 0 ? "start" : position === tickIndexes.length - 1 ? "end" : "middle",
    });
    label.textContent = compactDate(history[index].date);
    layer.appendChild(label);
  });
}

function drawSparkline(svg, values) {
  if (!svg || !values || values.length < 2) return;
  const width = 68;
  const height = 27;
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const range = Math.max(maxValue - minValue, 0.5);
  const x = (index) => 1 + (index / (values.length - 1)) * (width - 2);
  const y = (value) => 2 + ((maxValue - value) / range) * (height - 4);

  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("aria-hidden", "true");
  svg.appendChild(createSvgElement("path", {
    d: makePath(values, x, y),
    fill: "none",
    stroke: values[values.length - 1] >= values[0] ? "var(--green)" : "var(--red)",
    "stroke-width": "1.6",
    "stroke-linecap": "round",
    "stroke-linejoin": "round",
  }));
}

function renderHoldings(holdings, thresholds) {
  const container = $("#holdings-list");
  container.replaceChildren();

  holdings.forEach((holding) => {
    const details = document.createElement("details");
    details.className = "holding";

    const summary = document.createElement("summary");
    const name = document.createElement("span");
    name.className = "stock-name";
    const nameStrong = document.createElement("strong");
    nameStrong.textContent = holding.name;
    const nameSmall = document.createElement("small");
    nameSmall.textContent = `${holding.code} · ${holding.weight_pct.toFixed(1)}%`;
    name.append(nameStrong, nameSmall);
    if (!holding.qualifies) {
      const comparison = document.createElement("span");
      comparison.className = "condition-comparison";
      holding.failed_metrics.forEach((label) => {
        const line = document.createElement("small");
        line.textContent = compareMetric(label, holding, thresholds);
        comparison.appendChild(line);
      });
      name.appendChild(comparison);
    }

    const sparkline = createSvgElement("svg", { class: "mini-chart" });
    const badge = document.createElement("span");
    badge.className = `condition-badge ${holding.qualifies ? "pass" : "fail"}`;
    badge.textContent = holding.qualifies
      ? "符合"
      : holding.failed_metrics.length > 1
        ? `${holding.failed_metrics.length} 项掉线`
        : `${holding.failed_metrics[0]} 掉线`;

    const returnValue = document.createElement("span");
    returnValue.className = `stock-return${holding.return_pct < 0 ? " negative" : ""}`;
    returnValue.textContent = percent(holding.return_pct);
    summary.append(name, sparkline, badge, returnValue);

    const detail = document.createElement("div");
    detail.className = "holding-detail";
    METRIC_LABELS.forEach((label) => {
      const config = METRIC_CONFIG[label];
      const value = holding.metrics[config.metric];
      const threshold = thresholds?.[config.threshold];
      const item = document.createElement("span");
      const passes = metricPasses(label, value, thresholds);
      if (passes === false) item.className = "metric-fail";
      item.textContent = label;
      const strong = document.createElement("b");
      strong.textContent = metricText(label, value);
      const thresholdLabel = document.createElement("small");
      thresholdLabel.textContent = `阈值 ${metricText(label, threshold)}`;
      item.appendChild(strong);
      item.appendChild(thresholdLabel);
      detail.appendChild(item);
    });

    details.append(summary, detail);
    container.appendChild(details);
    drawSparkline(sparkline, holding.sparkline);
  });
}

function renderCandidates(candidates) {
  const container = $("#candidate-list");
  container.replaceChildren();

  const visibleCandidates = candidates.slice(0, 6);
  if (!visibleCandidates.length) {
    const empty = document.createElement("p");
    empty.className = "empty-note";
    empty.textContent = "本周没有股票通过全部条件";
    container.appendChild(empty);
    return;
  }

  visibleCandidates.forEach((candidate) => {
    const item = document.createElement("div");
    item.className = "compact-item";
    const text = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = `${candidate.name} ${candidate.code}`;
    const metric = document.createElement("small");
    metric.textContent = `PB ${candidate.metrics.pb?.toFixed(2) ?? "—"} · ROE ${candidate.metrics.roe?.toFixed(2) ?? "—"}%`;
    text.append(name, metric);

    const status = document.createElement("em");
    if (candidate.new_to_portfolio && candidate.target) {
      status.textContent = "NEW";
      status.className = "is-new";
    } else if (candidate.in_portfolio) {
      status.textContent = "在仓";
    } else {
      status.textContent = "候补";
    }
    item.append(text, status);
    container.appendChild(item);
  });
}

function renderConditions(holdings, thresholds) {
  const container = $("#condition-list");
  container.replaceChildren();

  if (!holdings.length) {
    const empty = document.createElement("p");
    empty.className = "empty-note";
    empty.textContent = "没有可用的持仓数据";
    container.appendChild(empty);
    return;
  }

  holdings.forEach((holding) => {
    const item = document.createElement("div");
    item.className = "compact-item";
    const text = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = holding.name;
    const detail = document.createElement("small");
    detail.textContent = holding.qualifies
      ? "PE / PB / PR / ROE 全部通过"
      : holding.failed_metrics
          .map((label) => compareMetric(label, holding, thresholds))
          .join(" · ");
    text.append(name, detail);
    const status = document.createElement("em");
    status.className = holding.qualifies ? "" : "is-fail";
    status.textContent = holding.qualifies ? "符合" : "掉线";
    item.append(text, status);
    container.appendChild(item);
  });
}

function renderWatchlist(watchlist) {
  const container = $("#watchlist-grid");
  container.replaceChildren();
  const thresholds = watchlist.thresholds;

  $("#watchlist-caption").textContent =
    `${watchlist.as_of} · ${watchlist.fully_qualifying_count}/${watchlist.stock_count} 四项全通过`;

  watchlist.stocks.forEach((stock) => {
    const card = document.createElement("article");
    card.className = "watchlist-card";

    const header = document.createElement("div");
    header.className = "watchlist-card-head";
    const name = document.createElement("div");
    const strong = document.createElement("strong");
    strong.textContent = stock.name;
    const code = document.createElement("small");
    code.textContent = stock.code;
    name.append(strong, code);

    const passCount = document.createElement("span");
    passCount.className = `watchlist-pass-count${stock.qualifies ? " all-pass" : ""}`;
    passCount.textContent = `${stock.passing_count}/4 通过`;
    header.append(name, passCount);

    const kpis = document.createElement("div");
    kpis.className = "watchlist-kpis";
    METRIC_LABELS.forEach((label) => {
      const config = METRIC_CONFIG[label];
      const value = stock.metrics[config.metric];
      const threshold = thresholds[config.threshold];
      const passes = metricPasses(label, value, thresholds);
      const cell = document.createElement("div");
      cell.className = `kpi-cell ${passes ? "pass" : "fail"}`;

      const kpiLabel = document.createElement("span");
      kpiLabel.className = "kpi-label";
      kpiLabel.textContent = label;
      const kpiValue = document.createElement("b");
      kpiValue.textContent = metricText(label, value);
      const comparison = document.createElement("small");
      comparison.textContent =
        `${metricOperator(label, passes)} 阈值 ${metricText(label, threshold)}`;
      cell.append(kpiLabel, kpiValue, comparison);
      kpis.appendChild(cell);
    });

    card.append(header, kpis);
    container.appendChild(card);
  });
}

function renderDashboard(data) {
  const summary = data.summary;
  const dateChip = $("#data-date");
  if (data.data_quality?.complete) {
    dateChip.textContent = `数据截至 ${data.data_as_of}`;
  } else {
    dateChip.textContent = `筛选 ${compactDate(data.data_as_of)} · 待更新`;
    dateChip.title = data.data_quality?.latest_price_date
      ? `行情已更新到 ${data.data_quality.latest_price_date}，但估值截面尚未完整`
      : "行情数据尚未完整更新";
  }
  dateChip.classList.toggle("needs-update", !data.data_quality?.complete);
  $("#portfolio-title").textContent = percent(summary.portfolio_return_pct);
  $("#portfolio-title").classList.toggle("negative", summary.portfolio_return_pct < 0);

  $("#excess-return").textContent = summary.excess_return_pp > 0
    ? `跑赢 ${summary.excess_return_pp.toFixed(2)}pp`
    : `落后 ${Math.abs(summary.excess_return_pp || 0).toFixed(2)}pp`;
  $("#excess-return").classList.toggle("negative", summary.excess_return_pp < 0);

  $("#benchmark-pill").textContent = `基准 ${percent(summary.benchmark_return_pct)}`;
  $("#qualify-pill").textContent = `${summary.qualifying_count}/${summary.holding_count} 仍符合选股条件`;
  $("#holdings-caption").textContent = `调仓日 ${data.rebalance_date}`;
  $("#screen-date").textContent =
    `${data.screen.as_of} · 动态池 ${data.rules.screen_universe_size} 只`;
  $("#passed-count").textContent = String(data.screen.passed_count);
  $("#still-count").textContent = `${summary.qualifying_count}/${summary.holding_count}`;
  $("#new-count").textContent = String(summary.new_candidate_count);
  $("#candidate-caption").textContent = `共 ${data.screen.passed_count} 只`;
  $("#condition-caption").textContent = `通过 ${summary.qualifying_count}/${summary.holding_count}`;
  $("#generated-at").textContent = `生成于 ${formatGeneratedAt(data.generated_at)}`;

  const rules = data.rules;
  $("#rules-copy").textContent =
    `持仓由 ${rules.holding_universe_size} 只的 ${rules.holding_universe_snapshot} 选出并锁定；` +
    `${rules.holding_selection}。` +
    `周更阈值和候选股使用 ${rules.screen_universe_size} 只的${rules.screen_universe_snapshot}。` +
    `PE、PB、PR 低于全样本最低 ${rules.valuation_quantile}% 分位，` +
    `ROE 高于最高 ${100 - rules.roe_quantile}% 分位；先裁去各指标不利尾部 ${(rules.trim_ratio * 100).toFixed(1)}%。` +
    `通过后按 ${rules.ranking}，最多保留 ${rules.max_positions} 只；上市不足 ${rules.new_stock_exclusion_days} 个交易日的股票排除。`;

  renderHoldings(data.holdings, data.screen.thresholds);
  renderCandidates(data.screen.candidates);
  renderConditions(data.holdings, data.screen.thresholds);
  renderWatchlist(data.watchlist);
  drawMainChart(data.history);

  $("#loading").hidden = true;
  $("#dashboard").hidden = false;
}

async function init() {
  try {
    const response = await fetch("./data/dashboard.json", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    renderDashboard(data);

    const chart = $("#trend-chart");
    if (chart && "ResizeObserver" in window) {
      new ResizeObserver(() => drawMainChart(data.history)).observe(chart.parentElement);
    }
  } catch (error) {
    $("#loading").hidden = true;
    $("#error").hidden = false;
    $("#error-message").textContent =
      `无法读取 /data/dashboard.json（${error.message}）。请先运行 scripts/build_dashboard.py。`;
  }
}

init();
