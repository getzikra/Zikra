import logging
import math
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Configurable via env vars — defaults preserve prior behaviour
DECAY_DAYS       = int(float(os.getenv('ZIKRA_DECAY_DAYS', '30')))
FREQUENCY_WEIGHT = float(os.getenv('ZIKRA_FREQUENCY_WEIGHT', '0.1'))


def score(raw: float, mem: dict) -> float:
    """
    Re-ranks search results using decay, frequency, and confidence.
    Applied post-search on top-K candidates only — not a full table scan.
    """
    try:
        created = datetime.fromisoformat(mem["created_at"].replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_days = max(0, (datetime.now(timezone.utc) - created).days)
    except Exception as e:
        logger.warning(f'Failed to parse created_at timestamp {mem.get("created_at")!r}: {e}')
        age_days = 0

    decay = max(0.05, math.exp(-0.693 * age_days / DECAY_DAYS))
    freq  = 1.0 + FREQUENCY_WEIGHT * math.log1p(mem.get("access_count") or 0)
    conf  = float(mem.get("confidence_score") or 1.0)
    return raw * decay * freq * conf
