#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
卡牌手游 & 小游戏资讯日报 + 名将like钩子缝合创想
适用产品：三国杀名将传
作者：游卡网络战略分析组
"""

import os
import smtplib
import json
import re
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from openai import OpenAI
from duckduckgo_search import DDGS

# ============================================================
# ★ 每次新产品接入只需修改这里 ★
# ============================================================
GAME_NAME_ZH   = "三国杀名将传"
GAME_NAME_EN   = "SGS Famous Generals"
PUBLISHER      = "游卡网络战略分析组"

# 竞品分级
L1_COMPETITORS = ["西游笔绘西行"]
L2_COMPETITORS = ["阴阳师", "伊瑟", "第七史诗", "忘川风华录", "三国志幻想大陆2"]
L3_COMPETITORS = ["龙族：卡塞尔之门", "剑与远征：启程", "崩坏：星穹铁道"]
L4_COMPETITORS = ["保卫向日葵", "永远的蔚蓝星球", "遗弃之地"]

# 收件人（从 Secret 读取，支持逗号分隔多人）
RECIPIENTS = os.environ.get("REPORT_RECIPIENT_EMAIL", "").split(",")

# ============================================================
# 时区 / 日期
# ============================================================
CST = timezone(timedelta(hours=8))
TODAY = datetime.now(CST).strftime("%Y-%m-%d")
TODAY_LABEL = datetime.now(CST).strftime("%Y年%m月%d日")

# ============================================================
# DeepSeek 客户端
# ============================================================
client = OpenAI(
    api_key=os.environ["DEEPSEEK_API_KEY"],
    base_url="https://api.deepseek.com/v1",
)

def ask_deepseek(prompt: str, system: str = "你是一位专业的游戏行业分析师，擅长卡牌手游市场分析。") -> str:
    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ],
        temperature=0.7,
        max_tokens=3000,
    )
    return resp.choices[0].message.content.strip()

# ============================================================
# 数据采集：DuckDuckGo
# ============================================================
def ddg_news(query: str, max_results: int = 5) -> list[dict]:
    """搜索近24小时新闻"""
    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.news(query, region="cn-zh", timelimit="d", max_results=max_results):
                results.append(r)
    except Exception as e:
        print(f"[DDG] 搜索 '{query}' 失败: {e}")
    return results

def ddg_text(query: str, max_results: int = 4) -> list[dict]:
    """搜索网页（用于小游戏/Steam热门）"""
    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, region="cn-zh", max_results=max_results):
                results.append(r)
    except Exception as e:
        print(f"[DDG] 文本搜索 '{query}' 失败: {e}")
    return results

# ============================================================
# 采集各类目数据
# ============================================================
def collect_competitors() -> dict:
    """采集各级竞品新闻"""
    data = {}
    all_competitors = {
        "L1": L1_COMPETITORS,
        "L2": L2_COMPETITORS,
        "L3": L3_COMPETITORS,
        "L4": L4_COMPETITORS,
    }
    for level, games in all_competitors.items():
        level_data = []
        for game in games:
            news = ddg_news(f"{game} 手游 更新 活动 版本", max_results=4)
            if news:
                level_data.append({"game": game, "news": news})
        data[level] = level_data
    return data

def collect_mini_games() -> list[dict]:
    """采集近期热门小游戏"""
    queries = [
        "小游戏 热门 爆款 2026",
        "微信小游戏 月活 排行 最新",
        "抖音小游戏 热门 新品 2026",
        "小程序游戏 热门 今日",
    ]
    results = []
    for q in queries:
        results.extend(ddg_text(q, max_results=4))
    return results

def collect_steam_indie() -> list[dict]:
    """采集近期热门Steam独立游戏"""
    queries = [
        "Steam 独立游戏 热门 新品 2026",
        "Steam 国产 独立游戏 好评 2026",
        "Steam 新作 热卖 今周",
        "indie game Steam trending 2026",
    ]
    results = []
    for q in queries:
        results.extend(ddg_text(q, max_results=4))
    return results

# ============================================================
# AI 分析
# ============================================================
def analyze_competitors(data: dict) -> str:
    items = []
    for level, games in data.items():
        for g in games:
            snippets = "\n".join([f"- [{r.get('date','')[:10]}] {r.get('title','')}：{r.get('body','')[:120]}" for r in g["news"]])
            if snippets:
                items.append(f"【{level} {g['game']}】\n{snippets}")
    if not items:
        return "今日暂无竞品重要动态。"
    raw = "\n\n".join(items)
    prompt = f"""
