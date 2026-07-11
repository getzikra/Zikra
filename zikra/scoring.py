import logging
import math
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Configurable via env vars — defaults preserve prior behaviour
DECAY_DAYS       = max(1, int(float(os.getenv('ZIKRA_DECAY_DAYS', '30'))))
FREQUENCY_WEIGHT = float(os.getenv('ZIKRA_FREQUENCY_WEIGHT', '0.1'))
PIN_MULTIPLIER   = float(os.getenv('ZIKRA_PIN_MULTIPLIER', '1.5'))


def _parse_ts(value):
    if not value:
        return None
    try:
        if isinstance(value, datetime):
            ts = value
        else:
            ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    except Exception:
        return None


def _idle_days(mem: dict) -> int:
    """Days since the memory was last touched: retrieval resets the decay
    clock, so the reference point is max(created_at, last_accessed_at)."""
    created = _parse_ts(mem.get("created_at"))
    accessed = _parse_ts(mem.get("last_accessed_at"))
    ref = max(t for t in (created, accessed) if t is not None) if (created or accessed) else None
    if ref is None:
        logger.warning(f'No usable timestamp on memory {mem.get("id") or mem.get("title")!r}')
        return 0
    return max(0, (datetime.now(timezone.utc) - ref).days)


def compute_score(mem: dict) -> float:
    """
    Absolute memory health score (0–1), independent of search query.
    Used for the UI decay gauge.
    """
    decay = max(0.05, math.exp(-0.693 * _idle_days(mem) / DECAY_DAYS))
    freq  = 1.0 + FREQUENCY_WEIGHT * math.log1p(mem.get("access_count") or 0)
    conf  = float(mem.get("confidence_score") or 1.0)
    pin   = PIN_MULTIPLIER if mem.get("pinned") else 1.0
    return min(1.0, decay * freq * conf * pin)


def score(raw: float, mem: dict) -> float:
    """
    Re-ranks search results using decay, frequency, confidence, and pin.
    Applied post-search on top-K candidates only — not a full table scan.
    """
    decay = max(0.05, math.exp(-0.693 * _idle_days(mem) / DECAY_DAYS))
    freq  = 1.0 + FREQUENCY_WEIGHT * math.log1p(mem.get("access_count") or 0)
    conf  = float(mem.get("confidence_score") or 1.0)
    pin   = PIN_MULTIPLIER if mem.get("pinned") else 1.0
    return raw * decay * freq * conf * pin
