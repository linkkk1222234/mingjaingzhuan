#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
手游 & 小游戏资讯日报 v5.0
适用产品：三国杀名将传
作者：游卡网络战略分析组
"""

import os, re, json, smtplib, time, requests
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
RECIPIENTS   = [r.strip() for r in os.environ.get("REPORT_RECIPIENT_EMAIL","").split(",") if r.strip()]

CST         = timezone(timedelta(hours=8))
TODAY       = datetime.now(CST).strftime("%Y-%m-%d")
TODAY_LABEL = datetime.now(CST).strftime("%Y年%m月%d日")

EXCLUDE_GAMES = {
    "王者荣耀","和平精英","原神","英雄联盟","穿越火线","荒野行动",
    "使命召唤手游","PUBG","Free Fire","部落冲突","皇室战争",
    "糖果传奇","开心消消乐","欢乐斗地主","天天爱消除","球球大作战",
}

client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url="https://api.deepseek.com/v1")


# ============================================================
# 工具
# ============================================================
def ask_deepseek(prompt: str, system: str = "你是专业游戏行业分析师，回复简洁专业。", max_tokens: int = 5000) -> str:
    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role":"system","content":system},{"role":"user","content":prompt}],
            temperature=0.7, max_tokens=max_tokens,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"[DeepSeek] 失败: {e}"); return ""


def safe_json(text: str, fallback):
    text = re.sub(r"```(?:json)?", "", text).strip().strip("`").strip()
    start = min(
        (text.find("[") if "[" in text else 9999),
        (text.find("{") if "{" in text else 9999),
    )
    if start == 9999: return fallback
    try: return json.loads(text[start:])
    except: return fallback


def ddg_news(query: str, max_results: int = 8, timelimit: str = "d", region: str = "cn-zh") -> list[dict]:
    """严格24小时内新闻"""
    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.news(query, region=region, timelimit=timelimit, max_results=max_results):
                results.append(r)
        time.sleep(2)
    except Exception as e:
        print(f"[DDG news] '{query[:30]}' 失败: {e}")
        time.sleep(4)
    return results


def ddg_text(query: str, max_results: int = 6) -> list[dict]:
    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, region="cn-zh", max_results=max_results):
                results.append(r)
        time.sleep(2)
    except Exception as e:
        print(f"[DDG text] '{query[:30]}' 失败: {e}")
        time.sleep(4)
    return results


def is_excluded(text: str) -> bool:
    return any(g in text for g in EXCLUDE_GAMES)


# ============================================================
# 数据采集：游戏微信公众号媒体（竞核/DataEye/游戏葡萄等）
# ============================================================
def fetch_game_media_news() -> list[dict]:
    """
    核心资讯来源：游戏行业微信公众号媒体
    严格限定24小时内（timelimit='d'）
    """
    # 每个媒体单独搜索，确保每个来源都有机会覆盖
    media_queries = [
        ("竞核",     "竞核 手游 新游 上线"),
        ("竞核",     "竞核 游戏 新品 今日"),
        ("SensorTower", "SensorTower 手游 排行 下载"),
        ("游戏先知", "游戏先知 手游 新作 今日"),
        ("游戏先知", "游戏先知 新游推荐"),
        ("游戏葡萄", "游戏葡萄 手游 独立游戏"),
        ("游戏葡萄", "游戏葡萄 新品 今日"),
        ("广大大",   "广大大 手游 买量 新素材"),
        ("广大大",   "广大大 游戏 今日"),
        ("DataEye",  "DataEye 手游 新品 数据"),
        ("DataEye",  "DataEye 游戏 今日"),
        ("手游圈圈", "手游圈圈 新游 推荐"),
        ("游戏茶馆", "游戏茶馆 手游 今日 新游"),
        ("游戏茶馆", "游戏茶馆 独立游戏"),
        # 兜底：通用行业资讯
        ("行业媒体", "手游 新品上线 今日 2026"),
        ("行业媒体", "卡牌手游 新作 爆款 今日"),
        ("行业媒体", "小游戏 爆款 微信 今日"),
        ("行业媒体", "Steam 独立游戏 国产 新品 2026"),
    ]

    all_news = []
    for source_hint, query in media_queries:
        results = ddg_news(query, max_results=6, timelimit="d")
        for r in results:
            if not is_excluded(r.get("title", "")):
                r["source_hint"] = source_hint
                all_news.append(r)

    # 去重（按标题）
    seen = set()
    unique = []
    for r in all_news:
        key = r.get("title", "")[:40]
        if key not in seen:
            seen.add(key)
            unique.append(r)

    print(f"    媒体资讯去重后：{len(unique)} 条")
    return unique


# ============================================================
# 数据采集：TapTap 安卓新品榜
# ============================================================
def fetch_taptap_new_android() -> list[dict]:
    """
    TapTap 安卓新品榜采集
    直接抓取被CDN拦截，改用三路DDG搜索+游戏媒体报道兜底
    """
    results = []

    # 路线A：DDG 新闻搜索 TapTap 近期新品
    news_queries = [
        "TapTap 安卓新品 手游 排行 本周",
        "TapTap 新游 上线 安卓 最新",
        "TapTap 新品榜 今日 手游",
    ]
    for q in news_queries:
        for r in ddg_news(q, max_results=6, timelimit="w"):
            r["taptap_source"] = "TapTap新闻"
            results.append(r)

    # 路线B：DDG 文本搜索 TapTap 应用页
    text_queries = [
        "taptap 安卓新品排行 最新手游 2026",
        "taptap top new android 2026",
        "TapTap 最新安卓新品手游排行榜 推荐",
    ]
    for q in text_queries:
        for r in ddg_text(q, max_results=5):
            r["taptap_source"] = "TapTap搜索"
            results.append(r)

    # 路线C：游戏媒体报道 TapTap 新品榜
    for r in ddg_news("taptap新品 手游 排行 新游推荐", max_results=6, timelimit="w"):
        r["taptap_source"] = "TapTap媒体报道"
        results.append(r)

    # 去重
    seen = set()
    unique = []
    for r in results:
        key = r.get("title", "")[:40]
        if key not in seen:
            seen.add(key); unique.append(r)

    print(f"    TapTap数据：{len(unique)} 条")
    return unique


# ============================================================
# AI 分析一：整合资讯 → 结构化 JSON（≥7条，标题短句）
# ============================================================
def analyze_news_to_json(media_news: list[dict]) -> list[dict]:
    """
    整合所有媒体资讯，AI输出结构化JSON
    标题格式：产品名+动态短句，如"《龙约》手游首月下载破200万"
    """
    news_text = "\n".join([
        f"[{r.get('source_hint', r.get('source', '媒体'))} | {r.get('date','')[:10]}] "
        f"标题：{r.get('title','')} | "
        f"URL：{r.get('url', r.get('href',''))} | "
        f"摘要：{r.get('body','')[:150]}"
        for r in media_news[:40]
    ])

    exclude_str = "、".join(sorted(EXCLUDE_GAMES))

    prompt = f"""
