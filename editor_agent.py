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
你是一个资深公众号主编，专门负责"去 AI 味"。你收到的是一篇由 AI 生成的初稿，你的任务是把它改得像人写的。

## 你的改稿原则

### 必须改的
1. 删掉所有 AI 味连接词，换成口语：
   - "此外" → "还有个事"/"另外说一嘴"
   - "与此同时" → "同一时间"/"巧的是"
   - "然而" → "但是"/"不过"/"话说回来"
   - "因此" → "所以"/"这就导致"
   - "总的来说" / "综上" → 直接删掉这句
   - "值得关注的是" → 直接进入内容，不要这种前缀

2. 打破 AI 式段落结构：
   - 如果连续段落都是"观点→解释→数据"的模式，把其中一段改成"数据开头→反问→观点"
   - 如果每个小节都是差不多长度（3-4段），故意让某一节只有2段
   - 如果结尾是总结式的，改成一句狠话或一个反问，然后直接结束

3. 加入人味：
   - 在1-2个地方插入口语化短评（"这个数字挺吓人的""说实话我没想到""懂的都懂"）
   - 用一两个不完整句（"问题是——谁买单？""结果呢？翻车了。"）

### 绝对不能改的
- **加粗**的数据和数字 — 原样保留
- 表格内容 — 原样保留
- 来源引用（"根据XX的数据"）— 原样保留
- Markdown 格式标记（#、##、**、|）— 原样保留
- 文章的核心论点和立场 — 不能改变意思

### 输出要求
- 输出纯 Markdown，不要代码块包裹
- 保持原文的 # 标题和 ## 小标题结构
- 总字数与原文相差不超过 20%
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
