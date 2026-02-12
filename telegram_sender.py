# -*- coding: utf-8 -*-
"""
Telegram Sender — 发送 .docx 文件到 Telegram

通过 Telegram Bot API sendDocument 发送文件，
触发 wechat-publisher cron 自动处理。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

import requests
from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings


def _get_telegram_config() -> tuple:
    """获取 Telegram 配置，优先从 BettaFish settings，回退到环境变量"""
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", None) or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = getattr(settings, "TELEGRAM_CHAT_ID", None) or os.environ.get("TELEGRAM_CHAT_ID", "")
    return token, chat_id


def send_document(
    file_path: str,
    caption: str = "",
    chat_id: Optional[str] = None,
) -> bool:
    """
    发送文档到 Telegram。

    Args:
        file_path: 本地文件路径
        caption: 附带的文字说明（可选，最多 1024 字符）
        chat_id: 目标 chat ID（可选，默认从配置读取）

    Returns:
        是否发送成功
    """
    token, default_chat_id = _get_telegram_config()
    target_chat = chat_id or default_chat_id

    if not token:
        logger.error("TELEGRAM_BOT_TOKEN 未配置")
        return False
    if not target_chat:
        logger.error("TELEGRAM_CHAT_ID 未配置")
        return False

    if not os.path.exists(file_path):
        logger.error(f"文件不存在: {file_path}")
        return False

    proxy = os.environ.get("https_proxy", os.environ.get("HTTPS_PROXY", ""))
    proxies = {"https": proxy, "http": proxy} if proxy else {}

    url = f"https://api.telegram.org/bot{token}/sendDocument"

    try:
        with open(file_path, "rb") as f:
            files = {"document": (os.path.basename(file_path), f)}
            data = {"chat_id": target_chat}
            if caption:
                data["caption"] = caption[:1024]

            resp = requests.post(url, data=data, files=files, timeout=60, proxies=proxies)
            result = resp.json()

            if result.get("ok"):
                logger.info(f"文件发送成功: {file_path} → chat_id={target_chat}")
                return True
            else:
                logger.error(f"Telegram API 错误: {result.get('description', 'unknown')}")
                return False

    except Exception as e:
        logger.error(f"发送文件失败: {e}")
        return False


def send_message(
    text: str,
    chat_id: Optional[str] = None,
    parse_mode: str = "HTML",
) -> bool:
    """
    发送文字消息到 Telegram。

    Args:
        text: 消息文本
        chat_id: 目标 chat ID
        parse_mode: 解析模式 (HTML / Markdown)

    Returns:
        是否发送成功
    """
    token, default_chat_id = _get_telegram_config()
    target_chat = chat_id or default_chat_id

    if not token or not target_chat:
        logger.error("Telegram 配置不完整")
        return False

    proxy = os.environ.get("https_proxy", os.environ.get("HTTPS_PROXY", ""))
    proxies = {"https": proxy, "http": proxy} if proxy else {}

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    try:
        resp = requests.post(
            url,
            json={
                "chat_id": target_chat,
                "text": text[:4096],
                "parse_mode": parse_mode,
            },
            timeout=10,
            proxies=proxies,
        )
        result = resp.json()
        if result.get("ok"):
            return True
        else:
            logger.error(f"Telegram sendMessage 错误: {result.get('description', '')}")
            return False
    except Exception as e:
        logger.error(f"发送消息失败: {e}")
        return False
