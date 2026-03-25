#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
手游 & 小游戏资讯日报 v4.0
适用产品：三国杀名将传
作者：游卡网络战略分析组
"""

import os
import re
import json
import smtplib
import time
import requests
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from openai import OpenAI
from duckduckgo_search import DDGS

# ============================================================
# 基础配置
# ============================================================
GAME_NAME_ZH = "三国杀名将传"
PUBLISHER    = "游卡网络战略分析组"
RECIPIENTS   = [r.strip() for r in os.environ.get("REPORT_RECIPIENT_EMAIL", "").split(",") if r.strip()]

CST         = timezone(timedelta(hours=8))
TODAY       = datetime.now(CST).strftime("%Y-%m-%d")
TODAY_LABEL = datetime.now(CST).strftime("%Y年%m月%d日")

# 自动排除的超头部产品（国民级，非竞品参考意义）
EXCLUDE_GAMES = {
    "王者荣耀", "和平精英", "原神", "英雄联盟", "穿越火线",
    "荒野行动", "使命召唤手游", "PUBG", "Free Fire", "部落冲突",
    "皇室战争", "糖果传奇", "开心消消乐", "欢乐斗地主",
    "天天爱消除", "贪吃蛇大作战", "球球大作战",
}

client = OpenAI(
    api_key=os.environ["DEEPSEEK_API_KEY"],
    base_url="https://api.deepseek.com/v1",
)


# ============================================================
# 工具函数
# ============================================================
def ask_deepseek(prompt: str, system: str = "你是专业游戏行业分析师，回复简洁专业。", max_tokens: int = 4000) -> str:
    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"[DeepSeek] 调用失败: {e}")
        return ""


def safe_json(text: str, fallback):
    """安全解析 AI 返回的 JSON，去除可能的 markdown 代码块"""
    text = re.sub(r"```(?:json)?", "", text).strip().strip("`").strip()
    # 找第一个 [ 或 {
    start = min(
        (text.find("[") if text.find("[") != -1 else 9999),
        (text.find("{") if text.find("{") != -1 else 9999),
    )
    if start == 9999:
        return fallback
    text = text[start:]
    try:
        return json.loads(text)
    except Exception:
        return fallback


def ddg_news(query: str, max_results: int = 6, timelimit: str = "d") -> list[dict]:
    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.news(query, region="cn-zh", timelimit=timelimit, max_results=max_results):
                results.append(r)
        time.sleep(1.5)
    except Exception as e:
        print(f"[DDG news] '{query}' 失败: {e}")
    return results


def ddg_text(query: str, max_results: int = 5) -> list[dict]:
    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, region="cn-zh", max_results=max_results):
                results.append(r)
        time.sleep(1.5)
    except Exception as e:
        print(f"[DDG text] '{query}' 失败: {e}")
    return results


def is_excluded(title: str) -> bool:
    """检查是否是需要排除的头部产品"""
    return any(game in title for game in EXCLUDE_GAMES)


def fmt_play(play) -> str:
    if isinstance(play, int) and play > 0:
        return f"{play // 10000:.1f}万" if play >= 10000 else str(play)
    return str(play) if play else "—"


# ============================================================
# 数据采集
# ============================================================
def fetch_bilibili_search(keyword: str, order: str = "pubdate", max_results: int = 10) -> list[dict]:
    """调用B站搜索API"""
    url = "https://api.bilibili.com/x/web-interface/search/type"
    params = {
        "keyword": keyword, "search_type": "video",
        "order": order, "duration": 0, "tids": 0,
        "page": 1, "page_size": max_results, "platform": "pc",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.bilibili.com",
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        data = resp.json()
        items = data.get("data", {}).get("result", [])
        results = []
        for v in items:
            title = re.sub(r"<[^>]+>", "", v.get("title", ""))
            if is_excluded(title):
                continue
            results.append({
                "title":   title,
                "author":  v.get("author", ""),
                "play":    v.get("play", 0),
                "desc":    v.get("description", "")[:200],
                "url":     "https://www.bilibili.com/video/" + v.get("bvid", ""),
                "pubdate": v.get("pubdate", 0),
                "tag":     v.get("tag", ""),
                "source":  "B站",
            })
        return results
    except Exception as e:
        print(f"[Bilibili] 搜索 '{keyword}' 失败: {e}")
        return []


def fetch_bilibili_trending_games() -> list[dict]:
    """B站多关键词采集"""
    bili_results = []
    for kw in ["手机游戏新作", "独立游戏", "小游戏推荐", "卡牌游戏 新作"]:
        items = fetch_bilibili_search(kw, order="pubdate", max_results=10)
        bili_results.extend(items)
        time.sleep(1.2)
    return bili_results


def fetch_taptap_data() -> list[dict]:
    """TapTap 新品榜 + 热门数据"""
    results = []
    queries = [
        "TapTap 新品榜 iOS 2026",
        "TapTap 安卓新游 热门 2026",
        "TapTap 新上线 推荐 本周",
        "taptap 手游 新品 今日",
    ]
    for q in queries:
        for r in ddg_text(q, max_results=5):
            r["source"] = "TapTap"
            if not is_excluded(r.get("title", "")):
                results.append(r)
    for r in ddg_news("TapTap 新游 排行 本周", max_results=6):
        r["source"] = "TapTap"
        if not is_excluded(r.get("title", "")):
            results.append(r)
    return results


def fetch_industry_news() -> list[dict]:
    """游戏行业媒体近24h资讯"""
    queries = [
        "竞核 手游 资讯",
        "DataEye 手游 数据",
        "游戏葡萄 手游 独立游戏",
        "手游那点事 资讯",
        "点点数据 手游",
        "手游 新品 上线 今日 2026",
        "卡牌手游 新作 爆款",
        "小游戏 爆款 微信 今日",
        "Steam 独立游戏 国产 新作 2026",
    ]
    all_results = []
    for q in queries:
        for r in ddg_news(q, max_results=5, timelimit="d"):
            r["source"] = r.get("source", "行业媒体")
            if not is_excluded(r.get("title", "")):
                all_results.append(r)
    return all_results


# ============================================================
# AI 分析一：生成结构化资讯列表（JSON）
# ============================================================
def analyze_news_to_json(industry_news, bili_data, taptap_data) -> list[dict]:
    """
    AI 整合所有渠道，输出结构化 JSON 资讯列表（≥7条）
    每条含：标题、来源名、来源URL、热度、玩法、动态、行业意义
    """
    # 整理 B站原始数据（保留 URL）
    bili_text = "\n".join([
        f"[B站] 《{v['title']}》 播放{fmt_play(v['play'])} 作者:{v['author']} URL:{v['url']} 简介:{v.get('desc','')[:100]}"
        for v in bili_data[:20]
    ])

    # 整理媒体新闻（保留 URL）
    news_text = "\n".join([
        f"[{r.get('source','媒体')}] {r.get('title','')} URL:{r.get('url', r.get('href','无'))} 摘要:{r.get('body','')[:120]}"
        for r in industry_news[:30]
    ])

    # 整理 TapTap 数据
    taptap_text = "\n".join([
        f"[TapTap] {r.get('title','')} URL:{r.get('href', r.get('url','无'))} 摘要:{r.get('body','')[:120]}"
        for r in taptap_data[:15]
    ])

    exclude_str = "、".join(sorted(EXCLUDE_GAMES))

    prompt = f"""
