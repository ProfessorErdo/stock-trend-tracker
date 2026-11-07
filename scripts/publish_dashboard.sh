#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "找不到 Python 环境：$PYTHON_BIN" >&2
  echo "请先运行 uv sync，或通过 PYTHON_BIN 指定解释器。" >&2
  exit 1
fi

publish=false
build_args=()
for arg in "$@"; do
  if [[ "$arg" == "--publish" ]]; then
    publish=true
  else
    build_args+=("$arg")
  fi
done

"$PYTHON_BIN" scripts/build_dashboard.py "${build_args[@]}"

if [[ "$publish" == true ]]; then
  date_tag="$(date +%Y-%m-%d)"
  git add -- docs/index.html docs/dashboard.css docs/dashboard.js docs/favicon.svg docs/.nojekyll docs/data/dashboard.json
  if git diff --cached --quiet; then
    echo "看板数据没有变化，无需提交。"
    exit 0
  fi
  git commit -m "chore: update dashboard ${date_tag}"
  git push
  echo "已推送。GitHub Pages 通常会在 1-2 分钟内完成更新。"
fi
