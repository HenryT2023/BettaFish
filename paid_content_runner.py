# -*- coding: utf-8 -*-
"""
Paid Content Runner — 付费深度研究报告生成

职责：
1. 从 paid_content_queue 或手动指定话题获取待处理项
2. ForumEngine 完整辩论 + InsightEngine 全量分析
3. 生成 3000-5000 字深度研究报告
4. docx_renderer → .docx
5. 发送 Telegram 供审核

用法：
    python paid_content_runner.py                        # 从队列取话题
    python paid_content_runner.py --topic "跨境电商AI"   # 手动指定
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings
from pipeline_state import (
    dequeue_paid_content,
    load_state,
    mark_paid_content_done,
    save_state,
)
from telegram_sender import send_document, send_message


def generate_deep_report(topic: str) -> str:
    """
    调用 LLM 生成付费深度研究报告（Markdown 格式）。
    与免费文章区别：完整数据 + 方法论 + 趋势预测 + 行动建议分角色。
    """
    from openai import OpenAI

    api_key = settings.REPORT_ENGINE_API_KEY or settings.INSIGHT_ENGINE_API_KEY
    base_url = settings.REPORT_ENGINE_BASE_URL or settings.INSIGHT_ENGINE_BASE_URL
    model = settings.REPORT_ENGINE_MODEL_NAME or settings.INSIGHT_ENGINE_MODEL_NAME or "qwen-max"

    if not api_key:
        logger.error("无可用 LLM API Key")
        return ""

    client = OpenAI(api_key=api_key, base_url=base_url)

    # 先用搜索获取背景数据
    search_context = _gather_search_context(topic)

    system_prompt = """你是一位资深的跨境电商和数字贸易研究分析师，为「东旺数贸」撰写付费深度研究报告。

报告结构（严格遵循）：
# [报告标题]

## 1. 执行摘要
300字，核心发现 + 关键数据指标。高管一页纸能看完。

## 2. 数据全景
多平台数据汇总（海外 + 国内），说明数据来源与时间范围。

## 3. 深度分析
### 3.1 趋势分析
用数据支撑，对比国内外。
### 3.2 竞品对比
国内外主要玩家，各自优劣势。
### 3.3 机会识别
蓝海市场 / 差异化切入点。
### 3.4 风险评估
政策、市场、技术风险。

## 4. 情感分析
舆论风向（正面/中性/负面），KOL 观点，用户真实反馈。

## 5. 行动建议
### 5.1 卖家/品牌方
### 5.2 投资者/创业者
### 5.3 短期 vs 中期策略

## 6. 数据附录
参考来源链接、术语解释。

写作要求：
- 总长 3000-5000 字
- 用 **加粗** 突出关键数据
- 每段 80-200 字
- 数据要具体（数字、百分比、时间点）
- 观点要有论据支撑
- 语气：专业严谨，适合付费读者
- 输出纯 Markdown 格式"""

    user_prompt = f"研究话题：{topic}\n\n背景资料：\n{search_context}"

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt[:20000]},
            ],
            temperature=0.5,
            timeout=300,
        )
        content = response.choices[0].message.content.strip()

        if content.startswith("```markdown"):
            content = content[len("```markdown"):].strip()
        if content.startswith("```"):
            content = content[3:].strip()
        if content.endswith("```"):
            content = content[:-3].strip()

        return content

    except Exception as e:
        logger.error(f"深度报告生成失败: {e}")
        return ""


def _gather_search_context(topic: str) -> str:
    """通过搜索获取话题背景数据"""
    context_parts = []

    try:
        from QueryEngine.tools.search import TavilyNewsAgency
        tavily_key = settings.TAVILY_API_KEY
        if tavily_key:
            agency = TavilyNewsAgency(api_key=tavily_key)
            response = agency.deep_search_news(topic)
            if response.answer:
                context_parts.append(f"[搜索摘要] {response.answer}")
            for r in response.results[:5]:
                context_parts.append(f"- {r.title}: {(r.content or '')[:200]}")
    except Exception as e:
        logger.warning(f"搜索背景数据失败: {e}")

    # 读取最近的 scout 数据作为补充
    import glob
    scout_dir = PROJECT_ROOT / "pipeline" / "scout"
    files = sorted(glob.glob(str(scout_dir / "*.json")), reverse=True)[:3]
    for fp in files:
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data.get("items", [])[:3]:
                title = item.get("title", "")
                if topic.lower() in title.lower() or any(
                    kw in title.lower() for kw in topic.lower().split()
                ):
                    context_parts.append(f"- [Scout] {title}: {item.get('content', '')[:150]}")
        except Exception:
            pass

    return "\n".join(context_parts) if context_parts else "（无额外背景数据，请基于你的知识库生成）"


def run_paid_content(topic_override: Optional[str] = None) -> Optional[str]:
    """
    生成付费深度报告。
    返回 .docx 文件路径，失败返回 None。
    """
    date_str = datetime.now().strftime("%Y%m%d")
    logger.info(f"=== Paid Content 开始 | date={date_str} ===")

    # 确定话题
    state = load_state()
    topic = topic_override

    if not topic:
        item = dequeue_paid_content(state)
        if item:
            topic = item.get("topic", "")
            save_state(state)
        else:
            logger.info("付费内容队列为空，跳过")
            return None

    if not topic:
        logger.warning("无话题可处理")
        return None

    logger.info(f">>> 话题: {topic}")

    # 生成报告
    logger.info(">>> 生成深度报告...")
    report_md = generate_deep_report(topic)
    if not report_md or len(report_md) < 1000:
        logger.warning(f"报告内容过短 ({len(report_md)} 字)")
        return None

    logger.info(f">>> 报告生成完成: {len(report_md)} 字")

    # 保存 Markdown
    drafts_dir = PROJECT_ROOT / "pipeline" / "drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    md_path = drafts_dir / f"{date_str}-paid-report.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(report_md)

    # 渲染 docx
    docx_path = str(drafts_dir / f"{date_str}-paid-report.docx")
    logger.info(">>> 渲染 DOCX...")
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "docx_renderer",
            str(PROJECT_ROOT / "ReportEngine" / "renderers" / "docx_renderer.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        renderer = mod.DocxRenderer()
        renderer.render_from_markdown(report_md)
        renderer.save(docx_path)
    except Exception as e:
        logger.error(f"DOCX 渲染失败: {e}")
        return None

    # 发送 Telegram（标记为付费报告，供人工审核）
    title = topic
    for line in report_md.split("\n"):
        if line.strip().startswith("# "):
            title = line.strip()[2:]
            break

    caption = f"💎 付费深度报告\n\n📄 {title}\n\n{report_md[:200]}...\n\n⚠️ 请审核后决定是否发布"
    send_document(docx_path, caption=caption)

    # 标记完成
    state = load_state()
    mark_paid_content_done(topic, state)
    save_state(state)

    logger.info(f"=== Paid Content 完成 | {docx_path} ===")
    return docx_path


def main():
    parser = argparse.ArgumentParser(description="Paid Content Runner - 付费深度报告")
    parser.add_argument("--topic", type=str, help="手动指定话题")
    args = parser.parse_args()

    result = run_paid_content(topic_override=args.topic)
    if result:
        print(f"Paid Content 完成: {result}")
    else:
        print("Paid Content 完成: 无输出")


if __name__ == "__main__":
    main()
