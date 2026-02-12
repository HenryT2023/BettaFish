# -*- coding: utf-8 -*-
"""
Trend DB — 轻量级 SQLite 数据资产管理

职责：
1. 沉淀每日 Scout 搜索结果（话题、评分、来源）
2. 沉淀 Sage 证据块（URL、引用、事实）
3. 查询话题频次、热度趋势、证据复用
4. 为 Observer/Growth 提供历史数据

表结构：
- scout_items: 每条搜索结果
- sage_evidence: 每条证据
- topics: 去重后的话题索引
- publish_log: 每日发布记录

用法：
    from trend_db import TrendDB
    db = TrendDB()
    db.ingest_scout("20260213", scout_items)
    db.ingest_sage("20260213", analysis)
    hot = db.get_hot_topics(days=7, top_n=10)
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent
DB_PATH = PROJECT_ROOT / "pipeline" / "trend.db"


class TrendDB:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or str(DB_PATH)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self):
        cur = self.conn.cursor()
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS scout_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_date TEXT NOT NULL,
                title TEXT,
                url TEXT UNIQUE,
                source TEXT,
                keyword TEXT,
                content TEXT,
                china_relevance REAL DEFAULT 0,
                info_asymmetry REAL DEFAULT 0,
                wechat_potential REAL DEFAULT 0,
                avg_score REAL DEFAULT 0,
                china_angle TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS sage_evidence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_date TEXT NOT NULL,
                topic TEXT,
                ref_id INTEGER,
                source_url TEXT,
                source_title TEXT,
                quote TEXT,
                verifiable_facts TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT UNIQUE,
                first_seen TEXT,
                last_seen TEXT,
                frequency INTEGER DEFAULT 1,
                best_score REAL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS publish_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_date TEXT NOT NULL,
                topic TEXT,
                title TEXT,
                article_words INTEGER DEFAULT 0,
                premium_words INTEGER DEFAULT 0,
                growth_words INTEGER DEFAULT 0,
                charts_count INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_scout_date ON scout_items(batch_date);
            CREATE INDEX IF NOT EXISTS idx_evidence_date ON sage_evidence(batch_date);
            CREATE INDEX IF NOT EXISTS idx_topics_freq ON topics(frequency DESC);
        """)
        self.conn.commit()

    def ingest_scout(self, batch_date: str, items: List[Dict]) -> int:
        """入库 Scout 搜索结果，返回新增条数"""
        cur = self.conn.cursor()
        inserted = 0
        for item in items:
            try:
                cur.execute("""
                    INSERT OR IGNORE INTO scout_items
                    (batch_date, title, url, source, keyword, content,
                     china_relevance, info_asymmetry, wechat_potential, avg_score, china_angle)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    batch_date,
                    item.get("title", ""),
                    item.get("url", ""),
                    item.get("source", ""),
                    item.get("keyword", ""),
                    item.get("content", "")[:500],
                    item.get("china_relevance", 0),
                    item.get("info_asymmetry", 0),
                    item.get("wechat_potential", 0),
                    item.get("avg_score", 0),
                    item.get("china_angle", ""),
                ))
                if cur.rowcount > 0:
                    inserted += 1
            except Exception as e:
                logger.debug(f"Scout 入库跳过: {e}")
        self.conn.commit()
        logger.info(f"Scout 入库: {inserted}/{len(items)} 条 (date={batch_date})")
        return inserted

    def ingest_sage(self, batch_date: str, analysis: Dict) -> int:
        """入库 Sage 分析结果（证据 + 话题索引），返回新增证据条数"""
        cur = self.conn.cursor()
        inserted = 0

        selected = analysis.get("selected_topic", {})
        topic = selected.get("topic", "")
        evidence_list = selected.get("evidence", [])

        # 证据入库
        for ev in evidence_list:
            facts = ev.get("verifiable_facts", [])
            facts_str = json.dumps(facts, ensure_ascii=False) if facts else ""
            try:
                cur.execute("""
                    INSERT INTO sage_evidence
                    (batch_date, topic, ref_id, source_url, source_title, quote, verifiable_facts)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    batch_date, topic,
                    ev.get("ref_id", 0),
                    ev.get("source_url", ""),
                    ev.get("source_title", ""),
                    ev.get("quote", ""),
                    facts_str,
                ))
                inserted += 1
            except Exception as e:
                logger.debug(f"证据入库跳过: {e}")

        # 话题索引更新
        if topic:
            cur.execute("SELECT id, frequency FROM topics WHERE topic = ?", (topic,))
            row = cur.fetchone()
            best_score = 0
            for t in analysis.get("top3_topics", []):
                if t.get("topic") == topic:
                    best_score = t.get("score", 0)
                    break
            if row:
                cur.execute("""
                    UPDATE topics SET last_seen = ?, frequency = frequency + 1,
                    best_score = MAX(best_score, ?) WHERE id = ?
                """, (batch_date, best_score, row["id"]))
            else:
                cur.execute("""
                    INSERT INTO topics (topic, first_seen, last_seen, frequency, best_score)
                    VALUES (?, ?, ?, 1, ?)
                """, (topic, batch_date, batch_date, best_score))

        self.conn.commit()
        logger.info(f"Sage 入库: {inserted} 条证据, topic='{topic}' (date={batch_date})")
        return inserted

    def log_publish(self, batch_date: str, topic: str, title: str,
                    article_words: int = 0, premium_words: int = 0,
                    growth_words: int = 0, charts_count: int = 0):
        """记录一次发布"""
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO publish_log
            (batch_date, topic, title, article_words, premium_words, growth_words, charts_count)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (batch_date, topic, title, article_words, premium_words, growth_words, charts_count))
        self.conn.commit()

    # ========== 查询接口 ==========

    def get_hot_topics(self, days: int = 7, top_n: int = 10) -> List[Dict]:
        """获取近 N 天的高频话题"""
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
        cur = self.conn.cursor()
        cur.execute("""
            SELECT topic, frequency, best_score, first_seen, last_seen
            FROM topics WHERE last_seen >= ?
            ORDER BY frequency DESC, best_score DESC
            LIMIT ?
        """, (cutoff, top_n))
        return [dict(r) for r in cur.fetchall()]

    def get_evidence_for_topic(self, topic: str, limit: int = 10) -> List[Dict]:
        """获取某话题的所有历史证据"""
        cur = self.conn.cursor()
        cur.execute("""
            SELECT * FROM sage_evidence WHERE topic LIKE ?
            ORDER BY created_at DESC LIMIT ?
        """, (f"%{topic}%", limit))
        return [dict(r) for r in cur.fetchall()]

    def get_daily_stats(self, batch_date: str) -> Dict:
        """获取某天的统计信息"""
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) as cnt FROM scout_items WHERE batch_date = ?", (batch_date,))
        scout_count = cur.fetchone()["cnt"]
        cur.execute("SELECT COUNT(*) as cnt FROM sage_evidence WHERE batch_date = ?", (batch_date,))
        evidence_count = cur.fetchone()["cnt"]
        cur.execute("SELECT * FROM publish_log WHERE batch_date = ? ORDER BY id DESC LIMIT 1", (batch_date,))
        pub = cur.fetchone()
        return {
            "batch_date": batch_date,
            "scout_items": scout_count,
            "evidence_count": evidence_count,
            "publish": dict(pub) if pub else None,
        }

    def get_all_urls(self, days: int = 30) -> List[str]:
        """获取近 N 天已入库的所有 URL（用于去重）"""
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
        cur = self.conn.cursor()
        cur.execute("SELECT url FROM scout_items WHERE batch_date >= ? AND url != ''", (cutoff,))
        return [r["url"] for r in cur.fetchall()]

    def close(self):
        self.conn.close()


