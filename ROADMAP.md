# JobVisualizer 整改路线图

> **本文件是整改工作的 single source of truth**。每次开始工作前先读它，每次完成任务后更新状态，不要在别处重复记录。
>
> 状态图标：`[ ]` 未开始 · `[~]` 进行中 · `[x]` 已完成 · `[!]` 被阻塞 · `[-]` 已放弃
>
> 更新规则：改状态 → 在"进度日志"追加一行 → commit 带任务 ID（如 `fix(I-1): commit crawler script`）。

---

## 产品目标（6 条）

| ID | 目标 | 当前状态 | 验收标准 |
|---|---|---|---|
| G1 | GitHub Pages 部署 | **基本完成** | pages.yml 三触发（push/每日 cron/手动），生产构建 `build_site.sh` 已本地验证；待 push + Pages source 切 GitHub Actions |
| G2 | 技能→岗位反向浏览 | 半吊子 | 首屏有"从技能找工作"引导；skill→company→job 视觉贯穿 |
| G3 | 自动爬取公司招聘 | **基本完成** | 13 家公司公开 API 每日 CI 自动抓（D-1 双轨制）；中文站走本地快照；live 增量/更多中文源留 S-9/L 系 |
| G4 | 中英文 i18n | 未做 | 顶部 zh/en 切换；中英文案 100% 覆盖；中文数据可搜索过滤 |
| G5 | Obsidian 式图谱 | **基本完成** | 力导向持续模拟（rAF 驱动）；Sigma/Cytoscape 双端拖拽启用；位置保留平滑过渡 |
| G6 | UI 美观 | **基本完成** | 中文字体 Noto Serif SC fallback；CSS 变量与 TYPE_THEME 打通；占位文案全面替换 |

---

## P0 · 立即修（1-2 天内）

### [x] I-1 · 把爬虫脚本提交到 git
- **问题**：`includes/company_site_crawler_bundle/company_site_crawler.py`（49KB 核心爬虫）**从未提交 git**，`git ls-files` 只有 82 个文件，整个 `includes/` 目录是空的。clone 下来 `--source tencent_campus` 立刻 `FileNotFoundError`。
- **要做**：
  1. 确认 `includes/company_site_crawler_bundle/` 下哪些是源码（.py、requirements.txt、tests、README）哪些是产物（.venv、__pycache__、logs）
  2. 改 `.gitignore` 只忽略产物
  3. `git add` 源码部分并提交
- **相关文件**：`includes/company_site_crawler_bundle/`、`.gitignore`
- **验收**：`git ls-files includes/ | wc -l` > 0；CI 上 `git clone` 后能 `import company_site_crawler`

### [x] I-2 · 清理 166MB `.venv` 并补环境安装文档
- **问题**：`includes/company_site_crawler_bundle/.venv` 占 166MB，.gitignore 在挡，但本地污染仓库体积；没有 `playwright install` 步骤文档，新环境跑不起来
- **要做**：
  1. 删除本地 `.venv`（`rm -rf includes/company_site_crawler_bundle/.venv`）
  2. 确认 `requirements.txt` 有 playwright 依赖
  3. 在 `includes/company_site_crawler_bundle/README.md` 写清：`python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && playwright install chromium`
- **相关文件**：`includes/company_site_crawler_bundle/README.md`、`includes/company_site_crawler_bundle/requirements.txt`
- **验收**：在干净机器上按 README 操作后 `python company_site_crawler.py --help` 能跑

### [x] I-3 · 补齐公司别名（腾讯被归到 `company:unknown`）
- **问题**：[dist/data/companies.json:45-51](dist/data/companies.json) "腾讯" 被归到 `company:unknown`，因为 [config/company_aliases.json](config/company_aliases.json) 只有字节跳动条目
- **要做**：在 `company_aliases.json` 添加腾讯、Tencent、TikTok、ByteDance、美团、Meituan、阿里、Alibaba、百度、Baidu 等常见映射
- **相关文件**：`config/company_aliases.json`
- **验收**：重跑 pipeline 后 `companies.json` 没有 `company:unknown`；腾讯 job 正确归属到 `company:tencent`

### [x] I-4 · heuristic.py 支持中文
- **问题**：[providers/heuristic.py:11-33](apps/pipeline/providers/heuristic.py) 的 `SECTION_PATTERNS`/`ROLE_FAMILY_PATTERNS`/`SENIORITY_PATTERNS` 全英文正则，字节/腾讯中文岗位 skill 匹配率 = 0（`dist/data/skill_jobs.json` 里没有任何 bytedance/tencent job）
- **要做**：
  1. 加中文 section pattern：`职位要求|岗位职责|任职资格|加分项|优先考虑|工作职责`
  2. 加中文技能词表种子：`Java|Python|C\+\+|后端|前端|Android|iOS|大模型|LLM|推荐系统|搜索|机器学习|深度学习|数据分析|算法|测试`
  3. 加中文 seniority：`应届|校招|实习生|初级|中级|高级|资深|专家`
  4. role_family 中文：`开发|工程师|研究员|分析师|产品经理|测试|运维`
- **相关文件**：`apps/pipeline/providers/heuristic.py`、`config/skill_dictionary.json`（如存在）
- **验收**：跑完 pipeline，`skill_jobs.json` 里字节/腾讯 job 至少能命中 2 个 skill

### [x] I-5 · 最小 GitHub Pages workflow
- **问题**：`.github/` 目录不存在，[docs/deploy-github-pages.md](docs/deploy-github-pages.md) 声称的 workflow 根本没有
- **要做**：创建 `.github/workflows/pages.yml`，至少完成：
  1. 在 push main 时触发
  2. 安装 Python + 依赖 + playwright
  3. 跑 `./run_demo.sh`（或等价的 pipeline 命令）产出 `dist/`
  4. 用 `actions/upload-pages-artifact` + `actions/deploy-pages` 发布
