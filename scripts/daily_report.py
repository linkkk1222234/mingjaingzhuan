#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
卡牌手游 & 小游戏资讯日报 v3.0
适用产品：三国杀名将传
作者：游卡网络战略分析组
"""

import os
import re
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

client = OpenAI(
    api_key=os.environ["DEEPSEEK_API_KEY"],
    base_url="https://api.deepseek.com/v1",
)

# ============================================================
# 工具函数
# ============================================================
def ask_deepseek(prompt: str, system: str = "你是一位专业的游戏行业分析师，擅长手游市场分析与玩法研究，回复简洁专业，不废话。") -> str:
    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt},
            ],
            temperature=0.7,
            max_tokens=4000,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"[DeepSeek] 调用失败: {e}")
        return f"AI 分析失败：{e}"


def ddg_news(query: str, max_results: int = 6, timelimit: str = "d") -> list[dict]:
    """DDG 新闻搜索，timelimit: d=24h, w=一周"""
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
    """DDG 网页搜索"""
    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, region="cn-zh", max_results=max_results):
                results.append(r)
        time.sleep(1.5)
    except Exception as e:
        print(f"[DDG text] '{query}' 失败: {e}")
    return results


def fetch_bilibili_search(keyword: str, order: str = "click", max_results: int = 8) -> list[dict]:
    """
    调用B站搜索API，抓取关键词相关视频
    order: click=最多播放, pubdate=最新发布, dm=最多弹幕
    """
    url = "https://api.bilibili.com/x/web-interface/search/type"
    params = {
        "keyword": keyword,
        "search_type": "video",
        "order": order,
        "duration": 0,      # 不限时长
        "tids": 0,          # 不限分区
        "page": 1,
        "page_size": max_results,
        "platform": "pc",
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
            results.append({
                "title": title,
                "author": v.get("author", ""),
                "play":   v.get("play", 0),
                "danmaku": v.get("video_review", 0),
                "desc":  v.get("description", "")[:200],
                "url":   "https://www.bilibili.com/video/" + v.get("bvid", ""),
                "pubdate": v.get("pubdate", 0),
                "tag":   v.get("tag", ""),
            })
        return results
    except Exception as e:
        print(f"[Bilibili] 搜索 '{keyword}' 失败: {e}")
        return []


def fetch_taptap_new_games() -> list[dict]:
    """
    抓取 TapTap 新品榜（iOS + 安卓）
    使用 DDG 搜索 + 网页抓取方式覆盖
    """
    results = []
    queries = [
        "TapTap 新品榜 iOS 2026 手游",
        "TapTap 安卓新游 热门榜单 2026",
        "taptap.cn 新游推荐 本周",
        "site:taptap.cn 新上线 热门",
    ]
    for q in queries:
        results.extend(ddg_text(q, max_results=5))
    # 同时搜索 TapTap 近期榜单新闻
    results.extend(ddg_news("TapTap 新游 热门 本周", max_results=5))
    return results


def fetch_industry_news() -> list[dict]:
    """
    抓取竞核、DataEye、游戏葡萄、DataMagic等游戏媒体近24h资讯
    """
    queries = [
        "竞核 手游 资讯 今日",
        "DataEye 手游 数据 资讯",
        "游戏葡萄 手游 独立游戏 今日",
        "手游那点事 资讯 今日",
        "DataMagic 游戏 今日",
        "点点数据 手游 今日",
        "手游 新品 上线 今日 2026",
        "卡牌手游 新作 爆款 今日",
        "小游戏 爆款 热门 今日 微信",
        "Steam 国产游戏 热门 本周 2026",
        "独立游戏 热门 今日 2026",
    ]
    all_results = []
    for q in queries:
        all_results.extend(ddg_news(q, max_results=5, timelimit="d"))
    return all_results


def fetch_bilibili_trending_games() -> list[dict]:
    """B站近24h游戏相关热门"""
    bili_results = []
    # 关键词：手机游戏 + 独立游戏
    for kw in ["手机游戏", "独立游戏", "手游新游", "小游戏 爆款"]:
        items = fetch_bilibili_search(kw, order="pubdate", max_results=8)
        bili_results.extend(items)
        time.sleep(1)
    return bili_results


# ============================================================
# AI 分析：整合所有资讯，生成 7 条以上重点资讯
# ============================================================
def analyze_all_news(
    industry_news: list[dict],
    bili_data: list[dict],
    taptap_data: list[dict],
) -> str:
    """将所有渠道原始数据交给 AI，整理出 7 条以上重点资讯"""

    # 整理 B站数据
    bili_text = ""
    if bili_data:
        bili_items = []
        for v in bili_data[:20]:
            play = v.get("play", 0)
            if isinstance(play, int) and play > 0:
                play_str = f"{play//10000:.1f}万" if play >= 10000 else str(play)
            else:
                play_str = str(play)
            bili_items.append(
                f"- 【{v['author']}】{v['title']} | 播放{play_str} | {v.get('desc','')[:100]}"
            )
        bili_text = "\n".join(bili_items)

    # 整理行业媒体新闻
    news_text = ""
    if industry_news:
        news_items = []
        for r in industry_news[:30]:
            pub = r.get("date", r.get("published", ""))[:10]
            news_items.append(
                f"- [{r.get('source','媒体')} {pub}] {r.get('title','')}：{r.get('body','')[:150]}"
            )
        news_text = "\n".join(news_items)

    # 整理 TapTap 数据
    taptap_text = ""
    if taptap_data:
        taptap_items = []
        for r in taptap_data[:15]:
            taptap_items.append(
                f"- {r.get('title','')}：{r.get('body','')[:150]}"
            )
        taptap_text = "\n".join(taptap_items)

    prompt = f"""
