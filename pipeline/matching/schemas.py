"""
Pydantic Schemas for Structured LLM Output
==========================================
集中管理所有 LLM 结构化输出的 Schema，确保数据在入口处即极致干净。

模块划分：
- JobRankingResult: LLM ranker 的评分结果
- ExtractedJob: custom_scraper 的企业站职位提取结果
- JDSkillAnalysis: JD 技能解析结果
"""
from __future__ import annotations

import json
import logging
import re
from typing import Dict as TypingDict
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


class JobRankingResult(BaseModel):
    """
    LLM Ranker 的结构化输出 Schema
    """
    score: int = Field(..., ge=1, le=10, description="岗位匹配度评分 1-10")
    reason: str = Field(..., min_length=1, description="评分理由，一句话说明")
    deal_breakers: List[str] = Field(default_factory=list, description="致命的不匹配项")

    @field_validator("score", mode="before")
    @classmethod
    def coerce_score(cls, v):
        if isinstance(v, str):
            import re
            m = re.search(r'\d+', v)
            if m:
                return int(m.group())
        return v


class ExtractedJob(BaseModel):
    """
    企业站 / 自定义 URL 的 LLM 提取 Schema
    对应 custom_scraper.py 的 extract_jobs_from_content()
    """
    id: str = Field(..., min_length=1, description="唯一标识（slug 格式）")
    title: str = Field(..., min_length=1, description="完整职位名称")
    company: str = Field(..., min_length=1, description="招聘公司名称")
    location: str = Field(default="Unknown", description="城市/地区")
    description: str = Field(default="", description="2-4 句话的关键职责和技能摘要")
    url: str = Field(..., description="职位详情页链接")
    job_type: Optional[str] = Field(
        default=None,
        description="合同类型：CDI / CDD / Internship / Apprentissage / Stage"
    )
    salary: Optional[str] = Field(default=None, description="薪资信息（可见时）")
    remote: Optional[str] = Field(
        default=None,
        description="远程办公：Yes / Partial / No"
    )
    experience: Optional[str] = Field(default=None, description="经验要求（年限/级别）")
    education: Optional[str] = Field(default=None, description="学历要求")

    @field_validator("job_type", mode="before")
    @classmethod
    def normalize_job_type(cls, v):
        if v is None:
            return None
        v = str(v).strip()
        # 归一化常见变体
        norm_map = {
            "cdi": "CDI",
            "cdd": "CDD",
            "stage": "Stage",
            "alternance": "Alternance",
            "apprentissage": "Apprentissage",
            "apprenticeship": "Apprentissage",
            "full-time": "CDI",
            "full time": "CDI",
            "part-time": "CDD",
            "contract": "CDD",
            "permanent": "CDI",
            "temporary": "CDD",
            "internship": "Stage",
        }
        lower = v.lower()
        return norm_map.get(lower, v)

    @field_validator("remote", mode="before")
    @classmethod
    def normalize_remote(cls, v):
        if v is None:
            return None
        v = str(v).strip().lower()
        if v in ("yes", "remote", "télétravail", "full remote", "fully remote"):
            return "Yes"
        if v in ("partial", "partiel", "hybrid", "partially remote", "occasionnel"):
            return "Partial"
        if v in ("no", "non", "onsite", "sur site", " Présentiel"):
            return "No"
        return v

    @field_validator("location")
    @classmethod
    def strip_location(cls, v):
        return v.strip()


class JDSkillAnalysis(BaseModel):
    """
    JD 技能深度分析 Schema
    对应 geomatics_jd_parser.py 的 LLM 增强解析
    """
    # 技术技能（按类别分组）
    technical_skills: TypingDict[str, List[str]] = Field(
        default_factory=dict,
        description="技术技能，按类别分组"
    )
    # 软技能
    soft_skills: List[str] = Field(
        default_factory=list,
        description="软技能列表"
    )
    # 缺失技能（你简历中没有但 JD 要求的）
    missing_skills: List[str] = Field(
        default_factory=list,
        description="要求但你可能缺乏的技能"
    )
    # 职责分类
    responsibilities: List[str] = Field(
        default_factory=list,
        description="职责分类标签"
    )
    # 约束条件
    mandatory_requirements: List[str] = Field(
        default_factory=list,
        description="必须要求（从 JD 中提取的硬性条件）"
    )
    bonus_requirements: List[str] = Field(
        default_factory=list,
        description="加分项（从 JD 中提取的软性条件）"
    )
    # 经验要求
    experience_years: Optional[float] = Field(
        default=None,
        ge=0,
        description="最低年限要求"
    )
    experience_field: List[str] = Field(
        default_factory=list,
        description="期望的领域经验"
    )
    # 职级
    seniority_level: str = Field(
        default="Mid",
        description="职级：Junior / Mid / Senior / Lead / Manager"
    )
    # 领域标签
    domain_tags: List[str] = Field(
        default_factory=list,
        description="领域标签：城市规划、环境、数据分析..."
    )
    # 总结
    summary: str = Field(
        default="",
        description="一句话总结该岗位的核心要求"
    )