- **相关文件**：`.github/workflows/pages.yml`（新建）
- **验收**：push main 后 Actions 跑通，Pages 站点可访问

### [x] I-6 · 清理/重生成 dist/data 污染数据
- **问题**：`dist/data/jobs.json` 里字节某 job `title="校招"`、`location_text` 是 2000+ 字文案、`responsibilities=qualifications` 同段粘贴两次。放到 demo 站上第一印象崩盘
- **要做**：I-4 修完后重跑 pipeline 重生数据；或先把 `dist/` 从追踪里移除，改 CI 产出
- **相关文件**：`dist/data/*.json`
- **验收**：抽查 5 条中文 job，title/responsibilities/qualifications 结构化正确

---

## P0.5 · UI 全面重做（用户验收不通过，需改设计语言）

### [x] R-1 · 深色现代设计语言（扔掉米色/衬线，切换到 dark + Inter + glass panel）
- **问题**：用户审阅 G5/G6 成果后直言"太丑了"，不接受沿用原有米色衬线风格。
- **要做**：
  1. `styles.css` 全量重写：深色底（#0b1117 系）+ 玻璃态浮层面板 + Inter 无衬线字体
  2. 节点颜色改为深色背景下高对比度（明蓝 / 翠绿 / 珊瑚橙）
  3. 大字号 display 字体做标题（Inter 700，1.5rem+）
  4. 图谱作为主画布铺满视口，search/detail rail 做成浮动玻璃面板
  5. Cytoscape 和 Sigma 的 nodeReducer、label 颜色、边颜色都要换成深底下好看的调色
  6. 背景加细格子/径向渐变做空间感
- **保留**：所有 ID、核心类名、JS 逻辑（因为 app.js 依赖它们）
- **相关文件**：`styles.css`、`index.html`、`graph-renderers.js`
- **验收**：screenshot 对比：① 不再是米色衬线 ② 节点比之前醒目 ③ 中文英文字号一致不崩 ④ 有清晰的视觉层级（hero 标题 > body > 次级文案）

## P0.9 · 上线数据链路（HTML+JS 静态站 + 每日自动抓新数据）

### [x] D-1 · 生产数据双轨制：live API + 中文快照
- **需求**（2026-07-06 用户提出）：html+js、GitHub Pages 上线、"积极抓取最新的互联网数据"
- **架构**：
  - **轨道 1 · CI 实时抓**：greenhouse/lever/ashby 公开 JSON API（纯 stdlib urllib，无 Playwright、无反爬风险）。13 家公司：Anthropic/OpenAI/Databricks/Scale AI/Mistral AI（AI 包）+ Stripe/Cloudflare/Figma/Airbnb/Duolingo/Palantir/Notion/Linear（多元科技包），每源 `max_jobs: 40` 截断
  - **轨道 2 · 中文快照**：腾讯/字节校招数据由本地 Playwright 爬虫产出，JSONL 提交到 `data/snapshots/`，CI 经 `--import-input` 合并
  - **入口**：`scripts/build_site.sh`（带 `--continue-on-error`，单源挂了不炸整个 build）；`source-config.ci.json` 为生产源配置
  - **调度**：pages.yml 三触发 push main / cron 每日 UTC 00:00（北京 08:00）/ 手动 dispatch
- **过程中修的 bug**：
  1. Ashby API 403 拒绝 `Python-urllib/*` UA → `io_utils.fetch_json` 统一诚实 UA `JobVisualizer/1.0`，三个 adapter 共用
  2. Lever `createdAt` 是毫秒时间戳 int，直塞 `posted_at` 违反 raw_job schema（string|null）→ `_epoch_to_iso` 转换
  3. Netflix/Plaid 的 lever 板返回空数组（HTTP 200 但 `[]`）→ 换成 Mistral AI（177 岗）/ Palantir（275 岗），全部实测非空
  4. `graph.full.json` 膨胀到 8.4MB：① job 图节点嵌完整 payload（最大单节点 36KB）→ 瘦身到 8 个字段；② SIMILAR_TO 边 6660 条（小词表下大量 Jaccard=1.0 对）→ 每 job 保留 top-8，边数 1938，文件 3.0MB
  5. API 源加通用 `max_jobs` 截断（source_registry）
- **实测**：本地跑 `build_site.sh` → 500 jobs / 15 companies / 35 skills；13 家公司别名映射齐（Mistral AI/Palantir 等显示名正确）；前端 1440 视口验证 Python → 113 jobs / 13 companies 反向链正常；19 个测试全绿
- **验收余项**：push 到 GitHub 后需在 Settings → Pages 把 source 切到 "GitHub Actions"（首次一次性操作）