def main():
    """CLI: 查看趋势数据库统计"""
    import argparse
    parser = argparse.ArgumentParser(description="Trend DB - 数据资产管理")
    parser.add_argument("--hot", action="store_true", help="查看近7天高频话题")
    parser.add_argument("--stats", type=str, help="查看指定日期统计 (YYYYMMDD)")
    parser.add_argument("--evidence", type=str, help="查看某话题的证据")
    args = parser.parse_args()

    db = TrendDB()
    if args.hot:
        topics = db.get_hot_topics()
        print("=== 近7天高频话题 ===")
        for t in topics:
            print(f"  [{t['frequency']}x] {t['topic']} (score={t['best_score']}, last={t['last_seen']})")
    elif args.stats:
        stats = db.get_daily_stats(args.stats)
        print(f"=== {args.stats} 统计 ===")
        print(f"  Scout: {stats['scout_items']} 条")
        print(f"  Evidence: {stats['evidence_count']} 条")
        if stats['publish']:
            p = stats['publish']
            print(f"  Publish: {p.get('title', '')} ({p.get('article_words', 0)} 字)")
    elif args.evidence:
        evs = db.get_evidence_for_topic(args.evidence)
        print(f"=== '{args.evidence}' 相关证据 ===")
        for ev in evs:
            print(f"  [{ev['batch_date']}] {ev['source_title'][:40]}: {ev['quote'][:60]}...")
    else:
        parser.print_help()
    db.close()


if __name__ == "__main__":
    main()
