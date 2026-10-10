# 职位数据抓取模块 (Ingestion)

本目录包含所有数据抓取实现，分为三类：第三方库封装、企业专属爬虫、平台爬虫。

---

## 爬虫一览

| 文件 | 目标 | 技术 | 维护成本 |
|------|------|------|----------|
| `jobspy_scraper.py` | LinkedIn / Indeed | JobSpy 库 | 极低（库作者维护） |
| `ats_scraper.py` | Greenhouse / Lever / SmartRecruiters | 公开 API | 低 |
| `custom_scraper.py` | GeoRezo + 企业站分发 | Crawl4AI + LLM | 中 |
| `aae_ensg_scraper.py` | AAE-ENSG 校友会求职板 | requests + BeautifulSoup | 低 |
| `platform_scraper.py` | Seek / Jobat / Oikotie / IamExpat / Jobs.lu | requests + Playwright | 低 |

### 企业专属爬虫

| 文件 | 目标 |
|------|------|
| `capgemini_scraper.py` | Capgemini careers |
| `magellium_scraper.py` | Magellium careers |
| `cgi_scraper.py` | CGI（被 Radware 拦截，返回 0 条） |
| `schneider_scraper.py` | Schneider Electric |
| `edf_scraper.py` | EDF |
| `totalenergies_scraper.py` | TotalEnergies |
| `tomtom_scraper.py` | TomTom |
| `esri_scraper.py` | ESRI (Workday) |
| `wttj_scraper.py` | Welcome to the Jungle |
| `taleo_scraper.py` | Taleo 平台 |
| `dutch_scraper.py` | 荷兰语站点 |

---

## AAE-ENSG 爬虫 (`aae_ensg_scraper.py`)

抓取法国 ENSG 校友会求职板 (`aae-ensg.eu`)。ENSG 是法国国立地理学校，其求职板主要面向 GIS/Data 岗位。

**解析方式**：
- 请求列表页，用 `BeautifulSoup` 解析 `article` 元素。
- 从中提取标题、链接、描述和地点。
- 薪资正则匹配：支持 `X XXX € brut/mois`、`X XXX €/an`、`XXk€` 等法文格式。
- 月薪 >= 3200 € 时，自动标为 `"3200 以上"`（阈值可调）。

**调用方式**（已在 `custom_scraper.py` 中注册）：

```python
from pipeline.ingestion.aae_ensg_scraper import scrape
jobs = scrape(max_jobs=15)
```

---

## 异常体系 (`exceptions.py`)

结构化错误码体系，参考 actionbook 的 `code` + `retryable` 模式。

| 异常类 | code | retryable | 适用场景 |
|--------|------|-----------|----------|
| `BlockedError` | `BLOCKED_*` | false | 网站主动拦截（geo-block / captcha / Radware） |
| `TransientError` | `TRANSIENT` | true | 临时故障（超时 / 连接重置 / 5xx） |
| `ParseError` | `PARSE_FAILED` | false | 页面结构异常（选择器未找到 / 内容格式不符） |

所有爬虫先用 `except ScraperError` 捕获结构化异常，再用 `except Exception` 兜底。

---

## 平台爬虫 (`platform_scraper.py`)

集中管理 5 个平台站点的抓取逻辑。

**公共工具函数**：

| 函数 | 说明 |
|------|------|
| `_detect_blocked(html)` | 检查 HTML 是否包含反爬/拦截特征。返回拦截类型或 None。支持 captcha / geo_block / cloudflare / radware / rate_limit |
| `_retry_request(url, max_retries=3)` | 带指数退避重试的 GET 请求（1s → 2s → 4s）。所有重试失败后抛 `TransientError` |
| `_block_resources(page)` | 拦截 Playwright 页面中的字体、图片、CSS，加速 2-3 倍 |
| `_launch_scraper(url, selector, site, ...)` | 统一 Playwright 爬虫入口：启动浏览器 → 拦截资源 → `page.evaluate()` 提取数据 |

**`page.evaluate()` 优化**：用单次 JS 调用替代 N+1 次 Python→浏览器往返。从 journalism skill 移植。

---

## 异常处理规范

所有爬虫遵循统一模式：

```python
try:
    # 抓取逻辑
    r = _retry_request(url)         # 自动重试
    blocked = _detect_blocked(r.text)  # 拦截检测
    if blocked:
        return []
    # 解析...
except ScraperError as e:
    logger.warning("[%s] %s", e.code, e)  # 结构化错误日志
except Exception as e:
    logger.error("...")
```

---

## 参考

- [Keep a Changelog](https://keepachangelog.com/) — 版本日志格式
- [actionbook](https://actionbook.dev) — 结构化错误码模式来源