### [x] R-2 · Observatory Minimal 重设计（2026-07-06 用户四点反馈）
- **用户反馈**：①界面丑，要现代极简 + 开源 Arial 类字体 ②要"二维宇宙交织网状结构" ③点排布成正方形，要随机 ④点击节点画面闪一下，要 Apple 官网般流畅 ⑤大量节点无标签不知是什么
- **设计语言**：近黑 `#060608` + Apple 系统色节点（蓝 #0a84ff / 绿 #30d158 / 橙 #ff9f0a / 紫 #bf5af2）+ 玻璃浮层。字体全换 OFL 开源：Instrument Sans（Arial 血统现代 grotesque）+ Noto Sans SC + IBM Plex Mono
- **交织网（②）**：`buildHierarchySimilarityLinks` 的相似度 link 原来只喂布局，现在同步输出为 `WOVEN` 渲染边（35 skill 出 64 条 hairline），静止态就是编织宇宙；WOVEN 边参与持续物理模拟（网会呼吸）
- **随机排布（③）**：`seedForceNode` 从黄金角螺旋（高密度下像方格）改为双 hash seeded 随机散布；`runHierarchyForceLayout` 关掉 anchor（0.024→0）只留碰撞+弱相似弹簧，散布不再收缩成圆盘
- **流畅过渡（④）**：三件事叠加 —— (a) app.js `cameraKey` 从 6 元组降为 `route.view`，同 lens 内所有变化走 canReuse morph；(b) 修 **冷路径顺序 bug**：`sigmaCameraKey = nextCameraKey` 在 `destroySigmaOverview()` 之前执行、被 destroy 置 null → canReuse 永远 false（闪烁真凶）；(c) 子节点 spawn 在父节点位置（`positionHierarchyChildren` 半径 0.2→0.05）+ `animateNodeGrowth` easeOutBack 从 0 长到目标尺寸 + `camera.animate(getNodeDisplayData(id), 650ms cubicInOut)` 镜头滑入
- **标签（⑤）**：labelRenderedSizeThreshold 11→2、labelDensity 0.1→1.2、labelGridCellSize 140→72、删掉 `hiddenLabel`（degree<4 job 藏标签）逻辑、nodeReducer 非活跃节点也保留 label
- **附带**：持续模拟加刚体回中（整体平移向原点 4%/帧，不变形防星团漂出画面）；节点尺寸从 orb 缩到 crisp dot（company 16→10）
- **实测**：35 skill + 64 WOVEN 边随机网；点击 Python → canvas/renderer 同一实例（无闪）→ 13 家蓝色公司 easeOutBack 长出 + 相机 0.9 ratio 滑入；拖拽正常且无 phantom click；19 测试全绿
- **遗留**：星团整体略偏画面左上（camera fit 微调）；相机 collapse 回根后 ratio 未完全复原 —— 下轮 UI 迭代处理

### [x] R-3 · 修点击失灵 + Obsidian 手感物理（2026-07-06 用户两点反馈）
- **反馈**：①展开一层后，点上一层其他节点/新层级节点全部无响应 ②节点达到稳态时间太长，要 Obsidian 般流畅
- **①根因（点击失灵）**：R-2 让 renderer 跨渲染复用后，冷路径绑定的 `clickNode` 监听器闭包着**第一次渲染的 renderToken**；app.js 回调里 `if (token !== state.renderToken) return;` 把第一次之后的所有点击静默吞掉（每次渲染 token 自增，旧闭包永远不匹配）
- **①修复**：graph-renderers 加模块级 `sigmaHandlers` 委托对象，每次 `renderSigmaOverview`（含复用路径）刷新 `onNodeSelect/onStageReset` 引用，监听器只调用委托；同时删掉 app.js 点击回调里的 token 守卫（点击处理从当前 route/path 状态取值，按渲染代际过滤本身就是错的）
- **②修复（物理调参）**：`startContinuousSimulation` — alpha 0.32→0.55（开局有劲）、alphaDecay 0.0035→0.015（能量期 ~0.5s 结束）、alphaTwinkle 0.05→0.006（静息近乎不动）、damping 0.93→0.68（果断制动，不再冰面滑行）、maxVelocity 0.022→0.06（大位移修正快速完成）、springStrength 显式 0.09、noise 减半
- **实测**：四步点击链（python→sql→anthropic 子层→sql 收起）全响应；连续切换 machine-learning→llm 均正常；稳态曲线 0.094→0.021（300ms）→0.0065 静息（原 0.013+，能量期原 >1.3s）

### [x] R-4 · 侧栏去繁杂：图谱成为唯一主角（2026-07-06 用户反馈"左右两侧很繁杂"）
- **左栏**：全高面板 → 顶部紧凑控制簇（135px：lens tabs + 搜索框），搜索结果变成簇内下拉（限高 52vh）；"SEARCH GRAPH"标签、lens 说明、summary 行、键盘提示全部 `hidden`（保留 DOM 供 app.js 写入 + 无障碍）
- **右栏**：静息态整体滑出视口（`data-state="welcome"` → translateX + opacity 0，460ms ease），选中节点才滑入；`renderDetail` 单点注入状态
- **场景提示**：feature-note 卡（kicker+title+copy+caption 四层）→ 底部中央一行 0.74rem 微光文字（复用 `#sceneSubtitle`，pointer-events none）
- **详情瘦身**：`.detail-group-head p` 的啰嗦 intro 用 clip 法视觉隐藏（读屏保留）；welcome 态的 meta 卡/建议路由随面板一起退场（图谱本身就是建议面）
- **修的坑**：`.search-box-label` 有显式 `display:block`，HTML `hidden` 属性被覆盖 → 加全局 `[hidden] { display: none !important; }`
- **实测**：静息态只有左上小簇 + 底部一行提示，宇宙独占视口；点 Python 右栏滑入（opacity 1）、再点收起滑出（opacity 0）；搜索下拉 6 结果正常；19 测试全绿

### [x] R-5 · 层级景深编码（2026-07-06 用户反馈"多层展开堆在一起，只靠颜色区分很费劲"）
- **方案**："景深"（depth-of-field）——用亮度/透明度编码层级距离，类型色保留（不丢"这是什么"的信息）：
  - 活跃链（展开路径祖先）：全亮 + 1.25x（空间中的面包屑）
  - 前沿层（最新展开的子层）+ 选中邻居：全亮 + 1.05x
  - 距前沿 1 层：50% alpha + 0.85x，保留标签
  - 距前沿 ≥2 层：26% alpha + 0.7x，标签让位（hover 即现）
  - 边同理分层：连接选中的 accent 蓝 0.6 > 前沿层级边 0.35 > 旧层级边 0.16 > 编织背景 0.035
- **数据管道**：snapshot 节点已有 `level`，adapter 给层级边补 `level` 标记；`createSigmaData` 透传 `level/onPath/maxLevel`；`sigmaViewState` 记录 `maxLevel + pathIds`；nodeReducer/edgeReducer 按 `depthGap = maxLevel - level` 分档
- **物理协同**：层级边在持续模拟中弹簧休息长度拉长（weight cap 0.45 → desired ≈0.3），子节点从父节点环开而不是叠在一起
- **实测**：skill:python → company:anthropic 三层展开（35+10+10 节点），三层亮度阶梯清晰：外围橙色 skill 网暗淡后退、蓝色公司环半亮带标签、绿色 job 前沿全亮、Python→Anthropic 活跃链放大；19 测试全绿