今天是{TODAY_LABEL}，你是游卡战略分析组游戏分析师。

以下是多渠道原始资讯，请整合后输出 JSON 数组，包含至少7条重点资讯。

【B站近24h热门游戏视频】
{bili_text or '暂无'}

【竞核/DataEye/游戏葡萄等媒体近24h资讯】
{news_text or '暂无'}

【TapTap新品榜资讯】
{taptap_text or '暂无'}

━━━━━━━━━━
排除规则：不得包含以下超头部产品：{exclude_str}

输出要求：返回纯 JSON 数组，不要任何额外说明，格式如下：
[
  {{
    "no": 1,
    "product": "产品名或话题名",
    "source_label": "B站 或 TapTap 或 竞核 或 DataEye 或 游戏葡萄 或 其他媒体",
    "source_url": "原始URL，没有则填空字符串",
    "heat": "热度表现（B站播放量X万/TapTap榜单排名/媒体多篇报道等，必须有具体数据）",
    "gameplay": "核心玩法一句话（如：三消+养成、塔防+建造）",
    "dynamics": "近期动态（新上线/新版本/爆量原因，具体说明）",
    "insight": "行业意义（对手游市场或名将like参考价值，1句话）"
  }},
  ...
]

要求：
1. 至少7条，最多12条
2. 涵盖：手游新品、热门小游戏、Steam独立游戏、行业动态
3. heat 字段必须有具体数据，实在没有就写"媒体关注"或"榜单新上"
4. source_url 尽量从原始数据中提取真实链接
5. 最后一条 no 填99，product 填"今日行业总结"，insight 填50字以内总结，其余字段为空
"""
    raw = ask_deepseek(prompt, system="你只输出合法JSON，不输出任何其他内容。", max_tokens=5000)
    result = safe_json(raw, [])
    if not result:
        # 降级：返回一条错误提示
        return [{"no": 1, "product": "数据获取异常", "source_label": "系统", "source_url": "",
                 "heat": "—", "gameplay": "—", "dynamics": "今日数据采集出现问题，请检查网络或API配置",
                 "insight": "建议手动触发重跑"}]
    return result


# ============================================================
# AI 分析二：TapTap新品榜表格（JSON）
# ============================================================
def analyze_taptap_table(taptap_data, news_analysis_items) -> list[dict]:
    """
    AI 从 TapTap 数据中整理 5-10 款有新意的双端新品，输出表格 JSON
    """
    taptap_raw = "\n".join([
        f"- {r.get('title','')} | {r.get('body','')[:150]} | URL:{r.get('href', r.get('url',''))}"
        for r in taptap_data[:20]
    ])

    # 也把资讯里的 TapTap 相关条目补充进来
    taptap_items_from_news = [
        item for item in news_analysis_items
        if "taptap" in item.get("source_label", "").lower() or "taptap" in item.get("source_url", "").lower()
    ]
    extra = "\n".join([
        f"- {i.get('product','')} | {i.get('gameplay','')} | {i.get('dynamics','')}"
        for i in taptap_items_from_news
    ])

    exclude_str = "、".join(sorted(EXCLUDE_GAMES))

    prompt = f"""
