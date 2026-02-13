# -*- coding: utf-8 -*-
"""
Scout Runner — 信息扫描模块

职责：
1. 根据当前小时确定扫描主题
2. 海外轨：Brave Search API 搜索英文新闻（备选 Tavily）
3. 国内轨：调用 MindSpider BroadTopicExtraction 获取国内热点（需要配置）
4. LLM 评分：china_relevance / info_asymmetry / wechat_potential
5. 去重 + 过滤 → 保存 JSON 到 pipeline/scout/

用法：
    python scout_runner.py                    # 自动按当前小时选主题
    python scout_runner.py --theme "AI Tools"  # 手动指定主题
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger

# 确保项目根目录在 path 中
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings
from pipeline_state import (
    filter_new_urls,
    load_state,
    mark_url_processed,
    save_state,
)

# ======== 赛道定义 & 主题轮换表 ========

# 赛道分层：free = 免费频道可见 / premium = 仅会员频道
TRACK_TIERS: Dict[str, str] = {
    "Cross-border E-commerce": "free",       # 核心赛道，引流
    "AI Tools & Agent":        "free",       # 高传播性，引流
    "SaaS & Digital Trade":    "premium",    # 深度付费
    "Crypto & Web3":           "premium",    # 细分付费
    "Deep/Academic":           "premium",    # 深度付费
    "General Tech":            "free",       # 泛科技，引流
}

THEME_SCHEDULE: Dict[int, Dict] = {
    2:  {"theme": "Deep/Academic",           "track_tier": "premium",
         "keywords_en": ["AI commerce research paper 2026", "cross-border trade technology study",
                         "ecommerce AI academic", "global trade digital transformation research"],
         "keywords_cn": ["跨境电商研究报告", "AI商业论文", "数字贸易学术", "电商人工智能白皮书"]},
    6:  {"theme": "AI Tools & Agent",        "track_tier": "free",
         "keywords_en": ["AI agent launch 2026", "new AI tool product", "AI automation startup",
                         "ChatGPT plugin new", "AI workflow tool release", "LLM application business"],
         "keywords_cn": ["AI工具发布", "AI Agent新品", "人工智能自动化", "大模型应用落地", "AI办公效率工具"]},
    10: {"theme": "Cross-border E-commerce", "track_tier": "free",
         "keywords_en": ["cross-border ecommerce trend 2026", "Amazon seller update", "TikTok Shop global",
                         "Temu Shein marketplace news", "Southeast Asia ecommerce", "global logistics DTC"],
         "keywords_cn": ["跨境电商趋势", "亚马逊卖家", "TikTok电商", "拼多多Temu出海", "东南亚电商", "独立站DTC"]},
    14: {"theme": "SaaS & Digital Trade",    "track_tier": "premium",
         "keywords_en": ["SaaS startup funding 2026", "digital trade platform", "B2B SaaS product launch",
                         "supply chain SaaS", "trade compliance software", "ERP ecommerce tool"],
         "keywords_cn": ["SaaS创业融资", "数字贸易平台", "B2B SaaS", "供应链管理软件", "外贸ERP工具"]},
    18: {"theme": "Crypto & Web3",           "track_tier": "premium",
         "keywords_en": ["crypto regulation update 2026", "Web3 commerce", "blockchain trade finance",
                         "stablecoin cross-border payment", "DeFi real world asset", "crypto ETF news"],
         "keywords_cn": ["加密货币监管", "Web3商业", "区块链贸易", "稳定币跨境支付", "数字货币政策"]},
    22: {"theme": "General Tech",            "track_tier": "free",
         "keywords_en": ["trending tech product 2026", "Product Hunt top", "tech startup launch",
                         "silicon valley funding news", "consumer tech breakthrough", "developer tool new"],
         "keywords_cn": ["科技新品", "技术趋势", "创业公司", "硅谷融资", "消费电子新品", "开发者工具"]},
}

# 最大 Scout 条目数
MAX_SCOUT_ITEMS = 8

# LLM 评分阈值
SCORE_THRESHOLD = 6.5


def get_current_theme(hour: Optional[int] = None) -> Dict:
    """根据当前小时获取主题，就近匹配"""
    if hour is None:
        hour = datetime.now().hour
    # 找最近的主题时间点
    schedule_hours = sorted(THEME_SCHEDULE.keys())
    best = schedule_hours[0]
    for h in schedule_hours:
        if h <= hour:
            best = h
    return THEME_SCHEDULE[best]


def _brave_search(query: str, count: int = 10, lang: str = "en", source_tag: str = "Brave/International") -> List[Dict]:
    """
    调用 Brave Search API，返回标准化结果列表。
    lang: "en" 海外搜索 / "zh" 国内搜索
    """
    import requests

    api_key = getattr(settings, "BRAVE_API_KEY", None) or os.getenv("BRAVE_API_KEY", "")
    if not api_key:
        return []

    headers = {"Accept": "application/json", "Accept-Encoding": "gzip", "X-Subscription-Token": api_key}
    params = {"q": query, "count": count, "freshness": "pw"}
    if lang and lang != "auto":
        params["search_lang"] = lang
    try:
        resp = requests.get("https://api.search.brave.com/res/v1/web/search", headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        items = []
        for r in data.get("web", {}).get("results", []):
            items.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": (r.get("description", ""))[:500],
                "source": source_tag,
                "published_date": r.get("page_age", ""),
                "keyword": query,
            })
        return items
    except Exception as e:
        logger.warning(f"Brave Search '{query}' ({lang}) 失败: {e}")
        return []


def _google_news_rss(query: str, lang: str = "en", max_results: int = 10, source_tag: str = "GoogleNews") -> List[Dict]:
    """
    通过 Google News RSS 抓取新闻，免费无限调用。
    lang: "en" 英文 / "zh" 中文
    """
    import requests
    import xml.etree.ElementTree as ET
    from html import unescape

    if lang == "zh":
        url = f"https://news.google.com/rss/search?q={query}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    else:
        url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        items = []
        for item_el in root.findall(".//item")[:max_results]:
            title = item_el.findtext("title", "")
            link = item_el.findtext("link", "")
            desc = unescape(item_el.findtext("description", ""))
            pub_date = item_el.findtext("pubDate", "")
            # 去掉 HTML 标签
            import re
            desc_clean = re.sub(r"<[^>]+>", "", desc)[:500]
            items.append({
                "title": title,
                "url": link,
                "content": desc_clean,
                "source": source_tag,
                "published_date": pub_date,
                "keyword": query,
            })
        return items
    except Exception as e:
        logger.warning(f"Google News RSS '{query}' ({lang}) 失败: {e}")
        return []


def _fetch_rss_feed(url: str, max_items: int = 10, source_tag: str = "RSS") -> List[Dict]:
    """通用 RSS/Atom feed 解析器"""
    import requests
    import xml.etree.ElementTree as ET
    from html import unescape
    import re

    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        root = ET.fromstring(resp.text)

        items = []
        # RSS 2.0 格式
        for item_el in root.findall(".//item")[:max_items]:
            title = item_el.findtext("title", "")
            link = item_el.findtext("link", "")
            desc = unescape(item_el.findtext("description", ""))
            pub_date = item_el.findtext("pubDate", "")
            desc_clean = re.sub(r"<[^>]+>", "", desc)[:500]
            items.append({
                "title": title, "url": link, "content": desc_clean,
                "source": source_tag, "published_date": pub_date, "keyword": "",
            })

        # Atom 格式（如果 RSS 没找到条目）
        if not items:
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            for entry in root.findall(".//atom:entry", ns)[:max_items]:
                title = entry.findtext("atom:title", "", ns)
                link_el = entry.find("atom:link", ns)
                link = link_el.get("href", "") if link_el is not None else ""
                summary = unescape(entry.findtext("atom:summary", "", ns) or entry.findtext("atom:content", "", ns))
                pub_date = entry.findtext("atom:published", "", ns) or entry.findtext("atom:updated", "", ns)
                desc_clean = re.sub(r"<[^>]+>", "", summary)[:500]
                items.append({
                    "title": title, "url": link, "content": desc_clean,
                    "source": source_tag, "published_date": pub_date, "keyword": "",
                })

        return items
    except Exception as e:
        logger.debug(f"RSS feed 抓取失败 ({source_tag}): {e}")
        return []


def search_subscriptions() -> List[Dict]:
    """
    从 pipeline/subscriptions.json 读取订阅源配置，
    抓取 Google Alerts (via Google News RSS) + Feedspot 博客 RSS。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    sub_file = PROJECT_ROOT / "pipeline" / "subscriptions.json"
    if not sub_file.exists():
        return []

    try:
        with open(sub_file, "r", encoding="utf-8") as f:
            subs = json.load(f)
    except Exception as e:
        logger.warning(f"订阅配置读取失败: {e}")
        return []

    results = []
    futures = []

    with ThreadPoolExecutor(max_workers=8) as executor:
        # Google Alerts → 转为 Google News RSS 查询
        for alert in subs.get("google_alerts_cn", []):
            query = alert.get("query", "")
            lang = alert.get("lang", "zh")
            tag = alert.get("tag", "GoogleAlerts")
            if query:
                futures.append(executor.submit(
                    _google_news_rss, query, lang, 8, tag))

        # Feedspot 博客 RSS
        for blog in subs.get("feedspot_trade_blogs", []):
            rss_url = blog.get("rss_url", "")
            tag = blog.get("tag", "Feedspot")
            if rss_url:
                futures.append(executor.submit(
                    _fetch_rss_feed, rss_url, 8, tag))

        # 自定义 RSS
        for custom in subs.get("custom_rss", []):
            rss_url = custom.get("rss_url", "")
            tag = custom.get("tag", "Custom")
            if rss_url:
                futures.append(executor.submit(
                    _fetch_rss_feed, rss_url, 8, tag))

        for future in as_completed(futures):
            try:
                items = future.result()
                if isinstance(items, list):
                    results.extend(items)
            except Exception as e:
                logger.debug(f"订阅源抓取异常: {e}")

    if results:
        logger.info(f"订阅源合计: {len(results)} 条")
    return results


