import logging
import re
from typing import Any, Dict, List, Optional

from ..ingestion.models import JobPosting
from ..utils.nlp import detect_language, process_text

logger = logging.getLogger(__name__)

class GeomaticsJDParser:
    """
    Parser for urban planning, GIS and data-analysis job descriptions.
    Converts unstructured JDs into structured data.
    """

    # Canonical skill labels
    SKILL_MAPPING = {
        "sig": "GIS (Geographic Information System)",
        "gis": "GIS (Geographic Information System)",
        "géomatique": "Geomatics",
        "geomatics": "Geomatics",
        "cartographie": "Cartography / map visualization",
        "cartography": "Cartography / map visualization",
        "analyse spatiale": "Spatial analysis",
        "spatial analysis": "Spatial analysis",
    }

    # Technology categories
    TECH_CATEGORIES = {
        "gis_related": ["qgis", "arcgis", "postgis", "geoserver", "openlayers", "leaflet", "fme", "mapinfo", "autocad", "gdal", "ogr", "osm"],
        "languages": ["python", "sql", "r", "javascript", "typescript", "c++", "java", "php"],
        "data_skills": ["pandas", "numpy", "postgresql", "mysql", "mongodb", "etl", "data analysis", "statistiques"],
        "tools": ["docker", "kubernetes", "git", "jenkins", "linux", "office", "excel"]
    }

    # Responsibility categories
    RESPONSIBILITY_MAPPING = {
        "Project management": ["chef de projet", "project management", "gestion de projet", "coordination"],
        "Data engineering / processing": ["data engineering", "traitement de données", "pipeline", "etl", "intégration"],
        "GIS analysis / spatial analysis": ["analyse spatiale", "spatial analysis", "cartographie", "modélisation"],
        "Team management": ["management", "équipe", "team lead", "encadrement"],
        "Business development": ["business development", "commercial", "vente", "partenariat"],
        "Methodology design": ["méthodologie", "conception", "design", "architecture"]
    }

    # Domain tags
    DOMAIN_TAGS_MAPPING = {
        "Urban planning": ["urbanisme", "urban planning", "aménagement"],
        "Public policy": ["politiques publiques", "public policy", "collectivité"],
        "Land management": ["foncier", "cadastre", "land management"],
        "Environment & resilience": ["environnement", "climat", "resilience", "écologie"],
        "Consulting": ["consulting", "conseil", "prestation"],
        "Data analysis": ["data analysis", "statistiques", "big data"],
        "Spatial data": ["données spatiales", "spatial data", "géodonnées"]
    }

    def __init__(self):
        pass

    def parse(self, job: JobPosting) -> Dict[str, Any]:
        """
        Core parsing entry point.
        """
        text = job.description
        lang = detect_language(text)
        doc = process_text(text, lang=lang)

        if not doc:
            return self._empty_result(job)

        # 1. Basic information
        title = job.title
        company = job.company
        location = [job.location] if job.location else []

        # 2. Experience requirements
        years, field_exp = self._extract_experience(text, doc)

        # 3. Seniority
        rank = self._determine_rank(years, text)

        # 4. Technical skills and normalization
        tech_skills = self._extract_tech_skills(text, doc)

        # 5. Responsibility categories
        responsibilities = self._extract_responsibilities(text)

        # 6. Constraints (mandatory vs nice-to-have)
        mandatory, bonus = self._extract_constraints(doc)

        # 7. Domain tags
        domain_tags = self._extract_domain_tags(text)

        # 8. Summary
        summary = self._generate_summary(title, company, rank, years, domain_tags)

        # 9. Merge results
        result = {
            "title": title,
            "company": company,
            "location": location,
            "job_type": job.job_type or "Unknown",
            "seniority": rank,
            "experience": {
                "minimum_years": years,
                "domain_experience": field_exp
            },
            "tech_skills": {
                "gis_related": tech_skills["gis_related"],
                "languages": tech_skills["languages"],
                "data_skills": tech_skills["data_skills"],
                "tools": tech_skills["tools"]
            },
            "responsibilities": responsibilities,
            "soft_skills": self._extract_soft_skills(text, doc),
            "constraints": {
                "mandatory": mandatory,
                "bonus": bonus
            },
            "domain_tags": domain_tags,
            "summary": summary
        }

        return result

    def _extract_experience(self, text: str, doc) -> (Optional[float], List[str]):
        text_lower = text.lower()
        years = None

        # Regex for years of experience
        # e.g., "8 ans d’expérience", "3-5 years", "min. 2 ans"
        match = re.search(r'(\d+)\s*(?:-|à|to)?\s*(\d+)?\s*(?:ans?|years?)', text_lower)
        if match:
            years = float(match.group(1))
        elif "confirmée" in text_lower or "confirmed" in text_lower:
            years = 5.0

        # Domain experience extraction (based on common domain keywords)
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
                return "Senior/Lead"
            if 5 <= years <= 7:
                return "Mid-Senior"
            if years < 5:
                return "Junior/Mid"

        # Fallback
        if is_manager:
            return "Lead/Team Lead"
        return "Mid/Undetermined"

    def _extract_tech_skills(self, text: str, doc) -> Dict[str, List[str]]:
        text_lower = text.lower()
        extracted = {cat: [] for cat in self.TECH_CATEGORIES}

        # 1. Bag-of-words matching against the preset vocabulary
        for cat, items in self.TECH_CATEGORIES.items():
            for item in items:
                # Simple word-boundary check
                if re.search(rf'\b{re.escape(item)}\b', text_lower):
                    extracted[cat].append(item.upper() if len(item) < 5 else item.capitalize())

        # 2. Skill normalization
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

        # Rule definitions
        mandatory_kws = ["required", "impératif", "exigé", "indispensable", "maîtrise"]
        bonus_kws = ["souhaité", "apprécié", "bonus", "idéalement", "plus", "atout"]

        for sent in doc.sents:
            sent_text = sent.text.lower()
            if any(kw in sent_text for kw in mandatory_kws):
                # Keep the sentence that states the requirement
                mandatory.append(sent.text.strip())
            elif any(kw in sent_text for kw in bonus_kws):
                bonus.append(sent.text.strip())

        return mandatory[:5], bonus[:5]  # Limit the number of items

    def _extract_domain_tags(self, text: str) -> List[str]:
        text_lower = text.lower()
        tags = []
        for domain, kws in self.DOMAIN_TAGS_MAPPING.items():
            if any(kw in text_lower for kw in kws):
                tags.append(domain)
        return list(set(tags))

    def _extract_soft_skills(self, text: str, doc) -> List[str]:
        # Simple extraction of common soft-skill keywords
        soft_skills_kws = ["autonomie", "rigueur", "aisance relationnelle", "travail en équipe", "curiosité"]
        found = []
        text_lower = text.lower()
        for kw in soft_skills_kws:
            if kw in text_lower:
                found.append(kw)
        return found

    def _generate_summary(self, title, company, rank, years, tags) -> str:
        tag_str = ", ".join(tags[:3])
        year_str = f"{int(years)} years" if years else "several years"
        return (
            f"This role is {title} at {company}, seniority {rank}. "
            f"It requires {year_str} of experience and covers {tag_str}. "
            f"Suitable for candidates with a relevant technical background."
        )

    def _empty_result(self, job: JobPosting) -> Dict[str, Any]:
        return {"title": job.title, "company": job.company, "summary": "Parsing failed"}
