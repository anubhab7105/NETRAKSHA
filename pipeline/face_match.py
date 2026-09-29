
from __future__ import annotations

import os
import threading
from typing import Optional

import numpy as np

from .common import (
    INSIGHTFACE_MODEL_ROOT,
    ModuleResult,
    inconclusive_result,
    load_image,
    new_evidence_path,
    ok_result,
    single_log,
)
from .face_quality import (
    RECAPTURE_GUIDANCE,
    QualityReport,
    assess_capture,
    assess_face,
    combine_reports,
)

MODULE_NAME = "face_match"



MATCH_THRESHOLD = 0.55

_face_analysis_lock = threading.Lock()
_face_analysis = None
_provider_used = None




_haar_lock = threading.Lock()
_haar_frontal = None
_haar_profile = None


def _haar_classifiers():
    global _haar_frontal, _haar_profile
    with _haar_lock:
        if _haar_frontal is not None or _haar_profile is not None:
            return _haar_frontal, _haar_profile
        try:
            import cv2

            frontal = cv2.CascadeClassifier(
                os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
            )
            profile = cv2.CascadeClassifier(
                os.path.join(cv2.data.haarcascades, "haarcascade_profileface.xml")
            )
            _haar_frontal = frontal if not frontal.empty() else None
            _haar_profile = profile if not profile.empty() else None
        except Exception:
            _haar_frontal, _haar_profile = None, None
        return _haar_frontal, _haar_profile


def _haar_fallback_codes(image_bgr) -> list:
    try:
        import cv2

        frontal, profile = _haar_classifiers()
        if frontal is None:
            return []
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        if len(frontal.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(50, 50))):
            return []
        if profile is not None:
            prof = profile.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(50, 50))
            if len(prof) == 0:
                flipped = cv2.flip(gray, 1)
                prof = profile.detectMultiScale(flipped, scaleFactor=1.1, minNeighbors=5, minSize=(50, 50))
            if len(prof):
                return ["side_angle"]
        return ["no_face"]
    except Exception:
        return []


def _quality_failure_result(doc_rep: QualityReport, live_rep: QualityReport) -> ModuleResult:
    quality = combine_reports(doc_rep, live_rep)
    target = quality["recapture_target"]
    reasons = quality["recapture_reasons"]
    detail = "; ".join(reasons) if reasons else "face image quality too poor for matching"
    return ModuleResult(
        module_name=MODULE_NAME,
        score=None,
        status="inconclusive",
        raw_output={
            "error": "inconclusive",
            "reason": f"face quality gate failed — recapture requested ({target}): {detail[:300]}",
            "quality_gate": "failed",
            "face_quality": {k: v for k, v in quality["inputs"].items()},
            "failed_quality_targets": quality["failed_targets"],
            "recapture_requested": True,
            "recapture_target": target,
            "recapture_reasons": reasons,
        },
        evidence_uri=None,
    )


def _get_face_analysis():
    global _face_analysis, _provider_used
    with _face_analysis_lock:
        if _face_analysis is not None:
            return _face_analysis
        import insightface
        from insightface.app import FaceAnalysis

        model_root = str(INSIGHTFACE_MODEL_ROOT)



        from onnxruntime import get_available_providers
        available = get_available_providers()
        pref = ("CUDAExecutionProvider", "ROCMExecutionProvider",
                "TensorrtExecutionProvider", "CoreMLExecutionProvider",
                "CPUExecutionProvider")
        providers = [p for p in pref if p in available] or ["CPUExecutionProvider"]
        app = FaceAnalysis(
            name="buffalo_l",
            root=model_root,
            providers=providers,
            allowed_modules=["detection", "recognition"],
        )

        bound = app.models.get("recognition")
        provider_used = "unknown"
        if hasattr(bound, "session"):
            provider_used = str(bound.session.get_providers())
        _provider_used = provider_used
        _face_analysis = app
        return _face_analysis





_REQUIRED_BUFFALO_FILES = ("det_10g.onnx", "w600k_r50.onnx")

