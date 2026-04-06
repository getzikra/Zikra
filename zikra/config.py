"""
Zikra Lite — shared constants.
Import from here instead of hardcoding values in search.py and db.py.
"""

# Token budget per result slot (chars / CHARS_PER_TOKEN applied in search.py)
SNIPPET_LENGTHS = [500, 300, 200, 150, 150]

# Number of vector candidates fetched before re-ranking
VECTOR_SEARCH_K = 20

# Default role assigned to new tokens when none is specified
DEFAULT_TOKEN_ROLE = 'admin'
