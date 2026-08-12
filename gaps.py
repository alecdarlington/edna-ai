"""
gaps.py — Log and monitor query failures (gaps in knowledge base coverage)
          Also comprehensive activity logging for debugging

A gap is detected when:
1. Search returns zero recipes AND zero theory chunks, OR
2. Edna's reply contains "no tengo / no está incluida" phrasing

Activity log captures all user interactions and system events.
"""

import json
import os
from datetime import datetime


GAPS_FILE = "gaps.jsonl"
ACTIVITY_FILE = "activity.jsonl"


def detect_gap(
    question: str,
    route_type: str,
    num_recipes: int,
    num_theory: int,
    reply: str,
) -> dict | None:
    """
    Detect if this query resulted in a gap.

    Returns a gap record (dict) if detected, else None.
    Note: Ignores API errors (route_type='error')—those are system issues, not gaps.
    """
    # Ignore API errors; they're not knowledge gaps
    if route_type == "error":
        return None

    # Criterion 1: zero results
    if num_recipes == 0 and num_theory == 0:
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "question": question,
            "route": route_type,
            "recipes_found": num_recipes,
            "theory_found": num_theory,
            "reply_excerpt": reply[:200],
            "reason": "zero_results",
        }

    # Criterion 2: Edna's "I don't have / not included" phrasing
    # (case-insensitive, strip accents for robustness)
    import unicodedata

    def norm(text):
        return "".join(
            c for c in unicodedata.normalize("NFD", text.lower())
            if unicodedata.category(c) != "Mn"
        )

    reply_norm = norm(reply)
    no_tengo_phrases = [
        "no tengo",
        "no esta incluida",
        "no esta en el material",
        "no aparece",
        "no se encuentra",
    ]
    if any(phrase in reply_norm for phrase in no_tengo_phrases):
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "question": question,
            "route": route_type,
            "recipes_found": num_recipes,
            "theory_found": num_theory,
            "reply_excerpt": reply[:200],
            "reason": "edna_no_tengo",
        }

    return None


def log_gap(gap: dict) -> None:
    """Append a gap record to gaps.jsonl."""
    with open(GAPS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(gap, ensure_ascii=False) + "\n")


def read_gaps(limit: int = 100) -> list[dict]:
    """
    Read all gaps from gaps.jsonl, newest first, limited to `limit` entries.
    """
    if not os.path.exists(GAPS_FILE):
        return []

    gaps = []
    try:
        with open(GAPS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        gaps.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except OSError:
        pass

    # Return in reverse order (most recent first) and limit
    return list(reversed(gaps))[:limit]


def get_gap_counts() -> dict:
    """Return aggregate statistics about gaps."""
    gaps = read_gaps(limit=10000)  # read all
    counts = {}
    for gap in gaps:
        reason = gap.get("reason", "unknown")
        route = gap.get("route", "unknown")
        counts[(reason, route)] = counts.get((reason, route), 0) + 1
    return counts


# ── Activity logging (comprehensive trace of all events) ────────────────────────

def log_activity(event_type: str, details: dict) -> None:
    """
    Log an activity event for debugging and audit purposes.

    event_type: 'query', 'search', 'api_call', 'error', 'gap', etc.
    details: dict with event-specific data
    """
    record = {
        "timestamp": datetime.utcnow().isoformat(),
        "event_type": event_type,
        **details,
    }
    try:
        with open(ACTIVITY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass  # Silently fail if we can't write to log


def read_activity(limit: int = 500) -> list[dict]:
    """Read most recent activity log entries, newest first."""
    if not os.path.exists(ACTIVITY_FILE):
        return []

    activities = []
    try:
        with open(ACTIVITY_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        activities.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except OSError:
        pass

    return list(reversed(activities))[:limit]