你是游卡网络战略分析组的游戏分析师，今天是{TODAY_LABEL}。

以下是从多个渠道收集的游戏资讯原始数据，请整理出【至少7条】重点资讯。

📱 B站近24小时游戏热门视频（含播放量）：
{bili_text or '暂无数据'}

📰 竞核/DataEye/游戏葡萄等游戏媒体近24小时资讯：
{news_text or '暂无数据'}

🎮 TapTap新品榜相关资讯：
{taptap_text or '暂无数据'}

━━━━━━━━━━━━━━━━━━
输出要求（严格按格式，每条独立，不合并）：

对每款产品/话题，输出以下格式：

**📌 [序号]. [产品名/话题名]**
• **热度表现**：（B站播放量/TapTap榜单排名/媒体关注度等，有数据就写数据）
• **玩法概述**：（核心玩法一句话，如"三消+养成"、"SLG+建造"等）
• **近期动态**：（新版本/新活动/爆量原因/上线情况等，具体说明）
• **行业意义**：（对手游市场或买量方向的参考价值，1句话）

━━━━━━━━━━━━━━━━━━
重要要求：
1. 必须至少输出7条，不足7条时从数据中挖掘更多产品
2. 优先选择：近24h内有明确热度信号的产品（榜单新上/播放量高/媒体报道多）
3. 如某条信息不完整，用"待确认"标注，但必须给出已知信息
4. 涵盖范围：手游新品、热门小游戏、Steam独立游戏、行业重要动态均可
5. 末尾加一行：**今日行业总结**：（50字以内，概括今日最值得关注的1-2个趋势）
"""
    return ask_deepseek(prompt)


# ============================================================
# AI 分析：从资讯产品中选择缝合对象
# ============================================================
def generate_fusion_ideas(news_analysis: str) -> str:
    prompt = f"""
你是三国杀名将传的游戏策划总监。

今日资讯已整理如下（这是今天真实收集的产品数据）：
{news_analysis}

━━━━━━━━━━━━━━━━━━
背景知识：
- 三国杀名将传（名将like）：卡牌+Roguelike手游，核心是组建6人名将阵容对战
- 我们在找"前期钩子副玩法"：用轻量上瘾的小玩法在D1-D7吸引新用户，再引入名将like核心
- 参考模型：SLG从传统过渡到无尽冬日（前期钩子副玩法买量思路）
- 特别关注：含模拟/建造/经营/塔防/RPG/解谜元素的产品

━━━━━━━━━━━━━━━━━━
任务：从今日资讯涉及的产品中，挑选 2-3 款最具缝合机会的产品，给出详细缝合设想。
必须从上方资讯中选择真实产品，不能自创产品名。

每个缝合方案按以下格式输出：

---
### 💡 [原型产品名（来自今日资讯）] × 名将like 缝合创想

**为什么选这款**：（从今日资讯中，它具备什么特质让你认为它有缝合价值）

**缝合核心逻辑**：
（用什么作为钩子，怎么实现从钩子玩法到名将like核心的自然过渡，2-3句）

**三阶段设计**：
- 🎣 D1–D3 钩子期：[让玩家上瘾的核心手感体验，反馈要快]
- 🌉 D4–D7 过渡期：[如何引入名将元素，让过渡自然]
- ⚔️ D7+ 名将期：[名将like全面介入，核心循环说明]

