import math
from datetime import datetime, timezone


def score(raw: float, mem: dict) -> float:
    """
    Re-ranks search results using decay, frequency, and confidence.
    Applied post-search on top-K candidates only — not a full table scan.
    """
    try:
        created = datetime.fromisoformat(mem["created_at"].replace("Z", "+00:00"))
        age_days = max(0, (datetime.now(timezone.utc) - created).days)
    except Exception:
        age_days = 0

    decay = max(0.05, math.exp(-0.693 * age_days / 30))
    freq  = 1.0 + 0.1 * math.log1p(mem.get("access_count") or 0)
    conf  = float(mem.get("confidence_score") or 1.0)
    return raw * decay * freq * conf
