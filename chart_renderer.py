# -*- coding: utf-8 -*-
"""
Chart Renderer — 自动生成信息差图表

职责：
1. 从 Scout 数据生成趋势热度 Top N 条形图
2. 从 Sage 数据生成国内外信息差对比表图
3. 输出 PNG 文件，随 Telegram 一起发送

用法：
    python chart_renderer.py --date 20260213
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict

from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent


def _setup_matplotlib():
    """配置 matplotlib 中文字体支持"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # 尝试使用系统中文字体
    font_candidates = [
        "PingFang SC",           # macOS
        "Heiti SC",              # macOS
        "STHeiti",               # macOS
        "SimHei",                # Windows
        "WenQuanYi Micro Hei",   # Linux
    ]
    for font in font_candidates:
        try:
            matplotlib.font_manager.findfont(font, fallback_to_default=False)
            plt.rcParams["font.sans-serif"] = [font]
            plt.rcParams["axes.unicode_minus"] = False
            logger.info(f"使用字体: {font}")
            return plt
        except Exception:
            continue

    # 回退：不设置中文字体，标签用英文
    logger.warning("未找到中文字体，图表标签将使用英文")
    return plt


def render_trend_chart(scout_items: List[Dict], output_path: str, top_n: int = 8) -> Optional[str]:
    """
    生成趋势热度 Top N 条形图。
    输入：Scout 评分后的 items 列表。
    输出：PNG 文件路径。
    """
    plt = _setup_matplotlib()

    if not scout_items:
        logger.warning("无 Scout 数据，跳过趋势图生成")
        return None

    # 按 avg_score 排序，取 Top N
    sorted_items = sorted(scout_items, key=lambda x: x.get("avg_score", 0), reverse=True)[:top_n]

    titles = []
    scores = []
    colors = []
    for item in sorted_items:
        title = item.get("title", "")[:25]
        if len(item.get("title", "")) > 25:
            title += "..."
        titles.append(title)
        scores.append(item.get("avg_score", 0))
        source = item.get("source", "")
        if "Domestic" in source:
            colors.append("#E74C3C")  # 红色=国内
        else:
            colors.append("#3498DB")  # 蓝色=海外

    fig, ax = plt.subplots(figsize=(10, max(4, len(titles) * 0.6)))
    bars = ax.barh(range(len(titles)), scores, color=colors, height=0.6)
    ax.set_yticks(range(len(titles)))
    ax.set_yticklabels(titles, fontsize=9)
    ax.set_xlabel("Score", fontsize=11)
    ax.set_title("Trend Relevance Top {}".format(top_n), fontsize=13, fontweight="bold")
    ax.invert_yaxis()
    ax.set_xlim(0, 10)

    # 添加分数标签
    for bar, score in zip(bars, scores):
        ax.text(bar.get_width() + 0.1, bar.get_y() + bar.get_height() / 2,
                f"{score:.1f}", va="center", fontsize=9)

    # 图例
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor="#3498DB", label="International"),
        Patch(facecolor="#E74C3C", label="Domestic"),
    ]
    ax.legend(handles=legend_elements, loc="lower right", fontsize=9)

    plt.tight_layout()
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()

    logger.info(f"趋势图已保存: {output_path}")
    return output_path


def render_gap_chart(analysis: Dict, output_path: str) -> Optional[str]:
    """
    生成信息差对比表图。
    输入：Sage 分析 JSON。
    输出：PNG 文件路径。
    """
    plt = _setup_matplotlib()

    info_gap = analysis.get("info_gap_analysis", {})
    top3 = analysis.get("top3_topics", [])

    if not top3:
        logger.warning("无 top3 话题数据，跳过信息差图")
        return None

    fig, ax = plt.subplots(figsize=(9, max(3, len(top3) * 1.2 + 1)))
    ax.axis("off")

    # 构建表格数据
    col_labels = ["Topic", "Score", "Domestic Match", "Gap Insight"]
    cell_data = []
    for t in top3[:5]:
        cell_data.append([
            t.get("topic", "")[:15],
            str(t.get("score", "")),
            t.get("domestic_comparison", "")[:20],
            t.get("actionable_advice", "")[:30],
        ])

    table = ax.table(
        cellText=cell_data,
        colLabels=col_labels,
        loc="center",
        cellLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1.2, 1.8)

    # 表头样式
    for j in range(len(col_labels)):
        table[0, j].set_facecolor("#2C3E50")
        table[0, j].set_text_props(color="white", fontweight="bold")

    # 信息差洞察文字
    gap_insight = info_gap.get("gap_insight", "")
    if gap_insight:
        fig.text(0.5, 0.02, f"Gap: {gap_insight[:80]}", ha="center", fontsize=9, style="italic", color="#7F8C8D")

    ax.set_title("Info Gap Analysis", fontsize=13, fontweight="bold", pad=20)
    plt.tight_layout()
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()

    logger.info(f"信息差图已保存: {output_path}")
    return output_path


def run_charts(date_str: Optional[str] = None) -> List[str]:
    """
    生成当天的所有图表，返回 PNG 路径列表。
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")

    charts = []
    chart_dir = PROJECT_ROOT / "pipeline" / "charts"
    chart_dir.mkdir(parents=True, exist_ok=True)

    # 1. 趋势图：从 Scout 数据
    scout_dir = PROJECT_ROOT / "pipeline" / "scout"
    all_items = []
    for f in sorted(scout_dir.glob(f"{date_str}*.json")):
        with open(f, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            all_items.extend(data.get("items", []))

    if all_items:
        trend_path = str(chart_dir / f"{date_str}-trend.png")
        result = render_trend_chart(all_items, trend_path)
        if result:
            charts.append(result)

    # 2. 信息差图：从 Sage 分析
    sage_json = PROJECT_ROOT / "pipeline" / "sage" / f"{date_str}-analysis.json"
    if sage_json.exists():
        with open(sage_json, "r", encoding="utf-8") as f:
            analysis = json.load(f)
        gap_path = str(chart_dir / f"{date_str}-gap.png")
        result = render_gap_chart(analysis, gap_path)
        if result:
            charts.append(result)

    return charts


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Chart Renderer - 自动图表")
    parser.add_argument("--date", type=str, help="目标日期 (YYYYMMDD)")
    args = parser.parse_args()

    date_str = args.date or datetime.now().strftime("%Y%m%d")
    charts = run_charts(date_str)
    if charts:
        print(f"图表生成完成: {charts}")
    else:
        print("无图表生成")


if __name__ == "__main__":
    main()
