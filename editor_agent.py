# -*- coding: utf-8 -*-
"""
Editor Agent — 审稿去 AI 味

职责：
- 接收 Quill 生成的 Markdown 初稿
- 用独立 LLM 调用做一轮 rewrite，专门消除 AI 写作痕迹
- 不改动事实数据、表格、来源引用，只改句式和语气
- 失败时返回原文，不阻塞管线

用法：
    from editor_agent import deai_rewrite
    cleaned_md = deai_rewrite(raw_article_md)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings

EDITOR_SYSTEM_PROMPT = """\
你是一个资深公众号主编，负责润色 AI 生成的初稿，使其读起来像一个有经验的行业分析师写的。

## 改稿原则

### 句式去模板化
1. 替换 AI 高频连接词为自然过渡：
   - "此外" → "另一方面"/"同时"
   - "与此同时" → 直接接下一句，不需要连接词
   - "然而" → "但"/"不过"
   - "因此" → "这意味着"/"结果是"
   - "总的来说" / "综上" → 删掉，直接给结论
   - "值得关注的是" → 删掉前缀，直接进入内容

2. 打破重复结构：
   - 如果连续段落都用相同的"论点→解释→数据"模式，调整其中一段的顺序
   - 如果每个小节长度接近，适当调整使节奏有变化
   - 如果结尾是套话式总结，改为具体的判断或建议

3. 保持专业语气：
   - 不要加入过度口语化的表达（不要用"说白了""懂的都懂""这玩意儿"等）
   - 语气应该是沉稳、自信的分析师，不是聊天群里的吐槽
   - 可以用简短有力的判断句，但不要刻意尖锐

### 绝对不能改的
- **加粗**的数据和数字 — 原样保留
- 表格内容 — 原样保留
- 来源引用（"根据XX的数据"）— 原样保留
- Markdown 格式标记（#、##、**、|）— 原样保留
- 文章的核心论点和立场 — 不能改变意思

### 输出要求
- 输出纯 Markdown，不要代码块包裹
- 保持原文的 # 标题和 ## 小标题结构
- 总字数与原文相差不超过 15%
- 不要加任何编辑注释或说明"""


def deai_rewrite(article_md: str) -> str:
    """
    对 Quill 初稿做去 AI 味 rewrite。

    Args:
        article_md: Quill 生成的 Markdown 文章

    Returns:
        去 AI 味后的 Markdown 文章。失败时返回原文。
    """
    if not article_md or len(article_md) < 300:
        logger.warning("Editor Agent: 文章过短，跳过去 AI 味")
        return article_md

    from openai import OpenAI

    api_key = settings.REPORT_ENGINE_API_KEY or settings.INSIGHT_ENGINE_API_KEY
    base_url = settings.REPORT_ENGINE_BASE_URL or settings.INSIGHT_ENGINE_BASE_URL
    model = settings.REPORT_ENGINE_MODEL_NAME or settings.INSIGHT_ENGINE_MODEL_NAME or "qwen-max"

    if not api_key:
        logger.warning("Editor Agent: 无 API Key，跳过去 AI 味")
        return article_md

    client = OpenAI(api_key=api_key, base_url=base_url)

    user_prompt = f"""\
以下是一篇 AI 生成的公众号初稿，请按照你的改稿原则进行去 AI 味 rewrite。

---
{article_md}
---

请输出改稿后的完整 Markdown 文章。"""

    try:
        logger.info(f"Editor Agent: 开始去 AI 味 rewrite（原文 {len(article_md)} 字）...")

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": EDITOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt[:20000]},
            ],
            temperature=0.8,
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

        # 基本校验：改稿后不应该太短（可能 LLM 只返回了部分）
        if len(content) < len(article_md) * 0.5:
            logger.warning(
                f"Editor Agent: 改稿后过短（{len(content)} vs 原文 {len(article_md)}），使用原文"
            )
            return article_md

        logger.info(
            f"Editor Agent: 去 AI 味完成（{len(article_md)} → {len(content)} 字，"
            f"变化 {abs(len(content) - len(article_md)) / len(article_md) * 100:.1f}%）"
        )
        return content

    except Exception as e:
        logger.error(f"Editor Agent: rewrite 失败（{e}），使用原文继续")
        return article_md
