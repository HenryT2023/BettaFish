---
name: info-arbitrage-scout
description: 信息差 Scout — 定时扫描海外+国内新闻，LLM 评分，去重存储。每4小时自动执行，或手动触发。当用户提到"扫描新闻""scout""信息采集"时使用此 skill。
---

# Info Arbitrage Scout

自动扫描海外（Tavily）和国内（MindSpider）新闻源，用 LLM 对每条结果评估 china_relevance / info_asymmetry / wechat_potential，过滤低分项后保存到 `pipeline/scout/`。

## 执行

```bash
cd ~/HenryBot/BettaFish && python run_pipeline.py --step scout
```

手动指定主题：
```bash
cd ~/HenryBot/BettaFish && python run_pipeline.py --step scout --theme "AI Agent"
```

## 输出

- `pipeline/scout/YYYYMMDD-HH.json` — 按批次保存的评分结果
- `state.json` — 自动更新已处理 URL 列表

## 调度

Moltbot Cron: `bf-scout`，每4小时（02/06/10/14/18/22 CST）
