import logging
from typing import Optional

import spacy

logger = logging.getLogger(__name__)

_models = {}

def get_spacy_model(lang: str = "en"):
    """
    Load and cache SpaCy models.
    'en' -> 'en_core_web_sm'
    'fr' -> 'fr_core_news_sm'
    """
    model_name = "en_core_web_sm" if lang == "en" else "fr_core_news_sm"

    if model_name not in _models:
        try:
            logger.info(f"Loading SpaCy model: {model_name}")
            _models[model_name] = spacy.load(model_name)
        except Exception as e:
            logger.error(f"Failed to load SpaCy model {model_name}: {e}")
            # Fallback or error out
            return None
    return _models[model_name]

def detect_language(text: str) -> str:
    """
    Simple language detection based on common French words.
    In a real app, you might use langdetect or similar.
    """
    french_indicators = [" et ", " le ", " la ", " les ", " dans ", " pour ", " avec ", " est ", " une "]
    text_lower = text.lower()
    fr_score = sum(1 for word in french_indicators if word in text_lower)

    # Very simple heuristic: if more than 2 french indicators, assume French
    return "fr" if fr_score > 2 else "en"

def process_text(text: str, lang: Optional[str] = None):
    """
    Process text with the appropriate SpaCy model.
    """
    if not lang:
        lang = detect_language(text)

    nlp = get_spacy_model(lang)
    if not nlp:
        return None

    return nlp(text)