### [x] R-6 · 类型化粒子特效 + luminous 配色（2026-07-06 用户："加粒子特效 + 更好看配色 + 区分度还不够"）
- **设计**："类型即天体" —— 粒子签名成为色相/尺寸之外的**第三个区分维度**：
  - skill = 琥珀恒星（3 颗火花慢速环绕 + 呼吸脉动）
  - company = 青蓝行星（细椭圆环 + 1 颗卫星）
  - job = 薄荷卫星（1 颗快速小粒子）
  - location/role_family = 单颗慢速微粒
  - 新生节点展开时 6 颗径向迸发火花（650ms 生命周期），与 grow-in 动画同步
- **配色**：Apple 系统色 → luminous 五色系：skill #fbbf24 琥珀 / company #38bdf8 青 / job #34d399 薄荷 / location #a78bfa 紫罗兰 / role-family #fb7185 玫瑰。色相 + 明度双重分离，暗层 depth-dim 后类型仍可辨；accent 同步切青色
- **尺寸再拉开**：company 11 / skill 10 / job 6.5 —— 尺寸即类型信号
- **实现**：2D canvas 覆盖层（`.particle-layer`，pointer-events none，z-index 4）独立 rAF；预渲染 radial-gradient sprite 按色缓存；`graphToViewport` 每帧同步相机；强度跟随景深分级（选中 1.0 → path 0.85 → 前沿 0.7 → gap1 0.28 → gap2+ 关闭）；>260 节点自动只画高亮层；`prefers-reduced-motion` 直接不建层
- **实测**：粒子层 2880x1800@2x、166 FPS 无性能损耗；选中节点旁 984 个发光像素、300ms 间 613 像素动态变化（环+卫星实际在转）；19 测试全绿

## P1 · 短期补（1-2 周）

### [ ] S-1 · i18n 基础设施
- **问题**：`index.html:2` 硬编码 `lang="en"`；所有 UI 文案硬编码；数据中文 + UI 英文 = 精神分裂
- **要做**：
  1. 建 `apps/web/site/i18n/zh.json` + `en.json`，把所有硬编码文案抽出
  2. 写 `apps/web/site/i18n.js` 提供 `t(key)` 函数 + 自动语言检测（navigator.language）
  3. 顶部加 `zh/en` 切换按钮，选择持久化到 localStorage
- **相关文件**：`apps/web/site/index.html`、`app.js`、新建 `i18n/`
- **验收**：切换按钮点一下界面全部切换，无死角；刷新保留选择

### [x] S-2 · 中文字体与语言标签（部分：字体栈已加，lang 属性留给 S-1）
- **问题**：`lang="en"` + `Cormorant Garamond` 在中文节点上 fallback 到系统字体，中英混排割裂
- **要做**：
  1. `lang` 根据 i18n 选择动态设
  2. `@font-face` 或 Google Fonts 加载 Noto Serif SC（中）+ Cormorant Garamond（英）
  3. `font-family` 栈按语言优先级排
- **相关文件**：`apps/web/site/index.html`、`styles.css`
- **验收**：中英混排节点排版整齐，无字号跳变

### [ ] S-3 · 拆分 graph-adapter.js
- **问题**：[graph-adapter.js](apps/web/site/graph-adapter.js) 1324 行单文件，职责混杂
- **要做**：按职责拆成 4 个模块：
  - `graph/overview.js` — 概览图数据组装
  - `graph/hierarchy.js` — 层级展开/折叠
  - `graph/force-layout.js` — 物理布局
  - `graph/features.js` — 节点 feature/属性计算
- **相关文件**：`apps/web/site/graph-adapter.js` → `apps/web/site/graph/*.js`
- **验收**：每个模块 < 400 行；原功能回归无异常

### [x] S-4 · 持续力导向模拟（改：保留手写物理，改造为持续 rAF 循环）
- **问题**：[graph-adapter.js:748-812](apps/web/site/graph-adapter.js) 手写 `runForcePass`，参数硬编码魔数（repulsion=0.016, damping=0.87），难调优
- **要做**：换用 `d3-force` 的 `forceSimulation + forceManyBody + forceLink`，参数改由配置文件驱动
- **相关文件**：`apps/web/site/graph/force-layout.js`
- **验收**：节点松弛后布局自然；有持续的轻微漂浮感（Obsidian 效果）

### [x] S-5 · 开启节点拖拽
- **问题**：[graph-renderers.js:195](apps/web/site/graph-renderers.js) `autoungrabify: true` 主动关闭 Cytoscape 拖拽；Sigma 侧也没挂 drag handler
- **要做**：
  1. Cytoscape 去掉 `autoungrabify` 或改 false
  2. Sigma 端用 `graph.setNodeAttribute` + `mousedown/mousemove` 实现拖拽
  3. 拖拽后节点 fx/fy 固定，双击解锁
- **相关文件**：`apps/web/site/graph-renderers.js`
- **验收**：鼠标拖节点跟手；松开后物理继续作用于其他节点

### [ ] S-6 · 重构 company_site.py 的 subprocess 反模式
- **问题**：[company_site.py:60](apps/pipeline/adapters/company_site.py) 用 `subprocess.run` 调外部脚本，富化上下文传不进去
- **要做**：二选一：
  - **方案 A**（推荐）：把 crawler 逻辑作为模块 `import` 到 adapter，直接 `from company_site_crawler import crawl`
  - **方案 B**：彻底外置，crawler 独立项目，adapter 只消费 JSONL artifact
- **相关文件**：`apps/pipeline/adapters/company_site.py`、`includes/company_site_crawler_bundle/`
- **验收**：`--source tencent_campus` 跑通；富化可访问原始 HTML