def search_international(keywords: List[str], max_results: int = 10) -> List[Dict]:
    """
    海外轨：Brave + Tavily + Google News RSS 三路并行搜索
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results = []
    futures = []

    with ThreadPoolExecutor(max_workers=6) as executor:
        # --- Brave Search ---
        brave_key = getattr(settings, "BRAVE_API_KEY", None) or os.getenv("BRAVE_API_KEY", "")
        if brave_key:
            for kw in keywords[:4]:
                futures.append(executor.submit(
                    _brave_search, kw, max_results, "en", "Brave/International"))

        # --- Tavily（并行，非备选）---
        try:
            tavily_key = getattr(settings, "TAVILY_API_KEY", None)
            if tavily_key:
                from QueryEngine.tools.search import TavilyNewsAgency
                agency = TavilyNewsAgency(api_key=tavily_key)
                def _tavily_search(kw):
                    items = []
                    try:
                        response = agency.basic_search_news(kw, max_results=max_results)
                        for r in response.results:
                            items.append({
                                "title": r.title or "",
                                "url": r.url or "",
                                "content": (r.content or "")[:500],
                                "source": "Tavily/International",
                                "published_date": r.published_date or "",
                                "keyword": kw,
                            })
                    except Exception as e:
                        logger.warning(f"Tavily 搜索 '{kw}' 失败: {e}")
                    return items
                for kw in keywords[:3]:
                    futures.append(executor.submit(_tavily_search, kw))
        except Exception:
            pass

        # --- Google News RSS ---
        for kw in keywords[:4]:
            futures.append(executor.submit(
                _google_news_rss, kw, "en", max_results, "GoogleNews/International"))

        # 收集所有结果
        for future in as_completed(futures):
            try:
                items = future.result()
                if isinstance(items, list):
                    results.extend(items)
            except Exception as e:
                logger.warning(f"搜索任务异常: {e}")

    logger.info(f"海外三路搜索合计: {len(results)} 条")
    return results


def search_domestic(keywords: List[str]) -> List[Dict]:
    """
    国内轨：Brave CN + Google News RSS CN + MindSpider 三路并行
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results = []
    futures = []

    with ThreadPoolExecutor(max_workers=6) as executor:
        # --- Brave 中文搜索 ---
        brave_key = getattr(settings, "BRAVE_API_KEY", None) or os.getenv("BRAVE_API_KEY", "")
        if brave_key:
            for kw in keywords[:4]:
                futures.append(executor.submit(
                    _brave_search, kw, 8, "auto", "Brave/Domestic"))

        # --- Google News RSS 中文 ---
        for kw in keywords[:4]:
            futures.append(executor.submit(
                _google_news_rss, kw, "zh", 10, "GoogleNews/Domestic"))

        # --- MindSpider ---
        def _mindspider_search():
            items = []
            try:
                from MindSpider.BroadTopicExtraction.get_today_news import get_today_news
                news_items = get_today_news()
                if news_items:
                    for item in news_items[:10]:
                        items.append({
                            "title": item.get("title", ""),
                            "url": item.get("url", ""),
                            "content": (item.get("content", "") or item.get("summary", ""))[:500],
                            "source": "MindSpider/Domestic",
                            "published_date": item.get("date", ""),
                            "keyword": "",
                        })
            except ImportError:
                pass
            except Exception as e:
                logger.warning(f"MindSpider 搜索异常: {e}")
            return items
        futures.append(executor.submit(_mindspider_search))

        # 收集所有结果
        for future in as_completed(futures):
            try:
                items = future.result()
                if isinstance(items, list):
                    results.extend(items)
            except Exception as e:
                logger.warning(f"国内搜索任务异常: {e}")

    logger.info(f"国内三路搜索合计: {len(results)} 条")
    return results


