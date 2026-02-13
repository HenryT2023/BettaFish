# -*- coding: utf-8 -*-
"""
Pipeline 状态管理模块

管理 URL 去重、话题冷却、每日发布计数、Observer 标记、付费内容队列。
所有状态持久化到 pipeline/state.json，使用原子写入避免损坏。
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

# 状态文件路径
PIPELINE_DIR = Path(__file__).resolve().parent / "pipeline"
STATE_FILE = PIPELINE_DIR / "state.json"

# 默认配置
TOPIC_COOLDOWN_DAYS = 7
MAX_FREE_ARTICLES_PER_DAY = 24
MAX_PAID_ARTICLES_PER_DAY = 1
MAX_PROCESSED_URLS = 5000  # 防止无限增长


def _default_state() -> Dict:
    """返回默认空状态"""
    return {
        "processed_urls": [],
        "written_topics": [],
        "daily_publish_count": 0,
        "last_reset_date": "",
        "observer_flags": [],
        "paid_content_queue": [],
    }


def load_state() -> Dict:
    """
    从 state.json 加载状态，文件不存在则返回默认值。
    自动重置每日计数器（跨天归零）。
    """
    if not STATE_FILE.exists():
        return _default_state()

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
    except (json.JSONDecodeError, IOError):
        return _default_state()

    # 跨天重置 daily_publish_count
    today = datetime.now().strftime("%Y-%m-%d")
    if state.get("last_reset_date") != today:
        state["daily_publish_count"] = 0
        state["last_reset_date"] = today

    return state


def save_state(state: Dict) -> None:
    """
    原子写入 state.json（先写 .tmp 再 rename，防止中断导致损坏）。
    """
    PIPELINE_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(PIPELINE_DIR), suffix=".tmp", prefix="state_"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, str(STATE_FILE))
    except Exception:
        # 清理临时文件
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ======== URL 去重 ========

def is_url_processed(url: str, state: Optional[Dict] = None) -> bool:
    """检查 URL 是否已处理过"""
    if state is None:
        state = load_state()
    return url in state.get("processed_urls", [])


def mark_url_processed(url: str, state: Optional[Dict] = None) -> Dict:
    """标记 URL 为已处理，返回更新后的 state"""
    if state is None:
        state = load_state()
    urls = state.setdefault("processed_urls", [])
    if url not in urls:
        urls.append(url)
    # 防止无限增长：保留最近 N 条
    if len(urls) > MAX_PROCESSED_URLS:
        state["processed_urls"] = urls[-MAX_PROCESSED_URLS:]
    return state


def filter_new_urls(urls: List[str], state: Optional[Dict] = None) -> List[str]:
    """从 URL 列表中过滤出未处理过的"""
    if state is None:
        state = load_state()
    processed = set(state.get("processed_urls", []))
    return [u for u in urls if u not in processed]


# ======== 话题冷却 ========

def is_topic_cooled_down(topic: str, state: Optional[Dict] = None) -> bool:
    """
    检查话题是否在冷却期内。
    written_topics 格式: [{"topic": "xxx", "date": "2026-02-12"}, ...]
    """
    if state is None:
        state = load_state()
    cutoff = (datetime.now() - timedelta(days=TOPIC_COOLDOWN_DAYS)).strftime("%Y-%m-%d")
    topic_lower = topic.lower().strip()
    for entry in state.get("written_topics", []):
        if isinstance(entry, dict):
            if entry.get("topic", "").lower().strip() == topic_lower:
                if entry.get("date", "") >= cutoff:
                    return False  # 还在冷却期
        elif isinstance(entry, str):
            # 兼容旧格式（纯字符串）
            if entry.lower().strip() == topic_lower:
                return False
    return True  # 已过冷却期或从未写过


def mark_topic_written(topic: str, state: Optional[Dict] = None) -> Dict:
    """标记话题为已写作"""
    if state is None:
        state = load_state()
    topics = state.setdefault("written_topics", [])
    topics.append({
        "topic": topic,
        "date": datetime.now().strftime("%Y-%m-%d"),
    })
    # 清理超过 30 天的旧记录
    cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    state["written_topics"] = [
        t for t in topics
        if isinstance(t, dict) and t.get("date", "") >= cutoff
    ]
    return state


# ======== 每日发布计数 ========

def can_publish_free(state: Optional[Dict] = None) -> bool:
    """检查今天是否还能发布免费文章"""
    if state is None:
        state = load_state()
    return state.get("daily_publish_count", 0) < MAX_FREE_ARTICLES_PER_DAY


def increment_publish_count(state: Optional[Dict] = None) -> Dict:
    """增加每日发布计数"""
    if state is None:
        state = load_state()
    state["daily_publish_count"] = state.get("daily_publish_count", 0) + 1
    state["last_reset_date"] = datetime.now().strftime("%Y-%m-%d")
    return state


# ======== Observer 标记 ========

def add_observer_flag(flag: str, detail: str = "", state: Optional[Dict] = None) -> Dict:
    """添加 Observer 审计标记"""
    if state is None:
        state = load_state()
    flags = state.setdefault("observer_flags", [])
    flags.append({
        "flag": flag,
        "detail": detail,
        "timestamp": datetime.now().isoformat(),
    })
    # 保留最近 100 条
    if len(flags) > 100:
        state["observer_flags"] = flags[-100:]
    return state


def get_observer_flags(state: Optional[Dict] = None) -> List[Dict]:
    """获取所有 Observer 标记"""
    if state is None:
        state = load_state()
    return state.get("observer_flags", [])


def clear_observer_flags(state: Optional[Dict] = None) -> Dict:
    """清除所有 Observer 标记"""
    if state is None:
        state = load_state()
    state["observer_flags"] = []
    return state


# ======== 付费内容队列 ========

def enqueue_paid_content(topic: str, priority: str = "normal", state: Optional[Dict] = None) -> Dict:
    """将话题加入付费内容生成队列"""
    if state is None:
        state = load_state()
    queue = state.setdefault("paid_content_queue", [])
    queue.append({
        "topic": topic,
        "priority": priority,
        "added": datetime.now().isoformat(),
        "status": "pending",
    })
    return state


def dequeue_paid_content(state: Optional[Dict] = None) -> Optional[Dict]:
    """从付费内容队列中取出一个待处理项"""
    if state is None:
        state = load_state()
    queue = state.get("paid_content_queue", [])
    for item in queue:
        if item.get("status") == "pending":
            item["status"] = "processing"
            return item
    return None


def mark_paid_content_done(topic: str, state: Optional[Dict] = None) -> Dict:
    """标记付费内容为已完成"""
    if state is None:
        state = load_state()
    for item in state.get("paid_content_queue", []):
        if item.get("topic") == topic:
            item["status"] = "done"
            item["completed"] = datetime.now().isoformat()
    return state


# ======== 便捷组合操作 ========

def check_and_prepare_publish(topic: str) -> Dict:
    """
    发布前综合检查：每日额度 + 话题冷却。
    返回 {"ok": bool, "reason": str, "state": dict}
    """
    state = load_state()
    if not can_publish_free(state):
        return {"ok": False, "reason": "daily_limit_reached", "state": state}
    if not is_topic_cooled_down(topic, state):
        return {"ok": False, "reason": "topic_in_cooldown", "state": state}
    return {"ok": True, "reason": "", "state": state}