今天是{TODAY_LABEL}，你是游卡战略分析组游戏分析师。

以下是来自竞核、DataEye、游戏葡萄、游戏先知、广大大、手游圈圈、游戏茶馆、SensorTower等微信公众号和行业媒体的近24小时资讯：

{news_text or '暂无数据'}

━━━━━━━━━━
排除规则：以下超头部产品不得出现：{exclude_str}

输出要求：返回纯JSON数组，至少7条，最多12条，格式如下：
[
  {{
    "no": 1,
    "title": "产品名+动态短句（必须含产品名，如《龙约》手游明日首发上线/《异环》二次元新游引发热议/某某游戏首月下载破百万）",
    "source_label": "竞核 或 DataEye 或 游戏葡萄 或 游戏先知 或 广大大 或 手游圈圈 或 游戏茶馆 或 SensorTower 或 36氪 或 其他（用原始来源媒体名）",
    "source_url": "原始文章URL，从输入数据中提取，没有则空字符串",
    "heat": "热度表现：下载量/榜单排名/播放量/媒体报道数等具体数据，无数据写媒体关注度高",
    "gameplay": "核心玩法一句话，如：动作RPG+换装、三消+农场经营",
    "dynamics": "近期动态：具体发生了什么（上线/新版本/数据表现/行业事件），50字以内",
    "insight": "对名将like或手游市场的参考意义，1句话"
  }}
]