今天是{TODAY_LABEL}，从以下TapTap相关资讯中，挑选5-10款【题材/玩法/画风有新意】的手游新品。

TapTap原始资讯：
{taptap_raw or '暂无'}

补充资讯中的TapTap相关产品：
{extra or '暂无'}

排除：{exclude_str}

输出纯JSON数组，格式：
[
  {{
    "rank": "iOS Top3 / 安卓新品 等（没有精确排名则写榜单来源）",
    "platform": "iOS / 安卓 / 双端",
    "name": "游戏名",
    "gameplay": "核心玩法（如三消+养成）",
    "theme": "题材（如古风、科幻、像素）",
    "art_style": "画风（如写实、卡通、水墨）",
    "note": "关注理由（玩法/题材/画风有新意的具体说明，20字以内）",
    "url": "TapTap产品页链接，没有则空字符串"
  }}
]

要求：
- 只选题材/玩法/画风有新意的，跳过换皮/常规产品
- 尽量覆盖 iOS 和安卓双端
- 没有精确数据时，note 写你认为值得关注的理由
- 只输出JSON，不要任何其他内容
"""
    raw = ask_deepseek(prompt, system="你只输出合法JSON，不输出任何其他内容。", max_tokens=2000)
    return safe_json(raw, [])


# ============================================================
# AI 分析三：缝合创想（基于本期资讯产品）
# ============================================================
def generate_fusion_ideas(news_items: list[dict]) -> str:
    # 提取产品列表给 AI
    products_summary = "\n".join([
        f"{i.get('no','')}. 【{i.get('product','')}】来源:{i.get('source_label','')} 玩法:{i.get('gameplay','')} 动态:{i.get('dynamics','')}"
        for i in news_items if i.get("no", 0) != 99
    ])

    prompt = f"""
你是三国杀名将传的游戏策划总监。

【今日资讯产品列表（必须从这里选）】
{products_summary}

