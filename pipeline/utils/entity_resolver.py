"""
Entity Resolution & Data Cleaning Layer (v2)
"""
from __future__ import annotations

import html as _html  # for unescape
import logging
import re
from typing import Optional
from urllib.parse import parse_qs, urlparse

from rapidfuzz import process

from ..ingestion.models import JobPosting

logger = logging.getLogger(__name__)

# ── Score threshold for fuzzy matching ──────────────────────────────────────
FUZZY_THRESHOLD = 82   # Below this score, keep the original value instead of fuzzy matching

# ── Company name whitelist (exact match first) ──────────────────────────────
# key: lowercase canonical form -> value: display name.
# Fictional examples for the public snapshot; the private pipeline keeps the
# production whitelist.
KNOWN_COMPANIES: dict[str, str] = {
    "acme": "Acme Corp",
    "acme corp": "Acme Corp",
    "acme corporation": "Acme Corp",
    "company a": "Company A",
    "company a france": "Company A",
    "company b": "Company B",
    "company b international": "Company B",
    "company c": "Company C",
}

# ── Location whitelist ──────────────────────────────────────────────────────
# lowercase key -> canonical display name
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

# ── Job type normalization ───────────────────────────────────────────────────
# Normalize output formats from JobSpy / French sources / ATS APIs
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

# ── Remote label normalization ───────────────────────────────────────────────
REMOTE_NORM: dict[str, str] = {
    "yes": "Yes", "remote": "Yes", "télétravail": "Yes",
    "full remote": "Yes", "fully remote": "Yes", "100% remote": "Yes",
    "remoto": "Yes",
    "partial": "Partial", "partiel": "Partial", "hybrid": "Partial",
    "partially remote": "Partial", "occasionnel": "Partial",
    "no": "No", "non": "No", "onsite": "No", "sur site": "No",
    " présentiel": "No",
}

# ── URL tracking parameter blocklist ─────────────────────────────────────────
TRACKING_PARAMS: set[str] = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "msclkid", "dclid",
    "mc_cid", "mc_eid",
    "_ga", "_gl",
    "ref", "ref_src", "ref_url",
    "source", "src",
    "via", "igshid",
}

# ── HTML handling ────────────────────────────────────────────────────────────
_HTML_TAG_RE = re.compile(r'<[^>]+>')


def _strip_html(s: str) -> str:
    """Strip HTML tags, decode entities (e.g. &nbsp; -> space) and collapse whitespace."""
    s = _HTML_TAG_RE.sub(' ', s)
    s = _html.unescape(s)
    return re.sub(r'\s+', ' ', s).strip()


# ── Core functions ───────────────────────────────────────────────────────────

def normalize_company_name(raw: str) -> str:
    """
    Normalize company names:
    1. Strip HTML tags and decode entities (e.g. &nbsp; -> space)
    2. Exact whitelist match (case-insensitive)
    3. rapidfuzz WRatio fallback; keep the original value below the threshold

    The whitelist wins; rapidfuzz is the safety net.
    """
    if not raw:
        return "Unknown"
    name = _strip_html(raw.strip())
    key = name.lower()

    # Exact match
    if key in KNOWN_COMPANIES:
        return KNOWN_COMPANIES[key]

    # Fuzzy match: WRatio with score_cutoff 82 (normalized 0-100)
    # Returns (value, score, dict_key)
    best = process.extractOne(key, KNOWN_COMPANIES, score_cutoff=FUZZY_THRESHOLD)
    if best is not None:
        best_value, score, best_key = best
        return KNOWN_COMPANIES[best_key]

    return name


def normalize_location(raw: str) -> str:
    """
    Normalize location names:
    1. Exact whitelist match
    2. rapidfuzz fallback
    3. Return the original value with whitespace collapsed
    """
    if not raw:
        return "Unknown"
    loc = raw.strip()
    key = loc.lower()

    # Exact match
    if key in KNOWN_LOCATIONS:
        return KNOWN_LOCATIONS[key]

    # Fuzzy match
    best = process.extractOne(key, KNOWN_LOCATIONS, score_cutoff=FUZZY_THRESHOLD)
    if best is not None:
        best_value, score, best_key = best
        return KNOWN_LOCATIONS[best_key]

    # Collapse whitespace and return the original value
    return re.sub(r'\s+', ' ', loc)


def normalize_job_type(raw: Optional[str]) -> Optional[str]:
    """Normalize contract type labels."""
    if not raw:
        return None
    key = str(raw).strip().lower()
    return JOB_TYPE_NORM.get(key, raw.strip())


def normalize_remote(raw: Optional[str]) -> Optional[str]:
    """Normalize remote-work labels."""
    if not raw:
        return None
    key = str(raw).strip().lower()
    return REMOTE_NORM.get(key, raw.strip())


def clean_url(url: str) -> str:
    """Remove tracking parameters from a URL while keeping the core address."""
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
    """Run full normalization and cleaning on a single JobPosting."""
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
    # Preserve extension fields populated by the pipeline
    if hasattr(job, "structured_data"):
        cleaned.structured_data = job.structured_data
    if hasattr(job, "screening_results"):
        cleaned.screening_results = job.screening_results
    return cleaned


def clean_jobs(jobs: list[JobPosting]) -> list[JobPosting]:
    """Clean a batch of JobPosting objects."""
    return [clean_job(job) for job in jobs]
