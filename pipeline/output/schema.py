"""
Output schema — single source of truth for JSON and CSV output.
"""
from dataclasses import dataclass

from pipeline.ingestion.models import JobPosting


@dataclass(frozen=True)
class Field:
    csv_name: str
    json_key: str


OUTPUT_FIELDS = [
    # Job basics
    Field("Id", "id"),
    Field("Title", "title"),
    Field("Company", "company"),
    Field("Location", "location"),
    Field("Site", "site"),
    Field("Job_Type", "job_type"),
    Field("Salary", "salary"),
    Field("Remote", "remote"),
    Field("Date_Posted", "date_posted"),
    Field("Description", "description"),
    Field("URL", "url"),
    # Score
    Field("Final_Score", "final_score"),
    Field("Thinking_Trace", "thinking_trace"),
    # Screening
    Field("Decision", "decision"),
    Field("Screening_Score", "screening_score"),
    Field("Filtered", "filtered"),
    Field("Filter_Reasons", "filter_reasons"),
    Field("Seniority", "seniority"),
    # 5-dimension match scores
    Field("Score_Tech_Match", "score_tech_match"),
    Field("Score_Function_Match", "score_function_match"),
    Field("Score_Domain_Match", "score_domain_match"),
    Field("Score_Experience_Match", "score_experience_match"),
    Field("Score_Growth_Potential", "score_growth_potential"),
    # Skills
    Field("GIS_Skills", "gis_skills"),
    Field("Data_Skills", "data_skills"),
    Field("DevOps_Skills", "devops_skills"),
    Field("Programming_Skills", "programming_skills"),
    Field("Missing_Skills", "missing_skills"),
    # Gap analysis
    Field("Risk_Factors", "risk_factors"),
    Field("Leverage_Points", "leverage_points"),
    Field("Summary", "summary"),
]


CSV_FIELDNAMES = [f.csv_name for f in OUTPUT_FIELDS]


def serialize_job(job: JobPosting) -> dict:
    screening = getattr(job, "screening_results", {}) or {}
    match_scores = screening.get("match_scores", {})
    skills = screening.get("skills", {})
    gap = screening.get("gap_analysis", {})

    return {
        "id": job.id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "site": getattr(job, "site", "unknown"),
        "job_type": job.job_type or "",
        "salary": job.salary or "",
        "remote": job.remote or "",
        "date_posted": job.date_posted or "",
        "description": job.description,
        "url": job.url,
        "final_score": round(job.final_score, 1),
        "thinking_trace": getattr(job, "thinking_trace", ""),
        "decision": screening.get("decision", "unknown"),
        "screening_score": screening.get("score", 0),
        "filtered": screening.get("filtered", False),
        "filter_reasons": screening.get("filter_reasons", []),
        "seniority": screening.get("seniority", ""),
        "score_tech_match": match_scores.get("tech_match", 0),
        "score_function_match": match_scores.get("function_match", 0),
        "score_domain_match": match_scores.get("domain_match", 0),
        "score_experience_match": match_scores.get("experience_match", 0),
        "score_growth_potential": match_scores.get("growth_potential", 0),
        "gis_skills": skills.get("gis", []),
        "data_skills": skills.get("data", []),
        "devops_skills": skills.get("devops", []),
        "programming_skills": skills.get("programming", []),
        "missing_skills": gap.get("missing_skills", []) or getattr(job, "missing_skills", []),
        "risk_factors": gap.get("risk_factors", []),
        "leverage_points": gap.get("leverage_points", []),
        "summary": screening.get("summary", ""),
    }


def job_to_csv_row(job: JobPosting) -> dict:
    data = serialize_job(job)
    row = {}
    for field in OUTPUT_FIELDS:
        val = data.get(field.json_key, "")
        if isinstance(val, list):
            val = " | ".join(str(v) for v in val)
        elif isinstance(val, bool):
            val = str(val)
        row[field.csv_name] = val
    return row
