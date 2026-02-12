# -*- coding: utf-8 -*-
"""
Growth Runner — 增长闭环 Agent

职责：
1. 读取当天 Quill 产出的文章
2. 生成：标题 A/B 测试候选、朋友圈/社群转发文案、付费 CTA、次日选题建议
3. 结果发送到 Telegram

用法：
    python growth_runner.py                    # 自动使用当天文章
    python growth_runner.py --date 20260213    # 指定日期
"""
from __future__ import annotations

import argparse
import os
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict

from loguru import logger

from config import settings

PROJECT_ROOT = Path(__file__).resolve().parent


def load_article(date_str: str) -> Optional[str]:
    """加载当天的免费文章 Markdown"""
    article_path = PROJECT_ROOT / "pipeline" / "drafts" / f"{date_str}-article.md"
    if not article_path.exists():
        logger.warning(f"文章不存在: {article_path}")
        return None
    with open(article_path, "r", encoding="utf-8") as f:
        return f.read()


def load_analysis(date_str: str) -> Dict:
    """加载当天的 Sage 分析 JSON"""
    json_path = PROJECT_ROOT / "pipeline" / "sage" / f"{date_str}-analysis.json"
    if not json_path.exists():
        return {}
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def generate_growth_pack(article_md: str, analysis: Dict) -> Optional[str]:
    """
    调用 LLM 生成增长素材包：
    - 3 组标题 A/B 测试候选
    - 3 条朋友圈/社群转发短文案
    - 2 条付费 CTA 文案
    - 次日选题建议
    """
    from openai import OpenAI

    api_key = settings.REPORT_ENGINE_API_KEY or settings.INSIGHT_ENGINE_API_KEY
    base_url = settings.REPORT_ENGINE_BASE_URL or settings.INSIGHT_ENGINE_BASE_URL
    model = settings.REPORT_ENGINE_MODEL_NAME or settings.INSIGHT_ENGINE_MODEL_NAME or "qwen-max"

    if not api_key:
        logger.error("无可用 LLM API Key")
        return None

    client = OpenAI(api_key=api_key, base_url=base_url)

    selected = analysis.get("selected_topic", {})
    topic = selected.get("topic", "")
    evidence = selected.get("evidence", [])
    info_gap = analysis.get("info_gap_analysis", {})

    # 提取文章标题
    title = topic
    for line in article_md.split("\n"):
        line = line.strip()
        if line.startswith("# "):
            title = line[2:].strip()
            break

    evidence_facts = []
    for ev in evidence:
        evidence_facts.extend(ev.get("verifiable_facts", []))

    prompt = f"""你是「东旺数贸」公众号的增长运营专家。

今天的文章标题：{title}
话题：{topic}
信息差洞察：{info_gap.get('gap_insight', '')}
关键数据：{', '.join(evidence_facts[:10])}

请生成以下增长素材（纯 Markdown 格式）：

## 📌 标题 A/B 测试（3组）
每组包含 A版（理性）和 B版（感性），20字以内，附简要理由。

## 📱 朋友圈/社群转发文案（3条）
每条 50-80 字，适合直接复制粘贴。要有信息差感、引发好奇。

## 💰 付费 CTA 文案（2条）
每条 30-50 字，引导读者进入会员频道。自然不生硬。

## 🔮 次日选题建议（3个）
基于今天话题的延伸方向，每个附简要理由（20字）。

只输出 Markdown，不要代码块包裹。"""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            timeout=60,
        )
        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1]
        if content.endswith("```"):
            content = content[:-3].strip()
        return content
    except Exception as e:
        logger.error(f"增长素材包生成失败: {e}")
        return None


def run_growth(date_str: Optional[str] = None) -> Optional[str]:
    """
    执行 Growth：生成增长素材包 → 保存 → 发送 Telegram。
    返回保存路径，失败返回 None。
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")

    logger.info(f"=== Growth 开始 | date={date_str} ===")

    # 1. 加载文章
    article_md = load_article(date_str)
    if not article_md:
        logger.warning("无当天文章，Growth 跳过")
        return None

    # 2. 加载分析
    analysis = load_analysis(date_str)

    # 3. 生成增长素材包
    logger.info(">>> 生成增长素材包...")
    growth_md = generate_growth_pack(article_md, analysis)
    if not growth_md:
        logger.warning("增长素材包生成失败")
        return None

    logger.info(f">>> 增长素材包生成完成: {len(growth_md)} 字")

    # 4. 保存
    output_path = PROJECT_ROOT / "pipeline" / "growth" / f"{date_str}-growth.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"# 增长素材包 | {date_str}\n\n{growth_md}")

    logger.info(f">>> 已保存: {output_path}")

    # 5. 发送到 Telegram
    try:
        from telegram_sender import send_message
        # 截取前 3000 字符（Telegram 消息限制 4096）
        msg = f"📈 增长素材包 | {date_str}\n\n{growth_md[:3000]}"
        send_message(msg)
        logger.info(">>> Telegram 发送成功")
    except Exception as e:
        logger.warning(f"Telegram 发送失败: {e}")

    logger.info(f"=== Growth 完成 | {output_path} ===")
    return str(output_path)


def main():
    parser = argparse.ArgumentParser(description="Growth Runner - 增长素材包")
    parser.add_argument("--date", type=str, help="目标日期 (YYYYMMDD)")
    args = parser.parse_args()

    result = run_growth(date_str=args.date)
    if result:
        print(f"Growth 完成: {result}")
    else:
        print("Growth 完成: 无输出")


if __name__ == "__main__":
    main()
