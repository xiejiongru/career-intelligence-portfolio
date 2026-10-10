import logging
import re
from typing import Any, Dict, List, Optional

from ..ingestion.models import JobPosting
from ..utils.nlp import detect_language, process_text

logger = logging.getLogger(__name__)

class GeomaticsJDParser:
    """
    专门用于解析城市规划、GIS、数据分析类岗位描述的解析器。
    将非结构化 JD 转换为符合要求的结构化数据。
    """

    # 技能标准化映射
    SKILL_MAPPING = {
        "sig": "GIS（地理信息系统）",
        "gis": "GIS（地理信息系统）",
        "géomatique": "地理信息 / geomatics",
        "geomatics": "地理信息 / geomatics",
        "cartographie": "制图 / 地图可视化",
        "cartography": "制图 / 地图可视化",
        "analyse spatiale": "空间分析",
        "spatial analysis": "空间分析",
    }

    # 技术栈分类
    TECH_CATEGORIES = {
        "gis_related": ["qgis", "arcgis", "postgis", "geoserver", "openlayers", "leaflet", "fme", "mapinfo", "autocad", "gdal", "ogr", "osm"],
        "languages": ["python", "sql", "r", "javascript", "typescript", "c++", "java", "php"],
        "data_skills": ["pandas", "numpy", "postgresql", "mysql", "mongodb", "etl", "data analysis", "statistiques"],
        "tools": ["docker", "kubernetes", "git", "jenkins", "linux", "office", "excel"]
    }

    # 职责分类关键词
    RESPONSIBILITY_MAPPING = {
        "项目管理": ["chef de projet", "project management", "gestion de projet", "coordination"],
        "数据工程/数据处理": ["data engineering", "traitement de données", "pipeline", "etl", "intégration"],
        "GIS分析/空间分析": ["analyse spatiale", "spatial analysis", "cartographie", "modélisation"],
        "团队管理": ["management", "équipe", "team lead", "encadrement"],
        "商务拓展": ["business development", "commercial", "vente", "partenariat"],
        "方法论设计": ["méthodologie", "conception", "design", "architecture"]
    }

    # 领域标签映射
    DOMAIN_TAGS_MAPPING = {
        "城市规划": ["urbanisme", "urban planning", "aménagement"],
        "公共政策": ["politiques publiques", "public policy", "collectivité"],
        "土地管理": ["foncier", "cadastre", "land management"],
        "环境与韧性": ["environnement", "climat", "resilience", "écologie"],
        "咨询行业": ["consulting", "conseil", "prestation"],
        "数据分析": ["data analysis", "statistiques", "big data"],
        "空间数据": ["données spatiales", "spatial data", "géodonnées"]
    }

    def __init__(self):
        pass

    def parse(self, job: JobPosting) -> Dict[str, Any]:
        """
        核心解析函数
        """
        text = job.description
        lang = detect_language(text)
        doc = process_text(text, lang=lang)

        if not doc:
            return self._empty_result(job)

        # 1. 基础信息
        title = job.title
        company = job.company
        location = [job.location] if job.location else []

        # 2. 经验要求
        years, field_exp = self._extract_experience(text, doc)

        # 3. 职级判断
        rank = self._determine_rank(years, text)

        # 4. 技术技能提取与标准化
        tech_skills = self._extract_tech_skills(text, doc)

        # 5. 职责分类
        responsibilities = self._extract_responsibilities(text)

        # 6. 约束条件 (必须要求 vs 加分项)
        mandatory, bonus = self._extract_constraints(doc)

        # 7. 领域标签
        domain_tags = self._extract_domain_tags(text)

        # 8. 总结
        summary = self._generate_summary(title, company, rank, years, domain_tags)

        # 9. 合并结果
        result = {
            "标题": title,
            "公司": company,
            "地点": location,
            "合同类型": job.job_type or "未知",
            "职级": rank,
            "经验要求": {
                "最低年限": years,
                "领域经验": field_exp
            },
            "技术技能": {
                "GIS相关": tech_skills["gis_related"],
                "编程语言": tech_skills["languages"],
                "数据能力": tech_skills["data_skills"],
                "工具": tech_skills["tools"]
            },
            "职责": responsibilities,
            "软技能": self._extract_soft_skills(text, doc),
            "约束条件": {
                "必须要求": mandatory,
                "加分项": bonus
            },
            "领域标签": domain_tags,
            "简要总结": summary
        }

        return result

    def _extract_experience(self, text: str, doc) -> (Optional[float], List[str]):
        text_lower = text.lower()
        years = None

        # 正则匹配年限
        # e.g., "8 ans d’expérience", "3-5 years", "min. 2 ans"
        match = re.search(r'(\d+)\s*(?:-|à|to)?\s*(\d+)?\s*(?:ans?|years?)', text_lower)
        if match:
            years = float(match.group(1))
        elif "confirmée" in text_lower or "confirmed" in text_lower:
            years = 5.0

        # 领域经验提取 (基于常见领域词)
        field_exp = []
        for domain, kws in self.DOMAIN_TAGS_MAPPING.items():
            if any(kw in text_lower for kw in kws):
                field_exp.append(domain)

        return years, list(set(field_exp))

    def _determine_rank(self, years: Optional[float], text: str) -> str:
        text_lower = text.lower()
        is_manager = any(kw in text_lower for kw in ["management", "responsable", "directeur", "lead", "chef"])

        if years is not None:
            if years >= 8 and is_manager:
                return "高级/负责人"
            if 5 <= years <= 7:
                return "中高级"
            if years < 5:
                return "初级/中级"

        # 兜底逻辑
        if is_manager:
            return "负责人/组长"
        return "中级/待定"

    def _extract_tech_skills(self, text: str, doc) -> Dict[str, List[str]]:
        text_lower = text.lower()
        extracted = {cat: [] for cat in self.TECH_CATEGORIES}

        # 1. 基于预设词表的词袋匹配
        for cat, items in self.TECH_CATEGORIES.items():
            for item in items:
                # 简单边界检查
                if re.search(rf'\b{re.escape(item)}\b', text_lower):
                    extracted[cat].append(item.upper() if len(item) < 5 else item.capitalize())

        # 2. 技能标准化
        for cat in extracted:
            new_list = []
            for item in extracted[cat]:
                mapped = self.SKILL_MAPPING.get(item.lower())
                new_list.append(mapped if mapped else item)
            extracted[cat] = list(set(new_list))

        return extracted

    def _extract_responsibilities(self, text: str) -> List[str]:
        text_lower = text.lower()
        found = []
        for category, kws in self.RESPONSIBILITY_MAPPING.items():
            if any(kw in text_lower for kw in kws):
                found.append(category)
        return list(set(found))

    def _extract_constraints(self, doc) -> (List[str], List[str]):
        mandatory = []
        bonus = []

        # 规则定义
        mandatory_kws = ["必须", "required", "impératif", "exigé", "indispensable", "maîtrise"]
        bonus_kws = ["souhaité", "apprécié", "bonus", "idéalement", "plus", "atout"]

        for sent in doc.sents:
            sent_text = sent.text.lower()
            if any(kw in sent_text for kw in mandatory_kws):
                # 提取该句中的核心名词短语作为要求
                mandatory.append(sent.text.strip())
            elif any(kw in sent_text for kw in bonus_kws):
                bonus.append(sent.text.strip())

        return mandatory[:5], bonus[:5] # 限制数量

    def _extract_domain_tags(self, text: str) -> List[str]:
        text_lower = text.lower()
        tags = []
        for domain, kws in self.DOMAIN_TAGS_MAPPING.items():
            if any(kw in text_lower for kw in kws):
                tags.append(domain)
        return list(set(tags))

    def _extract_soft_skills(self, text: str, doc) -> List[str]:
        # 简单提取，寻找常见软技能词汇
        soft_skills_kws = ["autonomie", "rigueur", "aisance relationnelle", "travail en équipe", "curiosité"]
        found = []
        text_lower = text.lower()
        for kw in soft_skills_kws:
            if kw in text_lower:
                found.append(kw)
        return found

    def _generate_summary(self, title, company, rank, years, tags) -> str:
        tag_str = "、".join(tags[:3])
        year_str = f"{int(years)}年" if years else "若干年"
        return f"该岗位是 {company} 招聘的 {title}，职级为 {rank}。要求具备 {year_str} 经验，核心领域涵盖 {tag_str}。适合有相关技术背景的候选人。"

    def _empty_result(self, job: JobPosting) -> Dict[str, Any]:
        return {"标题": job.title, "公司": job.company, "简要总结": "解析失败"}
