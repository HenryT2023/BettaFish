# -*- coding: utf-8 -*-
"""
Observer Runner — 每日审计 + 质量评估

职责：
1. 检查当天 Scout/Sage/Quill 产出
2. 检查 state.json 一致性
3. LLM 质量评分（文章可读性/信息量/标题吸引力）
4. 生成审计报告 → pipeline/observer/
5. Telegram 发送每日运行摘要

用法：
    python observer_runner.py                 # 审计当天
    python observer_runner.py --date 20260213 # 指定日期
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
from pipeline_state import add_observer_flag, load_state, save_state
from telegram_sender import send_message


def check_scout_output(date_str: str) -> Dict:
    """检查 Scout 产出"""
    scout_dir = PROJECT_ROOT / "pipeline" / "scout"
    pattern = str(scout_dir / f"{date_str}-*.json")
    files = glob.glob(pattern)

    total_items = 0
    for fp in files:
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
            total_items += len(data.get("items", []))
        except Exception:
            pass

    return {
        "scout_files": len(files),
        "scout_items": total_items,
        "scout_ok": len(files) >= 1,
        "scout_expected": 6,
    }


def check_sage_output(date_str: str) -> Dict:
    """检查 Sage 产出"""
    sage_json = PROJECT_ROOT / "pipeline" / "sage" / f"{date_str}-analysis.json"
    sage_md = PROJECT_ROOT / "pipeline" / "sage" / f"{date_str}-analysis.md"

    has_json = sage_json.exists()
    has_md = sage_md.exists()

    topic = ""
    if has_json:
        try:
            with open(sage_json, "r", encoding="utf-8") as f:
                data = json.load(f)
            topic = data.get("selected_topic", {}).get("topic", "")
        except Exception:
            pass

    return {
        "sage_json": has_json,
        "sage_md": has_md,
        "sage_topic": topic,
        "sage_ok": has_json and has_md,
    }


def check_quill_output(date_str: str) -> Dict:
    """检查 Quill 产出（含 premium-addon）"""
    drafts_dir = PROJECT_ROOT / "pipeline" / "drafts"
    docx_path = drafts_dir / f"{date_str}-article.docx"
    md_path = drafts_dir / f"{date_str}-article.md"
    premium_path = drafts_dir / f"{date_str}-premium-addon.md"

    docx_exists = docx_path.exists()
    md_exists = md_path.exists()
    premium_exists = premium_path.exists()
    docx_size = docx_path.stat().st_size if docx_exists else 0
    premium_words = 0
    if premium_exists:
        with open(premium_path, "r", encoding="utf-8") as f:
            premium_words = len(f.read())

    return {
        "quill_docx": docx_exists,
        "quill_md": md_exists,
        "quill_docx_size": docx_size,
        "quill_ok": docx_exists and docx_size > 1000,
        "premium_exists": premium_exists,
        "premium_words": premium_words,
    }


def check_state_consistency() -> Dict:
    """检查 state.json 一致性"""
    state = load_state()
    issues = []

    urls = state.get("processed_urls", [])
    if len(urls) != len(set(urls)):
        issues.append("processed_urls 有重复")

    topics = state.get("written_topics", [])
    for t in topics:
        if isinstance(t, dict) and not t.get("date"):
            issues.append(f"written_topics 条目缺少 date: {t}")

    count = state.get("daily_publish_count", 0)
    if count < 0:
        issues.append(f"daily_publish_count 为负数: {count}")

    return {
        "state_url_count": len(urls),
        "state_topic_count": len(topics),
        "state_publish_count": count,
        "state_issues": issues,
        "state_ok": len(issues) == 0,
    }


def quality_audit_article(date_str: str) -> Dict:
    """LLM 质量评分"""
    md_path = PROJECT_ROOT / "pipeline" / "drafts" / f"{date_str}-article.md"
    if not md_path.exists():
        return {"quality_score": 0, "quality_ok": False, "quality_reason": "文章不存在"}

    try:
        with open(md_path, "r", encoding="utf-8") as f:
            article_text = f.read()
    except Exception:
        return {"quality_score": 0, "quality_ok": False, "quality_reason": "读取失败"}

    if len(article_text) < 500:
        return {"quality_score": 3, "quality_ok": False, "quality_reason": "文章过短"}

    api_key = settings.INSIGHT_ENGINE_API_KEY or settings.QUERY_ENGINE_API_KEY
    base_url = settings.INSIGHT_ENGINE_BASE_URL or settings.QUERY_ENGINE_BASE_URL
    model = settings.INSIGHT_ENGINE_MODEL_NAME or "qwen-max"

    if not api_key:
        return {"quality_score": 5, "quality_ok": True, "quality_reason": "无 LLM Key，跳过评分"}

    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=base_url)

    system_prompt = """你是公众号文章质量与商业化审核员。请对文章评分并输出 JSON：
{
  "readability": 1-10,
  "info_value": 1-10,
  "title_appeal": 1-10,
  "sellability": 1-10,
  "overall": 1-10,
  "issues": ["问题1", "问题2"],
  "suggestion": "一句话改进建议",
  "monetization_hint": "付费内容可以怎么延伸（20字）"
}