### [ ] S-7 · 技能→岗位反向 onboarding
- **问题**：默认路由落 `#/skills` 但文案"Click a skill node to expand its neighborhood"和其他 lens 一样，反向叙事零引导
- **要做**：
  1. 首屏 hero：「输入你会的技能，找到匹配的岗位」+ 示意动画
  2. Skills lens 的 empty state 改专属文案
  3. 点技能节点 → 展开公司 → 再展开岗位，路径**贯穿式高亮**（边发光沿技能→公司→岗位动画流动）
- **相关文件**：`apps/web/site/app.js`、`index.html`、`styles.css`
- **验收**：首次访问有引导；路径高亮视觉明显

### [x] S-8 · 统一色彩系统
- **问题**：`styles.css` 的 CSS 变量（--company/--job/--skill）全是 `#000000`，graph-renderers.js 的 `TYPE_THEME` 是另一组蓝/青/橙 —— 两套系统并存没对齐
- **要做**：CSS 变量定义为真实色值，`TYPE_THEME` 从 `getComputedStyle` 读取
- **相关文件**：`apps/web/site/styles.css`、`graph-renderers.js`
- **验收**：改一处颜色两处联动

### [ ] S-9 · 爬虫字段解析修复
- **问题**：title 被提成 "校招"、`posted_at_raw` 是毫秒时间戳未解析、`description` 堆叠在 `location_text`
- **要做**：
  1. title 从详情页 H1/title 元素回退
  2. `posted_at_raw` 识别毫秒时间戳并转 ISO 8601
  3. 区分 `location_text` 和 `description_raw`
- **相关文件**：`includes/company_site_crawler_bundle/company_site_crawler.py`
- **验收**：抽查 10 条中文 job 字段结构正确

### [ ] S-10 · 拆分 app.js 巨石
- **问题**：[app.js](apps/web/site/app.js) 959 行全局脚本，`state` 全局可变
- **要做**：拆成 `routes.js`、`search.js`、`detail-pane.js`、`state.js`（简单的 subscribe 模式即可，不引入 React/Vue）
- **相关文件**：`apps/web/site/app.js` → 多文件
- **验收**：每文件 < 300 行；state 只能通过 dispatch 修改

---

## P2 · 长期重构（1 月+）

### [ ] L-1 · Enrichment LLM-first
- **问题**：heuristic 规则匹配脆弱；`openai_compatible.py` 存在但默认不启用
- **要做**：默认用 LLM，heuristic 降级为 fallback；CI 支持 secret 注入
- **相关文件**：`apps/pipeline/providers/openai_compatible.py`、`cli.py`
- **验收**：中文岗位 skill 命中率 ≥80%

### [ ] L-2 · Skill taxonomy 标准化
- **问题**：当前 skill 只有 10 条硬编码
- **要做**：引入 ESCO 或 Lightcast 开源词表作为种子，≥500 条技能
- **相关文件**：`config/skill_dictionary.json`

### [ ] L-3 · build_graph 性能
- **问题**：[build_graph.py:146-150](apps/pipeline/build_graph.py) 所有 job 两两 Jaccard，O(n²)
- **要做**：改倒排索引 + MinHash LSH
- **验收**：1 万 job 规模下 < 30 秒

### [ ] L-4 · Graph JSON 分 shard
- **问题**：`graph.full.json` 当前 171KB，真实数据量会到 50MB+
- **要做**：按 skill 拆 shard，前端按需加载

### [ ] L-5 · Vite/esbuild 打包
- **问题**：`build_site.py` 的 build 就是 `shutil.copytree`
- **要做**：真正 bundle + hash + base path 支持

### [ ] L-6 · 合规基线
- **要做**：LICENSE（MIT）+ `CRAWLING_POLICY.md` + robots 失败即停硬断言 + 邮箱/手机号敏感字段写入拦截
- **相关文件**：`LICENSE`、`docs/CRAWLING_POLICY.md`

### [ ] L-7 · 前端集成测试
- **问题**：前端 0 测试（除 rich-text sanitizer）
- **要做**：Playwright 覆盖"搜索技能→点节点→出现岗位"核心路径
- **相关文件**：`tests/e2e/` 新建

---

## 进度日志

格式：`YYYY-MM-DD · <任务ID> · <事件>`（事件示例：开始 / 完成 / 阻塞原因 / 改状态说明）

- 2026-04-25 · 初始化 · 基于 Opus 审计报告建立本路线图
- 2026-04-25 · S-2/S-4/S-5/S-8 · 完成 G5+G6 的前端整改一揽子：
  - CSS 变量 `--company/--job/--skill` 等填入真实色值（styles.css 顶层 + 底部 shell override 两处）
  - `--font-sans` 栈加入 Noto Serif SC / Songti SC / PingFang SC；index.html 预加载 Noto Serif SC
  - graph-renderers.js 的 TYPE_THEME 改为 `getTheme()`，从 CSS var 读取（`readCssColor`）
  - 新增 `runForceStep`（graph-adapter.js 导出单步版）+ `startContinuousSimulation` rAF 循环（≤400 节点）
  - Sigma 拖拽：`attachSigmaDragHandlers` 用 downNode + mouseCaptor 的 mousemovebody/mouseup；drag 触发 reheat + reanchor
  - Cytoscape 拖拽：`autoungrabify: false`、elements `grabbable: true`
  - `replaceSigmaGraphData` 保留原 x/y → 展开/折叠位置平滑过渡
  - app.js 四个 lens 的 `emptyTitle/emptyCopy` 全部替换；skills lens 强调"技能→岗位"反向叙事
  - 删除 `<p>Adaptive display block</p>` 占位；`renderWelcomeDetail` 用 `lens.emptyTitle`
  - 修复 sceneSubtitle 的"Click the same node again..."重复文案（graph-adapter.js `hierarchyExpandedCaption`）
  - 实测：Chinese 节点用 Noto Serif SC 渲染；合成 mousedown/move/up 能拖动 skill:python 到 (1.28, -0.45) 并停留
