"""Module 4 — Face match (1:1).

Approach (Techspec.md §3, Implementationplan.md Day 3):
  * InsightFace/ArcFace embedding extraction on both the document photo and the
    live capture.
  * cosine similarity between the two embeddings -> [0,1] "similarity".
  * ``match: bool`` derived from a per-module threshold, surfaced as evidence
    (not a case verdict). The Risk Engine / officer makes the final call.

ONNX runtime path: Techspec.md §2 says GPU is confirmed available, so we try
CUDA/ROCM GPU execution providers first, falling back to CPU only when no GPU
exists on the actual runtime (this box has none — flagged in Tracker.md §0).

Evidence: returns a real side-by-side image (doc-photo vs live-capture crops)
that the Case Result UI (Design.md §5) displays directly.

Never raises: any internal failure degrades to status="inconclusive", score=None.
"""

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

MODULE_NAME = "face_match"

# Same-person match threshold used ONLY to set the per-module `match` boolean
# (evidence). It is not a case verdict. Surfaced in raw_output for transparency.
MATCH_THRESHOLD = 0.55

_face_analysis_lock = threading.Lock()
_face_analysis = None
_provider_used = None


def _get_face_analysis():
    """Lazily build the shared InsightFace FaceAnalysis app (thread-safe)."""
    global _face_analysis, _provider_used
    with _face_analysis_lock:
        if _face_analysis is not None:
            return _face_analysis
        import insightface
        from insightface.app import FaceAnalysis

        model_root = str(INSIGHTFACE_MODEL_ROOT)

        # Prefer GPU providers (doc: GPU confirmed), else CPU fallback.
        providers = [
            ("CUDAExecutionProvider", {"device_id": 0}),
            ("ROCMExecutionProvider", {}),
            "CPUExecutionProvider",
        ]
        app = FaceAnalysis(
            name="buffalo_l",
            root=model_root,
            providers=providers,
            allowed_modules=["detection", "recognition"],
        )
        # record which provider actually bound (for raw_output explainability)
        from onnxruntime import get_available_providers

        bound = app.models.get("recognition")
        provider_used = "unknown"
        if hasattr(bound, "session"):
            provider_used = str(bound.session.get_providers())
        _provider_used = provider_used
        _face_analysis = app
        return _face_analysis


def _detect_faces(app, image_bgr: np.ndarray):
    """Detect the largest face; return (face, normalized_embedding) or (None,None)."""
    faces = app.get(image_bgr)
    if not faces:
        return None, None, None
    # pick largest face by bbox area
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
    """1:1 face match between a document photo and a live capture.

    Signature for the FastAPI route owner:
        run_face_match(document_photo, live_capture, save_evidence=True) -> ModuleResult

    Each input is a path (str/Path), bytes buffer, PIL Image, or BGR ndarray.
    Returns "ok" or "inconclusive". Never raises.
    """
    try:
        doc = load_image(document_photo)
        live = load_image(live_capture)
    except Exception as exc:  # noqa: BLE001
        return inconclusive_result(MODULE_NAME, exc)

    try:
        app = _get_face_analysis()
    except Exception as exc:  # noqa: BLE001
        single_log(f"face_match: insightface init failed ({type(exc).__name__})")
        return inconclusive_result(MODULE_NAME, exc)

    try:
        doc_face, doc_norm, doc_n = _detect_faces(app, doc)
        live_face, live_norm, live_n = _detect_faces(app, live)
    except Exception as exc:  # noqa: BLE001
        return inconclusive_result(MODULE_NAME, exc)

    if doc_norm is None or live_norm is None:
        return inconclusive_result(
            MODULE_NAME,
            "no face detected in document photo and/or live capture",
        )

    similarity = float(np.dot(doc_norm, live_norm))
    similarity = float(np.clip(similarity, 0.0, 1.0))
    match = bool(similarity >= MATCH_THRESHOLD)

    evidence_uri = None
    if save_evidence:
        try:
            # crop to detected faces (fall back to full image)
            doc_crop = _crop_face(doc, doc_face) if doc_face is not None else doc
            live_crop = _crop_face(live, live_face) if live_face is not None else live
            evidence_uri = _render_side_by_side(
                doc_crop, live_crop, new_evidence_path(MODULE_NAME, "png")
            )
        except Exception as exc:  # noqa: BLE001
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
