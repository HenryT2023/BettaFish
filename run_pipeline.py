# -*- coding: utf-8 -*-
"""
Pipeline 统一入口 — 串联 Scout → Sage → Quill → Observer → Paid

用法：
    python run_pipeline.py --step scout              # 单步：信息扫描
    python run_pipeline.py --step publish             # 单步：Sage + Quill（分析 + 生成 + 发布）
    python run_pipeline.py --step observe             # 单步：Observer 审计
    python run_pipeline.py --step paid                # 单步：付费深度报告
    python run_pipeline.py --step paid --topic "AI"   # 指定话题

    python run_pipeline.py --mode lite                # 全流程 lite（单 Agent）
    python run_pipeline.py --mode full                # 全流程 full（含 ForumEngine）
    python run_pipeline.py --mode auto                # 自动判断（按时间选步骤）
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def step_scout(args):
    """执行 Scout"""
    from scout_runner import run_scout
    result = run_scout(theme_override=args.theme if hasattr(args, "theme") else None)
    return result


def step_publish(args):
    """执行 Sage + Quill + Growth"""
    mode = getattr(args, "mode", "lite") or "lite"
    date_str = getattr(args, "date", None)

    from sage_runner import run_sage
    sage_result = run_sage(date_str=date_str, mode=mode)
    if not sage_result:
        logger.warning("Sage 无结果，跳过 Quill")
        return None

    from quill_runner import run_quill
    quill_result = run_quill(date_str=date_str)

    # Growth：Quill 完成后自动生成增长素材包
    if quill_result:
        try:
            from growth_runner import run_growth
            run_growth(date_str=date_str)
        except Exception as e:
            logger.warning(f"Growth 运行失败（不影响发布）: {e}")

        # Charts：自动生成图表并发送 Telegram
        try:
            from chart_renderer import run_charts
            charts = run_charts(date_str=date_str)
            if charts:
                from telegram_sender import send_document
                for chart_path in charts:
                    send_document(chart_path, caption=f"📊 {Path(chart_path).stem}")
                logger.info(f"图表已发送: {len(charts)} 张")
        except Exception as e:
            logger.warning(f"图表生成/发送失败（不影响发布）: {e}")

    return quill_result


def step_observe(args):
    """执行 Observer"""
    date_str = getattr(args, "date", None)
    from observer_runner import run_observer
    return run_observer(date_str=date_str)


def step_paid(args):
    """执行 Paid Content"""
    topic = getattr(args, "topic", None)
    from paid_content_runner import run_paid_content
    return run_paid_content(topic_override=topic)


def mode_auto(args):
    """
    自动模式：根据当前时间选择步骤。
    - 02/06/10/14/18/22: Scout
    - 09: Sage + Quill (publish)
    - 22: Observer (在 Scout 之后)
    - Friday 14: Paid
    """
    now = datetime.now()
    hour = now.hour
    weekday = now.weekday()  # 0=Monday

    results = []

    # Scout 时段
    if hour in (2, 6, 10, 14, 18, 22):
        logger.info("[Auto] 执行 Scout")
        results.append(("scout", step_scout(args)))

    # Publish 时段
    if 9 <= hour <= 10:
        logger.info("[Auto] 执行 Publish (Sage + Quill)")
        results.append(("publish", step_publish(args)))

    # Observer 时段
    if hour >= 22:
        logger.info("[Auto] 执行 Observer")
        results.append(("observe", step_observe(args)))

    # Paid 时段（周五下午）
    if weekday == 4 and 14 <= hour <= 16:
        logger.info("[Auto] 执行 Paid Content")
        results.append(("paid", step_paid(args)))

    if not results:
        logger.info(f"[Auto] 当前时间 {now.strftime('%H:%M')} 无需执行任何步骤")

    return results


def main():
    parser = argparse.ArgumentParser(
        description="BettaFish Pipeline — 信息差内容工厂",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--step",
        type=str,
        choices=["scout", "publish", "observe", "paid"],
        help="执行单个步骤",
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["lite", "full", "auto"],
        help="执行模式: lite/full=全流程, auto=按时间自动选择",
    )
    parser.add_argument("--date", type=str, help="目标日期 (YYYYMMDD)")
    parser.add_argument("--theme", type=str, help="Scout 主题覆盖")
    parser.add_argument("--topic", type=str, help="Paid Content 话题")

    args = parser.parse_args()

    # 配置日志
    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level:7}</level> | {message}",
        level="INFO",
    )
    log_file = PROJECT_ROOT / "pipeline" / "pipeline.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger.add(str(log_file), rotation="10 MB", retention="7 days", level="DEBUG")

    # 执行
    if args.step:
        step_map = {
            "scout": step_scout,
            "publish": step_publish,
            "observe": step_observe,
            "paid": step_paid,
        }
        handler = step_map[args.step]
        result = handler(args)
        if result:
            print(f"✅ {args.step} 完成: {result}")
        else:
            print(f"⚠️ {args.step} 完成: 无输出")

    elif args.mode == "auto":
        results = mode_auto(args)
        for step_name, result in results:
            status = "✅" if result else "⚠️"
            print(f"{status} {step_name}: {result or '无输出'}")

    elif args.mode in ("lite", "full"):
        logger.info(f"=== 全流程 ({args.mode}) 开始 ===")

        logger.info("[1/4] Scout")
        step_scout(args)

        logger.info("[2/4] Sage + Quill")
        step_publish(args)

        logger.info("[3/4] Observer")
        step_observe(args)

        if args.mode == "full":
            logger.info("[4/4] Paid Content (full mode only)")
            step_paid(args)

        logger.info("=== 全流程完成 ===")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