- 2026-04-25 · code review 跟进 · Opus reviewer 发现 1 blocker + 多个 medium，已修：
  - **Blocker**：app.js `hydrateGraphs` 移除无条件的 `destroyGraphRenderers()` — 原先每次 render 都销毁 sigma，`canReuse` 分支形同虚设，导致位置保留+平滑过渡在真实路径上失效
  - **Medium**：`inferTheme`（Cytoscape 本地图）原先硬编码颜色，绕过 CSS var；改为用 `getTheme` + `readCssColor(--TYPE-soft)`，打通色彩系统到本地图
  - **Medium**：styles.css 补齐 `--location-soft/--role-family-soft/--node-soft` 变量；底部 override 块加注释"仅覆盖形态，颜色请改顶部"防双写漂移
  - **Medium**：字体栈补 `Source Han Serif SC / STSong / Microsoft YaHei / Noto Sans CJK SC` 覆盖 Windows/Linux 场景
  - **Medium**：`startContinuousSimulation` 增加 `_snapshot()` 让 sim 状态跨 destroy+rebuild 保留（vx/vy/anchor/fixed），避免每次重建重播 heat-up
  - 实测：navigate python→machine-learning 8 个 skill 节点位置完全保留（diff 空）
- 2026-07-06 · D-1 · 生产数据链路落地（详见 P0.9 段）：13 家公司 live API + 中文快照双轨，每日 cron 自动重建部署；修 Ashby UA 403 / Lever 时间戳 schema / graph.full.json 8.4MB→3.0MB 瘦身；本地 build 实测 500 jobs / 15 companies；6 个语义 commit 把之前漂着的 1600+ 行 UI 工作与 P0 成果全部落库
- 2026-04-26 · I-1/I-2/I-5 · 派 Opus subagent 做完"clone 后能跑 + Pages 自动部署"打包：
  - **I-1**：6 个爬虫源文件（company_site_crawler.py 1395 行 / requirements.txt / sample-data 模板 / tests / README）入仓；`git ls-files includes/ | wc -l` 从 0 → 6
  - **I-2**：删 166MB `.venv` 并清掉 __pycache__/.DS_Store/TEST_RESULTS.txt；bundle README 含 4 行安装步骤 + `--help` 冒烟测试段
  - **I-5**：`.github/workflows/pages.yml` 通过 PyYAML safe_load 校验。Build job：setup-python 3.11 + 装根 requirements + `bash scripts/run_demo.sh` 产 dist。Deploy job：configure-pages@v5 / upload-pages-artifact@v3 / deploy-pages@v4 全套。permissions/concurrency/environment 齐全
  - **`.gitignore` 补全**：根级 + `includes/**/` 路径式，覆盖 `.venv/__pycache__/logs/.playwright-cli/output/TEST_RESULTS.txt`
  - **首部署提醒**：仓库 GitHub Settings → Pages source 必须切到 "GitHub Actions"（不是 deploy from a branch）；`docs/deploy-github-pages.md` 应同步更新（留给后续）
  - 注意 dist/ 当前 already-tracked 但 .gitignore 不会追溯撤销追踪；`scripts/run_demo.sh` 第 13 行 `rm -rf dist` 在 CI 上无害；如需彻底脱钩 `git rm -r --cached dist/`，留待 L-5
- 2026-04-26 · I-3/I-4/I-6 · 派 Opus subagent 做完"demo 数据翻身"打包：
  - **I-3**：`config/company_aliases.json` 从 1 条 → 40+ 别名；覆盖腾讯/字节/阿里/百度/美团/京东/小米/华为/网易/滴滴/快手 11 家中国大厂双语别名。重跑 pipeline 后 `dist/data/companies.json` 6 家公司全有规范 ID，**`company:unknown` 消失**
  - **I-4**：`heuristic.py` 全面中文化 —— SECTION 加 39 个中文锚点（required+responsibilities+qualifications+preferred）、ROLE_FAMILY 5 类全加中文 alternation、SENIORITY 6 个 level 全加中文映射 + 新增 `entry`（应届/校招/初级）；`config/skill_taxonomy.json` 10 → 44 条覆盖语言/后端/前端/移动/AI/数据/工具
  - **关键 bugfix（I-4）**：`_contains_term` 原用 `\b` 词边界对 CJK 永不匹配，改为 CJK-detect → 子串匹配；`_split_sentences` 加中文标点 `。！？；`
  - **I-4 测试**：`HeuristicChineseTests` 4 case（腾讯后端/字节校招/中文 SECTION/英文回归），全通过；整体 12/12 测试通过
  - **I-6**：`dist/` 已 .gitignore 不在 tracking 内 —— pipeline 通过 `tmp/company-sites-raw/{tencent,bytedance}-company-site.jsonl` 缓存重跑（init-db→import-raw→normalize→enrich→build-graph→build-site）。抽查 3 条 job：`job:tencent:101` 出 5 skills（Algorithm/Frontend/Java/Microservices PREFERS/Python）；`skill_jobs.json` 从 0 条字节/腾讯关联 → 20 字节 + 21 腾讯 skill→job 关联；enrichment 边 56
  - 提醒：S-9（爬虫字段解析）才能修 ByteDance `title="校招"` + 2000 字 location_text 的上游问题；`enrichment.skills` 在 jobs.json 仍是空数组（设计：技能反向索引在 `job_skills.json`/`skill_jobs.json`），前端要从反向索引读
