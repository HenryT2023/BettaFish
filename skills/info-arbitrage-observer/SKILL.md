---
name: info-arbitrage-observer
description: 信息差 Observer — 每日审计 Pipeline 运行状态和文章质量，发送 Telegram 摘要。当用户提到"审计""observer""检查运行状态"时使用此 skill。
---

# Info Arbitrage Observer

每日 22:00 检查 Scout/Sage/Quill 各环节产出、state.json 一致性、文章质量（LLM 评分），生成审计报告并发送 Telegram 摘要。

## 执行

```bash
cd ~/HenryBot/BettaFish && python run_pipeline.py --step observe
```

指定日期：
```bash
cd ~/HenryBot/BettaFish && python run_pipeline.py --step observe --date YYYYMMDD
```

## 输出

- `pipeline/observer/YYYYMMDD-audit.json` — 审计结果
- Telegram 每日运行摘要

## 调度

Moltbot Cron: `bf-observer`，每天 22:00 CST
