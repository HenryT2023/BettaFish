#!/usr/bin/env bash
# ============================================================
# BettaFish Pipeline — Moltbot Cron 注册脚本
# 在 Mac Mini 上执行，注册所有定时任务
# ============================================================

set -euo pipefail

PIPELINE_DIR="$HOME/HenryBot/BettaFish"
TELEGRAM_TO="8054772943"

echo "=== BettaFish Cron 注册 ==="

# 1. Scout — 每 4 小时（02/06/10/14/18/22 北京时间）
echo ">>> 注册 bf-scout..."
moltbot cron add \
  --name "bf-scout" \
  --cron "0 2,6,10,14,18,22 * * *" \
  --tz "Asia/Shanghai" \
  --session isolated \
  --message "Run: cd ${PIPELINE_DIR} && python run_pipeline.py --step scout" \
  --deliver --channel telegram --to "${TELEGRAM_TO}"

# 2. Publish (Sage + Quill) — 每天 09:30 北京时间
echo ">>> 注册 bf-publish..."
moltbot cron add \
  --name "bf-publish" \
  --cron "30 9 * * *" \
  --tz "Asia/Shanghai" \
  --session isolated \
  --message "Run: cd ${PIPELINE_DIR} && python run_pipeline.py --step publish --mode full" \
  --deliver --channel telegram --to "${TELEGRAM_TO}"

# 3. Observer — 每天 22:00 北京时间
echo ">>> 注册 bf-observer..."
moltbot cron add \
  --name "bf-observer" \
  --cron "0 22 * * *" \
  --tz "Asia/Shanghai" \
  --session isolated \
  --message "Run: cd ${PIPELINE_DIR} && python run_pipeline.py --step observe" \
  --deliver --channel telegram --to "${TELEGRAM_TO}"

# 4. Paid Report — 每周五 14:00 北京时间
echo ">>> 注册 bf-paid-report..."
moltbot cron add \
  --name "bf-paid-report" \
  --cron "0 14 * * 5" \
  --tz "Asia/Shanghai" \
  --session isolated \
  --message "Run: cd ${PIPELINE_DIR} && python run_pipeline.py --step paid" \
  --deliver --channel telegram --to "${TELEGRAM_TO}"

echo ""
echo "=== 注册完成 ==="
echo "查看已注册的 cron: moltbot cron list"
echo ""
echo "手动测试单步："
echo "  cd ${PIPELINE_DIR}"
echo "  python run_pipeline.py --step scout"
echo "  python run_pipeline.py --step publish --mode lite"
echo "  python run_pipeline.py --step observe"
echo "  python run_pipeline.py --step paid --topic '跨境电商AI工具'"