- 2026-04-25 · R-1 第四轮 · 用户要"星空 + 真实星体 + 电子排斥"的物理感，4 个新问题：①隐形边框太小（拖远了挤一起）②连拖几下其他节点卡住 ③拖太远其他节点全挤在一起 ④拖拽僵硬不灵动。重做物理 + 星辰视觉：
  - **runForceStep 物理重写**：anchor 默认 0（曾 0.018，是"被绳子拽回去"的元凶）；center 0.0014（弱）；repulsion 0.016→0.022；collisionPadding 0.06→0.085；damping 0.87→0.93（更多惯性）；maxVelocity 0.03→0.032；**clampBound 1.2→5.0**（隐形墙从 ±1.2 扩到 ±5）；新增 `noise` 选项做布朗扰动
  - **持续模拟 alpha 永不归零**：原来衰到 0.006 就 stop，现在永停在 alphaTwinkle=0.05 + noise 跟 alpha 联动 `0.00009 + alpha * 0.00012` —— 节点永远有微抖动（twinkle），像真正的星
  - **拖拽惯性 kick**：`mousemovebody` 用低通滤波器跟踪 graph-space 速度（`smoothing=0.45`）；`endDrag` 时 `sim.kick(node, vx, vy)` 把终端速度交给物理引擎 + reheat 0.5 → 释放后节点像被弹的星体继续滑行
  - **解决"连拖卡住"**：phantom click 还会触发 hash 变化和 destroy/rebuild。前面已加 `sigmaLastDragEndAt` 时间戳吞掉，这一轮加 `kick()` 释放后系统不再"死寂"，避免低 alpha 锁死的二次失败
  - **解决"挤一起"**：clampBound 扩到 5（原 1.2 是把所有非 fixed 节点夹在小盒子里）+ 强化短程斥力 0.28（原 0.18）→ 即使被拖到远处也不会把其他节点压成一坨
  - **节点像星辰**：`.graph-stage canvas.sigma-nodes` 加叠层 drop-shadow 滤镜 —— 内核 3px 羊皮纸暖光 + 9px 古金外晕 + 18px lapis 远光晕。每个 sigma 节点圆都有真实的辉光halo，不再是"贴纸式"扁平圆点
  - 实测：sigma sim 状态 `isRunning: true, alpha 衰至 0.05+noise`、node.vx/vy 微小非零（twinkle 实锤）、`kick` API 接入；视觉验证：Python 聚焦时所有节点（包括 dim cinnabar）都带 halo glow，腾讯/Example Labs/Fallback Labs 的 lapis 蓝 orb 真有"星"的感觉

- 2026-04-25 · R-1 第三轮 · 用户仍嫌丑，4 点反馈：节点配色丑 / 选中后同级灰掉丢信息 / 连拖卡住 / 拖完自动点击。用 `/frontend-design` skill 指导重做美学方向：
  - **设计方向承诺"Nocturnal Field Atlas"（天文年鉴）**：深靛蓝 `#0a0a14` + 羊皮纸暖白 `#e8dfc4` + 胶片颗粒 noise overlay + 四层径向色晕（lapis/amethyst/cinnabar/antique gold）
  - **字体整体换**：Inter → Instrument Serif（italic display，代替 Inter 大号）+ Newsreader（正文衬线，italic 次级）+ JetBrains Mono（大写元数据标签）。避免 skill 提到的"generic AI slop"
  - **节点配色换珠宝色**：company #6b9bd2 lapis / job #8bab78 malachite / skill #d68c5a cinnabar / location #b094c9 amethyst / role-family #d4a857 antique gold。收敛饱和度、往 illuminated-manuscript ink 靠
  - **解决用户痛点 #2（同级节点灰掉）**：`nodeReducer` 非活跃节点原为 `rgba(130,142,158,0.22)` 灰色；新加 `withAlpha(hex, a)` helper 把节点本身类型色降到 42% alpha —— 现在能看到"这还是个 skill / 这还是个 company"，不丢视觉信息
  - **解决用户痛点 #4（拖完自动点击）**：新增模块级 `sigmaLastDragEndAt` 时间戳；`endDrag` 时记录；`clickNode` 和 `clickStage` 检测 260ms 内来自 drag 的 phantom click 并吞掉
  - **解决用户痛点 #3（连续拖拽卡住）**：根因其实是 phantom click 触发 `onNodeSelect` → hash change → destroy/rebuild renderer → 下一次 drag 前状态未就绪。修了 #4 连带修 #3
  - **面板风格改"字段笔记卡"**：扔掉 glass/blur（generic macOS Big Sur 味），改为 solid ink card + 1px 羊皮纸色细裱边 + inset 顶边高光；结果卡/chip-link 用左侧 2px 金色指示条 + hover 入边微动
  - **meta 改"标本卡"网格**：4 格 specimen-tag，细 rule 分隔，数字用 display serif（不是 mono）
  - 实测：fresh state 8 个橙色 skill 节点带标签；Python 聚焦时其他 skill 保持 cinnabar 色（dim 但可辨），连接公司 lapis 蓝，边是羊皮纸色 hairline；右侧 Python 标题用 italic Instrument Serif 大号显示，meta grid 规整
- 2026-04-25 · R-1 follow-up · 用户反馈"图谱太丑 + 拖拽只有第一下能动"，做二次打磨：
  - **视觉**：删除 48px 背景格子（这是"丑"的最大元凶），改为 3 层径向渐变（蓝/紫/橙）+ 8 个星点 radial-gradient 组成的微星云；`body::after` 单独承担 starfield
  - **节点尺寸**：`createSigmaData` 引入 `baseSize(type)` + `degreeBoost`（log2 度数加成），company 起步 16，skill 15，job 13，最大 +6。原先 4-12 的"小点"观感消除
  - **Sigma 标签**：labelSize 13→14，labelDensity 0.05→0.08，labelGridCellSize 110→140，labelRenderedSizeThreshold focus=6/rest=12（过去是 4/9）
  - **nodeReducer**：rest 状态仍显全色（避免"所有节点灰一片"），focus 状态选中放大 1.8x / 悬浮 1.45x / 邻居 1.18x；非活跃淡为 `rgba(130,142,158,0.22)`
  - **edgeReducer**：ambient 边改为 `rgba(255,255,255,0.05)` 极细；focus 时已连接边 `rgba(136,192,255,0.55)` + 1.6x 粗
  - **拖拽 bug 修复**（用户"只有第一下能拖"）：
    - 移除 `event.original.stopPropagation()` —— 这会打断 Sigma 内部 pointer-capture 的清理，导致下一次 pointerdown 收不到 `downNode` 事件
    - 加 `renderer.__dragHandlersAttached` 幂等守卫，杜绝多次绑定
    - 加 document 级 `pointerup/pointercancel` 安全网（处理拖出画布再释放的场景）
    - `destroySigmaOverview` 通过 `renderer.__dragDetach` 取消 document 监听
  - 实测：fresh state 下 8 个 skill 节点全部带标签清晰展示（Large Language Models / Machine Learning / Static Timing Analysis / Python / FPGA / SQL / Silicon Photonics / Verilog）；Python 聚焦时橙色中心 + 4 个蓝色 company 邻居 + 蓝色边 + 背景节点柔化