_last_engine_error: Optional[str] = None


def _buffalo_pack_dir():
    import pathlib

    return pathlib.Path(str(INSIGHTFACE_MODEL_ROOT)) / "models" / "buffalo_l"


def buffalo_models_present() -> bool:
    try:
        pack = _buffalo_pack_dir()
        return all((pack / name).is_file() for name in _REQUIRED_BUFFALO_FILES)
    except Exception:
        return False


def local_engine_status() -> dict:
    return {
        "initialised": _face_analysis is not None,
        "models_present": buffalo_models_present(),
        "provider": _provider_used,
        "last_error": _last_engine_error,
    }


def prewarm_local_engine() -> bool:
    global _last_engine_error
    try:
        _get_face_analysis()
        _last_engine_error = None
        single_log(f"local face engine READY (provider={_provider_used})")
        return True
    except Exception as exc:
        _last_engine_error = f"{type(exc).__name__}: {str(exc)[:160]}"
        single_log(
            "local face engine UNAVAILABLE "
            f"({_last_engine_error}) — models_present={buffalo_models_present()}. "
            "Registry face legs (doc↔db, live↔db) will be N/A until the "
            "buffalo_l pack is provisioned (scripts/setup_vendor.sh) or the "
            "runtime can reach the model zoo."
        )
        return False


def _detect_faces(app, image_bgr: np.ndarray):
    faces = app.get(image_bgr)
    if not faces:
        return None, None, None

    def _area(f):
        b = getattr(f, "bbox", None)
        if b is None:
            return 0.0
        return max(0.0, (b[2] - b[0]) * (b[3] - b[1]))

    best = max(faces, key=_area)
    emb = np.asarray(best.embedding).reshape(-1)
    norm = emb / (np.linalg.norm(emb) + 1e-9)
    return best, norm, len(faces)


def _render_side_by_side(jpg_doc: np.ndarray, jpg_live: np.ndarray, out_path) -> str:
    import cv2

    def _square(img):
        h, w = img.shape[:2]
        s = min(h, w)
        x = (w - s) // 2
        y = (h - s) // 2
        return cv2.resize(img[y : y + s, x : x + s], (256, 256))

    a = _square(jpg_doc)
    b = _square(jpg_live)
    canvas = np.hstack([a, b])
    cv2.putText(
        canvas, "DOC PHOTO", (8, 246), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2, cv2.LINE_AA
    )
    cv2.putText(
        canvas, "LIVE CAPTURE", (264, 246), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 200, 0), 2, cv2.LINE_AA
    )
    cv2.imwrite(str(out_path), canvas)
    return str(out_path)