以下是今日卡牌手游竞品的新闻原文，请整理成日报摘要：
{raw}

输出格式要求（严格按此格式，不要多余说明）：
对每款有动态的竞品，输出：
**[竞品名]（L级别）**
• 核心动态：1-2句话总结
• 关注点：对三国杀名将传的参考意义或威胁点
• 原文链接：（如有URL请列出）

最后加一行：
**今日竞品关键信号**：（50字以内的总结性判断）
"""
    return ask_deepseek(prompt)

def analyze_mini_games(results: list[dict]) -> str:
    if not results:
        return "今日暂无小游戏热门数据。"
    snippets = "\n".join([f"- {r.get('title','')}：{r.get('body','')[:150]}" for r in results[:16]])
    prompt = f"""
以下是今日小游戏市场的资讯原文：
{snippets}

请从中提炼出 3-5 款值得关注的热门小游戏，对每款输出：
**[游戏名]**
• 热度信号：（为什么热）
• 核心玩法：（一句话）
• 对名将like的参考价值：（一句话）

最后一行：**小游戏市场今日趋势**：（40字以内）
"""
    return ask_deepseek(prompt)

def analyze_steam_indie(results: list[dict]) -> str:
    if not results:
        return "今日暂无Steam独立游戏热门数据。"
    snippets = "\n".join([f"- {r.get('title','')}：{r.get('body','')[:150]}" for r in results[:16]])
    prompt = f"""
以下是今日Steam独立游戏市场的资讯：
{snippets}

请从中提炼出 3-5 款值得关注的Steam独立/国产游戏，对每款输出：
**[游戏名]**
• 热度信号：（为什么热）
• 核心玩法机制：（一句话）
• 独特设计亮点：（一句话）

最后一行：**Steam独立游戏今日趋势**：（40字以内）
"""
    return ask_deepseek(prompt)

def generate_fusion_ideas(mini_game_analysis: str, steam_analysis: str) -> str:
    """每日名将like缝合创想（从小游戏/Steam中各挑1款以上）"""
    prompt = f"""
你是三国杀名将传的游戏策划专家。背景：
- 三国杀名将传（名将like）是一款卡牌+Roguelike手游，核心循环是组建六人名将阵容对战
- 我们正在寻找"前期钩子副玩法"：用轻量、上瘾的小玩法在D1-D7吸引新用户，最终引入名将like核心
- 参考思路：SLG从传统过渡到类似无尽冬日，用钩子副玩法买量
- 特别关注含模拟、建造、经营、塔防、RPG元素的产品
- 钩子玩法应有强手感反馈、快速正反馈循环、轻量上手

今日小游戏热门摘要：
{mini_game_analysis}

今日Steam热门摘要：
{steam_analysis}

任务：从上述产品中，挑选至少2款（小游戏和Steam各至少1款）你认为最具缝合机会的产品，给出详细缝合设想。

每个产品按以下格式输出：

---
### 💡 [原型产品名] + 名将like 缝合创想

**缝合核心思路**（2-3句话，说明用什么作为钩子，怎么过渡到名将like核心）

**玩法循环设计**：
- D1-D3：[钩子阶段体验]
- D4-D7：[过渡期设计]
- D7+：[名将like全面介入]

**差异化创新点**：
1. [与原型产品的差异]
2. [与现有名将like产品的差异]
3. [买量/留存的独特卖点]

**风险提示**：（一句话）
---