【背景】
- 三国杀名将传（名将like）：卡牌+Roguelike手游，核心是组建6人名将阵容对战
- 目标：找"前期钩子副玩法"——用轻量上瘾的小玩法在D1完成冷启动，D2-D7过渡，D7+引入名将like核心
- 参考模型：无尽冬日（SLG前期用建造钩子买量），关注模拟/建造/经营/塔防/RPG/解谜元素
- 钩子玩法要求：强手感、快反馈、轻量上手、对三国/名将IP有天然融合点

【任务】从上方产品中选2-3款最具缝合潜力的，给出创想方案。必须是真实产品，不得自创。

每个方案格式：

---
### 💡 [产品名] × 名将like 缝合创想

**选择理由**：（该产品的哪个特质让它有缝合价值，1-2句）

**缝合核心逻辑**：（钩子是什么 → 怎么自然引入名将like，2-3句）

**阶段设计**：
🎣 **D1 冷启动**：[钩子手感体验，要有快速正反馈，让玩家5分钟内上瘾]
🌉 **D2–D7 过渡**：[如何逐步引入名将元素，让过渡不突兀]
⚔️ **D7+ 名将期**：[名将like全面介入，核心循环是什么]

**创新差异点**：
① 与原型产品的差异：
② 与现有名将like的差异：
③ 买量/留存预期优势：

**最大落地挑战**：（一句话）

---

