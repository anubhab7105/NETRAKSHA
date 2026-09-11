"""Fairness & bias mitigation for face matching.

Evaluates face verification fairness across demographic and environmental conditions,
logs metrics per group for later audit, and flags low-confidence cases for manual
review to avoid unfair targeting.

Design:
- Keep the biometric threshold fixed (0.55) for transparency, but route the
  uncertainty band (0.45-0.65) to manual review instead of auto Green/Red.
  This band is where false-reject/false-accept rates diverge most across
  groups in ArcFace-style models.
- Record per-case fairness signals (gender/age band/quality) so aggregate
  disparity can be audited offline (see `fairness_report`).
- Environmental quality (blur, lighting, face size) is taken from
  `face_quality` and also forces manual review when the capture is poor —
  poor captures correlate with camera hardware and thus with deployment
  environment, not identity.
"""

from __future__ import annotations

import os
import statistics
from collections import defaultdict
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# In-memory fairness ledger (also persisted via audit log for durability)
# ---------------------------------------------------------------------------

_FAIRNESS_LEDGER: List[Dict[str, Any]] = []

# Demographic buckets for reporting
GENDER_BUCKETS = {"M", "F", "Other", "unknown"}
AGE_BUCKETS = ["<25", "25-40", "40-60", "60+"]


def _age_bucket(dob: Optional[str]) -> str:
    """Bucket age from YYYY-MM-DD or DD/MM/YYYY, fallback to unknown."""
    if not dob:
        return "unknown"
    try:
        # Try YYYY-MM-DD first
        if "-" in dob and len(dob.split("-")[0]) == 4:
            year = int(dob.split("-")[0])
        elif "-" in dob:
            year = int(dob.split("-")[-1])
        elif "/" in dob:
            year = int(dob.split("/")[-1])
        else:
            return "unknown"
        from datetime import datetime, timezone
        age = datetime.now(timezone.utc).year - year
        if age < 25:
            return "<25"
        if age < 40:
            return "25-40"
        if age < 60:
            return "40-60"
        return "60+"
    except Exception:
        return "unknown"


def _env_quality_bucket(quality_report: Optional[Dict[str, Any]]) -> str:
    """Bucket environmental quality from face_quality report."""
    if not quality_report or not isinstance(quality_report, dict):
        return "unknown"
    gate = quality_report.get("gate", "unknown")
    if gate == "failed":
        return "poor"
    # Check metrics
    metrics = quality_report.get("inputs", {}).get("live", {}).get("metrics", {}) if "inputs" in quality_report else {}
    if not metrics:
        metrics = quality_report.get("metrics", {})
    sharp = metrics.get("sharpness", 100)
    if sharp < 50:
        return "poor"
    if sharp < 100:
        return "fair"
    return "good"


def log_fairness_case(
    case_id: Optional[int],
    demographics: Optional[Dict[str, Any]],
    face_similarity: Optional[float],
    face_match: Optional[bool],
    quality_report: Optional[Dict[str, Any]] = None,
    low_confidence: bool = False,
) -> Dict[str, Any]:
    """Record a per-case fairness signal and return it for persistence.

    Called from the screening pipeline after face verification. Never raises.
    """
    try:
        gender = (demographics or {}).get("gender") or (demographics or {}).get("Gender") or "unknown"
        gender = str(gender).strip().title() if gender else "unknown"
        if gender not in {"M", "F", "Other"}:
            # Normalize Male/Female to M/F
            if gender.lower().startswith("m"):
                gender = "M"
            elif gender.lower().startswith("f"):
                gender = "F"
            else:
                gender = "unknown"

        dob = (demographics or {}).get("date_of_birth") or (demographics or {}).get("Date of Birth")
        age_b = _age_bucket(dob)
        env_b = _env_quality_bucket(quality_report)

        entry = {
            "case_id": case_id,
            "gender": gender,
            "age_bucket": age_b,
            "env_quality": env_b,
            "similarity": face_similarity,
            "match": face_match,
            "low_confidence": low_confidence,
        }
        _FAIRNESS_LEDGER.append(entry)
        # Keep ledger bounded
        if len(_FAIRNESS_LEDGER) > 5000:
            del _FAIRNESS_LEDGER[:1000]
        return entry
    except Exception:
        return {}


def get_fairness_report(limit: int = 200) -> Dict[str, Any]:
    """Aggregate fairness metrics for audit and UI.

    Returns per-group counts, mean similarity, and low-confidence rates.
    """
    if not _FAIRNESS_LEDGER:
        return {"total": 0, "groups": {}, "low_confidence_rate": 0.0, "note": "No cases yet"}

    total = len(_FAIRNESS_LEDGER)
    low_conf = sum(1 for e in _FAIRNESS_LEDGER if e.get("low_confidence"))

    # Group by gender
    by_gender: Dict[str, List[float]] = defaultdict(list)
    by_age: Dict[str, List[float]] = defaultdict(list)
    by_env: Dict[str, List[float]] = defaultdict(list)

    for e in _FAIRNESS_LEDGER[-limit:]:
        sim = e.get("similarity")
        if sim is None:
            continue
        by_gender[e.get("gender", "unknown")].append(float(sim))
        by_age[e.get("age_bucket", "unknown")].append(float(sim))
        by_env[e.get("env_quality", "unknown")].append(float(sim))

    def _stats(vals: List[float]) -> Dict[str, Any]:
        if not vals:
            return {"count": 0, "mean": None, "std": None}
        return {
            "count": len(vals),
            "mean": round(statistics.mean(vals), 3),
            "std": round(statistics.pstdev(vals), 3) if len(vals) > 1 else 0.0,
            "min": round(min(vals), 3),
            "max": round(max(vals), 3),
        }

    return {
        "total": total,
        "low_confidence_count": low_conf,
        "low_confidence_rate": round(low_conf / total, 3) if total else 0.0,
        "by_gender": {k: _stats(v) for k, v in by_gender.items()},
        "by_age": {k: _stats(v) for k, v in by_age.items()},
        "by_env_quality": {k: _stats(v) for k, v in by_env.items()},
        "threshold": 0.55,
        "low_conf_band": [0.45, 0.65],
        "note": "Balanced evaluation requires diverse enrollment. Route low-confidence to manual review.",
    }


def is_low_confidence(similarity: Optional[float]) -> bool:
    """Check if similarity is in the low-confidence band that should be manually reviewed."""
    if similarity is None:
        return False
    return 0.45 <= float(similarity) <= 0.65
