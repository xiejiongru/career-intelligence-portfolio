"""
Country utilities - simple matching without country-converter warnings
"""
import logging
import re

logger = logging.getLogger(__name__)

# Simple country name to code mapping
COUNTRY_CODES = {
    'france': 'fr',
    'netherlands': 'nl',
    'switzerland': 'ch',
    'belgium': 'be',
    'australia': 'au',
    'china': 'cn',
    'luxembourg': 'lu',
    'denmark': 'dk',
    'germany': 'de',
    'singapore': 'sg',
    'spain': 'es',
    'italy': 'it',
    'united kingdom': 'uk',
    'uk': 'uk',
    'united arab emirates': 'ae',
    'greece': 'gr',
    'philippines': 'ph',
}

def is_allowed_country(location: str, allowed_countries: list, mapping: dict = None) -> bool:
    """Check if location matches allowed countries"""
    if not allowed_countries:
        return True

    location = location.lower().strip()
    if not location or location == 'unknown':
        return False

    # Check for invalid/non-country locations first
    invalid_prefixes = ['mo - globe', 'metropolitan', 'worldwide', 'remote', 'home']
    for prefix in invalid_prefixes:
        if location.startswith(prefix) or prefix in location:
            return False

    # Build allowed set with both names and codes
    allowed_set = set()
    for c in allowed_countries:
        cl = c.lower()
        allowed_set.add(cl)
        # Add ISO code if we know it
        if cl in COUNTRY_CODES:
            allowed_set.add(COUNTRY_CODES[cl])

    # Extract country part from location (after last comma)
    parts = [p.strip() for p in location.split(',')]
    country_part = parts[-1] if parts else location

    # Clean the country part (remove HTML, department codes, etc)
    country_part = re.sub(r'<.*$', '', country_part).strip()
    country_part = re.sub(r'\s*\(\d+\)', '', country_part).strip()

    # Check if the country part matches any allowed country
    for allowed in allowed_set:
        if country_part == allowed:
            return True
        if allowed in country_part.split():
            return True
        if country_part.endswith(allowed):
            return True

    # Handle French department codes like "Paris (75)", "Grenoble (38)"
    dept_match = re.search(r'\((\d+)\)', location)
    if dept_match:
        dept_code = int(dept_match.group(1))
        if 1 <= dept_code <= 95:
            if 'france' in allowed_set:
                return True

    return False