最后：
**本期优选**：[最推荐的方案产品名]
**推荐理由**：（25字以内）
"""
    return ask_deepseek(
        prompt,
        system="你是10年手游策划总监，擅长玩法融合和买量产品设计，语言简练直接，不说废话。",
        max_tokens=4000,
    )


# ============================================================
# HTML 构建
# ============================================================
SOURCE_COLORS = {
    "B站":   ("#e8f4fd", "#1565c0", "📺"),
    "TapTap": ("#f0faf5", "#1b7a4e", "🎮"),
    "竞核":  ("#fef6e4", "#8a5a00", "📰"),
    "DataEye": ("#f5f0ff", "#5b2d9e", "📊"),
    "游戏葡萄": ("#fff0f3", "#a3153e", "🍇"),
    "其他媒体": ("#f8f8f8", "#555555", "📄"),
    "行业媒体": ("#f8f8f8", "#555555", "📄"),
    "系统":   ("#fff0f0", "#cc0000", "⚠️"),
}

def get_source_style(label: str):
    for key, val in SOURCE_COLORS.items():
        if key in label:
            return val
    return ("#f8f8f8", "#555555", "📄")


def build_news_html(items: list[dict]) -> str:
    cards = []
    for item in items:
        no = item.get("no", "")
        if no == 99:
            # 今日总结
            summary = item.get("insight", "")
            cards.append(f'''
<div style="background:linear-gradient(135deg,#fff8e1,#fffde7);border:1px solid #ffe082;border-radius:10px;
  padding:14px 18px;margin-top:8px">
  <span style="font-weight:700;color:#f57f17;font-size:13px">📊 今日行业总结</span>
  <p style="margin:6px 0 0;color:#5d4037;font-size:13px;line-height:1.7">{summary}</p>
</div>''')
            continue

        product = item.get("product", "")
        source_label = item.get("source_label", "其他媒体")
        source_url   = item.get("source_url", "")
        heat     = item.get("heat", "—")
        gameplay = item.get("gameplay", "—")
        dynamics = item.get("dynamics", "—")
        insight  = item.get("insight", "—")

        bg, tc, icon = get_source_style(source_label)

        # 来源标签
        source_badge = f'''<span style="background:{bg};color:{tc};border:1px solid {tc}33;
          border-radius:12px;padding:1px 9px;font-size:11px;font-weight:500;white-space:nowrap">
          {icon} {source_label}</span>'''

        # 产品名（带链接或不带）
        if source_url:
            product_link = f'<a href="{source_url}" style="color:#1a1a1a;text-decoration:none;border-bottom:1px solid #ccc" target="_blank">{product}</a>'
        else:
            product_link = product

        cards.append(f'''
<div style="background:#fff;border:1px solid #eaeaea;border-radius:10px;margin-bottom:14px;
  overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.05)">
  <div style="padding:12px 16px 10px;border-bottom:1px solid #f5f5f5;display:flex;align-items:center;
    gap:10px;flex-wrap:wrap">
    <span style="background:#c0392b;color:#fff;border-radius:50%;width:22px;height:22px;
      display:inline-flex;align-items:center;justify-content:center;font-size:11px;
      font-weight:700;flex-shrink:0">{no}</span>
    <span style="font-size:15px;font-weight:700;color:#1a1a1a;flex:1">{product_link}</span>
    {source_badge}
  </div>
  <div style="padding:10px 16px 12px">
    <table style="width:100%;border-collapse:collapse;font-size:13px">
      <tr>
        <td style="width:72px;color:#888;padding:3px 0;vertical-align:top">📈 热度</td>
        <td style="color:#333;padding:3px 0 3px 6px;line-height:1.6">{heat}</td>
      </tr>
      <tr>
        <td style="color:#888;padding:3px 0;vertical-align:top">🎮 玩法</td>
        <td style="color:#333;padding:3px 0 3px 6px;line-height:1.6">{gameplay}</td>
      </tr>
      <tr>
        <td style="color:#888;padding:3px 0;vertical-align:top">🔔 动态</td>
        <td style="color:#333;padding:3px 0 3px 6px;line-height:1.6">{dynamics}</td>
      </tr>
      <tr>
        <td style="color:#888;padding:3px 0;vertical-align:top">💡 意义</td>
        <td style="color:#666;padding:3px 0 3px 6px;line-height:1.6;font-style:italic">{insight}</td>
      </tr>
    </table>
  </div>
</div>''')
    return "\n".join(cards)


def build_taptap_table_html(table_items: list[dict]) -> str:
    if not table_items:
        return '<p style="color:#888;font-size:13px">今日TapTap新品数据暂未获取到，请明日查看。</p>'

    platform_color = {"iOS": ("#e8f4fd", "#0d6efd"), "安卓": ("#e8f5e9", "#2e7d32"), "双端": ("#f3e5f5", "#6a1b9a")}

    rows = []
    for item in table_items:
        plat = item.get("platform", "—")
        pc, tc = platform_color.get(plat, ("#f8f8f8", "#444"))
        rank = item.get("rank", "—")
        name = item.get("name", "—")
        url  = item.get("url", "")
        gp   = item.get("gameplay", "—")
        theme = item.get("theme", "—")
        art  = item.get("art_style", "—")
        note = item.get("note", "—")

        name_cell = f'<a href="{url}" style="color:#c0392b;font-weight:600;text-decoration:none" target="_blank">{name}</a>' if url else f'<strong>{name}</strong>'

        rows.append(f'''
<tr style="border-bottom:1px solid #f0f0f0">
  <td style="padding:10px 12px;text-align:center">
    <span style="background:{pc};color:{tc};border-radius:4px;padding:2px 7px;font-size:11px;font-weight:600">{plat}</span>
  </td>
  <td style="padding:10px 8px;font-size:12px;color:#666;text-align:center;white-space:nowrap">{rank}</td>
  <td style="padding:10px 12px;font-size:13px">{name_cell}</td>
  <td style="padding:10px 8px;font-size:12px;color:#444">{gp}</td>
  <td style="padding:10px 8px;font-size:12px;color:#666">{theme}</td>
  <td style="padding:10px 8px;font-size:12px;color:#666">{art}</td>
  <td style="padding:10px 12px;font-size:12px;color:#888;font-style:italic">{note}</td>
</tr>''')

    rows_html = "\n".join(rows)
    return f'''
<div style="overflow-x:auto;border-radius:10px;border:1px solid #e8e8e8">
<table style="width:100%;border-collapse:collapse;background:#fff;font-family:inherit">
  <thead>
    <tr style="background:#f7f7f7;border-bottom:2px solid #eaeaea">
      <th style="padding:10px 12px;font-size:12px;font-weight:600;color:#555;text-align:center;white-space:nowrap">平台</th>
      <th style="padding:10px 8px;font-size:12px;font-weight:600;color:#555;text-align:center;white-space:nowrap">榜单</th>
      <th style="padding:10px 12px;font-size:12px;font-weight:600;color:#555;text-align:left">产品名</th>
      <th style="padding:10px 8px;font-size:12px;font-weight:600;color:#555;text-align:left">玩法</th>
      <th style="padding:10px 8px;font-size:12px;font-weight:600;color:#555;text-align:left">题材</th>
      <th style="padding:10px 8px;font-size:12px;font-weight:600;color:#555;text-align:left">画风</th>
      <th style="padding:10px 12px;font-size:12px;font-weight:600;color:#555;text-align:left">关注理由</th>
    </tr>
  </thead>
  <tbody>
    {rows_html}
  </tbody>
</table>
</div>'''


def md_to_html_fusion(text: str) -> str:
    """专门处理缝合创想部分的 Markdown → HTML"""
    lines = text.split("\n")
    out = []
    for line in lines:
        line = line.rstrip()
        if line.startswith("### "):
            content = line[4:]
            out.append(f'<h4 style="color:#8e1a0e;margin:22px 0 8px;font-size:15px;font-weight:700">{content}</h4>')
        elif line == "---":
            out.append('<hr style="border:none;border-top:2px dashed #f0d0c8;margin:16px 0">')
        elif line.startswith("🎣 **") or line.startswith("🌉 **") or line.startswith("⚔️ **"):
            # 阶段标签
            m = re.match(r"^(.{1,3})\s+\*\*(.+?)\*\*：(.*)$", line)
            if m:
                emoji, label, content = m.group(1), m.group(2), m.group(3)
                label_colors = {"D1 冷启动": "#e65100", "D2–D7 过渡": "#1565c0", "D7+ 名将期": "#1b5e20"}
                lc = label_colors.get(label, "#555")
                out.append(f'''<div style="display:flex;gap:10px;margin:8px 0;align-items:flex-start">
  <span style="background:{lc};color:#fff;border-radius:6px;padding:2px 10px;font-size:11px;
    font-weight:600;white-space:nowrap;margin-top:2px">{emoji} {label}</span>
  <span style="font-size:13px;color:#444;line-height:1.7">{content}</span>
</div>''')
            else:
                out.append(f'<p style="margin:6px 0;font-size:13px">{line}</p>')
        elif re.match(r"^\*\*(.+?)\*\*：(.*)$", line):
            m = re.match(r"^\*\*(.+?)\*\*：(.*)$", line)
            out.append(f'<p style="margin:6px 0;font-size:13px"><strong style="color:#2c3e50">{m.group(1)}</strong>：{m.group(2)}</p>')
        elif re.match(r"^\*\*(.+?)\*\*$", line):
            m = re.match(r"^\*\*(.+?)\*\*$", line)
            out.append(f'<p style="margin:10px 0 4px;font-weight:700;color:#c0392b;font-size:13px">{m.group(1)}</p>')
        elif line.startswith("① ") or line.startswith("② ") or line.startswith("③ "):
            out.append(f'<li style="margin:4px 0;font-size:13px;color:#444">{line[2:]}</li>')
        elif line.startswith("- ") or line.startswith("• "):
            out.append(f'<li style="margin:4px 0;font-size:13px;color:#444">{line[2:]}</li>')
        elif line == "":
            out.append("<div style='height:4px'></div>")
        else:
            line = re.sub(r"\*\*(.+?)\*\*", r'<strong style="color:#2c3e50">\1</strong>', line)
            out.append(f'<p style="margin:4px 0;font-size:13px;line-height:1.7;color:#333">{line}</p>')
    html = "\n".join(out)
    html = re.sub(
        r"((?:<li[^>]*>.*?</li>\n?)+)",
        lambda m: f'<ul style="padding-left:20px;margin:6px 0">{m.group(0)}</ul>',
        html,
    )
    return html


def build_html(news_items: list[dict], taptap_table: list[dict], fusion_text: str) -> str:
    news_count = len([i for i in news_items if i.get("no", 0) != 99])
    news_html   = build_news_html(news_items)
    taptap_html = build_taptap_table_html(taptap_table)
    fusion_html = md_to_html_fusion(fusion_text)

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{TODAY_LABEL} 手游&小游戏资讯日报</title>
<style>
  *{{box-sizing:border-box}}
  body{{font-family:'PingFang SC','Helvetica Neue','Microsoft YaHei',Arial,sans-serif;
    background:#f0f2f5;margin:0;padding:24px 16px;color:#333;font-size:14px;line-height:1.7}}
  .container{{max-width:820px;margin:0 auto;background:#fff;border-radius:16px;overflow:hidden;
    box-shadow:0 4px 24px rgba(0,0,0,.1)}}
  .header{{background:linear-gradient(135deg,#c0392b 0%,#7b1010 100%);color:#fff;padding:30px 36px}}
  .header h1{{margin:0 0 4px;font-size:23px;letter-spacing:.3px;font-weight:700}}
  .header .sub{{opacity:.88;font-size:13px;margin:0}}
  .meta-row{{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}}
  .badge{{display:inline-block;background:rgba(255,255,255,.15);border:1px solid rgba(255,255,255,.25);
    border-radius:20px;padding:3px 12px;font-size:11px}}
  .toc{{background:#fafafa;padding:14px 36px;border-bottom:1px solid #f0f0f0}}
  .toc-inner{{display:flex;gap:0;flex-wrap:wrap}}
  .toc-item{{display:flex;align-items:center;gap:6px;padding:4px 16px;font-size:12px;color:#666;
    border-right:1px solid #e8e8e8}}
  .toc-item:first-child{{padding-left:0}}
  .toc-item:last-child{{border-right:none}}
  .toc-num{{background:#c0392b;color:#fff;border-radius:50%;width:18px;height:18px;
    display:inline-flex;align-items:center;justify-content:center;font-size:10px;font-weight:700}}
  .section{{padding:28px 36px;border-bottom:1px solid #f0f0f0}}
  .section:last-child{{border-bottom:none}}
  .section-header{{display:flex;align-items:center;gap:10px;margin-bottom:20px}}
  .section-num{{background:linear-gradient(135deg,#c0392b,#8e1a0e);color:#fff;border-radius:8px;
    padding:4px 12px;font-size:13px;font-weight:700}}
  .section-title{{font-size:17px;font-weight:700;color:#1a1a1a}}
  .section-desc{{font-size:12px;color:#999;margin-left:auto}}
  .channel-row{{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:18px;
    padding:10px 14px;background:#fafafa;border-radius:8px;border:1px solid #f0f0f0}}
  .ch-pill{{font-size:11px;padding:2px 10px;border-radius:12px;background:#fff;
    border:1px solid #ddd;color:#555}}
  .fusion-intro{{background:linear-gradient(135deg,#fff5f5,#fff8f0);border:1px solid #f5c6c6;
    border-radius:10px;padding:14px 18px;margin-bottom:16px;font-size:13px;color:#7b1010;
    line-height:1.7}}
  .footer{{background:#2c3e50;color:#8899aa;text-align:center;padding:18px;font-size:11px;
    line-height:1.8}}
  a{{color:#c0392b;text-decoration:none}}
  a:hover{{text-decoration:underline}}
</style>
</head>
<body>
<div class="container">

  <!-- 顶部标题 -->
  <div class="header">
    <h1>🃏 手游 & 小游戏资讯日报</h1>
    <p class="sub">{TODAY_LABEL} · 三国杀名将传战略参考 · 数据时效：近24小时</p>
    <div class="meta-row">
      <span class="badge">📺 B站 · 🎮 TapTap · 📰 竞核 · 📊 DataEye · 🍇 游戏葡萄</span>
      <span class="badge">🤖 DeepSeek AI 分析</span>
      <span class="badge">📌 {PUBLISHER}</span>
    </div>
  </div>

  <!-- 目录 -->
  <div class="toc">
    <div class="toc-inner">
      <div class="toc-item"><span class="toc-num">①</span> 行业资讯（{news_count}条）</div>
      <div class="toc-item"><span class="toc-num">②</span> TapTap 新品观察</div>
      <div class="toc-item"><span class="toc-num">③</span> 名将like 缝合创想</div>
    </div>
  </div>

  <!-- Section 1：行业资讯 -->
  <div class="section">
    <div class="section-header">
      <span class="section-num">① 行业资讯</span>
      <span class="section-title">手游 & 小游戏 热点追踪</span>
      <span class="section-desc">近24小时 · 自动排除超头部产品</span>
    </div>
    <div class="channel-row">
      <span class="ch-pill">📺 B站·手机游戏</span>
      <span class="ch-pill">📺 B站·独立游戏</span>
      <span class="ch-pill">🎮 TapTap新品</span>
      <span class="ch-pill">📰 竞核</span>
      <span class="ch-pill">📊 DataEye</span>
      <span class="ch-pill">🍇 游戏葡萄</span>
    </div>
    {news_html}
  </div>

  <!-- Section 2：TapTap 新品表格 -->
  <div class="section">
    <div class="section-header">
      <span class="section-num">② TapTap 新品观察</span>
      <span class="section-title">双端新品榜 · 今日精选</span>
      <span class="section-desc">题材/玩法/画风有新意 · 5–10款</span>
    </div>
    {taptap_html}
  </div>

  <!-- Section 3：缝合创想 -->
  <div class="section">
    <div class="section-header">
      <span class="section-num">③ 缝合创想</span>
      <span class="section-title">名将like 前期钩子设想</span>
      <span class="section-desc">基于本期资讯产品 · AI策划建议</span>
    </div>
    <div class="fusion-intro">
      💡 从本期资讯产品中精选 2–3 款，探索三国杀名将传前期轻量化钩子副玩法缝合方向
      （D1冷启动 → D2–D7过渡 → D7+名将like全面介入）
    </div>
    <div style="background:#fff8f5;border:1px solid #f0d5c8;border-radius:10px;padding:20px">
      {fusion_html}
    </div>
  </div>

  <div class="footer">
    {TODAY_LABEL} &nbsp;·&nbsp; 手游&小游戏资讯日报 &nbsp;·&nbsp; {PUBLISHER}<br>
    数据来源：B站API · TapTap · 竞核 · DataEye · 游戏葡萄 · DuckDuckGo · DeepSeek AI<br>
    <span style="color:#566a7f">内部参考文件，请勿外传</span>
  </div>

</div>
</body>
</html>"""


