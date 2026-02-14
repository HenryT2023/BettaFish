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
    evidence = selected.get("evidence", [])
    forum_summary = analysis.get("forum_summary", "")
    info_gap = analysis.get("info_gap_analysis", {})

    # 构建大纲文本
    outline_text = ""
    if isinstance(outline, list):
        for i, section in enumerate(outline):
            if isinstance(section, dict):
                refs = section.get("evidence_refs", [])
                ref_str = f" [证据: {refs}]" if refs else ""
                outline_text += f"{i+1}. {section.get('title', '')}: {section.get('points', section.get('content', ''))}{ref_str}\n"
            elif isinstance(section, str):
                outline_text += f"{i+1}. {section}\n"
    elif isinstance(outline, str):
        outline_text = outline

    # 构建证据块文本
    evidence_text = ""
    if evidence:
        for ev in evidence:
            evidence_text += (
                f"[证据{ev.get('ref_id', '?')}] {ev.get('source_title', '')}\n"
                f"  URL: {ev.get('source_url', '')}\n"
                f"  原文: {ev.get('quote', '')}\n"
                f"  可验证事实: {', '.join(ev.get('verifiable_facts', []))}\n\n"
            )

    # 信息差分析文本
    gap_text = ""
    if info_gap:
        gap_text = (
            f"海外视角: {info_gap.get('international_view', '')}\n"
            f"国内视角: {info_gap.get('domestic_view', '')}\n"
            f"信息差洞察: {info_gap.get('gap_insight', '')}"
        )

    # 多视角参考
    forum_text = ""
    if forum_summary:
        if isinstance(forum_summary, dict):
            for agent, view in forum_summary.items():
                forum_text += f"- {agent}: {view}\n"
        else:
            forum_text = str(forum_summary)

    system_prompt = """你是一个在跨境电商圈混了十年的人，靠写公众号养活了一个小团队。你的号叫「东旺数贸」，粉丝不多但黏性极强，因为你只写你真正懂的东西。

## 你的人设
- 你在深圳华强北待过，做过亚马逊，现在主要研究AI工具怎么帮卖家省钱
- 你说话直接，偶尔毒舌，但数据一定准
- 你最讨厌的文章类型：「一文读懂XXX」「全面解析XXX」「盘点2026年十大趋势」
- 你写文章像在微信群里给朋友发语音，只不过整理成了文字

## 写法
- 开头30字内必须出现一个具体的数字、人名或事件，不要任何铺垫
- 段落最多3句。超过3句就拆
- 小标题要有态度，不要描述性标题。比如"Temu的算盘没打响"而不是"Temu近期发展分析"
- 如果你要引用数据，直接说来源（"根据Marketplace Pulse上周的数据"），不要"据统计""有数据显示"
- 允许出现一两句脏话级别的口语（"说白了就是割韭菜""这玩意儿就是换皮"）
- 文章里有且只有一个表格，放在最能形成对比冲击的位置
- 全文不超过2000字。写完如果超了，砍掉最弱的一节

## 结构
1. 标题：从候选中选最好的或改写（20字以内），以 # 开头
2. 开头：一个具体事实或场景，30-50字，直接进
3. 正文3-4个小节，用 ## 小标题，小标题必须有观点
4. 关键数据用 **加粗**，只能来自证据块
5. 结尾只写两件事：你的一句判断 + 一个反问。不要总结，不要升华
6. 输出纯 Markdown，不要代码块包裹

## 绝对不能出现的词和句式
"随着" "在当今" "值得注意的是" "不可否认" "毋庸置疑" "众所周知"
"让我们" "本文将" "综上所述" "总而言之" "事实上" "显而易见"
"首先...其次...最后" "一方面...另一方面"
"为XXX提供了新的思路" "对XXX具有重要意义" "为XXX注入新动能"
"据统计" "据报告" "据了解" "有数据显示"
任何以"在"字开头的段落
禁止编造数字/金额/百分比——只能引用证据块中的 verifiable_facts
禁止每段都用相同句式开头
禁止在每节结尾都列3条 bullet"""

    user_prompt = f"""话题：{topic}

标题候选：
{chr(10).join(f'{i+1}. {h}' for i, h in enumerate(headlines))}

文章大纲：
{outline_text}

=== 证据块（写作时只能引用这些事实）===
{evidence_text if evidence_text else "（无结构化证据，请基于大纲内容写作，不要编造数据）"}

=== 信息差分析 ===
{gap_text if gap_text else "（无信息差分析）"}

=== 多视角参考 ===
{forum_text}

请撰写1500-2500字的公众号文章（Markdown 格式）。"""

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


def render_docx(markdown_text: str, output_path: str, image_paths: Optional[List[str]] = None) -> Optional[str]:
    """将 Markdown 文本渲染为 .docx，可选插入图片"""
    try:
        DocxRenderer = _import_docx_renderer()
        renderer = DocxRenderer()
        renderer.render_from_markdown(markdown_text)

        # 插入图片（封面图 + 数据图 + 关系图）
        if image_paths:
            valid_images = [p for p in image_paths if Path(p).exists()]
            if valid_images:
                renderer.insert_images(valid_images)
                logger.info(f"已插入 {len(valid_images)} 张图片到 DOCX")

        renderer.save(output_path)
        return output_path

    except Exception as e:
        logger.error(f"DOCX 渲染失败: {e}")
        return None


