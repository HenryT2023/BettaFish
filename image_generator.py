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

# Nano Banana 模型名（Flash 省钱，Pro 质量高）
MODEL_COVER = "gemini-2.0-flash-exp"
MODEL_DIAGRAM = "gemini-2.0-flash-exp"

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


def plan_images(analysis: Dict) -> List[Dict]:
    """
    用 LLM 根据 Sage 分析决定需要生成哪些图片。
    返回图片计划列表，每项包含 type 和 description。
    失败时回退到默认的 cover + gap。
    """
    import sys
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from config import settings

    selected = analysis.get("selected_topic", {})
    topic = selected.get("topic", "")
    outline = analysis.get("outline", "")
    info_gap = analysis.get("info_gap_analysis", {})

    # 默认回退计划
    default_plan = [{"type": "cover", "description": topic}]
    if info_gap:
        default_plan.append({
            "type": "gap",
            "description": info_gap.get("gap_insight", topic),
        })

    api_key = settings.REPORT_ENGINE_API_KEY or settings.INSIGHT_ENGINE_API_KEY
    base_url = settings.REPORT_ENGINE_BASE_URL or settings.INSIGHT_ENGINE_BASE_URL
    model = settings.REPORT_ENGINE_MODEL_NAME or settings.INSIGHT_ENGINE_MODEL_NAME or "qwen-max"
    if not api_key:
        return default_plan

    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=base_url)

    system_prompt = """你是一个图片编辑，负责为公众号文章规划配图。根据文章的话题和大纲，决定需要哪些类型的图片。

可用图片类型：
- cover: 封面图（必选，每篇文章都需要）
- gap: 信息差对比图（文章涉及海外vs国内、信息不对称时使用）
- process: 流程图/时间线（文章涉及步骤、发展阶段、操作指南时使用）
- data: 数据可视化图（文章有关键数字对比、市场数据时使用）
- comparison: 对比图（文章涉及产品/方案/平台 A vs B 对比时使用）

规则：
- 必须包含 cover
- 总共2-3张图，不要超过3张
- 根据文章内容选择最合适的类型，不要强凑
- 每张图给出简短的中文描述（说明这张图应该展示什么）

输出 JSON 数组，格式：
[{"type": "cover", "description": "..."}, {"type": "data", "description": "..."}]
只输出 JSON，不要其他内容。"""

    context = f"话题：{topic}\n大纲：{str(outline)[:500]}"
    if info_gap:
        context += f"\n信息差：海外视角={info_gap.get('international_view', '')}，国内视角={info_gap.get('domestic_view', '')}"

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": context},
            ],
            temperature=0.3,
            timeout=30,
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            raw = raw.rsplit("```", 1)[0]
        plan = json.loads(raw)

        # 校验：必须是 list，每项必须有 type 和 description
        valid_types = {"cover", "gap", "process", "data", "comparison"}
        validated = []
        for item in plan:
            if isinstance(item, dict) and item.get("type") in valid_types:
                validated.append(item)
        if not any(p["type"] == "cover" for p in validated):
            validated.insert(0, {"type": "cover", "description": topic})

        logger.info(f"图片计划: {[p['type'] for p in validated]}")
        return validated[:3]

    except Exception as e:
        logger.warning(f"图片规划 LLM 失败（{e}），使用默认计划")
        return default_plan