def run_face_match(document_photo, live_capture, save_evidence: bool = True) -> ModuleResult:
    try:
        doc = load_image(document_photo)
        live = load_image(live_capture)
    except Exception as exc:
        return inconclusive_result(MODULE_NAME, exc)





    doc_cap = assess_capture(doc, "document")
    live_cap = assess_capture(live, "live")
    early_failed = [r for r in (doc_cap, live_cap) if not r.passed and not r.reference_mode]
    if early_failed:
        return _quality_failure_result(doc_cap, live_cap)

    try:
        app = _get_face_analysis()
    except Exception as exc:
        single_log(f"face_match: insightface init failed ({type(exc).__name__})")
        return inconclusive_result(MODULE_NAME, exc)

    try:
        doc_face, doc_norm, doc_n = _detect_faces(app, doc)
        live_face, live_norm, live_n = _detect_faces(app, live)

        if doc_norm is None:
            import cv2
            h, w = doc.shape[:2]
            if max(h, w) < 800:
                doc_up = cv2.resize(doc, (int(w*1.8), int(h*1.8)), interpolation=cv2.INTER_CUBIC)
                doc_face, doc_norm, doc_n = _detect_faces(app, doc_up)
        if live_norm is None:
            import cv2
            h, w = live.shape[:2]
            if max(h, w) < 500:
                live_up = cv2.resize(live, (int(w*1.6), int(h*1.6)), interpolation=cv2.INTER_CUBIC)
                live_face, live_norm, live_n = _detect_faces(app, live_up)
    except Exception as exc:
        return inconclusive_result(MODULE_NAME, exc)





    doc_rep = assess_face(doc, doc_face, doc_n or 0, "document")
    live_rep = assess_face(live, live_face, live_n or 0, "live")
    for rep, cap_rep in ((doc_rep, doc_cap), (live_rep, live_cap)):
        if cap_rep.reference_mode:

            keep = [c for c in rep.failed if c in ("no_face", "multi_face")]
            rep.warnings.extend(c for c in rep.failed if c not in keep)
            rep.failed = keep
            rep.reference_mode = True
            rep.passed = not keep


    for rep, img in ((doc_rep, doc), (live_rep, live)):
        if rep.failed == ["no_face"]:
            alt = _haar_fallback_codes(img)
            if alt == ["side_angle"]:
                rep.failed = ["side_angle"]
                rep.metrics["pose_hint"] = "haar_profile_only"
    if not doc_rep.passed or not live_rep.passed:
        return _quality_failure_result(doc_rep, live_rep)

    if doc_norm is None or live_norm is None:


        return _quality_failure_result(doc_rep, live_rep)

    similarity = float(np.dot(doc_norm, live_norm))
    similarity = float(np.clip(similarity, 0.0, 1.0))
    match = bool(similarity >= MATCH_THRESHOLD)

    evidence_uri = None
    if save_evidence:
        try:

            doc_crop = _crop_face(doc, doc_face) if doc_face is not None else doc
            live_crop = _crop_face(live, live_face) if live_face is not None else live
            evidence_uri = _render_side_by_side(
                doc_crop, live_crop, new_evidence_path(MODULE_NAME, "png")
            )
        except Exception as exc:
            single_log(f"face_match: evidence write failed ({type(exc).__name__})")

    raw = {
        "similarity": round(similarity, 4),
        "match": match,
        "match_threshold": MATCH_THRESHOLD,
        "doc_faces_detected": doc_n,
        "live_faces_detected": live_n,
        "doc_embedding_norm": round(float(np.linalg.norm(doc_norm)), 4),
        "live_embedding_norm": round(float(np.linalg.norm(live_norm)), 4),
        "model": "insightface/buffalo_l (ArcFace w600k_r50)",
        "providers": _provider_used,



        "quality_gate": "passed",
        "face_quality": {
            "document": doc_rep.to_dict(),
            "live": live_rep.to_dict(),
        },
        "recapture_requested": False,
        "recapture_reasons": [],
    }
    return ok_result(MODULE_NAME, similarity, raw, evidence_uri)


def _crop_face(image_bgr: np.ndarray, face, pad: float = 0.35) -> np.ndarray:
    import cv2

    bbox = getattr(face, "bbox", None)
    if bbox is None:
        return image_bgr
    h, w = image_bgr.shape[:2]
    x1, y1, x2, y2 = [int(v) for v in bbox]
    bw, bh = x2 - x1, y2 - y1
    padx, pady = int(bw * pad), int(bh * pad)
    x1, y1 = max(0, x1 - padx), max(0, y1 - pady)
    x2, y2 = min(w, x2 + padx), min(h, y2 + pady)
    return image_bgr[y1:y2, x1:x2]


def _pair_unavailable(reason: str) -> dict:
    return {
        "status": "unavailable",
        "match": None,
        "similarity": None,
        "reason": reason,
        "recapture_requested": False,
        "recapture_reasons": [],
    }


