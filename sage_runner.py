# -*- coding: utf-8 -*-
"""
Sage Runner — 深度分析 + ForumEngine 多 Agent 辩论

职责：
1. 读取当天所有 Scout JSON
2. 合并 + 按综合评分排序
3. InsightEngine 深度分析（情感 + 趋势）
4. ForumEngine 多 Agent 辩论（交叉验证选题）
5. 选出最终话题 → 生成 3 个标题候选 + 详细大纲
6. 检查话题冷却 → 保存分析结果

用法：
    python sage_runner.py                         # 自动分析当天 scout 数据
    python sage_runner.py --date 2026-02-13       # 指定日期
    python sage_runner.py --mode full             # 启用 ForumEngine 辩论
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings
from pipeline_state import (
    is_topic_cooled_down,
    load_state,
    mark_topic_written,
    save_state,
)


def load_scout_data(date_str: Optional[str] = None) -> List[Dict]:
    """加载指定日期的所有 Scout JSON，合并并排序"""
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")

    scout_dir = PROJECT_ROOT / "pipeline" / "scout"
    pattern = str(scout_dir / f"{date_str}-*.json")
    files = sorted(glob.glob(pattern))

    if not files:
        logger.warning(f"未找到 Scout 数据: {pattern}")
        return []

    all_items = []
    for fp in files:
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
            items = data.get("items", [])
            for item in items:
                item["_scout_batch"] = data.get("batch", "")
                item["_scout_theme"] = data.get("theme", "")
            all_items.extend(items)
            logger.info(f"  加载 {fp}: {len(items)} 条")
        except Exception as e:
            logger.error(f"  加载失败 {fp}: {e}")

    # 按 avg_score 排序
    all_items.sort(key=lambda x: x.get("avg_score", 0), reverse=True)
    return all_items


def analyze_with_llm(items: List[Dict], mode: str = "lite") -> Dict:
    """
    用 LLM 进行深度分析，选出最佳话题并生成大纲。
    mode='lite': 单 Agent 分析
    mode='full': 包含 ForumEngine 辩论摘要
    """
    from openai import OpenAI

    api_key = settings.INSIGHT_ENGINE_API_KEY or settings.QUERY_ENGINE_API_KEY
    base_url = settings.INSIGHT_ENGINE_BASE_URL or settings.QUERY_ENGINE_BASE_URL
    model = settings.INSIGHT_ENGINE_MODEL_NAME or settings.QUERY_ENGINE_MODEL_NAME or "qwen-max"

    if not api_key:
        logger.error("无可用 LLM API Key")
        return {}

    client = OpenAI(api_key=api_key, base_url=base_url)

    # 准备输入
    items_text = ""
    for i, item in enumerate(items[:10]):  # Top 10
        items_text += (
            f"\n[{i}] 标题: {item.get('title', '')}\n"
            f"    来源: {item.get('source', '')}\n"
            f"    摘要: {item.get('content', '')[:200]}\n"
            f"    评分: china_relevance={item.get('china_relevance', 0)}, "
            f"info_asymmetry={item.get('info_asymmetry', 0)}, "
            f"wechat_potential={item.get('wechat_potential', 0)}\n"
            f"    中国视角: {item.get('china_angle', '')}\n"
        )

    system_prompt = """你是「东旺数贸」公众号的首席内容策略师。
你的读者是：跨境电商从业者、数字贸易关注者、AI工具爱好者。
你的任务：从候选新闻中选出最适合做公众号深度文章的话题。

请执行以下分析并输出 JSON：

1. top3_topics: 选出 Top 3 话题，每个包含：
   - index: 原始条目索引
   - topic: 话题名（中文，10字以内）
   - why_readers_care: 为什么中国读者关心（50字）
   - domestic_comparison: 国内对标产品/事件
   - actionable_advice: 读者可以采取的行动（30字）
   - score: 综合推荐分 (1-10)

2. selected_topic: 最终选定话题（从 top3 中选 1 个），包含：
   - topic: 话题名
   - headlines: 3 个标题候选（20字以内，精炼有力，适合公众号）
   - outline: 文章大纲，包含 3-5 个小节，每节有标题和要点

3. forum_summary: 多视角分析摘要（如果是 full 模式，模拟 QueryAgent/InsightAgent/MediaAgent 三方观点交叉验证）

