"""Rule-based Risk Engine — composite screening assessment.

Aggregates results from all pipeline modules and produces a final risk
verdict (Green / Yellow / Red) with a composite risk score and
recommendations for the reviewing officer.

Hard flag rules (per plan.md §1.6):
  * Demographic Mismatch (Altered DOB/Name)  → Forces RED or YELLOW
  * Watchlist Hit                             → Forces RED
  * Face Verification Mismatch               → Forces RED
  * Liveness Failure                          → Forces at least YELLOW
  * Any Module Inconclusive                   → Forces at least YELLOW

The engine never produces a verdict on its own — it only flags risk.
Only a human officer can deny entry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional


@dataclass
class RiskAssessment:
    """The output of the risk engine."""
    verdict: str              # "Green" | "Yellow" | "Red"
    risk_score: float         # 0.0 (safe) to 1.0 (maximum risk)
    recommendations: List[str]
    flags: List[str]          # specific flags that triggered escalation
    module_summary: dict      # per-module summary for audit

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "risk_score": round(self.risk_score, 4),
            "recommendations": self.recommendations,
            "flags": self.flags,
            "module_summary": self.module_summary,
        }


def assess_risk(
    demographic_result: Optional[dict] = None,
    tamper_score: Optional[float] = None,
    tamper_status: str = "ok",
    deepfake_score: Optional[float] = None,
    deepfake_status: str = "ok",
    face_similarity: Optional[float] = None,
    face_match: Optional[bool] = None,
    face_status: str = "ok",
    liveness_live: Optional[bool] = None,
    liveness_score: Optional[float] = None,
    liveness_status: str = "ok",
    watchlist_hit: bool = False,
    watchlist_result: Optional[dict] = None,
    gemini_face_match: Optional[dict] = None,
    gemini_photo_tamper: Optional[bool] = None,
) -> RiskAssessment:
    """Evaluate composite risk from all module outputs.

    Each parameter corresponds to the output of one pipeline module.
    Missing/None values are treated as inconclusive.

    Returns:
        RiskAssessment with verdict, score, flags, and recommendations.
    """
    flags: List[str] = []
    recommendations: List[str] = []
    risk_components: List[float] = []
    min_verdict = "Green"  # will be escalated by hard rules

    # --- Watchlist (highest priority) ---
    if watchlist_hit:
        flags.append("WATCHLIST_HIT")
        min_verdict = "Red"
        risk_components.append(1.0)
        recommendations.append(
            "CRITICAL: Traveler matches a watchlist entry. "
            "Recommend immediate escalation to supervisor for review."
        )

    # --- Demographic Parity ---
    if demographic_result is not None:
        overall_match = demographic_result.get("overall_match", True)
        critical = demographic_result.get("critical_mismatches", [])
        mismatch_fields = demographic_result.get("mismatch_fields", [])

        if critical:
            flags.append(f"DEMOGRAPHIC_CRITICAL_MISMATCH:{','.join(critical)}")
            min_verdict = _escalate(min_verdict, "Red")
            risk_components.append(0.95)
            recommendations.append(
                f"CRITICAL: Document demographics do not match database for: "
                f"{', '.join(critical)}. Possible document forgery or identity fraud."
            )
        elif mismatch_fields:
            flags.append(f"DEMOGRAPHIC_MISMATCH:{','.join(mismatch_fields)}")
            min_verdict = _escalate(min_verdict, "Yellow")
            risk_components.append(0.6)
            recommendations.append(
                f"WARNING: Minor demographic discrepancies in: "
                f"{', '.join(mismatch_fields)}. Verify with original documents."
            )
        else:
            risk_components.append(0.0)
    else:
        # No demographic data available
        risk_components.append(0.3)

    # --- Face Verification (InsightFace local + Gemini 3-way) ---
    if face_status == "inconclusive":
        flags.append("FACE_VERIFICATION_INCONCLUSIVE")
        min_verdict = _escalate(min_verdict, "Yellow")
        risk_components.append(0.5)
        recommendations.append(
            "Face verification module was inconclusive. Manual face comparison required."
        )
    elif face_match is False:
        flags.append("FACE_MISMATCH")
        min_verdict = _escalate(min_verdict, "Red")
        risk_components.append(0.9)
        recommendations.append(
            "CRITICAL: Face on document does not match live capture. "
            "Possible impersonation or photo substitution."
        )
    elif face_similarity is not None:
        # Score inversely: high similarity = low risk
        face_risk = max(0.0, 1.0 - face_similarity)
        risk_components.append(face_risk)

    # Gemini 3-way face match (supplementary)
    if gemini_face_match is not None:
        live_vs_doc = gemini_face_match.get("live_vs_doc_match")
        if live_vs_doc is False:
            flags.append("GEMINI_FACE_LIVE_VS_DOC_MISMATCH")
            min_verdict = _escalate(min_verdict, "Red")
            risk_components.append(0.85)

    # Gemini photo tamper
    if gemini_photo_tamper is True:
        flags.append("GEMINI_PHOTO_TAMPER_ANOMALY")
        min_verdict = _escalate(min_verdict, "Yellow")
        risk_components.append(0.7)
        recommendations.append(
            "AI detected possible photo tampering/splicing on the document."
        )

    # --- Tamper Detection ---
    if tamper_status == "inconclusive":
        flags.append("TAMPER_INCONCLUSIVE")
        min_verdict = _escalate(min_verdict, "Yellow")
        risk_components.append(0.4)
        recommendations.append(
            "Tamper detection module was inconclusive. Inspect document physically."
        )
    elif tamper_score is not None:
        risk_components.append(tamper_score)
        if tamper_score >= 0.7:
            flags.append("HIGH_TAMPER_SCORE")
            min_verdict = _escalate(min_verdict, "Red")
            recommendations.append(
                f"HIGH RISK: Tamper score {tamper_score:.2f} indicates likely document manipulation. "
                "Inspect ELA heatmap overlay for tampered regions."
            )
        elif tamper_score >= 0.4:
            flags.append("MODERATE_TAMPER_SCORE")
            min_verdict = _escalate(min_verdict, "Yellow")
            recommendations.append(
                f"MODERATE: Tamper score {tamper_score:.2f} warrants manual document inspection."
            )

    # --- Deepfake Detection ---
    if deepfake_status == "inconclusive":
        flags.append("DEEPFAKE_INCONCLUSIVE")
        min_verdict = _escalate(min_verdict, "Yellow")
        risk_components.append(0.4)
    elif deepfake_score is not None:
        risk_components.append(deepfake_score)
        if deepfake_score >= 0.7:
            flags.append("HIGH_DEEPFAKE_SCORE")
            min_verdict = _escalate(min_verdict, "Yellow")
            recommendations.append(
                f"Deepfake score {deepfake_score:.2f} suggests possible synthetic image. "
                "Verify with additional biometric challenge."
            )

    # --- Liveness Detection ---
    if liveness_status == "inconclusive":
        flags.append("LIVENESS_INCONCLUSIVE")
        min_verdict = _escalate(min_verdict, "Yellow")
        risk_components.append(0.5)
        recommendations.append(
            "Liveness detection was inconclusive. Request a new webcam frame burst."
        )
    elif liveness_live is False:
        flags.append("LIVENESS_FAILURE")
        min_verdict = _escalate(min_verdict, "Yellow")
        risk_components.append(0.7)
        recommendations.append(
            "Liveness check failed — presentation attack suspected (static photo or screen). "
            "Require in-person blink verification."
        )
    elif liveness_score is not None:
        # Low liveness = higher risk
        live_risk = max(0.0, 1.0 - liveness_score)
        risk_components.append(live_risk * 0.5)  # weight liveness lower than face/tamper

    # --- Composite Risk Score ---
    if risk_components:
        risk_score = sum(risk_components) / len(risk_components)
    else:
        risk_score = 0.5  # no data at all → uncertain

    risk_score = max(0.0, min(1.0, risk_score))

    # --- Final Verdict ---
    # Score-based verdict (can only escalate above the hard-flag minimum)
    if risk_score >= 0.65:
        score_verdict = "Red"
    elif risk_score >= 0.35:
        score_verdict = "Yellow"
    else:
        score_verdict = "Green"

    verdict = _escalate(min_verdict, score_verdict)

    # Add default recommendation for green
    if verdict == "Green" and not recommendations:
        recommendations.append(
            "All checks passed. Low risk. Recommend clearance pending officer confirmation."
        )

    # Build module summary for audit
    module_summary = {
        "demographic": {
            "overall_match": demographic_result.get("overall_match") if demographic_result else None,
            "mismatch_fields": demographic_result.get("mismatch_fields", []) if demographic_result else [],
        },
        "tamper": {"score": tamper_score, "status": tamper_status},
        "deepfake": {"score": deepfake_score, "status": deepfake_status},
        "face_verification": {
            "similarity": face_similarity,
            "match": face_match,
            "status": face_status,
        },
        "liveness": {
            "live": liveness_live,
            "score": liveness_score,
            "status": liveness_status,
        },
        "watchlist": {
            "hit": watchlist_hit,
            "details": watchlist_result,
        },
        "gemini_ai": {
            "face_match": gemini_face_match,
            "photo_tamper": gemini_photo_tamper,
        },
    }

    return RiskAssessment(
        verdict=verdict,
        risk_score=round(risk_score, 4),
        recommendations=recommendations,
        flags=flags,
        module_summary=module_summary,
    )


# ---------------------------------------------------------------------------
# Verdict escalation helper
# ---------------------------------------------------------------------------

_VERDICT_LEVELS = {"Green": 0, "Yellow": 1, "Red": 2}
_LEVEL_TO_VERDICT = {0: "Green", 1: "Yellow", 2: "Red"}


def _escalate(current: str, proposed: str) -> str:
    """Return the higher-severity verdict between current and proposed."""
    c = _VERDICT_LEVELS.get(current, 0)
    p = _VERDICT_LEVELS.get(proposed, 0)
    return _LEVEL_TO_VERDICT[max(c, p)]
