"""
Zikra — shared constants.
Import from here instead of hardcoding values in search.py and db.py.
"""
import os


def _flag(name, default):
    return os.getenv(name, default) not in ('0', 'false', 'False', 'no', '')

# Token budget per result slot (chars / CHARS_PER_TOKEN applied in search.py)
SNIPPET_LENGTHS = [500, 300, 200, 150, 150]

# Number of vector candidates fetched before re-ranking
VECTOR_SEARCH_K = 20

# Default role assigned to new tokens when none is specified
DEFAULT_TOKEN_ROLE = 'developer'

# Write-time capture
PROJECT_RECLASSIFY_ENABLED = _flag('ZIKRA_PROJECT_RECLASSIFY_ENABLED', '1')
PROJECT_RECLASSIFY_TYPES = {'conversation', 'diary', 'auto-compact'}
PROJECT_RECLASSIFY_K = int(os.getenv('ZIKRA_PROJECT_RECLASSIFY_K', '9'))
PROJECT_RECLASSIFY_MIN_SIM = float(os.getenv('ZIKRA_PROJECT_RECLASSIFY_MIN_SIM', '0.55'))
PROJECT_RECLASSIFY_MIN_AGREE = float(os.getenv('ZIKRA_PROJECT_RECLASSIFY_MIN_AGREE', '0.6'))
PROJECT_RECLASSIFY_MIN_VOTES = int(os.getenv('ZIKRA_PROJECT_RECLASSIFY_MIN_VOTES', '3'))
SAVE_DEDUP_ENABLED = _flag('ZIKRA_SAVE_DEDUP_ENABLED', '1')
SAVE_DEDUP_TYPES = {'conversation', 'diary', 'auto-compact'}
SAVE_DEDUP_SIM_THRESHOLD = float(os.getenv('ZIKRA_SAVE_DEDUP_SIM_THRESHOLD', '0.90'))
SAVE_DEDUP_WINDOW_MIN = int(os.getenv('ZIKRA_SAVE_DEDUP_WINDOW_MIN', '45'))