# ============================================================
# 发送邮件
# ============================================================
def send_email(html: str):
    sender   = os.environ["GMAIL_SENDER_EMAIL"]
    password = os.environ["GMAIL_APP_PASSWORD"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"【{TODAY_LABEL}】手游&小游戏资讯日报 · {GAME_NAME_ZH}战略参考"
    msg["From"]    = sender
    msg["To"]      = ", ".join(RECIPIENTS)
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, RECIPIENTS, msg.as_string())
    print(f"✅ 邮件已发送至：{RECIPIENTS}")


# ============================================================
# 主流程
# ============================================================
def main():
    print(f"=== {TODAY} 日报开始生成（v4.0）===")

    print("📺 [1/3] 采集B站游戏视频数据...")
    bili_data = fetch_bilibili_trending_games()
    print(f"    B站获取 {len(bili_data)} 条（已过滤超头部产品）")

    print("🎮 [2/3] 采集TapTap新品榜数据...")
    taptap_data = fetch_taptap_data()
    print(f"    TapTap获取 {len(taptap_data)} 条")

    print("📰 [3/3] 采集行业媒体近24h资讯...")
    industry_news = fetch_industry_news()
    print(f"    媒体资讯获取 {len(industry_news)} 条")

    print("🤖 [AI-1] 整合生成结构化资讯（JSON）...")
    news_items = analyze_news_to_json(industry_news, bili_data, taptap_data)
    print(f"    生成 {len([i for i in news_items if i.get('no',0)!=99])} 条资讯")

    print("🤖 [AI-2] 生成TapTap新品表格（JSON）...")
    taptap_table = analyze_taptap_table(taptap_data, news_items)
    print(f"    TapTap表格 {len(taptap_table)} 款")

    print("🤖 [AI-3] 生成名将like缝合创想...")
    fusion_text = generate_fusion_ideas(news_items)

    print("📝 构建HTML邮件...")
    html = build_html(news_items, taptap_table, fusion_text)

    print("📧 发送邮件...")
    send_email(html)

    print("=== 日报完成 ✅ ===")


if __name__ == "__main__":
    main()