def safe_parse_json(raw: str, model: type[BaseModel], max_retries: int = 3) -> Optional[BaseModel]:
    """
    带清理和重试的 Pydantic 安全 JSON 解析。

    处理常见的 LLM 输出问题：
    1. Markdown 代码块包裹（```json ... ```）
    2. 解释性前缀（"Here is the JSON: ..."）
    3. 尾部多余文本
    4. 非标准 JSON 语法（如单引号、trailing comma）
    """
    for attempt in range(max_retries):
        try:
            cleaned = _clean_json_string(raw)
            data = json.loads(cleaned)
            return model.model_validate(data)
        except Exception as e:
            if attempt < max_retries - 1:
                logger.debug(f"Attempt {attempt + 1} failed: {e}, retrying...")
                continue
            logger.warning(f"Failed to parse JSON after {max_retries} attempts: {e}")
    return None


def _clean_json_string(s: str) -> str:
    """
    清理 LLM 原始输出中的常见问题。
    处理顺序：代码块 → 前缀/后缀 → 引号 → trailing comma → 尾部文本
    """
    # 1. 去掉 markdown 代码块标记（首尾都处理）
    s = re.sub(r'^```(?:json)?\s*', '', s.strip(), flags=re.MULTILINE)
    s = re.sub(r'\s*```$', '', s, flags=re.MULTILINE)

    # 2. 去掉 LLM 常见的解释性前缀
    #    优先找 [，因为 JSON 数组以 [ 开头（用于企业站批量提取）
    first_bracket = s.find('[')
    first_brace = s.find('{')
    if first_bracket != -1 and (first_brace == -1 or first_bracket < first_brace):
        s = s[first_bracket:]
    elif first_brace != -1:
        s = s[first_brace:]

    # 3. 处理单引号（不标准但 LLM 偶尔会输出）
    s = s.replace("'", '"')

    # 4. 处理 trailing comma（在 JSON 中非法）
    s = re.sub(r',(\s*[}\]])', r'\1', s)

    # 5. 处理尾部多余文本（第一个完整的 JSON 对象/数组之后的内容）
    #    找最后一个 } 或 ]
    last_close = max(s.rfind('}'), s.rfind(']'))
    if last_close != -1:
        s = s[:last_close + 1]

    return s.strip()


def parse_json_list(raw: str, model: type[BaseModel], max_retries: int = 3) -> List[BaseModel]:
    """
    解析 LLM 返回的 JSON 数组，每个元素按 model 验证。
    用于 extract_jobs_from_content() 的批量提取。
    """
    for attempt in range(max_retries):
        try:
            cleaned = _clean_json_string(raw)
            data = json.loads(cleaned)
            if not isinstance(data, list):
                # 如果 LLM 返回了 {"jobs": [...]} 这种包裹结构
                if isinstance(data, dict):
                    for key in ("jobs", "data", "results", "postings"):
                        if key in data and isinstance(data[key], list):
                            data = data[key]
                            break
                    else:
                        raise ValueError(f"Expected list, got dict with keys {list(data.keys())}")
                else:
                    raise ValueError(f"Expected list, got {type(data)}")
            results = []
            for item in data:
                try:
                    results.append(model.model_validate(item))
                except Exception as ve:
                    logger.debug(f"Skipping invalid item: {ve}")
                    continue
            return results
        except Exception as e:
            if attempt < max_retries - 1:
                logger.debug(f"Attempt {attempt + 1} failed: {e}, retrying...")
                continue
            logger.warning(f"Failed to parse JSON list after {max_retries} attempts: {e}")
    return []