def score_items_with_llm(items: List[Dict], theme: str) -> List[Dict]:
    """
    用 LLM 对搜索结果评分。
    评分维度：china_relevance / info_asymmetry / wechat_potential (各 1-10)
    """
    if not items:
        return []

    from openai import OpenAI

    api_key = settings.QUERY_ENGINE_API_KEY or settings.INSIGHT_ENGINE_API_KEY
    base_url = settings.QUERY_ENGINE_BASE_URL or settings.INSIGHT_ENGINE_BASE_URL
    model = os.getenv("SCOUT_MODEL_NAME") or settings.QUERY_ENGINE_MODEL_NAME or settings.INSIGHT_ENGINE_MODEL_NAME or "qwen-max"

    if not api_key:
        logger.error("无可用 LLM API Key，跳过评分")
        # 返回默认分数
        for item in items:
            item.update({"china_relevance": 5, "info_asymmetry": 5, "wechat_potential": 5, "china_angle": ""})
        return items

    client = OpenAI(api_key=api_key, base_url=base_url)

    # 批量评分（一次调用处理所有条目，节省 token）
    items_text = ""
    for i, item in enumerate(items):
        items_text += f"\n[{i}] {item['title']}\nSource: {item['source']}\nSummary: {item['content'][:200]}\n"

    system_prompt = """你是一个信息差分析专家，专注于中国跨境电商和数字贸易领域。
请对以下新闻条目逐一评分，每个条目给出：
- china_relevance (1-10): 中国读者关心程度
- info_asymmetry (1-10): 信息差程度（国内是否已知）
- wechat_potential (1-10): 适合做公众号文章的程度
- china_angle: 一句话说明为何中国读者应该关注（中文）

严格以 JSON 数组格式返回，每个元素包含 index, china_relevance, info_asymmetry, wechat_potential, china_angle。
只返回 JSON，不要其他文字。"""

    user_prompt = f"当前主题：{theme}\n\n待评分条目：{items_text}"

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt[:20000]},  # Token guard
            ],
            temperature=0.3,
            timeout=180,
        )
        content = response.choices[0].message.content.strip()

        # 清理 markdown 代码块
        if content.startswith("```"):
            content = content.split("\n", 1)[-1]
            if content.endswith("```"):
                content = content[:-3]

        import json_repair
        scores = json_repair.loads(content)

        if isinstance(scores, list):
            for score_entry in scores:
                idx = score_entry.get("index", -1)
                if 0 <= idx < len(items):
                    items[idx]["china_relevance"] = score_entry.get("china_relevance", 5)
                    items[idx]["info_asymmetry"] = score_entry.get("info_asymmetry", 5)
                    items[idx]["wechat_potential"] = score_entry.get("wechat_potential", 5)
                    items[idx]["china_angle"] = score_entry.get("china_angle", "")

    except Exception as e:
        logger.error(f"LLM 评分失败: {e}")
        for item in items:
            item.setdefault("china_relevance", 5)
            item.setdefault("info_asymmetry", 5)
            item.setdefault("wechat_potential", 5)
            item.setdefault("china_angle", "")

    return items


