# -*- coding: utf-8 -*-
"""
Quill Runner — 文章生成 + docx 渲染 + Telegram 发送

职责：
1. 读取 Sage 分析结果（JSON + Markdown）
2. 调用 LLM 生成公众号风格完整文章（Markdown）
3. docx_renderer → .docx
4. telegram_sender → 发送到 Telegram → 触发 wechat-publisher
5. 更新 state.json 发布计数

用法：
    python quill_runner.py                        # 自动处理当天 sage 分析
    python quill_runner.py --date 20260213        # 指定日期
"""

from __future__ import annotations

import argparse
import json
import os
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
    can_publish_free,
    increment_publish_count,
    load_state,
    save_state,
)
from telegram_sender import send_document, send_message


def load_sage_analysis(date_str: Optional[str] = None) -> Optional[Dict]:
    """加载指定日期的 Sage 分析 JSON"""
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")

    json_path = PROJECT_ROOT / "pipeline" / "sage" / f"{date_str}-analysis.json"
    if not json_path.exists():
        logger.warning(f"Sage 分析不存在: {json_path}")
        return None

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"加载 Sage 分析失败: {e}")
        return None


def generate_article_markdown(analysis: Dict) -> str:
    """
    调用 LLM 生成公众号风格完整文章（Markdown 格式）。
    输入：Sage 分析的 selected_topic + outline。
    输出：1500-3000 字的 Markdown 文章。
    """
    from openai import OpenAI

    api_key = settings.REPORT_ENGINE_API_KEY or settings.INSIGHT_ENGINE_API_KEY
    base_url = settings.REPORT_ENGINE_BASE_URL or settings.INSIGHT_ENGINE_BASE_URL
    model = settings.REPORT_ENGINE_MODEL_NAME or settings.INSIGHT_ENGINE_MODEL_NAME or "qwen-max"

    if not api_key:
        logger.error("无可用 LLM API Key，无法生成文章")
        return ""

    client = OpenAI(api_key=api_key, base_url=base_url)

    selected = analysis.get("selected_topic", {})
    topic = selected.get("topic", "")
    headlines = selected.get("headlines", [])
    outline = selected.get("outline", [])
    forum_summary = analysis.get("forum_summary", "")

    # 构建大纲文本
    outline_text = ""
    if isinstance(outline, list):
        for section in outline:
            if isinstance(section, dict):
                outline_text += f"- {section.get('title', '')}: {section.get('points', section.get('content', ''))}\n"
            elif isinstance(section, str):
                outline_text += f"- {section}\n"
    elif isinstance(outline, str):
        outline_text = outline

    # 多视角参考
    forum_text = ""
    if forum_summary:
        if isinstance(forum_summary, dict):
            for agent, view in forum_summary.items():
                forum_text += f"- {agent}: {view}\n"
        else:
            forum_text = str(forum_summary)

    system_prompt = """你是「东旺数贸」公众号的资深撰稿人。
你的读者是：跨境电商从业者、数字贸易关注者、AI工具爱好者。

写作要求：
1. 标题：从候选标题中选最好的一个，或改写得更好（20字以内）
2. 导语：用数据/故事/对比开头，100字内，直击痛点，不要废话
3. 正文：3-5个小节，每节有醒目小标题（## 格式）
4. 每段 80-150 字，避免大段落
5. 用 **加粗** 突出关键数据和观点
6. 结尾：一句话总结 + 互动提问
7. 总长 1500-3000 字
8. 语气：专业但不学术，有信息差感，让读者觉得"学到了"
9. 输出纯 Markdown 格式，不要代码块包裹

禁止：
- 不要用"本文将介绍"之类的废话开头
- 不要用"总之/综上所述"做机械总结
- 不要堆砌信息，要有洞察和观点"""

    user_prompt = f"""话题：{topic}

标题候选：
{chr(10).join(f'- {h}' for h in headlines)}

文章大纲：
{outline_text}

多视角参考：
{forum_text}

请根据以上信息撰写完整的公众号文章（Markdown 格式）。"""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt[:20000]},
            ],
            temperature=0.7,
            timeout=180,
        )
        content = response.choices[0].message.content.strip()

        # 清理可能的 markdown 代码块包裹
        if content.startswith("```markdown"):
            content = content[len("```markdown"):].strip()
        if content.startswith("```"):
            content = content[3:].strip()
        if content.endswith("```"):
            content = content[:-3].strip()

        return content

    except Exception as e:
        logger.error(f"文章生成失败: {e}")
        return ""


