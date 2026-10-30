"""
Pydantic Schemas for Structured LLM Output
==========================================
Centralized schemas for structured LLM output, keeping data clean at the
entry point.

Modules:
- JobRankingResult: scoring output from the LLM ranker
- ExtractedJob: job extraction output for company sites / custom URLs
- JDSkillAnalysis: JD skill analysis output
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
    Structured output schema for the LLM ranker.
    """
    score: int = Field(..., ge=1, le=10, description="Job match score, 1-10")
    reason: str = Field(..., min_length=1, description="One-sentence scoring rationale")
    deal_breakers: List[str] = Field(default_factory=list, description="Fatal mismatches")

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
    LLM extraction schema for company sites / custom URLs.
    Mirrors extract_jobs_from_content() in custom_scraper.py.
    """
    id: str = Field(..., min_length=1, description="Unique identifier (slug format)")
    title: str = Field(..., min_length=1, description="Full job title")
    company: str = Field(..., min_length=1, description="Hiring company name")
    location: str = Field(default="Unknown", description="City / region")
    description: str = Field(default="", description="2-4 sentence summary of key responsibilities and skills")
    url: str = Field(..., description="Job detail page URL")
    job_type: Optional[str] = Field(
        default=None,
        description="Contract type: CDI / CDD / Internship / Apprentissage / Stage"
    )
    salary: Optional[str] = Field(default=None, description="Salary information when visible")
    remote: Optional[str] = Field(
        default=None,
        description="Remote policy: Yes / Partial / No"
    )
    experience: Optional[str] = Field(default=None, description="Experience requirement (years / level)")
    education: Optional[str] = Field(default=None, description="Education requirement")

    @field_validator("job_type", mode="before")
    @classmethod
    def normalize_job_type(cls, v):
        if v is None:
            return None
        v = str(v).strip()
        # Normalize common contract-type variants
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
    JD skill analysis schema.
    Mirrors the LLM-enhanced parsing in geomatics_jd_parser.py.
    """
    # Technical skills grouped by category
    technical_skills: TypingDict[str, List[str]] = Field(
        default_factory=dict,
        description="Technical skills grouped by category"
    )
    # Soft skills
    soft_skills: List[str] = Field(
        default_factory=list,
        description="Soft skills"
    )
    # Missing skills (required by the JD but absent from the resume)
    missing_skills: List[str] = Field(
        default_factory=list,
        description="Required skills you may be missing"
    )
    # Responsibility categories
    responsibilities: List[str] = Field(
        default_factory=list,
        description="Responsibility category labels"
    )
    # Constraints
    mandatory_requirements: List[str] = Field(
        default_factory=list,
        description="Mandatory requirements extracted from the JD"
    )
    bonus_requirements: List[str] = Field(
        default_factory=list,
        description="Nice-to-have requirements extracted from the JD"
    )
    # Experience requirements
    experience_years: Optional[float] = Field(
        default=None,
        ge=0,
        description="Minimum years of experience"
    )
    experience_field: List[str] = Field(
        default_factory=list,
        description="Expected domain experience"
    )
    # Seniority
    seniority_level: str = Field(
        default="Mid",
        description="Seniority: Junior / Mid / Senior / Lead / Manager"
    )
    # Domain tags
    domain_tags: List[str] = Field(
        default_factory=list,
        description="Domain tags: urban planning, environment, data analysis..."
    )
    # Summary
    summary: str = Field(
        default="",
        description="One-sentence summary of the role's core requirements"
    )


def safe_parse_json(raw: str, model: type[BaseModel], max_retries: int = 3) -> Optional[BaseModel]:
    """
    Safe Pydantic JSON parsing with cleanup and retries.

    Handles common LLM output issues:
    1. Markdown code fences (```json ... ```)
    2. Explanatory prefixes ("Here is the JSON: ...")
    3. Trailing text
    4. Non-standard JSON syntax (single quotes, trailing commas)
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
    Clean common issues in raw LLM output.
    Order: code fences -> prefix/suffix -> quotes -> trailing comma -> trailing text
    """
    # 1. Remove markdown code fences (both ends)
    s = re.sub(r'^```(?:json)?\s*', '', s.strip(), flags=re.MULTILINE)
    s = re.sub(r'\s*```$', '', s, flags=re.MULTILINE)

    # 2. Remove explanatory prefixes commonly emitted by LLMs.
    #    Prefer [ because JSON arrays start with [ (used for batch company-site extraction)
    first_bracket = s.find('[')
    first_brace = s.find('{')
    if first_bracket != -1 and (first_brace == -1 or first_bracket < first_brace):
        s = s[first_bracket:]
    elif first_brace != -1:
        s = s[first_brace:]

    # 3. Normalize single quotes (non-standard but occasionally emitted by LLMs)
    s = s.replace("'", '"')

    # 4. Remove trailing commas (invalid JSON)
    s = re.sub(r',(\s*[}\]])', r'\1', s)

    # 5. Remove trailing text after the first complete JSON object/array.
    #    Find the last } or ]
    last_close = max(s.rfind('}'), s.rfind(']'))
    if last_close != -1:
        s = s[:last_close + 1]

    return s.strip()


def parse_json_list(raw: str, model: type[BaseModel], max_retries: int = 3) -> List[BaseModel]:
    """
    Parse a JSON array returned by the LLM, validating each item with model.
    Used for batch extraction in extract_jobs_from_content().
    """
    for attempt in range(max_retries):
        try:
            cleaned = _clean_json_string(raw)
            data = json.loads(cleaned)
            if not isinstance(data, list):
                # LLM may wrap the list in {"jobs": [...]}
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
