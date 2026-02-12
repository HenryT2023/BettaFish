---
name: info-arbitrage-paid
description: 信息差 Paid — 生成 3000-5000 字付费深度研究报告，ForumEngine 辩论+全量数据分析，发送 Telegram 供审核。当用户提到"付费报告""deep report""paid content"时使用此 skill。
---

# Info Arbitrage Paid Content

从付费内容队列或手动指定话题，生成 3000-5000 字深度研究报告。与免费文章区别：完整数据分析 + 方法论 + 趋势预测 + 分角色行动建议。

## 执行

从队列：
```bash
cd ~/HenryBot/BettaFish && python run_pipeline.py --step paid
```

指定话题：
```bash
cd ~/HenryBot/BettaFish && python run_pipeline.py --step paid --topic "跨境电商AI工具"
```

## 输出

- `pipeline/drafts/YYYYMMDD-paid-report.md` — Markdown 备份
- `pipeline/drafts/YYYYMMDD-paid-report.docx` — 发送到 Telegram 供审核
- Telegram 消息（标记为付费报告，需人工审核）

## 调度

Moltbot Cron: `bf-paid-report`，每周五 14:00 CST
