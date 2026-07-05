# Company Website Crawler Bundle

这份 bundle 按你提供的 crawler 规范实现，目标是从 **公司官网** 抓取岗位，并产出可直接导入主 pipeline 的 **UTF-8 JSONL / RawJob**。

## 设计选择

按规范，针对字节跳动和腾讯这类 **重前端 / JS 渲染 / 可能依赖 XHR** 的站点，默认采用：

- **Mode A: External crawler artifact mode**
- 不直接写 SQLite
- 不做 title/company 归一化
- 不做 dedupe / skill enrichment / seniority inference
- 只做抓取、字段提取、输出 JSONL、输出 crawl report

脚本优先级与规范一致：

1. 优先捕获页面上的 **一方 JSON/XHR** 数据
2. 不够时退回 **渲染后 DOM**
3. 详情页提取失败时输出失败报告，不静默吞错
4. 尊重 `robots.txt`，若 robots 不允许则直接跳过/失败

## 目录

- `company_site_crawler.py`：主脚本
- `requirements.txt`：依赖
- `tests/test_company_site_crawler.py`：关键纯函数测试
- `sample-data/report-template.json`：报告模板

## 依赖

- Python 3.10+
- Playwright
- BeautifulSoup4
- lxml

安装：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

> 注：`.venv/`、`__pycache__/`、本地 `output/`、`logs/` 等产物均已被仓库根 `.gitignore` 排除，不会污染版本控制。

### 冒烟测试

环境装好后，先验证依赖加载与 CLI 可用：

```bash
python company_site_crawler.py --help
```

应输出 `--source / --output / --report / --max-jobs / --headful / --list-url` 等参数说明。也可以跑一次单元测试：

```bash
python -m unittest discover -s tests -v
```

## 运行方式

### 字节跳动校招

```bash
python company_site_crawler.py \
  --source bytedance_campus \
  --output data/raw/company-sites/bytedance-campus.jsonl \
  --report data/raw/company-sites/bytedance-campus.report.json
```

### 腾讯校招

```bash
python company_site_crawler.py \
  --source tencent_campus \
  --output data/raw/company-sites/tencent-campus.jsonl \
  --report data/raw/company-sites/tencent-campus.report.json
```

### 限制抓取数量（本地调试）

```bash
python company_site_crawler.py \
  --source tencent_campus \
  --max-jobs 20 \
  --headful \
  --output /tmp/tencent-campus.jsonl \
  --report /tmp/tencent-campus.report.json
```

### 覆盖列表页 URL

```bash
python company_site_crawler.py \
  --source tencent_campus \
  --list-url 'https://join.qq.com/post.html?query=p_2' \
  --output /tmp/tencent-campus.jsonl
```

## 输出合同

每条记录一行 JSON，符合 `RawJob` 约束：

必填字段：

- `source_type`（固定 `company_site`）
- `source_url`
- `title`
- `company_name`
- `fetched_at`

常见附加字段：

- `external_job_id`
- `location_text`
- `employment_type`
- `posted_at`
- `description_text`
- `description_html`
- `json_payload`
- `metadata`

## 字段映射说明

### 1) 字节跳动 `bytedance_campus`

默认列表页：

- `https://jobs.bytedance.com/campus/position/list?keywords=`

详情页 URL 识别：

- `/campus/position/<numeric_id>/detail`
- `/campus/position/detail/<numeric_id>`

字段来源：

- `source_url`
  - 详情页 canonical URL
  - 去掉 `external_referral_code`、`recomId`、`sourceJobId` 等跟踪参数
- `external_job_id`
  - 优先来自一方 JSON / XHR 的 `id/jobId/positionId`
  - 否则来自详情页 URL 中的数字 ID
- `title`
  - 优先详情页一方 JSON 的 `title/name/jobTitle/...`
  - 否则退回详情页正文顶部标题 / 列表页标题 hint
- `location_text`
  - 优先一方 JSON 中的 `location/city/...`
  - 否则匹配正文中 `工作地点` / `Location`
  - 再退回列表页卡片文本 hint
- `employment_type`
  - 优先一方 JSON `employmentType/jobType/...`
  - 否则匹配正文中 `Employment Type` / `招聘类型`
  - 再退回列表页显式标签
  - **不会仅从 title 中“实习生”字样推断**
- `posted_at`
  - 仅从显式日期字段提取，例如 `发布时间` / `Posted on`
  - 未找到则保留 `null`
- `description_text`
  - 优先一方 JSON 的 description 字段
  - 否则拼接正文中的：
    - `团队介绍`
    - `职位描述`
    - `职位要求`