只返回 JSON，不要其他文字。"""

    mode_hint = ""
    if mode == "full":
        mode_hint = "\n\n【Full 模式】请模拟三个 Agent 的视角进行交叉验证：\n- QueryAgent（信息搜索视角）: 这个话题的全球信息覆盖度如何？\n- InsightAgent（深度分析视角）: 数据和趋势支持什么结论？\n- MediaAgent（社媒传播视角）: 这个话题在社交媒体上的传播潜力？"

    user_prompt = f"今天的候选新闻：{items_text}{mode_hint}"

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt[:20000]},
            ],
            temperature=0.5,
            timeout=120,
        )
        content = response.choices[0].message.content.strip()

        if content.startswith("```"):
            content = content.split("\n", 1)[-1]
            if content.endswith("```"):
                content = content[:-3]

        import json_repair
        analysis = json_repair.loads(content)
        return analysis

    except Exception as e:
        logger.error(f"LLM 分析失败: {e}")
        return {}


def run_forum_debate(topic: str, items: List[Dict]) -> str:
    """
    调用 ForumEngine 进行多 Agent 辩论。
    如果 ForumEngine 不可用，返回空字符串（优雅降级）。
    """
    try:
        from ForumEngine.llm_host import LLMHost

        host_api_key = settings.FORUM_HOST_API_KEY
        host_base_url = settings.FORUM_HOST_BASE_URL
        host_model = settings.FORUM_HOST_MODEL_NAME

        if not host_api_key:
            logger.info("ForumEngine API Key 未配置，跳过辩论")
            return ""

        host = LLMHost(
            api_key=host_api_key,
            base_url=host_base_url,
            model_name=host_model,
        )

        context = f"话题：{topic}\n\n相关数据：\n"
        for item in items[:5]:
            context += f"- {item.get('title', '')}: {item.get('content', '')[:100]}\n"

        debate_result = host.run_debate(
            topic=f"这个话题是否适合做「东旺数贸」公众号的深度文章？{topic}",
            context=context,
        )
        return debate_result or ""

    except ImportError:
        logger.info("ForumEngine 模块不可用，跳过辩论")
        return ""
    except Exception as e:
        logger.warning(f"ForumEngine 辩论失败: {e}")
        return ""


def run_sage(date_str: Optional[str] = None, mode: str = "lite") -> Optional[str]:
    """
    执行 Sage 分析。
    返回保存的分析文件路径，无结果时返回 None。
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")

    logger.info(f"=== Sage 开始 | date={date_str} | mode={mode} ===")

    # 1. 加载 Scout 数据
    items = load_scout_data(date_str)
    if not items:
        logger.warning("无 Scout 数据，Sage 跳过")
        return None

    logger.info(f">>> 共 {len(items)} 条候选，开始分析...")

    # 2. LLM 分析
    analysis = analyze_with_llm(items, mode=mode)
    if not analysis:
        logger.warning("LLM 分析无结果，跳过")
        return None

    # 3. ForumEngine 辩论（full 模式）
    debate_log = ""
    selected = analysis.get("selected_topic", {})
    if mode == "full" and selected.get("topic"):
        logger.info(">>> ForumEngine 辩论...")
        debate_log = run_forum_debate(selected["topic"], items)
        if debate_log:
            analysis["forum_debate_log"] = debate_log

    # 4. 话题冷却检查
    topic_name = selected.get("topic", "")
    if topic_name:
        state = load_state()
        if not is_topic_cooled_down(topic_name, state):
            logger.warning(f"话题 '{topic_name}' 在冷却期内，尝试替换...")
            # 尝试 Top 3 中的其他话题
            for alt in analysis.get("top3_topics", []):
                alt_topic = alt.get("topic", "")
                if alt_topic and alt_topic != topic_name and is_topic_cooled_down(alt_topic, state):
                    logger.info(f"替换为: {alt_topic}")
                    selected["topic"] = alt_topic
                    topic_name = alt_topic
                    break
            else:
                logger.warning("所有候选话题均在冷却期，跳过")
                return None

        # 标记话题
        mark_topic_written(topic_name, state)
        save_state(state)

    # 5. 保存分析结果
    output_dir = PROJECT_ROOT / "pipeline" / "sage"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{date_str}-analysis.md"

    # 生成 Markdown 格式的分析报告
    md_content = f"# Sage 分析报告 — {date_str}\n\n"
    md_content += f"**模式**: {mode}\n"
    md_content += f"**候选数**: {len(items)}\n"
    md_content += f"**生成时间**: {datetime.now().isoformat()}\n\n"

    # Top 3
    md_content += "## Top 3 候选话题\n\n"
    for t in analysis.get("top3_topics", []):
        md_content += f"### {t.get('topic', '')}\n"
        md_content += f"- **读者关心**: {t.get('why_readers_care', '')}\n"
        md_content += f"- **国内对标**: {t.get('domestic_comparison', '')}\n"
        md_content += f"- **行动建议**: {t.get('actionable_advice', '')}\n"
        md_content += f"- **推荐分**: {t.get('score', '')}\n\n"

    # 选定话题
    md_content += "## 选定话题\n\n"
    md_content += f"**话题**: {selected.get('topic', '')}\n\n"
    md_content += "**标题候选**:\n"
    for h in selected.get("headlines", []):
        md_content += f"1. {h}\n"
    md_content += "\n**文章大纲**:\n\n"
    outline = selected.get("outline", [])
    if isinstance(outline, list):
        for section in outline:
            if isinstance(section, dict):
                md_content += f"### {section.get('title', '')}\n"
                md_content += f"{section.get('points', section.get('content', ''))}\n\n"
            elif isinstance(section, str):
                md_content += f"- {section}\n"
    elif isinstance(outline, str):
        md_content += outline + "\n"

    # ForumEngine 辩论
    if debate_log:
        md_content += "\n## ForumEngine 辩论记录\n\n"
        md_content += debate_log + "\n"

    # Forum summary
    forum_summary = analysis.get("forum_summary", "")
    if forum_summary:
        md_content += "\n## 多视角分析摘要\n\n"
        if isinstance(forum_summary, dict):
            for agent, view in forum_summary.items():
                md_content += f"**{agent}**: {view}\n\n"
        else:
            md_content += str(forum_summary) + "\n"

    # 保存原始 JSON（供 Quill 读取）
    json_file = output_dir / f"{date_str}-analysis.json"
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)

    # 保存 Markdown
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(md_content)

    logger.info(f"=== Sage 完成 | {output_file} ===")
    return str(output_file)


def main():
    parser = argparse.ArgumentParser(description="Sage Runner - 深度分析")
    parser.add_argument("--date", type=str, help="分析日期 (YYYYMMDD)")
    parser.add_argument("--mode", type=str, default="lite", choices=["lite", "full"],
                        help="分析模式: lite=单Agent, full=ForumEngine辩论")
    args = parser.parse_args()

    result = run_sage(date_str=args.date, mode=args.mode)
    if result:
        print(f"Sage 完成: {result}")
    else:
        print("Sage 完成: 无结果")


if __name__ == "__main__":
    main()