def run_scout(theme_override: Optional[str] = None) -> Optional[str]:
    """
    执行一轮 Scout 扫描。
    返回保存的 JSON 文件路径，无结果时返回 None。
    """
    now = datetime.now()
    batch_id = now.strftime("%Y%m%d-%H")

    # 确定主题
    if theme_override:
        tier = TRACK_TIERS.get(theme_override, "free")
        theme_info = {"theme": theme_override, "track_tier": tier, "keywords_en": [theme_override], "keywords_cn": [theme_override]}
    else:
        theme_info = get_current_theme(now.hour)

    theme = theme_info["theme"]
    track_tier = theme_info.get("track_tier", TRACK_TIERS.get(theme, "free"))
    logger.info(f"=== Scout 开始 | batch={batch_id} | theme={theme} | tier={track_tier} ===")

    # 1. 海外搜索
    logger.info(">>> 海外搜索...")
    intl_results = search_international(theme_info.get("keywords_en", []))
    logger.info(f"    海外结果: {len(intl_results)} 条")

    # 2. 国内搜索
    logger.info(">>> 国内搜索...")
    domestic_results = search_domestic(theme_info.get("keywords_cn", []))
    logger.info(f"    国内结果: {len(domestic_results)} 条")

    # 3. 订阅源（Google Alerts + Feedspot RSS）
    logger.info(">>> 订阅源...")
    sub_results = search_subscriptions()
    logger.info(f"    订阅源结果: {len(sub_results)} 条")

    # 4. 合并 + URL 去重
    all_results = intl_results + domestic_results + sub_results
    if not all_results:
        logger.warning("Scout 无搜索结果，跳过")
        return None

    state = load_state()
    all_urls = [r["url"] for r in all_results if r.get("url")]
    new_urls = filter_new_urls(all_urls, state)

    # 过滤掉已处理的 URL
    all_results = [r for r in all_results if r.get("url") in new_urls]
    if not all_results:
        logger.info("所有结果已处理过，跳过")
        return None

    # 4. LLM 评分
    logger.info(f">>> LLM 评分 ({len(all_results)} 条)...")
    scored_results = score_items_with_llm(all_results, theme)

    # 5. 过滤低分项
    filtered = []
    for item in scored_results:
        avg = (
            item.get("china_relevance", 0)
            + item.get("info_asymmetry", 0)
            + item.get("wechat_potential", 0)
        ) / 3
        item["avg_score"] = round(avg, 1)
        if avg >= SCORE_THRESHOLD:
            filtered.append(item)

    # 按分数排序，取 top N
    filtered.sort(key=lambda x: x["avg_score"], reverse=True)
    filtered = filtered[:MAX_SCOUT_ITEMS]

    if not filtered:
        logger.info(f"评分后无高分结果（阈值 {SCORE_THRESHOLD}），跳过")
        return None

    logger.info(f">>> 保留 {len(filtered)} 条高分结果")

    # 6. 标记 URL 为已处理
    for item in filtered:
        if item.get("url"):
            mark_url_processed(item["url"], state)
    save_state(state)

    # 7. 保存 JSON
    output_dir = PROJECT_ROOT / "pipeline" / "scout"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{batch_id}.json"

    output_data = {
        "batch": batch_id,
        "theme": theme,
        "track_tier": track_tier,
        "timestamp": now.isoformat(),
        "total_raw": len(intl_results) + len(domestic_results),
        "total_filtered": len(filtered),
        "items": filtered,
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    # 8. 入库 TrendDB
    try:
        from trend_db import TrendDB
        db = TrendDB()
        db.ingest_scout(now.strftime("%Y%m%d"), filtered)
        db.close()
    except Exception as e:
        logger.debug(f"TrendDB 入库跳过: {e}")

    logger.info(f"=== Scout 完成 | 保存: {output_file} ===")
    return str(output_file)


def main():
    parser = argparse.ArgumentParser(description="Scout Runner - 信息扫描")
    parser.add_argument("--theme", type=str, help="手动指定扫描主题")
    args = parser.parse_args()

    result = run_scout(theme_override=args.theme)
    if result:
        print(f"Scout 完成: {result}")
    else:
        print("Scout 完成: 无新结果")


if __name__ == "__main__":
    main()
