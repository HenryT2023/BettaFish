# -*- coding: utf-8 -*-
"""
Image Generator — Nano Banana 图片生成

职责：
1. 为每篇文章生成封面图（Nano Banana Pro / Flash Image）
2. 生成信息差概念关系图
3. 输出 PNG → pipeline/charts/

依赖：pip install google-genai Pillow

用法：
    python image_generator.py --date 20260213
"""
from __future__ import annotations

import json
import os
import random
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List

from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent

# Nano Banana 模型名（标准版用 Flash Image，Pro 版用 gemini-3-pro-image-preview）
MODEL_COVER = "gemini-3-pro-image-preview"
MODEL_DIAGRAM = "gemini-3-pro-image-preview"

# 风格池：每次随机组合，避免封面图千篇一律
_PALETTES = [
    "deep blue and teal with white accents",
    "warm amber and burnt orange with cream highlights",
    "forest green and gold with dark slate background",
    "rich crimson and champagne gold on charcoal",
    "soft lavender and silver with pearl white",
    "midnight indigo and electric cyan on matte black",
    "coral pink and sage green with sandy beige",
    "steel grey and bright yellow with clean white",
]
_COMPOSITIONS = [
    "isometric 3D perspective with floating elements",
    "top-down bird's-eye view with layered depth",
    "split-screen comparison layout with central divider",
    "radial burst composition emanating from center",
    "flowing wave patterns with smooth gradients",
    "interconnected node network with glowing edges",
    "stacked horizontal bands with subtle parallax",
    "diagonal slash composition with bold contrast",
]
_METAPHORS = [
    "abstract geometric shapes representing data flow and global commerce",
    "stylized world map fragments with trade route lines",
    "interlocking gears and circuit patterns symbolizing supply chains",
    "rising bar charts morphing into city skylines",
    "shipping containers and cargo ships in minimalist silhouette",
    "digital currency symbols flowing through fiber optic streams",
    "puzzle pieces connecting across continents",
    "layered transparent cards showing market dashboards",
]


def _get_client():
    """初始化 google-genai 客户端"""
    from google import genai

    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        # 尝试从 BettaFish .env 读取
        from config import settings
        api_key = (
            getattr(settings, "INSIGHT_ENGINE_API_KEY", "")
            or getattr(settings, "MEDIA_ENGINE_API_KEY", "")
            or ""
        )
    if not api_key:
        logger.error("无 Gemini API Key，无法生成图片")
        return None

    return genai.Client(api_key=api_key)


def generate_cover_image(
    topic: str,
    keywords: List[str],
    output_path: str,
    aspect_ratio: str = "16:9",
) -> Optional[str]:
    """
    用 Nano Banana 生成文章封面图。
    Prompt 用英文（避免中文乱码），风格：科技商业插画。
    """
    from google.genai import types

    client = _get_client()
    if not client:
        return None

    kw_str = ", ".join(keywords[:5])
    palette = random.choice(_PALETTES)
    composition = random.choice(_COMPOSITIONS)
    metaphor = random.choice(_METAPHORS)
    # 从 topic 中提取短标题（8字以内）
    short_title = topic[:8] if len(topic) > 8 else topic
    prompt = (
        f"生成一张公众号封面图。"
        f"主题：{topic}。关键词：{kw_str}。"
        f"风格：商业科技杂志封面，扁平插画，{palette}。"
        f"构图：{composition}。"
        f"视觉元素：{metaphor}。"
        f"图片正中央必须包含中文大标题「{short_title}」，白色粗体字，清晰可读。"
        f"不要出现人脸。专业公众号封面风格。"
    )

    try:
        response = client.models.generate_content(
            model=MODEL_COVER,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(
                    aspect_ratio=aspect_ratio,
                ),
            ),
        )

        for part in response.parts:
            if part.inline_data:
                image = part.as_image()
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                image.save(output_path)
                logger.info(f"封面图已保存: {output_path}")
                return output_path

        logger.warning("Nano Banana 未返回图片")
        return None

    except Exception as e:
        logger.warning(f"封面图生成失败: {e}")
        return None


