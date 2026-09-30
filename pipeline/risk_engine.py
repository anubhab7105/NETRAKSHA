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
    verdict: str
    risk_score: float
    recommendations: List[str]
    flags: List[str]
    module_summary: dict

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
    physical_score: Optional[float] = None,
    physical_status: str = "ok",
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
    registry_trust: Optional[dict] = None,
    db_face_pairs: Optional[dict] = None,
    iris_match: Optional[bool] = None,
    iris_quality: Optional[dict] = None,
    iris_liveness: Optional[dict] = None,
    document_quality_status: Optional[str] = None,
    document_quality_issues: Optional[list] = None,
    security_zones_status: Optional[str] = None,
    security_zones_score: Optional[float] = None,
    **kwargs
) -> RiskAssessment:
    """Evaluate composite risk from all module outputs.

    Each parameter corresponds to the output of one pipeline module.
    Missing/None values are treated as inconclusive.
    `registry_trust` is {"level": ..., "verified": bool, "reasons": [...]}:
    an `unverified` registry match floors the verdict at Yellow so a
    malicious single-writer entry can never read as Green; `legacy`
    (pre-dual-approval) rows add an informational flag but keep Green
    possible for demo continuity (see reconciliation report).
    `db_face_pairs` is {"doc_vs_db_match": bool|None,
    "live_vs_db_match": bool|None, "evidence": "local"|...}: an
    evidence-backed (local InsightFace) registry mismatch forces Red —
    a photo-substituted document can agree with the live impostor while
    disagreeing with the official record. Anything but local evidence
    (e.g. simulated guesses) is ignored here.

    Returns:
        RiskAssessment with verdict, score, flags, and recommendations.

    Unknown keyword arguments are rejected (TypeError) so a misspelled
    module output can never be silently dropped from scoring.
    """
    if kwargs:
        raise TypeError(
            f"assess_risk() got unexpected keyword(s): {sorted(kwargs)}"
        )
    flags: List[str] = []
    recommendations: List[str] = []
    risk_components: List[float] = []
    min_verdict = "Green"

    try:
        from pipeline.common import load_thresholds as _load_thr

        _thr = _load_thr()
    except Exception:
        _thr = {}
    FACE_LOW_CONF_BAND = (
        float(_thr.get("face_low_conf_low", 0.45)),
        float(_thr.get("face_low_conf_high", 0.65)),
    )
    _TAMPER_HIGH = float(_thr.get("tamper_high", 0.7))
    _TAMPER_MOD = float(_thr.get("tamper_moderate", 0.4))
    _PHYS_HIGH = float(_thr.get("physical_high", 0.7))
    _PHYS_MOD = float(_thr.get("physical_moderate", 0.4))
    _DF_HIGH = float(_thr.get("deepfake_high", 0.7))
    _RISK_RED = float(_thr.get("risk_red", 0.65))
    _RISK_YELLOW = float(_thr.get("risk_yellow", 0.35))


    if watchlist_hit:
        flags.append("WATCHLIST_HIT")
        min_verdict = "Red"
        risk_components.append(1.0)
        recommendations.append(
            "CRITICAL: Traveler matches a watchlist entry. "
            "Recommend immediate escalation to supervisor for review."
        )


    if demographic_result is not None and demographic_result != {}:
        overall_match = demographic_result.get("overall_match", False)
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

        risk_components.append(0.3)




    if registry_trust is not None and demographic_result is not None:
        level = registry_trust.get("level", "")
        reasons = ";".join(registry_trust.get("reasons", []) or [])
        if level == "unverified":
            flags.append(f"UNVERIFIED_REGISTRY_SOURCE:{reasons}"[:160])
            min_verdict = _escalate(min_verdict, "Yellow")
            risk_components.append(0.6)
            recommendations.append(
                "WARNING: The matching registry record was enrolled without "
                "dual approval or authority verification — it cannot vouch for "
                "this identity. Manual authority check required before clearance."
            )
        elif level == "legacy":
            flags.append("LEGACY_REGISTRY_NEEDS_REVERIFICATION")
            recommendations.append(
                "Note: the matching registry record predates dual-approval "
                "controls. Schedule it for authority re-verification "
                "(see reconciliation report)."
            )






    if isinstance(db_face_pairs, dict) and db_face_pairs.get("evidence") == "local":
        for key, flag, label in (
            ("doc_vs_db_match", "DOC_DB_FACE_MISMATCH", "document photo vs registry photo"),
            ("live_vs_db_match", "LIVE_DB_FACE_MISMATCH", "live capture vs registry photo"),
        ):
            if db_face_pairs.get(key) is False:
                flags.append(flag)
                min_verdict = _escalate(min_verdict, "Red")
                risk_components.append(0.9)
                recommendations.append(
                    f"CRITICAL: {label} do not match. Possible photo substitution "
                    f"or impersonation against the official registry record."
                )




    is_low_confidence = False
    if face_similarity is not None and FACE_LOW_CONF_BAND[0] <= face_similarity <= FACE_LOW_CONF_BAND[1]:
        is_low_confidence = True
        flags.append(f"FACE_LOW_CONFIDENCE:{face_similarity:.3f}")

        min_verdict = _escalate(min_verdict, "Yellow")
        risk_components.append(0.55)
        recommendations.append(
            f"Face similarity {face_similarity:.3f} is near the decision threshold (0.55) — low confidence. "
            "Manual officer review required to avoid bias. Environmental factors (lighting, camera quality) "
            "or demographic variations may have affected the score. Do not auto-clear."
        )
    if face_status == "inconclusive":
        flags.append("FACE_VERIFICATION_INCONCLUSIVE")
        min_verdict = _escalate(min_verdict, "Yellow")
        risk_components.append(0.5)
        recommendations.append(
            "Face verification module was inconclusive. Manual face comparison required."
        )
    elif face_match is False and not is_low_confidence:
        flags.append("FACE_MISMATCH")
        min_verdict = _escalate(min_verdict, "Red")
        risk_components.append(0.9)
        recommendations.append(
            "CRITICAL: Face on document does not match live capture. "
            "Possible impersonation or photo substitution."
        )
    elif face_similarity is not None and not is_low_confidence:

        face_risk = max(0.0, 1.0 - face_similarity)
        risk_components.append(face_risk)


    if gemini_face_match is not None:
        live_vs_doc = gemini_face_match.get("live_vs_doc_match")
        if live_vs_doc is False:
            flags.append("GEMINI_FACE_LIVE_VS_DOC_MISMATCH")
            min_verdict = _escalate(min_verdict, "Red")
            risk_components.append(0.85)


    if gemini_photo_tamper is True:
        flags.append("GEMINI_PHOTO_TAMPER_ANOMALY")
        min_verdict = _escalate(min_verdict, "Yellow")
        risk_components.append(0.7)
        recommendations.append(
            "AI detected possible photo tampering/splicing on the document."
        )


    if tamper_status == "inconclusive":
        flags.append("TAMPER_INCONCLUSIVE")
        min_verdict = _escalate(min_verdict, "Yellow")
        risk_components.append(0.4)
        recommendations.append(
            "Tamper detection module was inconclusive. Inspect document physically."
        )
    elif tamper_score is not None:
        risk_components.append(tamper_score)
        if tamper_score >= _TAMPER_HIGH:
            flags.append("HIGH_TAMPER_SCORE")
            min_verdict = _escalate(min_verdict, "Red")
            recommendations.append(
                f"HIGH RISK: Tamper score {tamper_score:.2f} indicates likely document manipulation. "
                "Inspect ELA heatmap overlay for tampered regions."
            )
        elif tamper_score >= _TAMPER_MOD:
            flags.append("MODERATE_TAMPER_SCORE")
            min_verdict = _escalate(min_verdict, "Yellow")
            recommendations.append(
                f"MODERATE: Tamper score {tamper_score:.2f} warrants manual document inspection."
            )


    if physical_status == "inconclusive":
        flags.append("PHYSICAL_FORGERY_INCONCLUSIVE")
        min_verdict = _escalate(min_verdict, "Yellow")
        risk_components.append(0.4)
        recommendations.append(
            "Physical-forgery checks were inconclusive. Inspect document physically."
        )
    elif physical_score is not None:
        risk_components.append(physical_score)
        if physical_score >= _PHYS_HIGH:
            flags.append("HIGH_PHYSICAL_FORGERY_SCORE")
            min_verdict = _escalate(min_verdict, "Red")
            recommendations.append(
                f"HIGH RISK: Physical-forgery score {physical_score:.2f} indicates likely "
                "document counterfeit/alteration. Inspect layout, portrait frame and MRZ print."
            )
        elif physical_score >= _PHYS_MOD:
            flags.append("MODERATE_PHYSICAL_FORGERY_SCORE")
            min_verdict = _escalate(min_verdict, "Yellow")
            recommendations.append(
                f"MODERATE: Physical-forgery score {physical_score:.2f} warrants manual document inspection."
            )


    if deepfake_status == "inconclusive":
        flags.append("DEEPFAKE_INCONCLUSIVE")
        min_verdict = _escalate(min_verdict, "Yellow")
        risk_components.append(0.4)
    elif deepfake_score is not None:
        risk_components.append(deepfake_score)
        if deepfake_score >= _DF_HIGH:
            flags.append("HIGH_DEEPFAKE_SCORE")
            min_verdict = _escalate(min_verdict, "Yellow")
            recommendations.append(
                f"Deepfake score {deepfake_score:.2f} suggests possible synthetic image. "
                "Verify with additional biometric challenge."
            )


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

        live_risk = max(0.0, 1.0 - liveness_score)
        risk_components.append(live_risk * 0.5)




    if iris_quality is not None and not iris_quality.get("usable", True):
        flags.append("IRIS_QUALITY_POOR")
        min_verdict = _escalate(min_verdict, "Yellow")
        risk_components.append(0.6)
        recommendations.append("Iris image quality poor — recapture eye in good light.")
    elif iris_match is False:
        flags.append("IRIS_MISMATCH")
        min_verdict = _escalate(min_verdict, "Red")
        risk_components.append(0.85)
        recommendations.append("Iris does not match enrolled template — possible impersonation.")
    elif iris_liveness is not None and iris_liveness.get("passed") is False:
        flags.append("IRIS_LIVENESS_FAILED")
        min_verdict = _escalate(min_verdict, "Yellow")
        risk_components.append(0.7)
        recommendations.append("Iris liveness failed — possible contact lens or replay.")
    elif iris_match is True:
        risk_components.append(0.0)


    if document_quality_status == "inconclusive":
        issues = ",".join(document_quality_issues or []) or "low quality"
        flags.append(f"DOCUMENT_QUALITY_FAILED:{issues}"[:160])
        min_verdict = _escalate(min_verdict, "Yellow")
        risk_components.append(0.6)
        recommendations.append(
            "Document image quality too low for reliable forensics "
            f"({issues}). Recapture in good light and re-screen."
        )

    if security_zones_status == "inconclusive":
        flags.append("SECURITY_ZONES_INCONCLUSIVE")
        min_verdict = _escalate(min_verdict, "Yellow")
        risk_components.append(0.4)
        recommendations.append(
            "Template/security-zone checks were inconclusive. Inspect layout and portrait zone physically."
        )
    elif security_zones_score is not None:
        risk_components.append(security_zones_score)
        if security_zones_score >= 0.7:
            flags.append("HIGH_SECURITY_ZONE_ANOMALY")
            min_verdict = _escalate(min_verdict, "Red")
            recommendations.append(
                f"HIGH RISK: Security-zone anomaly score {security_zones_score:.2f} — "
                "photo/zone layout deviates from the document template."
            )
        elif security_zones_score >= 0.4:
            flags.append("MODERATE_SECURITY_ZONE_ANOMALY")
            min_verdict = _escalate(min_verdict, "Yellow")
            recommendations.append(
                f"MODERATE: Security-zone anomaly score {security_zones_score:.2f} warrants manual inspection."
            )


    if risk_components:
        risk_score = sum(risk_components) / len(risk_components)
    else:
        risk_score = 0.5

    risk_score = max(0.0, min(1.0, risk_score))



    if risk_score >= _RISK_RED:
        score_verdict = "Red"
    elif risk_score >= _RISK_YELLOW:
        score_verdict = "Yellow"
    else:
        score_verdict = "Green"

    verdict = _escalate(min_verdict, score_verdict)


    if verdict == "Green" and not recommendations:
        recommendations.append(
            "All checks passed. Low risk. Recommend clearance pending officer confirmation."
        )


    module_summary = {
        "demographic": {
            "overall_match": demographic_result.get("overall_match") if demographic_result else None,
            "mismatch_fields": demographic_result.get("mismatch_fields", []) if demographic_result else [],
            "registry_trust": registry_trust,
        },
        "tamper": {"score": tamper_score, "status": tamper_status},
        "physical_forgery": {"score": physical_score, "status": physical_status},
        "deepfake": {"score": deepfake_score, "status": deepfake_status},
        "face_verification": {
            "similarity": face_similarity,
            "match": face_match,
            "status": face_status,
            "db_pairs": db_face_pairs,
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
        "document_quality": {
            "status": document_quality_status,
            "issues": document_quality_issues or [],
        },
        "security_zones": {
            "score": security_zones_score,
            "status": security_zones_status,
        },
    }

    return RiskAssessment(
        verdict=verdict,
        risk_score=round(risk_score, 4),
        recommendations=recommendations,
        flags=flags,
        module_summary=module_summary,
    )






_VERDICT_LEVELS = {"Green": 0, "Yellow": 1, "Red": 2}
_LEVEL_TO_VERDICT = {0: "Green", 1: "Yellow", 2: "Red"}


def _escalate(current: str, proposed: str) -> str:
    """Return the higher-severity verdict between current and proposed."""
    c = _VERDICT_LEVELS.get(current, 0)
    p = _VERDICT_LEVELS.get(proposed, 0)
    return _LEVEL_TO_VERDICT[max(c, p)]