- `description_html`
  - 优先一方 JSON 的 HTML 字段
  - 否则退回 **完整详情页 HTML**（规范允许作为 fallback）
- `json_payload`
  - 保留详情页最像职位对象的一方 JSON payload
  - 若没有详情页 JSON，则保留列表页 item payload
- `metadata`
  - 包含 `company_slug/crawler_name/crawler_version/list_url/detail_url/source_page_type`
  - 以及 `location_raw/employment_type_raw/posted_at_raw/req_id_raw/department_raw/team_raw`

### 2) 腾讯 `tencent_campus`

默认列表页：

- `https://join.qq.com/post.html?query=p_2`

详情页 URL 识别：

- `/post_detail.html?id=<id>&pid=<pid>&tid=<tid>`
- `/post_detail.html?postid=<postid>`

字段来源：

- `source_url`
  - 详情页 canonical URL
  - 去掉 `activity/activityLink/from` 等跟踪参数
- `external_job_id`
  - 优先 `postid/postId`
  - 其次 `id`
- `title`
  - 优先一方 JSON `title/name/postName/...`
  - 否则退回详情页顶部标题 / 列表页标题 hint
- `location_text`
  - 优先一方 JSON `location/city/...`
  - 否则优先匹配正文中的：
    - `招聘部门和工作地`
    - `参加面试的城市`
- `employment_type`
  - 优先一方 JSON
  - 否则从正文显式标签匹配：
    - `应届实习`
    - `日常实习`
    - `实习`
    - `校招`
    - `培训生`
- `posted_at`
  - 仅从显式 `发布时间` 等字段提取
- `description_text`
  - 优先一方 JSON
  - 否则拼接：
    - `岗位描述`
    - `岗位要求`
    - `加分项或注意事项`
    - `加分项`
- `description_html`
  - 优先一方 JSON HTML
  - 否则退回完整详情页 HTML
- `json_payload`
  - 保留最佳详情页 JSON payload
- `metadata`
  - 同字节配置，并额外保留列表页卡片原文用于追溯

## 正确性与可靠性策略

1. **先详情页、后列表页**
   - 列表页只用于发现 URL 和给 hint
   - 最终字段尽量以详情页为准

2. **优先官方一方数据**
   - 监听页面中的 `xhr/fetch` JSON 响应
   - 如果捕获到结构化 payload，优先用 payload 而不是 brittle DOM

3. **显式字段优先，不做推断污染**
   - `posted_at` 没有明确日期就写 `null`
   - `employment_type` 不从 title 猜

4. **去跟踪参数，保留 canonical provenance**
   - 输出 `source_url` 可长期追溯

5. **失败可见**
   - 所有 detail 失败写入 report
   - 不静默吞掉失败

6. **低并发、保守节奏**
   - 默认串行抓取 detail
   - 默认 `delay_seconds=1.0`

7. **robots 前置检查**
   - 列表页和详情页都检查 `robots.txt`
   - robots 不允许则不抓

## Failure Policy

### 列表页能打开，但详情页失败

- 记录到 report 的 `extraction_failures`
- 继续抓后续岗位
- 输出 partial results

### 页面一方 JSON 消失

- 自动退回渲染后 DOM 提取
- `json_payload` 可能回退到列表页 item 或 `null`

### 某些字段缺失

- 必填字段无法保证时跳过该岗位并记失败
- 非必填字段写 `null`

### 页面结构变化

- 若 anchors 消失但 XHR 仍存在，仍可通过 JSON 列表继续工作
- 若 XHR 消失但 DOM 仍存在，仍可通过详情页文本提取继续工作
- 两者都失效时，report 会明确显示失败 URL 和异常原因

## 测试

```bash
python -m unittest discover -s tests -v
```

当前测试覆盖：

- URL canonicalization
- job id 提取
- 文本 section 切分
- 日期规范化
- JSON item -> JobStub
- RawJob 合同校验

## 导入到主 pipeline

按规范，可以直接导入：

```bash
python -m apps.pipeline.cli import-raw \
  --input data/raw/company-sites/tencent-campus.jsonl \
  --db data/recruit_graph.sqlite3
```

或：

```bash
python -m apps.pipeline.cli run-pipeline \
  --import-input data/raw/company-sites/bytedance-campus.jsonl \
  --db data/recruit_graph.sqlite3
```

## 备注

这个 bundle 已把“脚本规范”落实到结构和输出合同里，但我在当前环境里 **无法直接联网执行到这些官网**，所以这里交付的是：

- 可运行脚本
- 字段映射说明
- 测试
- report 机制

你在有正常外网访问的机器上跑一次，就能得到真实 `.jsonl` 和 `.report.json` 产物。