def generate_contextual_image(
    image_type: str,
    topic: str,
    description: str,
    output_path: str,
    info_gap: Optional[Dict] = None,
    keywords: Optional[List[str]] = None,
) -> Optional[str]:
    """
    根据图片类型生成对应的图片。
    统一入口，内部根据 type 构建不同的 prompt。
    """
    from google.genai import types

    client = _get_client()
    if not client:
        return None

    palette = random.choice(_PALETTES)
    composition = random.choice(_COMPOSITIONS)

    if image_type == "cover":
        kw_str = ", ".join((keywords or [topic])[:5])
        metaphor = random.choice(_METAPHORS)
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
    elif image_type == "gap":
        gap = info_gap or {}
        gap_composition = random.choice([
            "维恩图交叉发光区域",
            "双栏对比加桥梁箭头连接",
            "天平秤两侧加权元素",
            "双雷达图并排对比",
            "冰山图展示可见层与隐藏层",
        ])
        prompt = (
            f"生成一张信息差对比图。"
            f"左侧标注「海外」：{gap.get('international_view', description)[:80]}。"
            f"右侧标注「国内」：{gap.get('domestic_view', description)[:80]}。"
            f"中间用箭头或桥梁表示信息差：{gap.get('gap_insight', description)[:80]}。"
            f"构图：{gap_composition}。配色：{palette}。"
            f"关键标签用中文。底部小字：东旺数贸。"
            f"风格：深色背景，数据仪表盘风格，专业商业信息图。"
            f"不要出现水印。"
        )
    elif image_type == "process":
        prompt = (
            f"生成一张流程图/时间线信息图。"
            f"主题：{topic}。"
            f"内容：{description[:120]}。"
            f"风格：从左到右或从上到下的清晰流程箭头，每个步骤用图标和简短中文标签。"
            f"配色：{palette}。"
            f"底部小字：东旺数贸。"
            f"深色背景，扁平设计，专业信息图风格。"
            f"不要出现人脸或水印。"
        )
    elif image_type == "data":
        prompt = (
            f"生成一张数据可视化信息图。"
            f"主题：{topic}。"
            f"展示内容：{description[:120]}。"
            f"风格：仪表盘式布局，包含柱状图/饼图/数字卡片等数据元素。"
            f"关键数字用大号中文标注。"
            f"配色：{palette}。"
            f"底部小字：东旺数贸。"
            f"深色背景，现代商业数据报告风格。"
            f"不要出现人脸或水印。"
        )
    elif image_type == "comparison":
        prompt = (
            f"生成一张对比分析信息图。"
            f"主题：{topic}。"
            f"对比内容：{description[:120]}。"
            f"风格：左右分栏对比，每侧用图标和中文标签列出要点，中间用VS或分隔线。"
            f"配色：{palette}。"
            f"底部小字：东旺数贸。"
            f"深色背景，专业商业对比图风格。"
            f"不要出现人脸或水印。"
        )
    else:
        logger.warning(f"未知图片类型: {image_type}")
        return None

    try:
        response = client.models.generate_content(
            model=MODEL_COVER if image_type == "cover" else MODEL_DIAGRAM,
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
                logger.info(f"{image_type} 图已保存: {output_path}")
                return output_path

        logger.warning(f"Nano Banana 未返回 {image_type} 图")
        return None

    except Exception as e:
        logger.warning(f"{image_type} 图生成失败: {e}")
        return None


def run_image_gen(date_str: Optional[str] = None) -> List[str]:
    """
    为当天文章动态生成图片。
    先用 LLM 规划需要哪些图片类型，再逐张生成。
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

    # LLM 动态规划图片类型
    image_plan = plan_images(analysis)
    logger.info(f">>> 图片计划: {[p['type'] for p in image_plan]}")

    # 逐张生成
    type_suffix = {
        "cover": "cover",
        "gap": "gap-ai",
        "process": "process",
        "data": "data-viz",
        "comparison": "comparison",
    }
    for plan_item in image_plan:
        img_type = plan_item["type"]
        desc = plan_item.get("description", topic)
        suffix = type_suffix.get(img_type, img_type)
        output_path = str(chart_dir / f"{date_str}-{suffix}.png")

        logger.info(f">>> 生成 {img_type} 图: {desc[:50]}")
        result = generate_contextual_image(
            image_type=img_type,
            topic=topic,
            description=desc,
            output_path=output_path,
            info_gap=info_gap if img_type == "gap" else None,
            keywords=keywords if img_type == "cover" else None,
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
