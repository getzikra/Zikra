"""
Zikra — shared constants.
Import from here instead of hardcoding values in search.py and db.py.
"""
import os


def _flag(name, default):
    return os.getenv(name, default) not in ('0', 'false', 'False', 'no', '')


def _bounded_int(name, default, minimum, maximum):
    value = int(os.getenv(name, str(default)))
    if value < minimum or value > maximum:
        raise ValueError(f'{name} must be between {minimum} and {maximum}')
    return value

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

# Server-side distiller LLM (OpenAI-compatible chat completions endpoint).
# Point ZIKRA_LLM_BASE_URL at any proxy (LiteLLM, OpenRouter, ...) or leave
# the OpenAI default. Distillation is disabled unless an API key is set
# (ZIKRA_LLM_API_KEY, falling back to OPENAI_API_KEY).
LLM_BASE_URL = os.getenv('ZIKRA_LLM_BASE_URL', 'https://api.openai.com/v1').rstrip('/')
LLM_MODEL = os.getenv('ZIKRA_LLM_MODEL', 'gpt-4o-mini')
LLM_API_KEY = os.getenv('ZIKRA_LLM_API_KEY') or os.getenv('OPENAI_API_KEY') or ''
LLM_TIMEOUT_S = int(os.getenv('ZIKRA_LLM_TIMEOUT_S', '120'))
DISTILL_ENABLED = _flag('ZIKRA_DISTILL_ENABLED', '1')
DISTILL_MAX_TAIL_BYTES = int(os.getenv('ZIKRA_DISTILL_MAX_TAIL_BYTES', '200000'))
DISTILL_CONCURRENCY = int(os.getenv('ZIKRA_DISTILL_CONCURRENCY', '2'))

# Recurring-error promotion: identical errors logged this many times within
# the window become a searchable 'bug' memory (pending_review=1)
ERROR_PROMOTE_THRESHOLD = int(os.getenv('ZIKRA_ERROR_PROMOTE_THRESHOLD', '3'))
ERROR_PROMOTE_WINDOW_DAYS = int(os.getenv('ZIKRA_ERROR_PROMOTE_WINDOW_DAYS', '7'))

# Weekly consolidation of old conversation diaries into durable memories
CONSOLIDATE_ENABLED = _flag('ZIKRA_CONSOLIDATE_ENABLED', '1')
CONSOLIDATE_INTERVAL_HOURS = int(os.getenv('ZIKRA_CONSOLIDATE_INTERVAL_HOURS', '168'))
CONSOLIDATE_MIN_AGE_DAYS = int(os.getenv('ZIKRA_CONSOLIDATE_MIN_AGE_DAYS', '14'))
CONSOLIDATE_BATCH = int(os.getenv('ZIKRA_CONSOLIDATE_BATCH', '200'))
CONSOLIDATE_MAX_CLUSTER_CHARS = int(os.getenv('ZIKRA_CONSOLIDATE_MAX_CLUSTER_CHARS', '60000'))

# Nightly, project-scoped architecture snapshots. This intentionally has a
# separate model knob so memory distillation can stay on a small inexpensive
# model while architecture synthesis uses a long-context reviewer such as Kimi.
ARCHITECTURE_ENABLED = _flag('ZIKRA_ARCHITECTURE_ENABLED', '0')
ARCHITECTURE_MODEL = os.getenv('ZIKRA_ARCHITECTURE_MODEL', 'kimi-for-coding')
ARCHITECTURE_PROJECTS = tuple(
    p.strip().lower() for p in os.getenv('ZIKRA_ARCHITECTURE_PROJECTS', '').split(',')
    if p.strip()
)
ARCHITECTURE_HOUR = _bounded_int('ZIKRA_ARCHITECTURE_HOUR', 2, 0, 23)
ARCHITECTURE_TIMEZONE = os.getenv('ZIKRA_ARCHITECTURE_TIMEZONE', 'America/New_York')
ARCHITECTURE_SOURCE_LIMIT = _bounded_int('ZIKRA_ARCHITECTURE_SOURCE_LIMIT', 300, 1, 2000)
ARCHITECTURE_MAX_SOURCE_CHARS = _bounded_int(
    'ZIKRA_ARCHITECTURE_MAX_SOURCE_CHARS', 180000, 10000, 1000000)
ARCHITECTURE_MAX_COMPLETION_TOKENS = _bounded_int(
    'ZIKRA_ARCHITECTURE_MAX_COMPLETION_TOKENS', 12000, 1000, 64000)
ARCHITECTURE_TIMEOUT_S = _bounded_int(
    'ZIKRA_ARCHITECTURE_TIMEOUT_S', 600, 30, 3600)
ARCHITECTURE_DRAFT_RETENTION = _bounded_int(
    'ZIKRA_ARCHITECTURE_DRAFT_RETENTION', 30, 1, 500)
ARCHITECTURE_LEASE_SECONDS = _bounded_int(
    'ZIKRA_ARCHITECTURE_LEASE_SECONDS', 900, 120, 7200)
ARCHITECTURE_PROMPT_VERSION = 'architecture-twin-v1'