def run_quill(date_str: Optional[str] = None, image_paths: Optional[List[str]] = None) -> Optional[str]:
    """
    执行 Quill：生成文章 → docx（含图片）→ 发送 Telegram。
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

    # 4. 渲染 docx（含图片）
    docx_path = str(PROJECT_ROOT / "pipeline" / "drafts" / f"{date_str}-article.docx")
    logger.info(f">>> 渲染 DOCX...（图片: {len(image_paths or [])} 张）")
    result = render_docx(article_md, docx_path, image_paths=image_paths)
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

    word_count = len(article_md)
    caption = f"📄 {title}（{word_count}字）"
    logger.info(">>> 发送到 Telegram...")
    sent = send_document(docx_path, caption=caption)
    if sent:
        logger.info(">>> Telegram 发送成功")
    else:
        logger.warning(">>> Telegram 发送失败（文章已保存，可手动发送）")

    # 6. 生成付费加料 premium-addon
    _generate_premium_addon(analysis, date_str, title)

    # 7. 触发 wechat-publisher 创建公众号草稿
    _trigger_wechat_publisher(docx_path)

    # 8. 更新发布计数
    state = load_state()
    increment_publish_count(state)
    save_state(state)

    logger.info(f"=== Quill 完成 | {docx_path} ===")
    return docx_path


def _generate_premium_addon(analysis: Dict, date_str: str, title: str):
    """生成付费加料 premium-addon.md（300-800字：数据表+行动清单+资源链接）"""
    from openai import OpenAI

    api_key = settings.REPORT_ENGINE_API_KEY or settings.INSIGHT_ENGINE_API_KEY
    base_url = settings.REPORT_ENGINE_BASE_URL or settings.INSIGHT_ENGINE_BASE_URL
    model = settings.REPORT_ENGINE_MODEL_NAME or settings.INSIGHT_ENGINE_MODEL_NAME or "qwen-max"

    if not api_key:
        logger.info("无 LLM API Key，跳过 premium-addon 生成")
        return

    selected = analysis.get("selected_topic", {})
    evidence = selected.get("evidence", [])
    info_gap = analysis.get("info_gap_analysis", {})
    outline = selected.get("outline", [])

    evidence_text = ""
    for ev in evidence:
        evidence_text += f"- [{ev.get('source_title', '')}]({ev.get('source_url', '')}): {ev.get('quote', '')}\n"
        evidence_text += f"  事实: {', '.join(ev.get('verifiable_facts', []))}\n"

    prompt = f"""基于以下信息，生成一份"会员加料"内容（Markdown 格式，300-800字）。

话题：{title}
信息差洞察：{info_gap.get('gap_insight', '')}

证据来源：
{evidence_text}

要求输出结构：
## 📊 数据对比表
（用 Markdown 表格，海外 vs 国内 对比关键指标）

## ✅ 行动清单
（5条可执行步骤，每条1句话，具体可操作）

## 🔗 延伸资源
（3-5个链接，来自证据的原始 URL，附简要说明）

## 💡 深度洞察
（1段100字的独家分析，只在会员版出现）

只输出 Markdown，不要代码块包裹。"""

    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            timeout=60,
        )
        addon_md = response.choices[0].message.content.strip()
        if addon_md.startswith("```"):
            addon_md = addon_md.split("\n", 1)[-1]
        if addon_md.endswith("```"):
            addon_md = addon_md[:-3].strip()

        # 保存
        addon_path = PROJECT_ROOT / "pipeline" / "drafts" / f"{date_str}-premium-addon.md"
        addon_path.parent.mkdir(parents=True, exist_ok=True)
        with open(addon_path, "w", encoding="utf-8") as f:
            f.write(f"# 会员加料 | {title}\n\n{addon_md}")

        logger.info(f">>> Premium addon 已保存: {addon_path} ({len(addon_md)} 字)")

        # 发送到 Premium Telegram 频道（如果配置了）
        paid_chat_id = getattr(settings, "PAID_TELEGRAM_CHAT_ID", None) or os.getenv("PAID_TELEGRAM_CHAT_ID", "")
        if paid_chat_id:
            from telegram_sender import send_message
            send_message(f"🔒 会员加料 | {title}\n\n{addon_md[:3000]}", chat_id=paid_chat_id)
            logger.info(">>> Premium addon 已发送到会员频道")
        else:
            logger.info(">>> PAID_TELEGRAM_CHAT_ID 未配置，跳过会员频道投递")

    except Exception as e:
        logger.warning(f"Premium addon 生成失败: {e}")


def _trigger_wechat_publisher(docx_path: str):
    """直接调用 wechat_publisher_cron.py --file 创建公众号草稿"""
    import subprocess
    wechat_script = Path.home() / "CascadeProjects" / "wechat_publisher_cron.py"
    if not wechat_script.exists():
        logger.info("wechat_publisher_cron.py 不存在，跳过公众号发布")
        return
    try:
        logger.info(">>> 触发 wechat-publisher 创建公众号草稿...")
        result = subprocess.run(
            ["/usr/bin/python3", str(wechat_script), "--file", docx_path],
            capture_output=True, text=True, timeout=120,
            cwd=str(wechat_script.parent),
        )
        if result.returncode == 0:
            logger.info(">>> wechat-publisher 执行成功")
            if result.stdout:
                for line in result.stdout.strip().split("\n")[-5:]:
                    logger.info(f"    {line}")
        else:
            logger.warning(f">>> wechat-publisher 返回码 {result.returncode}")
            if result.stderr:
                logger.warning(f"    {result.stderr[:300]}")
    except subprocess.TimeoutExpired:
        logger.warning(">>> wechat-publisher 超时 (120s)")
    except Exception as e:
        logger.warning(f">>> wechat-publisher 调用失败: {e}")


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
