"""
Entity Resolution & Data Cleaning Layer (v2)
"""
from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import parse_qs, urlparse

from rapidfuzz import process

from ..ingestion.models import JobPosting

logger = logging.getLogger(__name__)

# ── Score threshold for fuzzy matching ──────────────────────────────────────
FUZZY_THRESHOLD = 82   # 低于此分数不做模糊匹配，直接保留原值

# ── 公司名称白名单（精确匹配优先）──────────────────────────────────────────────
#  key: 小写标准形  →  value: 用户可见的标准写法
#  支持带国家/地区后缀的变体（如 "edf france" → "EDF"）
KNOWN_COMPANIES: dict[str, str] = {
    # EDF 家族
    "edf": "EDF",
    "edf france": "EDF",
    "electricite de france": "EDF",
    "edf energies nouvelles": "EDF EN",
    "edf renouvellement": "EDF Renouvelables",
    "edf.en": "EDF EN",
    # Schneider 家族
    "schneider electric": "Schneider Electric",
    "schneider-electric": "Schneider Electric",
    "schneider electric se": "Schneider Electric",
    "se.com": "Schneider Electric",
    # Total 家族
    "totalenergies": "TotalEnergies",
    "total energies": "TotalEnergies",
    "total energies france": "TotalEnergies",
    "totalenergies.com": "TotalEnergies",
    "total.com": "TotalEnergies",
    # 咨询/IT
    "capgemini": "Capgemini",
    "cap gemini": "Capgemini",
    "atos": "Atos",
    "atos syntel": "Atos",
    "accenture": "Accenture",
    "accenture france": "Accenture",
    "dassault systemes": "Dassault Systèmes",
    "dassault-systemes": "Dassault Systèmes",
    "dassault systèmes": "Dassault Systèmes",
    # 地图/GIS
    "esri": "ESRI",
    "esri france": "ESRI France",
    "esri france sas": "ESRI France",
    "hexagon": "Hexagon",
    "hexagon geospatial": "Hexagon Geospatial",
    # 云/数据平台
    "amazon": "Amazon",
    "amazon web services": "AWS",
    "aws": "AWS",
    "microsoft": "Microsoft",
    "google": "Google",
    "snowflake": "Snowflake",
    "datadog": "Datadog",
    "mongodb": "MongoDB",
    "elastic": "Elastic",
    "confluent": "Confluent",
    # 工程/制造
    "tomtom": "TomTom",
    "tom tom": "TomTom",
    "tomtom b.v.": "TomTom",
    "thales": "Thales",
    "safran": "Safran",
    "dassault aviation": "Dassault Aviation",
    # 运营商/基建
    "sncf": "SNCF",
    "ratp": "RATP",
    "orange": "Orange",
    "bouygues": "Bouygues",
    "vinci": "Vinci",
    "eiffage": "Eiffage",
    "sipartech": "Sipartech",
    # 数据/咨询
    "artefact": "Artefact",
    "octo technology": "Octo Technology",
    "octo": "Octo Technology",
    "valuence": "Valuence",
    "mp data": "MP DATA",
    "dataiku": "Dataiku",
    # 招聘/猎头平台
    "sii": "SII",
    "sii group": "SII",
    "page personnel": "Page Personnel",
    "expectra": "Expectra",
    "hays": "Hays",
    "michael page": "Michael Page",
    "adecco": "Adecco",
    "prolific": "Prolific",
    "prolific research": "Prolific",
}

