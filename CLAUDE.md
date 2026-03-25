# 三国杀名将传 · 卡牌手游 & 小游戏资讯日报

## 项目简介

本仓库用于三国杀名将传产品的每日自动化资讯监控与战略参考日报生成。

每天北京时间 09:00 自动运行，内容包含：

1. **竞品动态追踪**（L1–L4 分级监控）
   - L1 核心竞品：西游笔绘西行
   - L2 直接竞品：阴阳师、伊瑟、第七史诗、忘川风华录、三国志幻想大陆2
   - L3 关联赛道：龙族卡塞尔之门、剑与远征·启程、崩坏·星穹铁道
   - L4 细分赛道：保卫向日葵、永远的蔚蓝星球、遗弃之地

2. **热门小游戏资讯**（微信/抖音小程序，热度为先，不限品类）

3. **Steam 独立游戏热门**（热度为先，不限品类）

4. **名将like 前期钩子缝合创想**（每日从小游戏/Steam中挑选≥2款，给出玩法融合方案）

## 文件结构

```
.
├── .github/workflows/daily-report.yml   # GitHub Actions 定时任务
├── scripts/daily_report.py              # 主脚本
├── requirements.txt                     # Python 依赖
└── CLAUDE.md                            # 本说明文件
```

## 需要配置的 GitHub Secrets

| Secret 名称 | 说明 |
|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek API Key，platform.deepseek.com 获取 |
| `GMAIL_SENDER_EMAIL` | 发件 Gmail 地址 |
| `GMAIL_APP_PASSWORD` | Gmail 应用专用密码（16位，非登录密码） |
| `REPORT_RECIPIENT_EMAIL` | 收件人邮箱，多人用英文逗号分隔，无空格 |

> ⚠️ 本仓库**不需要** YouTube API Key，数据采集全部通过 DuckDuckGo 完成。

## 快速部署检查清单

- [ ] 新建 GitHub 私有仓库
- [ ] 上传四个文件（yml 需放在 `.github/workflows/` 目录）
- [ ] 配置 4 个 GitHub Secrets
- [ ] 手动触发 Run workflow 测试
- [ ] 确认收到邮件，内容格式正常

## 费用参考

| 服务 | 每次预估 | 月度预估 |
|---|---|---|
| DeepSeek API | ¥0.1～0.4 | ¥3～12 |
| GitHub Actions | 约3～5分钟 | 免费额度充足 |
| DuckDuckGo | 免费 | 免费 |
| Gmail SMTP | 免费 | 免费 |

---
*© 游卡网络战略分析组 · 内部使用*