def generate_gap_diagram(
    topic: str,
    international_view: str,
    domestic_view: str,
    gap_insight: str,
    output_path: str,
) -> Optional[str]:
    """
    用 Nano Banana 生成信息差概念关系图。
    展示海外 vs 国内的信息流和差距。
    """
    from google.genai import types

    client = _get_client()
    if not client:
        return None

    palette = random.choice(_PALETTES)
    composition = random.choice([
        "维恩图交叉发光区域",
        "双栏对比加桥梁箭头连接",
        "天平秤两侧加权元素",
        "双雷达图并排对比",
        "冰山图展示可见层与隐藏层",
    ])
    prompt = (
        f"生成一张信息差对比图。"
        f"左侧标注「海外」：{international_view[:80]}。"
        f"右侧标注「国内」：{domestic_view[:80]}。"
        f"中间用箭头或桥梁表示信息差：{gap_insight[:80]}。"
        f"构图：{composition}。配色：{palette}。"
        f"关键标签用中文。底部小字：东旺数贸。"
        f"风格：深色背景，数据仪表盘风格，专业商业信息图。"
        f"不要出现水印。"
    )

    try:
        response = client.models.generate_content(
            model=MODEL_DIAGRAM,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(
                    aspect_ratio="16:9",
                ),
            ),
        )

        for part in response.parts:
            if part.inline_data:
                image = part.as_image()
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                image.save(output_path)
                logger.info(f"信息差关系图已保存: {output_path}")
                return output_path

        logger.warning("Nano Banana 未返回信息差图")
        return None

    except Exception as e:
        logger.warning(f"信息差关系图生成失败: {e}")
        return None


def run_image_gen(date_str: Optional[str] = None) -> List[str]:
    """
    为当天文章生成所有 Nano Banana 图片。
    读取 Sage 分析 JSON，生成封面图 + 信息差关系图。
    返回生成的图片路径列表。
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")

    images = []
    chart_dir = PROJECT_ROOT / "pipeline" / "charts"
    chart_dir.mkdir(parents=True, exist_ok=True)

    # 加载 Sage 分析
    sage_json = PROJECT_ROOT / "pipeline" / "sage" / f"{date_str}-analysis.json"
    if not sage_json.exists():
        logger.warning(f"无 Sage 分析文件: {sage_json}")
        return images

    with open(sage_json, "r", encoding="utf-8") as f:
        analysis = json.load(f)

    selected = analysis.get("selected_topic", {})
    topic = selected.get("topic", "")
    info_gap = analysis.get("info_gap_analysis", {})

    if not topic:
        logger.warning("无选定话题，跳过图片生成")
        return images

    # 提取关键词
    keywords = []
    for ev in selected.get("evidence", []):
        keywords.extend(ev.get("verifiable_facts", []))
    if not keywords:
        keywords = [topic]

    # 1. 封面图
    logger.info(f">>> 生成封面图: {topic}")
    cover_path = str(chart_dir / f"{date_str}-cover.png")
    result = generate_cover_image(topic, keywords, cover_path)
    if result:
        images.append(result)

    # 2. 信息差关系图
    if info_gap:
        logger.info(f">>> 生成信息差关系图")
        gap_path = str(chart_dir / f"{date_str}-gap-ai.png")
        result = generate_gap_diagram(
            topic=topic,
            international_view=info_gap.get("international_view", ""),
            domestic_view=info_gap.get("domestic_view", ""),
            gap_insight=info_gap.get("gap_insight", ""),
            output_path=gap_path,
        )
        if result:
            images.append(result)

    return images


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Image Generator - Nano Banana")
    parser.add_argument("--date", type=str, help="目标日期 (YYYYMMDD)")
    args = parser.parse_args()

    date_str = args.date or datetime.now().strftime("%Y%m%d")
    images = run_image_gen(date_str)
    if images:
        print(f"图片生成完成: {images}")
    else:
        print("无图片生成")


if __name__ == "__main__":
    main()