关键要求：
1. title必须是"产品名+动态短句"格式，不能只写产品名，不能是泛泛标题
2. 只选24小时内的最新动态，有明确时间戳{TODAY}的优先
3. 必须覆盖多个品类：手游新品、小游戏、Steam独立游戏、行业动态等
4. source_url从输入数据的URL字段提取真实链接
5. 最后一条 no填99，title填"今日行业总结"，insight写50字以内总结，其余字段空
6. 只输出JSON，不要任何其他内容
"""
    raw = ask_deepseek(prompt, system="你只输出合法JSON数组，不输出任何其他内容。", max_tokens=5000)
    result = safe_json(raw, [])
    if not result:
        return [{"no":1,"title":"今日数据采集异常","source_label":"系统","source_url":"",
                 "heat":"—","gameplay":"—","dynamics":"数据获取失败，请检查网络或API配置","insight":"建议手动重跑"}]
    return result


# ============================================================
# AI 分析二：TapTap 新品表格（JSON，10款）
# ============================================================
def analyze_taptap_table(taptap_data: list[dict]) -> list[dict]:
    taptap_raw = "\n".join([
        f"- {r.get('title','')} | {r.get('body', r.get('snippet',''))[:150]} | URL:{r.get('href', r.get('url',''))}"
        for r in taptap_data[:25]
    ])

    exclude_str = "、".join(sorted(EXCLUDE_GAMES))

    prompt = f"""
今天是{TODAY_LABEL}。从以下TapTap安卓新品榜相关资讯中，筛选10款值得关注的手游新品（题材/玩法/画风有新意）。

原始数据：
{taptap_raw or '暂无'}

排除：{exclude_str}

输出纯JSON数组，恰好10条（不足则补充你知道的近期TapTap新品，明确标注"AI补充"），格式：
[
  {{
    "rank": "安卓新品Top1 / 安卓新品Top3 / 近期新上线 等描述",
    "platform": "安卓",
    "name": "游戏名",
    "gameplay": "核心玩法（如三消+养成、动作RPG+建造）",
    "theme": "题材（如古风、科幻、像素、现代）",
    "art_style": "画风（如写实、卡通、水墨、赛博朋克）",
    "note": "关注理由（玩法/题材/画风的新意点，15字以内）",
    "url": "TapTap产品链接，如https://www.taptap.cn/app/xxxxx，没有则空"
  }}
]
只输出JSON，不要其他内容。
"""
    raw = ask_deepseek(prompt, system="你只输出合法JSON数组，不输出任何其他内容。", max_tokens=2500)
    return safe_json(raw, [])


# ============================================================
# AI 分析三：缝合创想
# ============================================================
def generate_fusion_ideas(news_items: list[dict]) -> str:
    products = "\n".join([
        f"{i.get('no','')}. 【{i.get('title','')}】玩法:{i.get('gameplay','')} 动态:{i.get('dynamics','')}"
        for i in news_items if i.get("no",0) != 99
    ])

    prompt = f"""
你是三国杀名将传的游戏策划总监。

【今日资讯产品（必须从这里选，不得自创）】
{products}

【背景】
- 三国杀名将传（名将like）：卡牌+Roguelike手游，核心是组建6人名将阵容对战
- 目标：找"前期钩子副玩法"——D1让玩家上瘾，D2-D7过渡，D7+全面引入名将like
- 参考：无尽冬日（SLG用建造钩子买量），关注模拟/建造/经营/塔防/RPG/解谜元素
- 钩子要求：强手感、快反馈、5分钟内能感受到核心乐趣、对三国IP有融合点

从上方产品中选2-3款最具缝合潜力的，每个方案格式：

