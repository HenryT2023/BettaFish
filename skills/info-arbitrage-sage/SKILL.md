---
name: info-arbitrage-sage
description: 信息差 Sage — 对 Scout 数据进行深度分析，ForumEngine 多 Agent 辩论，选题+大纲生成。当用户提到"分析新闻""sage""选题"时使用此 skill。
---

# Info Arbitrage Sage

读取当天 Scout JSON，用 LLM 从 Top 10 中选出最佳话题，支持 ForumEngine 多 Agent 辩论交叉验证。输出分析报告 + 选定话题 + 3 个标题候选 + 文章大纲。

## 执行

```bash
cd ~/HenryBot/BettaFish && python run_pipeline.py --step publish --mode lite
```

Full 模式（含 ForumEngine 辩论）：
```bash
cd ~/HenryBot/BettaFish && python run_pipeline.py --step publish --mode full
```

## 输出

- `pipeline/sage/YYYYMMDD-analysis.json` — 结构化分析（供 Quill 读取）
- `pipeline/sage/YYYYMMDD-analysis.md` — 可读分析报告