**差异化创新点**：
① [与原型游戏的差异]
② [与现有名将like产品的差异]  
③ [预期的买量/留存优势]

**落地风险**：（一句话说最大挑战）

---

最后输出：
**本期缝合优选**：[推荐最优方案的名称]
**推荐理由**：（30字以内）
"""
    return ask_deepseek(prompt, system="你是有10年经验的手游策划总监，擅长玩法融合和买量产品设计，语言直接不废话。")


# ============================================================
# 构建 HTML 邮件
# ============================================================
def md_to_html(text: str) -> str:
    """Markdown → HTML 转换，支持常见格式"""
    lines = text.split("\n")
    out = []
    for line in lines:
        line = line.rstrip()
        if line.startswith("### "):
            out.append(f'<h4 style="color:#c0392b;margin:20px 0 8px;font-size:15px">{line[4:]}</h4>')
        elif line.startswith("## "):
            out.append(f'<h3 style="color:#2c3e50;margin:18px 0 8px">{line[3:]}</h3>')
        elif line.startswith("**📌"):
            # 重点资讯标题
            content = line.strip("*").strip()
            out.append(f'<div style="font-size:15px;font-weight:700;color:#1a1a1a;margin:20px 0 6px;padding:6px 0;border-bottom:1px solid #f0f0f0">{content}</div>')
        elif line == "---":
            out.append('<hr style="border:none;border-top:2px dashed #e8e8e8;margin:18px 0">')
        elif re.match(r"^\*\*(.+?)\*\*$", line):
            m = re.match(r"^\*\*(.+?)\*\*$", line)
            out.append(f'<p style="margin:8px 0"><strong style="color:#2c3e50">{m.group(1)}</strong></p>')
        elif re.match(r"^\*\*(.+?)\*\*：(.*)$", line):
            m = re.match(r"^\*\*(.+?)\*\*：(.*)$", line)
            out.append(f'<p style="margin:5px 0"><strong style="color:#2c3e50">{m.group(1)}</strong>：{m.group(2)}</p>')
        elif re.match(r"^• \*\*(.+?)\*\*：(.*)$", line):
            m = re.match(r"^• \*\*(.+?)\*\*：(.*)$", line)
            out.append(f'<li style="margin:4px 0"><strong style="color:#2c3e50">{m.group(1)}</strong>：{m.group(2)}</li>')
        elif line.startswith("• ") or line.startswith("- "):
            out.append(f'<li style="margin:4px 0">{line[2:]}</li>')
        elif line.startswith("① ") or line.startswith("② ") or line.startswith("③ "):
            out.append(f'<li style="margin:4px 0">{line[2:]}</li>')
        elif line.startswith("🎣 ") or line.startswith("🌉 ") or line.startswith("⚔️ "):
            out.append(f'<li style="margin:6px 0;list-style:none;padding-left:0">{line}</li>')
        elif line == "":
            out.append("<br>")
        else:
            # 处理行内加粗
            line = re.sub(r"\*\*(.+?)\*\*", r'<strong style="color:#2c3e50">\1</strong>', line)
            out.append(f'<p style="margin:4px 0;line-height:1.7">{line}</p>')

    html = "\n".join(out)
    # 包裹连续 li
    html = re.sub(
        r"((?:<li[^>]*>.*?</li>\n?)+)",
        lambda m: f'<ul style="padding-left:20px;margin:6px 0">{m.group(0)}</ul>',
        html,
    )
    return html


def build_html(news_analysis: str, fusion_ideas: str) -> str:
    news_html   = md_to_html(news_analysis)
    fusion_html = md_to_html(fusion_ideas)

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{TODAY_LABEL} 手游&小游戏资讯日报</title>
<style>
  body{{font-family:'PingFang SC','Microsoft YaHei',Arial,sans-serif;background:#f4f6f9;margin:0;padding:20px;color:#333;font-size:14px;line-height:1.7}}
  .container{{max-width:800px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 16px rgba(0,0,0,.1)}}
  .header{{background:linear-gradient(135deg,#c0392b 0%,#8e1a0e 100%);color:#fff;padding:28px 36px}}
  .header h1{{margin:0 0 6px;font-size:22px;letter-spacing:.5px}}
  .header p{{margin:0;opacity:.85;font-size:13px}}
  .meta-row{{display:flex;gap:12px;margin-top:10px;flex-wrap:wrap}}
  .badge{{display:inline-block;background:rgba(255,255,255,.18);border-radius:20px;padding:2px 12px;font-size:11px}}
  .toc{{background:#fafafa;padding:14px 36px;border-bottom:1px solid #f0f0f0;font-size:12px;color:#666}}
  .section{{padding:24px 36px;border-bottom:1px solid #f0f0f0}}
  .section:last-child{{border-bottom:none}}
  .section-title{{font-size:17px;font-weight:700;color:#2c3e50;margin:0 0 18px;padding-left:12px;border-left:4px solid #c0392b;display:flex;align-items:center;gap:8px}}
  .news-item{{background:#fafafa;border-radius:8px;padding:14px 16px;margin-bottom:14px;border:1px solid #f0f0f0}}
  .fusion-box{{background:#fff8f5;border:1px solid #f5d5c8;border-radius:10px;padding:18px;margin-top:4px}}
  .channel-pills{{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px}}
  .pill{{font-size:11px;padding:2px 10px;border-radius:12px;border:1px solid #e0e0e0;color:#666;background:#fff}}
  .highlight{{background:#fef9e7;border-left:3px solid #f39c12;padding:10px 14px;border-radius:0 6px 6px 0;margin:12px 0;font-size:13px}}
  .footer{{background:#2c3e50;color:#aaa;text-align:center;padding:16px;font-size:11px}}
  a{{color:#c0392b}}
  strong{{color:#1a1a1a}}
</style>
</head>
<body>
<div class="container">

  <div class="header">
    <h1>🃏 手游 & 小游戏资讯日报</h1>
    <p>{TODAY_LABEL} · 三国杀名将传战略参考 · 数据时效：24小时内</p>
    <div class="meta-row">
      <span class="badge">📡 B站 · TapTap · 竞核 · DataEye</span>
      <span class="badge">🤖 DeepSeek AI 分析</span>
      <span class="badge">📌 {PUBLISHER}</span>
    </div>
  </div>

  <div class="toc">
    本期内容：
    <strong style="color:#c0392b">① 行业资讯</strong>（≥7条·含热度数据）&nbsp;|&nbsp;
    <strong style="color:#c0392b">② 名将like钩子缝合创想</strong>（基于本期资讯产品）
  </div>

  <!-- Section 1 -->
  <div class="section">
    <div class="section-title">
      <span>①</span> 手游 & 小游戏 行业资讯
    </div>
    <div class="channel-pills">
      <span class="pill">📺 B站·独立游戏</span>
      <span class="pill">📺 B站·手机游戏</span>
      <span class="pill">🎮 TapTap新品榜</span>
      <span class="pill">📰 竞核</span>
      <span class="pill">📊 DataEye</span>
      <span class="pill">📰 游戏葡萄</span>
    </div>
    {news_html}
  </div>

  <!-- Section 2 -->
  <div class="section">
    <div class="section-title">
      <span>②</span> 名将like · 前期钩子缝合创想
    </div>
    <div class="highlight">
      💡 从本期资讯产品中精选，探索三国杀名将传前期轻量化钩子副玩法方向
    </div>
    <div class="fusion-box">
      {fusion_html}
    </div>
  </div>

  <div class="footer">
    {TODAY_LABEL} · 手游&小游戏资讯日报 · {PUBLISHER}<br>
    数据来源：B站API · TapTap · 竞核 · DataEye · 游戏葡萄 · DuckDuckGo · DeepSeek AI · 内部参考，请勿外传
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
    print(f"=== {TODAY} 日报开始生成（v3.0）===")

    # ── 数据采集 ──
    print("📺 [1/4] B站近24h热门游戏视频...")
    bili_data = fetch_bilibili_trending_games()
    print(f"    → 获取 {len(bili_data)} 条B站数据")

    print("🎮 [2/4] TapTap新品榜...")
    taptap_data = fetch_taptap_new_games()
    print(f"    → 获取 {len(taptap_data)} 条TapTap数据")

    print("📰 [3/4] 游戏媒体近24h资讯（竞核/DataEye/游戏葡萄等）...")
    industry_news = fetch_industry_news()
    print(f"    → 获取 {len(industry_news)} 条媒体资讯")

    # ── AI 分析 ──
    print("🤖 [AI-1] 整合分析，生成7条以上重点资讯...")
    news_analysis = analyze_all_news(industry_news, bili_data, taptap_data)

    print("🤖 [AI-2] 基于本期资讯生成名将like缝合创想...")
    fusion_ideas = generate_fusion_ideas(news_analysis)

    # ── 发送 ──
    print("📝 构建HTML邮件...")
    html = build_html(news_analysis, fusion_ideas)

    print("📧 发送邮件...")
    send_email(html)

    print("=== 日报完成 ✅ ===")


if __name__ == "__main__":
    main()
