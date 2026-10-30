"""
Skill Extractor using FlashText - fast keyword matching
"""

from flashtext import KeywordProcessor

# Core skills for Geo/GIS/DevOps
SKILL_CATEGORIES = {
    'cloud': [
        'aws', 'azure', 'gcp', 'google cloud', 'cloudformation', 'cloudwatch',
        'ec2', 's3', 'lambda', 'ecs', 'eks', 'kube', 'kubernetes',
        'terraform', 'cloudformation', 'ansible', 'chef', 'puppet'
    ],
    'devops': [
        'ci/cd', 'jenkins', 'gitlab', 'github actions', 'circleci', 'travis',
        'docker', 'containerd', 'podman', 'helm', 'argocd',
        'prometheus', 'grafana', 'elk', 'splunk', 'datadog',
        'sre', 'site reliability', 'observability', 'monitoring'
    ],
    'gis': [
        'gis', 'geographic', 'geospatial', 'spatial', 'mapping',
        'arcgis', 'qgis', 'postgis', 'geoserver', 'mapbox',
        'geotiff', 'shapefile', 'geojson', 'wms', 'wfs', 'wmts',
        'gdal', 'ogr', 'proj', 'geodesy', 'coordinate', 'projection',
        'epsg', 'crs', 'srid', 'rtk', 'gnss', 'gps'
    ],
    'data': [
        'sql', 'postgresql', 'mysql', 'mongodb', 'redis', 'elasticsearch',
        'kafka', 'spark', 'hadoop', 'hive', 'databricks',
        'pandas', 'numpy', 'etl', 'elt', 'pipeline', 'data lake'
    ],
    'coding': [
        'python', 'java', 'javascript', 'typescript', 'go', 'rust',
        'c++', 'c#', 'ruby', 'scala', 'kotlin', 'swift',
        'git', 'rest', 'graphql', 'api', 'microservices'
    ]
}

# Build FlashText processor
kp = KeywordProcessor(case_sensitive=False)
for category, skills in SKILL_CATEGORIES.items():
    for skill in skills:
        kp.add_keyword(skill, category)

def extract_skills(text: str) -> dict:
    """Extract skills from job description"""
    if not text:
        return {'categories': [], 'skills': [], 'score': 0}

    # Clean text
    text_clean = text.lower()

    # Extract using FlashText
    found = kp.extract_keywords(text_clean)

    # Count categories
    categories = list(set(found))
    skills = found

    # Score = number of unique skill matches
    score = len(set(found))

    return {
        'categories': categories,
        'skills': skills,
        'score': score,
        'skill_count': len(found)
    }

def calculate_match_score(job: dict, target_skills: list = None) -> float:
    """Calculate how well a job matches target skills"""
    if target_skills is None:
        target_skills = ['gis', 'geospatial', 'python', 'aws', 'docker', 'kubernetes']

    description = job.get('description', '') or ''
    title = job.get('title', '') or ''

    text = f"{title} {description}".lower()

    score = 0
    matched = []
    for skill in target_skills:
        if skill.lower() in text:
            score += 1
            matched.append(skill)

    # Return percentage match
    return {
        'score': score,
        'max_score': len(target_skills),
        'percentage': round(score / len(target_skills) * 100, 1),
        'matched': matched
    }