def _import_docx_renderer():
    """直接加载 docx_renderer 模块，绕过 ReportEngine/__init__ 的重依赖链"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "docx_renderer",
        str(PROJECT_ROOT / "ReportEngine" / "renderers" / "docx_renderer.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.DocxRenderer


def render_docx(markdown_text: str, output_path: str) -> Optional[str]:
    """将 Markdown 文本渲染为 .docx"""
    try:
        DocxRenderer = _import_docx_renderer()
        renderer = DocxRenderer()
        renderer.render_from_markdown(markdown_text)
        renderer.save(output_path)
        return output_path

    except Exception as e:
        logger.error(f"DOCX 渲染失败: {e}")
        return None


def run_quill(date_str: Optional[str] = None) -> Optional[str]:
    """
    执行 Quill：生成文章 → docx → 发送 Telegram。
    返回 .docx 文件路径，失败返回 None。
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")

    logger.info(f"=== Quill 开始 | date={date_str} ===")

    # 0. 检查每日发布额度
    state = load_state()
    if not can_publish_free(state):
        logger.warning("今日免费文章额度已用完，跳过")
        return None

    # 1. 加载 Sage 分析
    analysis = load_sage_analysis(date_str)
    if not analysis:
        logger.warning("无 Sage 分析数据，Quill 跳过")
        return None

    selected = analysis.get("selected_topic", {})
    topic = selected.get("topic", "")
    if not topic:
        logger.warning("Sage 未选定话题，跳过")
        return None

    logger.info(f">>> 话题: {topic}")

    # 2. 生成文章
    logger.info(">>> 生成文章...")
    article_md = generate_article_markdown(analysis)
    if not article_md or len(article_md) < 500:
        logger.warning(f"文章内容过短 ({len(article_md)} 字)，跳过")
        return None

    logger.info(f">>> 文章生成完成: {len(article_md)} 字")

    # 3. 保存 Markdown 备份
    md_backup = PROJECT_ROOT / "pipeline" / "drafts" / f"{date_str}-article.md"
    md_backup.parent.mkdir(parents=True, exist_ok=True)
    with open(md_backup, "w", encoding="utf-8") as f:
        f.write(article_md)

    # 4. 渲染 docx
    docx_path = str(PROJECT_ROOT / "pipeline" / "drafts" / f"{date_str}-article.docx")
    logger.info(">>> 渲染 DOCX...")
    result = render_docx(article_md, docx_path)
    if not result:
        logger.error("DOCX 渲染失败")
        return None

    logger.info(f">>> DOCX 已保存: {docx_path}")

    # 5. 发送到 Telegram
    # 提取标题（Markdown 第一行 # 开头）
    title = topic
    for line in article_md.split("\n"):
        line = line.strip()
        if line.startswith("# "):
            title = line[2:].strip()
            break

    caption = f"📄 {title}\n\n{article_md[:200]}..."
    logger.info(">>> 发送到 Telegram...")
    sent = send_document(docx_path, caption=caption)
    if sent:
        logger.info(">>> Telegram 发送成功")
    else:
        logger.warning(">>> Telegram 发送失败（文章已保存，可手动发送）")

    # 6. 更新发布计数
    state = load_state()
    increment_publish_count(state)
    save_state(state)

    logger.info(f"=== Quill 完成 | {docx_path} ===")
    return docx_path


def main():
    parser = argparse.ArgumentParser(description="Quill Runner - 文章生成")
    parser.add_argument("--date", type=str, help="目标日期 (YYYYMMDD)")
    args = parser.parse_args()

    result = run_quill(date_str=args.date)
    if result:
        print(f"Quill 完成: {result}")
    else:
        print("Quill 完成: 无输出")


if __name__ == "__main__":
    main()