---
### 💡 [产品名] × 名将like 缝合创想

**选择理由**：（该产品哪个特质有缝合价值，1-2句）

**缝合核心逻辑**：（钩子是什么 → 怎么自然引入名将like，2-3句）

**阶段设计**：
🎣 **D1 冷启动**：[钩子手感体验，快速正反馈，5分钟内上瘾]
🌉 **D2–D7 过渡期**：[如何逐步引入名将元素，让过渡不突兀]
⚔️ **D7+ 名将期**：[名将like全面介入，核心循环说明]

**创新差异点**：
① 与原型产品的差异：
② 与现有名将like的差异：
③ 买量/留存预期优势：

**最大落地挑战**：（一句话）

---

最后：
**本期优选**：[最推荐方案的产品名]
**推荐理由**：（25字以内）
"""
    return ask_deepseek(prompt, system="你是10年手游策划总监，语言简练直接，不说废话。", max_tokens=4000)


# ============================================================
# HTML 构建
# ============================================================
SOURCE_STYLES = {
    "竞核":       ("#e8f4fd","#1565c0","📰"),
    "DataEye":    ("#f5f0ff","#5b2d9e","📊"),
    "游戏葡萄":   ("#fff0f3","#a3153e","🍇"),
    "游戏先知":   ("#e8fdf5","#0d6e50","🔮"),
    "广大大":     ("#fff8e1","#8a5a00","📈"),
    "手游圈圈":   ("#fce4ec","#880e4f","🎮"),
    "游戏茶馆":   ("#f3e5f5","#6a1b9a","🍵"),
    "SensorTower":("#e3f2fd","#0d47a1","📡"),
    "36氪":       ("#fbe9e7","#bf360c","🔶"),
    "系统":       ("#ffebee","#c62828","⚠️"),
}

def get_source_style(label: str):
    for key, val in SOURCE_STYLES.items():
        if key in label:
            return val
    return ("#f5f5f5","#424242","📄")


def build_news_html(items: list[dict]) -> str:
    cards = []
    for item in items:
        no = item.get("no","")
        if no == 99:
            summary = item.get("insight","")
            cards.append(f'''
<div style="background:linear-gradient(135deg,#fff8e1,#fffde7);border:1px solid #ffe082;
  border-radius:10px;padding:14px 18px;margin-top:4px">
  <span style="font-weight:700;color:#f57f17;font-size:13px">📊 今日行业总结</span>
  <p style="margin:6px 0 0;color:#5d4037;font-size:13px;line-height:1.7">{summary}</p>
</div>''')
            continue

        title    = item.get("title","")
        source_l = item.get("source_label","其他")
        source_u = item.get("source_url","")
        heat     = item.get("heat","—")
        gameplay = item.get("gameplay","—")
        dynamics = item.get("dynamics","—")
        insight  = item.get("insight","—")
        bg, tc, icon = get_source_style(source_l)

        badge = f'<span style="background:{bg};color:{tc};border:1px solid {tc}30;border-radius:12px;padding:2px 9px;font-size:11px;font-weight:500;white-space:nowrap">{icon} {source_l}</span>'

        if source_u:
            title_html = f'<a href="{source_u}" target="_blank" style="color:#1a1a1a;text-decoration:none;border-bottom:1px dashed #aaa">{title}</a>'
        else:
            title_html = title

        cards.append(f'''
<div style="background:#fff;border:1px solid #e8e8e8;border-radius:10px;margin-bottom:14px;
  box-shadow:0 1px 4px rgba(0,0,0,.04);overflow:hidden">
  <div style="padding:11px 16px 10px;border-bottom:1px solid #f5f5f5;display:flex;
    align-items:flex-start;gap:10px;flex-wrap:wrap">
    <span style="background:#c0392b;color:#fff;border-radius:50%;min-width:22px;height:22px;
      display:inline-flex;align-items:center;justify-content:center;font-size:11px;
      font-weight:700;flex-shrink:0;margin-top:1px">{no}</span>
    <span style="font-size:14px;font-weight:700;color:#1a1a1a;flex:1;line-height:1.5">{title_html}</span>
    {badge}
  </div>
  <div style="padding:10px 16px 12px">
    <table style="width:100%;border-collapse:collapse;font-size:13px">
      <tr><td style="width:68px;color:#999;padding:3px 0;vertical-align:top">📈 热度</td>
          <td style="color:#444;padding:3px 0 3px 8px;line-height:1.6">{heat}</td></tr>
      <tr><td style="color:#999;padding:3px 0;vertical-align:top">🎮 玩法</td>
          <td style="color:#444;padding:3px 0 3px 8px;line-height:1.6">{gameplay}</td></tr>
      <tr><td style="color:#999;padding:3px 0;vertical-align:top">🔔 动态</td>
          <td style="color:#333;padding:3px 0 3px 8px;line-height:1.6">{dynamics}</td></tr>
      <tr><td style="color:#999;padding:3px 0;vertical-align:top">💡 参考</td>
          <td style="color:#777;padding:3px 0 3px 8px;line-height:1.6;font-style:italic">{insight}</td></tr>
    </table>
  </div>
</div>''')
    return "\n".join(cards)


def build_taptap_table_html(table_items: list[dict]) -> str:
    if not table_items:
        return '<p style="color:#888;font-size:13px;padding:12px 0">今日TapTap数据暂未获取，请明日查看。</p>'

    plat_style = {
        "安卓":("#e8f5e9","#2e7d32"),
        "iOS": ("#e3f2fd","#1565c0"),
        "双端":("#f3e5f5","#6a1b9a"),
    }

    rows = []
    for i, item in enumerate(table_items[:10]):
        plat = item.get("platform","安卓")
        pc, ptc = plat_style.get(plat, ("#f5f5f5","#444"))
        rank  = item.get("rank","—")
        name  = item.get("name","—")
        url   = item.get("url","")
        gp    = item.get("gameplay","—")
        theme = item.get("theme","—")
        art   = item.get("art_style","—")
        note  = item.get("note","—")
        is_ai = "AI补充" in rank or "AI" in str(item.get("note",""))

        name_cell = (f'<a href="{url}" target="_blank" style="color:#c0392b;font-weight:600;text-decoration:none">{name}</a>'
                     if url else f'<strong style="color:#333">{name}</strong>')

        row_bg = "#fafafa" if i % 2 == 0 else "#fff"
        ai_mark = ' <span style="font-size:10px;color:#999;font-style:italic">(AI补充)</span>' if is_ai else ""

        rows.append(f'''
<tr style="background:{row_bg};border-bottom:1px solid #f0f0f0">
  <td style="padding:10px 10px;text-align:center;width:52px">
    <span style="background:{pc};color:{ptc};border-radius:4px;padding:2px 7px;font-size:11px;font-weight:600">{plat}</span>
  </td>
  <td style="padding:10px 8px;font-size:11px;color:#888;width:120px;line-height:1.4">{rank}{ai_mark}</td>
  <td style="padding:10px 12px;font-size:13px;min-width:90px">{name_cell}</td>
  <td style="padding:10px 8px;font-size:12px;color:#444;min-width:100px">{gp}</td>
  <td style="padding:10px 8px;font-size:12px;color:#666;white-space:nowrap">{theme}</td>
  <td style="padding:10px 8px;font-size:12px;color:#666;white-space:nowrap">{art}</td>
  <td style="padding:10px 12px;font-size:12px;color:#888;font-style:italic">{note}</td>
</tr>''')

    return f'''
<div style="overflow-x:auto;border-radius:10px;border:1px solid #e4e4e4;box-shadow:0 1px 6px rgba(0,0,0,.04)">
<table style="width:100%;border-collapse:collapse;background:#fff;font-family:inherit">
  <thead>
    <tr style="background:linear-gradient(135deg,#f7f7f7,#f0f0f0);border-bottom:2px solid #e0e0e0">
      <th style="padding:10px;font-size:12px;font-weight:600;color:#555;text-align:center">平台</th>
      <th style="padding:10px 8px;font-size:12px;font-weight:600;color:#555;text-align:left">榜单</th>
      <th style="padding:10px 12px;font-size:12px;font-weight:600;color:#555;text-align:left">产品名</th>
      <th style="padding:10px 8px;font-size:12px;font-weight:600;color:#555;text-align:left">玩法</th>
      <th style="padding:10px 8px;font-size:12px;font-weight:600;color:#555;text-align:left">题材</th>
      <th style="padding:10px 8px;font-size:12px;font-weight:600;color:#555;text-align:left">画风</th>
      <th style="padding:10px 12px;font-size:12px;font-weight:600;color:#555;text-align:left">关注理由</th>
    </tr>
  </thead>
  <tbody>{''.join(rows)}</tbody>
</table>
</div>
<p style="font-size:11px;color:#bbb;margin:8px 0 0;text-align:right">
  * 数据来源：TapTap安卓新品榜 &nbsp;|&nbsp; 
  <a href="https://www.taptap.cn/top/new-android" target="_blank" style="color:#bbb">查看完整榜单 →</a>
</p>'''


def md_to_html_fusion(text: str) -> str:
    """缝合创想 Markdown → HTML"""
    lines = text.split("\n"); out = []
    for line in lines:
        line = line.rstrip()
        if line.startswith("### "):
            out.append(f'<h4 style="color:#8e1a0e;margin:22px 0 8px;font-size:15px;font-weight:700">{line[4:]}</h4>')
        elif line == "---":
            out.append('<hr style="border:none;border-top:2px dashed #f0d0c8;margin:18px 0">')
        elif re.match(r"^🎣\s+\*\*(.+?)\*\*：(.*)$", line):
            m = re.match(r"^🎣\s+\*\*(.+?)\*\*：(.*)$", line)
            out.append(f'<div style="display:flex;gap:10px;margin:8px 0;align-items:flex-start"><span style="background:#e65100;color:#fff;border-radius:6px;padding:2px 10px;font-size:11px;font-weight:600;white-space:nowrap;flex-shrink:0;margin-top:2px">🎣 {m.group(1)}</span><span style="font-size:13px;color:#333;line-height:1.7">{m.group(2)}</span></div>')
        elif re.match(r"^🌉\s+\*\*(.+?)\*\*：(.*)$", line):
            m = re.match(r"^🌉\s+\*\*(.+?)\*\*：(.*)$", line)
            out.append(f'<div style="display:flex;gap:10px;margin:8px 0;align-items:flex-start"><span style="background:#1565c0;color:#fff;border-radius:6px;padding:2px 10px;font-size:11px;font-weight:600;white-space:nowrap;flex-shrink:0;margin-top:2px">🌉 {m.group(1)}</span><span style="font-size:13px;color:#333;line-height:1.7">{m.group(2)}</span></div>')
        elif re.match(r"^⚔️\s+\*\*(.+?)\*\*：(.*)$", line):
            m = re.match(r"^⚔️\s+\*\*(.+?)\*\*：(.*)$", line)
            out.append(f'<div style="display:flex;gap:10px;margin:8px 0;align-items:flex-start"><span style="background:#1b5e20;color:#fff;border-radius:6px;padding:2px 10px;font-size:11px;font-weight:600;white-space:nowrap;flex-shrink:0;margin-top:2px">⚔️ {m.group(1)}</span><span style="font-size:13px;color:#333;line-height:1.7">{m.group(2)}</span></div>')
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
            out.append("<div style='height:5px'></div>")
        else:
            line = re.sub(r"\*\*(.+?)\*\*", r'<strong style="color:#2c3e50">\1</strong>', line)
            out.append(f'<p style="margin:4px 0;font-size:13px;line-height:1.7;color:#333">{line}</p>')
    html = "\n".join(out)
    html = re.sub(r"((?:<li[^>]*>.*?</li>\n?)+)",
                  lambda m: f'<ul style="padding-left:20px;margin:6px 0">{m.group(0)}</ul>', html)
    return html


def build_html(news_items: list[dict], taptap_table: list[dict], fusion_text: str) -> str:
    news_count  = len([i for i in news_items if i.get("no",0) != 99])
    news_html   = build_news_html(news_items)
    taptap_html = build_taptap_table_html(taptap_table)
    fusion_html = md_to_html_fusion(fusion_text)

    # 来源图例
    legend_items = "".join([
        f'<span style="background:{bg};color:{tc};border:1px solid {tc}25;border-radius:12px;padding:2px 9px;font-size:11px">{icon} {name}</span>'
        for name,(bg,tc,icon) in SOURCE_STYLES.items() if name not in ("系统",)
    ])

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{TODAY_LABEL} 手游&小游戏资讯日报</title>
<style>
  *{{box-sizing:border-box}}
  body{{font-family:'PingFang SC','Helvetica Neue','Microsoft YaHei',Arial,sans-serif;
    background:#eff1f5;margin:0;padding:24px 16px;color:#333;font-size:14px;line-height:1.7}}
  .wrap{{max-width:830px;margin:0 auto}}
  .card{{background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 2px 16px rgba(0,0,0,.08);margin-bottom:16px}}
  .header{{background:linear-gradient(135deg,#c0392b 0%,#7b1010 100%);color:#fff;padding:28px 34px 24px}}
  .header h1{{margin:0 0 4px;font-size:22px;letter-spacing:.3px;font-weight:700}}
  .header .sub{{opacity:.88;font-size:13px;margin:0 0 12px}}
  .meta-row{{display:flex;gap:7px;flex-wrap:wrap}}
  .mbadge{{background:rgba(255,255,255,.15);border:1px solid rgba(255,255,255,.22);
    border-radius:20px;padding:3px 12px;font-size:11px;display:inline-block}}
  .toc{{padding:13px 34px;border-bottom:1px solid #f0f0f0;display:flex;gap:0;flex-wrap:wrap}}
  .toc-item{{display:flex;align-items:center;gap:6px;padding:3px 16px;font-size:12px;color:#666;
    border-right:1px solid #eee}}
  .toc-item:first-child{{padding-left:0}}
  .toc-item:last-child{{border-right:none}}
  .toc-n{{background:#c0392b;color:#fff;border-radius:50%;width:17px;height:17px;
    display:inline-flex;align-items:center;justify-content:center;font-size:10px;font-weight:700}}
  .sec{{padding:26px 34px;border-bottom:1px solid #f5f5f5}}
  .sec:last-child{{border-bottom:none}}
  .sec-hd{{display:flex;align-items:center;gap:10px;margin-bottom:18px;flex-wrap:wrap}}
  .sec-num{{background:linear-gradient(135deg,#c0392b,#8e1a0e);color:#fff;border-radius:7px;
    padding:3px 12px;font-size:13px;font-weight:700;white-space:nowrap}}
  .sec-title{{font-size:16px;font-weight:700;color:#1a1a1a}}
  .sec-desc{{font-size:11px;color:#bbb;margin-left:auto}}
  .legend{{display:flex;gap:5px;flex-wrap:wrap;margin-bottom:16px;
    padding:10px 12px;background:#fafafa;border-radius:8px;border:1px solid #f0f0f0}}
  .fusion-intro{{background:linear-gradient(135deg,#fff5f5,#fff8f0);border:1px solid #f5c6c6;
    border-radius:10px;padding:13px 16px;margin-bottom:14px;font-size:13px;color:#7b1010;line-height:1.7}}
  .footer{{background:#2c3e50;color:#7a8fa0;text-align:center;padding:18px;font-size:11px;line-height:1.9}}
  a{{color:#c0392b;text-decoration:none}}
  a:hover{{text-decoration:underline}}
</style>
</head>
<body>
<div class="wrap">
<div class="card">

  <!-- Header -->
  <div class="header">
    <h1>🃏 手游 & 小游戏资讯日报</h1>
    <p class="sub">{TODAY_LABEL} · 三国杀名将传战略参考 · 数据时效：近24小时</p>
    <div class="meta-row">
      <span class="mbadge">📰 竞核 · DataEye · 游戏葡萄 · 游戏先知 · 广大大 · 手游圈圈 · 游戏茶馆 · SensorTower</span>
      <span class="mbadge">🤖 DeepSeek AI</span>
      <span class="mbadge">📌 {PUBLISHER}</span>
    </div>
  </div>

  <!-- 目录 -->
  <div class="toc">
    <div class="toc-item"><span class="toc-n">①</span> 行业资讯（{news_count}条）</div>
    <div class="toc-item"><span class="toc-n">②</span> TapTap 安卓新品观察（10款）</div>
    <div class="toc-item"><span class="toc-n">③</span> 名将like 缝合创想</div>
  </div>

  <!-- ① 行业资讯 -->
  <div class="sec">
    <div class="sec-hd">
      <span class="sec-num">① 行业资讯</span>
      <span class="sec-title">手游 & 小游戏 热点</span>
      <span class="sec-desc">近24小时 · 自动排除超头部产品</span>
    </div>
    <div class="legend">{legend_items}</div>
    {news_html}
  </div>

  <!-- ② TapTap新品 -->
  <div class="sec">
    <div class="sec-hd">
      <span class="sec-num">② TapTap 新品观察</span>
      <span class="sec-title">安卓新品榜 精选</span>
      <span class="sec-desc">题材/玩法/画风有新意 · 10款</span>
    </div>
    {taptap_html}
  </div>

  <!-- ③ 缝合创想 -->
  <div class="sec">
    <div class="sec-hd">
      <span class="sec-num">③ 缝合创想</span>
      <span class="sec-title">名将like 前期钩子设想</span>
      <span class="sec-desc">来源于本期资讯产品</span>
    </div>
    <div class="fusion-intro">
      💡 从本期资讯产品精选 2–3 款，探索三国杀名将传前期轻量钩子副玩法缝合方向
      （D1冷启动 → D2–D7过渡 → D7+名将like全面介入）
    </div>
    <div style="background:#fff8f5;border:1px solid #f0d5c8;border-radius:10px;padding:20px">
      {fusion_html}
    </div>
  </div>

  <!-- Footer -->
  <div class="footer">
    {TODAY_LABEL} &nbsp;·&nbsp; 手游&小游戏资讯日报 &nbsp;·&nbsp; {PUBLISHER}<br>
    资讯来源：竞核 · DataEye · 游戏葡萄 · 游戏先知 · 广大大 · 手游圈圈 · 游戏茶馆 · SensorTower · DuckDuckGo搜索<br>
    <span style="color:#4a6070">AI分析：DeepSeek &nbsp;|&nbsp; 内部参考，请勿外传</span>
  </div>

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
    msg.attach(MIMEText(html,"html","utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com",465) as s:
        s.login(sender,password)
        s.sendmail(sender,RECIPIENTS,msg.as_string())
    print(f"✅ 邮件已发送至：{RECIPIENTS}")


# ============================================================
# 主流程
# ============================================================
def main():
    print(f"=== {TODAY} 日报开始生成（v5.0）===")

    print("📰 [1/2] 采集游戏媒体资讯（竞核/DataEye/游戏葡萄/游戏先知/广大大/手游圈圈/游戏茶馆）...")
    media_news = fetch_game_media_news()

    print("🎮 [2/2] 采集TapTap安卓新品榜...")
    taptap_data = fetch_taptap_new_android()

    print("🤖 [AI-1] 整合生成结构化资讯JSON...")
    news_items = analyze_news_to_json(media_news)
    print(f"    生成 {len([i for i in news_items if i.get('no',0)!=99])} 条资讯")

    print("🤖 [AI-2] 生成TapTap新品表格（10款）...")
    taptap_table = analyze_taptap_table(taptap_data)

    print("🤖 [AI-3] 生成名将like缝合创想...")
    fusion_text = generate_fusion_ideas(news_items)

    print("📝 构建HTML并发送邮件...")
    html = build_html(news_items, taptap_table, fusion_text)
    send_email(html)

    print("=== 日报完成 ✅ ===")


if __name__ == "__main__":
    main()