- 2026-04-25 · R-1 · UI 彻底重做（用户嫌米色衬线丑）：
  - `styles.css` 完全重写（1444 行 → 600 行），扔掉米色/Cormorant Garamond，改为深色（`#0b1117`）+ Inter + Noto Sans SC
  - 玻璃态浮层面板（backdrop-filter blur+saturate），图谱铺满视口做主画布
  - 节点类型色重调：company=电光蓝 `#58a6ff`，job=翠绿 `#3fb950`，skill=珊瑚橙 `#ff9966`，location=紫 `#bc8cff`，role-family=琥珀 `#ffa657`
  - 背景加径向渐变 + 48px 细格子纹理，mask radial 聚焦中心
  - graph-renderers.js 更新 nodeReducer（selected 保留本色 + 1.7x 放大，de-emph 改为 `rgba(255,255,255,0.12)`）、edgeReducer（connected 改 accent 蓝）、Sigma labelColor+labelFont+labelSize、Cytoscape 标签色从黑改白、边色全部换成深底下可见的 RGBA
  - index.html 字体改 Inter + Noto Sans SC + JetBrains Mono
  - 细节卡、meta grid、chip link 都做成带 hover transform 的现代卡片
  - 实测：dark bg 生效；中文"腾讯/算法-多模态方向"字体栈正确；detail pane 层级清晰（eyebrow → display title → body）；选中 Python 时连接的 4 家公司一目了然；search state 的 match/related 分区清爽
- 2026-04-25 · I-1/I-2/I-5 · P0 三件套打通"clone 即可跑 + Pages 自动部署"链路：
  - **I-1**：`includes/company_site_crawler_bundle/` 6 个源码文件 stage（README.md / company_site_crawler.py / requirements.txt / tests/test_company_site_crawler.py / sample-data/rawjob-template.jsonl / sample-data/report-template.json）；之前未提交是因为 `git ls-files includes/` 完全为空
  - **gitignore 加固**：原 `.gitignore` 中 `__pycache__/` 和 `.venv/` 是 leading-pattern 已覆盖各层级，但 `logs/**`、`reports/**` 仅匹配根目录。补 `includes/**/.venv/`、`includes/**/__pycache__/`、`includes/**/logs/`、`includes/**/.playwright-cli/`、`includes/**/output/`、`includes/**/TEST_RESULTS.txt` 显式拦截 bundle 内产物；同时补根 `tmp/`、`output/`、`.playwright-cli/` 防止本地污染再次入仓
  - **I-2**：`rm -rf includes/company_site_crawler_bundle/.venv`（166MB）+ `__pycache__` + `.DS_Store` + 空 `TEST_RESULTS.txt`；bundle README 既有 4 行安装段落（venv + pip + playwright install chromium），新增 `### 冒烟测试` 子段落（`python company_site_crawler.py --help` + `unittest discover`），并在仓库根 `README.md` 的 Quick demo 段后加一段指向 bundle README 的链接（说明实站爬取走 bundle，不走 demo）
  - **I-5**：新建 `.github/workflows/pages.yml`（2.3KB，YAML 通过 PyYAML safe_load 验证）。两 job：`build`（checkout@v4 + setup-python@v5 Py3.11 + pip 安装根 requirements.txt 防御性兼容 + `bash scripts/run_demo.sh` 产 dist + `test -f dist/index.html` 防御 + configure-pages@v5 + upload-pages-artifact@v3 path=dist）→ `deploy`（needs build + environment github-pages + deploy-pages@v4）。permissions: contents:read pages:write id-token:write；concurrency: group=pages cancel-in-progress=false。爬虫故意不在 CI 跑 —— sample-data fixtures (jsonld + html fallback) 是 standard-library only 的最小可部署链路，Playwright/真实爬取留给 bundle 在开发机手动跑后导入产物
  - **链路命令来源**：build job 的 `bash scripts/run_demo.sh` 等价于 `python -m apps.pipeline.cli run-pipeline --config <tmp> --import-input sample-data/input --site-out dist`（见 scripts/run_demo.sh 第 41-53 行），data/raw/.gitkeep 等占位文件已追踪故 CI 上 mktemp/find 不会 NPE
  - 验收：`git ls-files includes/ | wc -l = 6`（原为 0）；YAML safe_load 解析出 jobs=[build,deploy]、on=[push,workflow_dispatch]、build 7 steps；bundle README 含完整 4 行安装步骤 + playwright install + smoke test
  - 不动的：未 commit（主 agent 统一 commit）；未改 docs/deploy-github-pages.md（任务边界外，但其旧叙述与新 workflow 一致即不需更新）；其他 agent 范围的文件（heuristic.py / company_aliases.json / company_site.py adapter）原状保留
<!-- 新事件追加在这一行下方 -->

---

## 维护指令（给 Claude 自己看）

- 开工前：`Read` 本文件 → 找到目标任务 → 改状态为 `[~]` → 追加日志
- 完工后：改状态为 `[x]` → 追加日志 → commit message 带任务 ID
- 新发现的问题：追加到对应优先级下，不要单开文档
- 路线图如果大改（新增整个 phase），先和用户确认
- 不要在 commit message 或 PR 描述里长篇 paste 任务描述，用 ID 引用