sellability 评分维度：
- 话题是否有付费深挖空间（数据报告/工具测评/案例拆解）
- 文末是否有自然的付费引导
- 内容是否留了"钩子"（读者想看完整版的动力）
- 目标读者的付费意愿（跨境电商/SaaS 从业者偏高）

只返回 JSON。"""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": article_text[:10000]},
            ],
            temperature=0.2,
            timeout=60,
        )
        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1]
            if content.endswith("```"):
                content = content[:-3]

        import json_repair
        scores = json_repair.loads(content)
        overall = scores.get("overall", 5)

        return {
            "quality_score": overall,
            "quality_detail": scores,
            "quality_ok": overall >= 6,
            "quality_reason": scores.get("suggestion", ""),
        }
    except Exception as e:
        logger.warning(f"质量评分失败: {e}")
        return {"quality_score": 5, "quality_ok": True, "quality_reason": f"评分异常: {e}"}


def run_observer(date_str: Optional[str] = None) -> Optional[str]:
    """执行每日审计"""
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")

    logger.info(f"=== Observer 开始 | date={date_str} ===")

    # 1. 各模块产出检查
    scout = check_scout_output(date_str)
    sage = check_sage_output(date_str)
    quill = check_quill_output(date_str)
    state_check = check_state_consistency()

    # 2. 质量审计
    quality = quality_audit_article(date_str)

    # 3. 汇总
    audit = {
        "date": date_str,
        "timestamp": datetime.now().isoformat(),
        **scout,
        **sage,
        **quill,
        **state_check,
        **quality,
    }

    all_ok = scout["scout_ok"] and sage["sage_ok"] and quill["quill_ok"] and state_check["state_ok"]

    # 4. 记录 Observer 标记
    state = load_state()
    if not all_ok:
        issues = []
        if not scout["scout_ok"]:
            issues.append(f"Scout: {scout['scout_files']} files (期望>=1)")
        if not sage["sage_ok"]:
            issues.append("Sage: 无分析输出")
        if not quill["quill_ok"]:
            issues.append("Quill: 无文章输出")
        if state_check["state_issues"]:
            issues.extend(state_check["state_issues"])
        add_observer_flag("daily_audit_issues", "; ".join(issues), state)

    if not quality.get("quality_ok"):
        add_observer_flag("quality_below_threshold", f"score={quality['quality_score']}", state)

    save_state(state)

    # 5. 保存审计报告
    output_dir = PROJECT_ROOT / "pipeline" / "observer"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{date_str}-audit.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)

    # 6. Telegram 报告（精简版：只列搜索标题，不给建议）
    status_tag = "OK" if all_ok else "WARN"

    report_text = (
        f"<b>Observer {date_str} [{status_tag}]</b>\n\n"
        f"Scout: {scout['scout_files']}批 / {scout['scout_items']}条\n"
        f"Sage: {sage['sage_topic'] if sage['sage_ok'] else '无输出'}\n"
        f"Quill: {str(quill['quill_docx_size']) + 'B' if quill['quill_ok'] else '无输出'}\n"
        f"质量: {quality.get('quality_score', '?')}/10\n"
    )

    # 列出当天 Scout 搜索到的标题
    scout_dir = PROJECT_ROOT / "pipeline" / "scout"
    scout_titles = []
    for fp in sorted(glob.glob(str(scout_dir / f"{date_str}-*.json"))):
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data.get("items", []):
                t = item.get("title", "").strip()
                if t and t not in scout_titles:
                    scout_titles.append(t)
        except Exception:
            pass

    if scout_titles:
        report_text += f"\n<b>今日搜索标题 ({len(scout_titles)}条)</b>\n"
        for t in scout_titles[:20]:
            report_text += f"- {t}\n"
        if len(scout_titles) > 20:
            report_text += f"... 还有 {len(scout_titles) - 20} 条\n"

    if state_check["state_issues"]:
        report_text += f"\nState问题: {'; '.join(state_check['state_issues'])}\n"

    send_message(report_text)
    logger.info(f"=== Observer 完成 | {output_file} ===")
    return str(output_file)


def main():
    parser = argparse.ArgumentParser(description="Observer Runner - 每日审计")
    parser.add_argument("--date", type=str, help="审计日期 (YYYYMMDD)")
    args = parser.parse_args()

    result = run_observer(date_str=args.date)
    if result:
        print(f"Observer 完成: {result}")
    else:
        print("Observer 完成: 无输出")


if __name__ == "__main__":
    main()