最后输出：
**今日缝合优选推荐**：（从以上方案中选出你认为最有潜力的1个，用一句话说明理由）
"""
    return ask_deepseek(prompt, system="你是一位有10年经验的手游策划总监，擅长发现玩法融合机会，语言简洁直接。")

# ============================================================
# 构建 HTML 邮件
# ============================================================
def build_html(
    competitor_analysis: str,
    mini_game_analysis: str,
    steam_analysis: str,
    fusion_ideas: str,
) -> str:

    def md_to_html(text: str) -> str:
        """极简 markdown → HTML 转换"""
        lines = text.split("\n")
        out = []
        for line in lines:
            line = line.rstrip()
            if line.startswith("### "):
                out.append(f"<h4 style='color:#c0392b;margin:18px 0 6px'>{line[4:]}</h4>")
            elif line.startswith("## "):
                out.append(f"<h3 style='color:#2c3e50;margin:20px 0 8px'>{line[3:]}</h3>")
            elif line.startswith("**") and line.endswith("**") and len(line) > 4:
                out.append(f"<p><strong>{line[2:-2]}</strong></p>")
            elif line.startswith("---"):
                out.append("<hr style='border:1px solid #eee;margin:12px 0'>")
            elif re.match(r"^\*\*(.+?)\*\*(.*)$", line):
                m = re.match(r"^\*\*(.+?)\*\*(.*)$", line)
                out.append(f"<p><strong style='color:#2c3e50'>{m.group(1)}</strong>{m.group(2)}</p>")
            elif line.startswith("• ") or line.startswith("- "):
                out.append(f"<li style='margin:3px 0'>{line[2:]}</li>")
            elif line == "":
                out.append("<br>")
            else:
                out.append(f"<p style='margin:4px 0'>{line}</p>")
        html = "\n".join(out)
        # 包裹连续 li
        html = re.sub(r"(<li.*?</li>\n?)+", lambda m: f"<ul style='padding-left:20px;margin:6px 0'>{m.group(0)}</ul>", html)
        return html

    competitor_html  = md_to_html(competitor_analysis)
    mini_game_html   = md_to_html(mini_game_analysis)
    steam_html       = md_to_html(steam_analysis)
    fusion_html      = md_to_html(fusion_ideas)

    html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{TODAY_LABEL} 卡牌手游&小游戏资讯日报</title>
<style>
  body{{font-family:'PingFang SC','Microsoft YaHei',Arial,sans-serif;background:#f4f6f9;margin:0;padding:20px;color:#333;font-size:14px}}
  .container{{max-width:780px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.1)}}
  .header{{background:linear-gradient(135deg,#c0392b 0%,#8e1a0e 100%);color:#fff;padding:28px 32px}}
  .header h1{{margin:0 0 6px;font-size:22px;letter-spacing:1px}}
  .header p{{margin:0;opacity:.85;font-size:13px}}
  .badge{{display:inline-block;background:rgba(255,255,255,.2);border-radius:20px;padding:2px 12px;font-size:12px;margin-top:8px}}
  .section{{padding:24px 32px;border-bottom:1px solid #f0f0f0}}
  .section:last-child{{border-bottom:none}}
  .section-title{{font-size:17px;font-weight:700;color:#2c3e50;margin:0 0 16px;padding-left:10px;border-left:4px solid #c0392b}}
  .level-tag{{display:inline-block;border-radius:4px;padding:1px 8px;font-size:11px;font-weight:700;margin-right:6px}}
  .l1{{background:#c0392b;color:#fff}}
  .l2{{background:#e67e22;color:#fff}}
  .l3{{background:#27ae60;color:#fff}}
  .l4{{background:#7f8c8d;color:#fff}}
  .fusion-box{{background:#fff8f0;border:1px solid #f0d9c0;border-radius:8px;padding:16px;margin-top:8px}}
  .highlight{{background:#fef9e7;border-left:3px solid #f39c12;padding:10px 14px;border-radius:0 6px 6px 0;margin:12px 0}}
  .footer{{background:#2c3e50;color:#aaa;text-align:center;padding:16px;font-size:12px}}
  a{{color:#c0392b;text-decoration:none}}
</style>
</head>
<body>
<div class="container">

  <!-- Header -->
  <div class="header">
    <h1>🃏 卡牌手游 &amp; 小游戏资讯日报</h1>
    <p>三国杀名将传战略参考 · {TODAY_LABEL} · 数据时效：24小时内</p>
    <span class="badge">📌 {PUBLISHER}</span>
  </div>

  <!-- 目录 -->
  <div class="section" style="background:#fafafa;padding:16px 32px">
    <p style="margin:0;font-size:13px;color:#666">
      本期内容：
      <strong style="color:#c0392b">① 竞品动态</strong>（L1–L4）&nbsp;|&nbsp;
      <strong style="color:#c0392b">② 热门小游戏</strong>&nbsp;|&nbsp;
      <strong style="color:#c0392b">③ Steam 独立游戏</strong>&nbsp;|&nbsp;
      <strong style="color:#c0392b">④ 名将like钩子缝合创想</strong>
    </p>
  </div>

  <!-- Section 1: 竞品 -->
  <div class="section">
    <div class="section-title">① 竞品动态追踪</div>
    <p style="margin:0 0 12px;font-size:12px;color:#999">
      <span class="level-tag l1">L1</span>核心竞品
      <span class="level-tag l2">L2</span>直接竞品
      <span class="level-tag l3">L3</span>关联赛道
      <span class="level-tag l4">L4</span>细分赛道
    </p>
    {competitor_html}
  </div>

  <!-- Section 2: 小游戏 -->
  <div class="section">
    <div class="section-title">② 热门小游戏</div>
    {mini_game_html}
  </div>

  <!-- Section 3: Steam -->
  <div class="section">
    <div class="section-title">③ Steam 独立游戏热门</div>
    {steam_html}
  </div>

  <!-- Section 4: 缝合创想 -->
  <div class="section">
    <div class="section-title">④ 名将like · 前期钩子缝合创想</div>
    <div class="highlight">
      💡 从今日资讯中挑选具备缝合机会的产品，探索三国杀名将传前期轻量化钩子副玩法方向
    </div>
    <div class="fusion-box">
      {fusion_html}
    </div>
  </div>

  <!-- Footer -->
  <div class="footer">
    {TODAY_LABEL} · 卡牌手游&amp;小游戏资讯日报 · {PUBLISHER}<br>
    由 GitHub Actions + DeepSeek AI 自动生成 · 内部参考，请勿外传
  </div>

</div>
</body>
</html>"""
    return html