def _pair_from_result(res) -> dict:
    raw = res.raw_output or {}
    if res.status == "ok":
        return {
            "status": "ok",
            "match": bool(raw.get("match")),
            "similarity": float(raw.get("similarity")) if raw.get("similarity") is not None else None,
            "engine": "insightface_local",
            "quality_gate": raw.get("quality_gate", "passed"),
            "warnings": ((raw.get("face_quality") or {}).get("live", {}).get("warnings", [])
                         + (raw.get("face_quality") or {}).get("document", {}).get("warnings", [])),
            "recapture_requested": False,
            "recapture_reasons": [],
        }
    return {
        "status": "inconclusive",
        "match": None,
        "similarity": None,
        "engine": "insightface_local",
        "quality_gate": raw.get("quality_gate", "failed"),
        "reason": raw.get("reason", "inconclusive"),
        "face_quality": raw.get("face_quality"),
        "recapture_requested": bool(raw.get("recapture_requested", False)),
        "recapture_target": raw.get("recapture_target"),
        "recapture_reasons": list(raw.get("recapture_reasons") or []),
    }


def run_three_way_match(
    document_photo,
    live_capture=None,
    db_reference=None,
    save_evidence: bool = False,
) -> dict:
    try:
        pairs = {}
        if live_capture is None:
            pairs["live_vs_doc"] = _pair_unavailable("no_live_capture")
        else:
            try:
                pairs["live_vs_doc"] = _pair_from_result(
                    run_face_match(document_photo, live_capture, save_evidence=save_evidence)
                )
            except Exception as exc:
                pairs["live_vs_doc"] = {**_pair_unavailable("comparison_failed"),
                                        "reason": f"comparison_failed: {type(exc).__name__}"}
        if db_reference is None:
            pairs["doc_vs_db"] = _pair_unavailable("no_registry_photo")
            pairs["live_vs_db"] = _pair_unavailable(
                "no_registry_photo" if live_capture is not None else "no_live_capture_no_registry_photo"
            )
        else:
            try:
                pairs["doc_vs_db"] = _pair_from_result(
                    run_face_match(document_photo, db_reference, save_evidence=False)
                )
            except Exception as exc:
                pairs["doc_vs_db"] = {**_pair_unavailable("comparison_failed"),
                                      "reason": f"comparison_failed: {type(exc).__name__}"}
            if live_capture is None:
                pairs["live_vs_db"] = _pair_unavailable("no_live_capture")
            else:
                try:
                    pairs["live_vs_db"] = _pair_from_result(
                        run_face_match(live_capture, db_reference, save_evidence=False)
                    )
                except Exception as exc:
                    pairs["live_vs_db"] = {**_pair_unavailable("comparison_failed"),
                                           "reason": f"comparison_failed: {type(exc).__name__}"}

        computed = [p for p in pairs.values() if p.get("status") == "ok"]
        if len(computed) == 3:
            completeness = "complete"
        elif computed:
            completeness = "partial"
        else:
            completeness = "unavailable"

        db_reasons = [pairs[k].get("reason") for k in ("doc_vs_db", "live_vs_db")
                      if pairs[k].get("status") == "unavailable"]
        db_reason = db_reasons[0] if db_reasons else None

        recapture_reasons: list = []
        recapture_target = None
        for key in ("live_vs_doc", "doc_vs_db", "live_vs_db"):
            p = pairs[key]
            if p.get("recapture_requested"):
                recapture_reasons.extend(p.get("recapture_reasons") or [])
                if recapture_target is None:
                    recapture_target = p.get("recapture_target")

        primary_pair = pairs["live_vs_doc"]
        return {
            "pairs": pairs,
            "completeness": completeness,
            "db_pairs_unavailable_reason": db_reason,
            "recapture_requested": bool(recapture_reasons),
            "recapture_target": recapture_target,
            "recapture_reasons": recapture_reasons,
            "primary": {
                "similarity": primary_pair.get("similarity"),
                "match": primary_pair.get("match"),
            },
        }
    except Exception as exc:
        return {
            "pairs": {
                "live_vs_doc": _pair_unavailable("comparison_failed"),
                "doc_vs_db": _pair_unavailable("comparison_failed"),
                "live_vs_db": _pair_unavailable("comparison_failed"),
            },
            "completeness": "unavailable",
            "db_pairs_unavailable_reason": f"comparison_failed: {type(exc).__name__}",
            "recapture_requested": False,
            "recapture_target": None,
            "recapture_reasons": [],
            "primary": {"similarity": None, "match": None},
        }