# ── 地点白名单 ────────────────────────────────────────────────────────────────
# 小写 key → 标准写法
KNOWN_LOCATIONS: dict[str, str] = {
    # Paris arrondissements
    "paris": "Paris",
    "paris 01": "Paris", "paris 75001": "Paris",
    "paris 02": "Paris", "paris 75002": "Paris",
    "paris 03": "Paris", "paris 75003": "Paris",
    "paris 04": "Paris", "paris 75004": "Paris",
    "paris 05": "Paris", "paris 75005": "Paris",
    "paris 06": "Paris", "paris 75006": "Paris",
    "paris 07": "Paris", "paris 75007": "Paris",
    "paris 08": "Paris", "paris 75008": "Paris",
    "paris 09": "Paris", "paris 75009": "Paris",
    "paris 10": "Paris", "paris 75010": "Paris",
    "paris 11": "Paris", "paris 75011": "Paris",
    "paris 12": "Paris", "paris 75012": "Paris",
    "paris 13": "Paris", "paris 75013": "Paris",
    "paris 14": "Paris", "paris 75014": "Paris",
    "paris 15": "Paris", "paris 75015": "Paris",
    "paris 16": "Paris", "paris 75016": "Paris",
    "paris 17": "Paris", "paris 75017": "Paris",
    "paris 18": "Paris", "paris 75018": "Paris",
    "paris 19": "Paris", "paris 75019": "Paris",
    "paris 20": "Paris", "paris 75020": "Paris",
    # IDF departments
    "92": "Hauts-de-Seine", "92 - nanterre": "Hauts-de-Seine",
    "93": "Seine-Saint-Denis", "94": "Val-de-Marne",
    "91": "Essonne", "78": "Yvelines", "95": "Val-d'Oise",
    # IDF region
    "idf": "Île-de-France", "î-de-france": "Île-de-France",
    "ile de france": "Île-de-France", "region parisienne": "Île-de-France",
    "la defense": "La Défense", "la défense": "La Défense",
    "neuilly-sur-seine": "Neuilly-sur-Seine",
    "issy-les-moulineaux": "Issy-les-Moulineaux",
    "levallois-perret": "Levallois-Perret",
    "puteaux": "Puteaux", "courbevoie": "Courbevoie",
    "nanterre": "Nanterre",
    # Major cities France
    "lyon": "Lyon", "marseille": "Marseille", "toulouse": "Toulouse",
    "bordeaux": "Bordeaux", "nice": "Nice", "rennes": "Rennes",
    "strasbourg": "Strasbourg", "nantes": "Nantes",
    "montpellier": "Montpellier", "grenoble": "Grenoble", "lille": "Lille",
    "aix-en-provence": "Aix-en-Provence", "aix": "Aix-en-Provence",
    "tours": "Tours", "angers": "Angers", "caen": "Caen",
    "rouen": "Rouen", "brest": "Brest", "orleans": "Orléans", "clermont": "Clermont-Ferrand",
    # International
    "london": "London", "amsterdam": "Amsterdam",
    "berlin": "Berlin", "geneva": "Geneva",
    "zurich": "Zürich", "zürich": "Zürich",
    "brussels": "Brussels", "bruxelles": "Brussels",
    "madrid": "Madrid", "barcelona": "Barcelona",
    "milan": "Milan", "milano": "Milan",
    "rome": "Rome", "roma": "Rome",
    "dublin": "Dublin", "vienna": "Vienna", "wien": "Vienna",
    "luxembourg": "Luxembourg", "genève": "Geneva",
}

# ── 合同类型归一化 ────────────────────────────────────────────────────────────
# 处理各种来源的输出格式：JobSpy 英文 / 法国本土 / ATS API
JOB_TYPE_NORM: dict[str, str] = {
    "cdi": "CDI", "full-time": "CDI", "full time": "CDI",
    "permanent": "CDI", "indefinite": "CDI",
    "employee, full time": "CDI", "employee full-time": "CDI",
    "cdd": "CDD", "contract": "CDD", "temporary": "CDD",
    "part-time": "Part-time", "part time": "Part-time",
    "stage": "Stage", "internship": "Stage", "intern": "Stage",
    "alternance": "Alternance",
    "apprentissage": "Apprentissage", "apprenticeship": "Apprentissage",
    "freelance": "Freelance", "consultant": "Freelance", "indépendant": "Freelance",
    "vie": "VIE",
}

# ── 远程办公标签归一化 ────────────────────────────────────────────────────────
REMOTE_NORM: dict[str, str] = {
    "yes": "Yes", "remote": "Yes", "télétravail": "Yes",
    "full remote": "Yes", "fully remote": "Yes", "100% remote": "Yes",
    "完全远程": "Yes", "remoto": "Yes",
    "partial": "Partial", "partiel": "Partial", "hybrid": "Partial",
    "partially remote": "Partial", "occasionnel": "Partial", "混合": "Partial",
    "no": "No", "non": "No", "onsite": "No", "sur site": "No",
    " présentiel": "No", "现场": "No",
}

# ── URL tracking 参数黑名单 ──────────────────────────────────────────────────
TRACKING_PARAMS: set[str] = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "msclkid", "dclid",
    "mc_cid", "mc_eid",
    "_ga", "_gl",
    "ref", "ref_src", "ref_url",
    "source", "src",
    "via", "igshid",
}

# ── HTML 处理 ─────────────────────────────────────────────────────────────────
_HTML_TAG_RE = re.compile(r'<[^>]+>')