# ============================================================
# 发送邮件
# ============================================================
def send_email(html: str):
    sender  = os.environ["GMAIL_SENDER_EMAIL"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    recipients = [r.strip() for r in RECIPIENTS if r.strip()]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"【{TODAY_LABEL}】卡牌手游&小游戏资讯日报 · {GAME_NAME_ZH}战略参考"
    msg["From"]    = sender
    msg["To"]      = ", ".join(recipients)
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, recipients, msg.as_string())
    print(f"✅ 邮件已发送至 {recipients}")

# ============================================================
# 主流程
# ============================================================
def main():
    print(f"=== {TODAY} 日报开始生成 ===")

    print("📡 [1/4] 采集竞品数据...")
    competitor_data = collect_competitors()

    print("📡 [2/4] 采集热门小游戏数据...")
    mini_game_data = collect_mini_games()

    print("📡 [3/4] 采集Steam独立游戏数据...")
    steam_data = collect_steam_indie()

    print("🤖 [AI] 分析竞品动态...")
    competitor_analysis = analyze_competitors(competitor_data)

    print("🤖 [AI] 分析热门小游戏...")
    mini_game_analysis = analyze_mini_games(mini_game_data)

    print("🤖 [AI] 分析Steam独立游戏...")
    steam_analysis = analyze_steam_indie(steam_data)

    print("🤖 [AI] 生成名将like缝合创想...")
    fusion_ideas = generate_fusion_ideas(mini_game_analysis, steam_analysis)

    print("📝 构建 HTML 邮件...")
    html = build_html(competitor_analysis, mini_game_analysis, steam_analysis, fusion_ideas)

    print("📧 发送邮件...")
    send_email(html)

    print("=== 日报生成完成 ✅ ===")

if __name__ == "__main__":
    main()
