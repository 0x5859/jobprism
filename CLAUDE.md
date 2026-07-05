# JobVisualizer — Claude 项目指引

## 必读

**每次开始工作前先读 [ROADMAP.md](ROADMAP.md)**。它是整改工作的 single source of truth，包含：
- 6 个产品目标及其验收标准
- 所有待办任务（按 P0/P1/P2 分组，带唯一 ID）
- 每个任务的问题描述、要做的事、相关文件、验收标准
- 进度日志

## 工作流

1. 接到新诉求 → 先判断是 ROADMAP.md 中已有任务还是新问题
2. 是已有任务 → 改状态为 `[~]` 进行中 → 追加进度日志
3. 是新问题 → 追加到对应优先级（P0/P1/P2）下，用下一个可用 ID
4. 完工后 → 改状态为 `[x]` → 追加日志 → commit message 格式：`<type>(<任务ID>): <简述>`，如 `fix(I-1): commit crawler script to git`

## 项目背景一句话

Python ETL pipeline + 原生 ES 模块前端。目标：**从技能反向找岗位**的可视化招聘图谱，部署到 GitHub Pages，支持中英文，图谱效果类 Obsidian。

## 关键事实（避免重复探索）

- 核心爬虫 `includes/company_site_crawler_bundle/company_site_crawler.py` **未提交 git**（见 ROADMAP I-1）
- `.github/` 目录不存在，Pages workflow 未实现（见 ROADMAP I-5）
- heuristic.py 全英文正则，中文数据匹配率 0（见 ROADMAP I-4）
- 拖拽被主动关闭（`autoungrabify: true`，见 ROADMAP S-5）
- i18n 零实现（见 ROADMAP S-1）
- 审计详情见 git log 和 ROADMAP 各任务的"问题"段

## 禁止事项

- 不要另开追踪文档（TODO.md、TASKS.md 等）。所有任务追踪统一在 ROADMAP.md
- 不要在 commit message 里粘贴长篇任务描述，用任务 ID 引用
- 不要跳过任务状态更新。改代码必须同步改 ROADMAP.md