import html as _html  # for unescape


def _strip_html(s: str) -> str:
    """去掉 HTML 标签、实体解码（如 &nbsp; → space）和多余空白。"""
    s = _HTML_TAG_RE.sub(' ', s)
    s = _html.unescape(s)
    return re.sub(r'\s+', ' ', s).strip()


# ── 核心函数 ──────────────────────────────────────────────────────────────────

def normalize_company_name(raw: str) -> str:
    """
    公司名称归一化：
    1. 去 HTML 标签 + HTML 实体解码（如 &nbsp; → space）
    2. 精确白名单匹配（忽略大小写）
    3. rapidfuzz 模糊匹配（默认 WRatio），低于阈值则保留原值

    白名单优先，rapidfuzz 做安全网。
    """
    if not raw:
        return "Unknown"
    name = _strip_html(raw.strip())
    key = name.lower()

    # 精确匹配
    if key in KNOWN_COMPANIES:
        return KNOWN_COMPANIES[key]

    # 模糊匹配：默认 WRatio，score_cutoff 设为 82（normalized 0-100 分）
    # 返回 (value, score, dict_key)
    best = process.extractOne(key, KNOWN_COMPANIES, score_cutoff=FUZZY_THRESHOLD)
    if best is not None:
        best_value, score, best_key = best
        return KNOWN_COMPANIES[best_key]

    return name


def normalize_location(raw: str) -> str:
    """
    地点名称归一化：
    1. 精确白名单匹配
    2. rapidfuzz 模糊匹配
    3. 去掉多余空白返回原值
    """
    if not raw:
        return "Unknown"
    loc = raw.strip()
    key = loc.lower()

    # 精确匹配
    if key in KNOWN_LOCATIONS:
        return KNOWN_LOCATIONS[key]

    # 模糊匹配
    best = process.extractOne(key, KNOWN_LOCATIONS, score_cutoff=FUZZY_THRESHOLD)
    if best is not None:
        best_value, score, best_key = best
        return KNOWN_LOCATIONS[best_key]

    # 去掉多余空格返回原值
    return re.sub(r'\s+', ' ', loc)


def normalize_job_type(raw: Optional[str]) -> Optional[str]:
    """合同类型归一化。"""
    if not raw:
        return None
    key = str(raw).strip().lower()
    return JOB_TYPE_NORM.get(key, raw.strip())


def normalize_remote(raw: Optional[str]) -> Optional[str]:
    """远程办公标签归一化。"""
    if not raw:
        return None
    key = str(raw).strip().lower()
    return REMOTE_NORM.get(key, raw.strip())


def clean_url(url: str) -> str:
    """清除 URL 中的 tracking 参数，保留核心地址。"""
    if not url:
        return url
    try:
        parsed = urlparse(url)
        query_params = parse_qs(parsed.query, keep_blank_values=True)
        clean_params = {
            k: v for k, v in query_params.items()
            if k.lower() not in TRACKING_PARAMS
        }
        clean_query = "&".join(f"{k}={v[0]}" for k, v in clean_params.items())
        return parsed._replace(query=clean_query).geturl()
    except Exception:
        return url


def clean_job(job: JobPosting) -> JobPosting:
    """对单个 JobPosting 进行全量标准化清洗。"""
    cleaned = JobPosting(
        id=job.id,
        title=re.sub(r'\s+', ' ', job.title.strip() if job.title else "Unknown"),
        company=normalize_company_name(job.company),
        location=normalize_location(job.location),
        description=job.description.strip() if job.description else "",
        url=clean_url(job.url) if job.url else "",
        site=job.site,
        job_type=normalize_job_type(job.job_type),
        salary=job.salary.strip() if job.salary else None,
        date_posted=job.date_posted,
        experience=job.experience,
        education=job.education,
        remote=normalize_remote(job.remote),
        final_score=job.final_score,
        reason=job.reason,
        missing_skills=job.missing_skills,
        passed_hard_filter=job.passed_hard_filter,
    )
    # 保留 pipeline 中填充的扩展字段
    if hasattr(job, "structured_data"):
        cleaned.structured_data = job.structured_data
    if hasattr(job, "screening_results"):
        cleaned.screening_results = job.screening_results
    return cleaned


def clean_jobs(jobs: list[JobPosting]) -> list[JobPosting]:
    """对一批 JobPosting 进行全量清洗。"""
    return [clean_job(job) for job in jobs]
