---
name: info-arbitrage-quill
description: 信息差 Quill — 基于 Sage 分析生成公众号文章，渲染 .docx，发送 Telegram，触发 wechat-publisher。当用户提到"写文章""quill""生成公众号内容"时使用此 skill。
---

# Info Arbitrage Quill

读取 Sage 分析结果，调用 LLM 生成 1500-3000 字公众号风格文章（Markdown），通过 DocxRenderer 渲染为 .docx，发送到 Telegram 触发 wechat-publisher 创建微信草稿。

## 执行

Quill 通常由 `--step publish` 自动串联（Sage → Quill），不单独调用。

如需单独执行（已有 sage 数据）：
```bash
cd ~/HenryBot/BettaFish && python quill_runner.py --date YYYYMMDD
```

## 输出

- `pipeline/drafts/YYYYMMDD-article.md` — Markdown 备份
- `pipeline/drafts/YYYYMMDD-article.docx` — 发送到 Telegram 的文件
- Telegram 消息 → wechat-publisher → 微信草稿

## 调度

由 `bf-publish` cron 在每天 09:30 CST 自动执行（Sage + Quill 串联）。
