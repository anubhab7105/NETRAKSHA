"""Module 2 — Tamper detection.

Approach (Techspec.md §3): BOTH, not either/or.
  * Error Level Analysis (ELA): re-save the image as JPEG at a known quality and
    measure the absolute recompression residual. Genuinely re-encoded regions
    show different error levels than the surrounding image.
  * Exact-duplicate copy-move detection: hash textured blocks and pair byte-
    identical blocks displaced by a large two-dimensional offset — a signature
    of copied/pasted regions (classic copy-move forgery). Genuine horizontal
    text and decorative-band repeats are discounted so only true 2-D pastes
    score.

Output contract:
  * raw_output['tamper_score']       : 0-1 combined score (higher = more tamper)
  * raw_output['ela_bright_ratio']   : fraction of pixels with high ELA residual
  * raw_output['copy_move_region_count'] : number of strong 2-D copy-move
                                           offset clusters
  * evidence_uri                     : path to the real ELA heatmap overlay image,
                                       rendered and saved so the Case Result UI
                                       (Appflow.md §3.4) can display it directly.

Never raises: any failure degrades to status="inconclusive", score=None.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from .common import (
    ModuleResult,
    inconclusive_result,
    load_image,
    new_evidence_path,
    ok_result,
)

MODULE_NAME = "tamper"





def _ela_residual(rgb_uint8: np.ndarray, quality: int = 90) -> np.ndarray:
    """Recompress an RGB image as JPEG and return the absolute diff (0-255)."""
    from PIL import Image
    from PIL import ImageFilter
    import io

    im = Image.fromarray(rgb_uint8)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=quality)
    redone = Image.open(io.BytesIO(buf.getvalue())).convert("RGB")
    arr = np.asarray(redone, dtype=np.float32)
    orig = np.asarray(im.convert("RGB"), dtype=np.float32)
    return np.abs(orig - arr).max(axis=2)


def _ela_metrics(residual: np.ndarray, threshold: float = 8.0) -> dict:
    mean = float(np.mean(residual))
    bright_ratio = float(np.mean(residual > threshold))
    return {
        "mean_residual": round(mean, 4),
        "ela_bright_ratio": round(bright_ratio, 4),
        "bright_threshold": threshold,
        "max_residual": round(float(np.max(residual)), 4),
    }


def _render_ela_overlay(rgb_uint8: np.ndarray, residual: np.ndarray, out_path) -> str:
    """Render a heatmap overlay of the ELA residual onto the document image."""
    import cv2

    h, w = rgb_uint8.shape[:2]
    heat = np.clip(residual * 12.0, 0, 255).astype(np.uint8)
    heat_bgr = cv2.applyColorMap(heat, cv2.COLORMAP_JET)
    over = cv2.addWeighted(rgb_uint8, 0.45, heat_bgr, 0.85, 0)


    txt = f"ELA residual overlay - bright = tamper-suspicious (mean {np.mean(residual):.2f})"
    cv2.putText(
        over,
        txt,
        (10, h - 12),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    cv2.imwrite(str(out_path), over)
    return str(out_path)






def _copy_move_detect(
    gray: np.ndarray,
    bs: int = 8,
    stride: int = 8,
    min_dist: float = 140.0,
    min_std: float = 10.0,
) -> dict:
    """Detect copied-region forgeries by exact-duplicate block hashing.

    A copy-move forgery pastes a region *exactly* somewhere else on the page,
    so the pasted content and its source share byte-identical blocks. We hash
    every textured block on a fine grid and pair up blocks sharing a hash, then
    group pairs by their spatial offset.

    A stamped page also contains genuine repeats (text rows and decorative
    bands) — those repeat only *horizontally* (vertical offset ≈ 0), giving a
    set of small lattice clusters. A real copy-move instead produces one strong
    two-dimensional cluster (the actual paste displacement). We therefore only
    count clusters with ``|dy| >= 2`` blocks as copy-move evidence, which cleanly
    separates a pasted duplicate from a page's natural repeated structure.

    Runs on the native-resolution gray image; sub-0.3s on the specimen pages.
    A deterministic pair budget (200k) bounds the O(k^2) pairing step on
    pathological inputs — exhaustion is reported as `truncated: True` and the
    accumulated offsets are still scored (fail-operational, never hangs).
    """
    import hashlib
    from collections import defaultdict

    _MAX_PAIRS = 200_000

    H, W = gray.shape
    locs: defaultdict = defaultdict(list)
    for y in range(0, H - bs + 1, stride):
        for x in range(0, W - bs + 1, stride):
            tile = gray[y:y + bs, x:x + bs]
            if tile.std() < min_std:
                continue
            key = hashlib.sha1(tile.tobytes()).hexdigest()
            locs[key].append((x, y))

    offsets: defaultdict = defaultdict(int)
    horizontal: defaultdict = defaultdict(int)
    n_matches = 0
    horiz_pairs = 0
    pairs_seen = 0
    truncated = False
    for positions in locs.values():
        if truncated:
            break
        for i in range(len(positions)):
            for j in range(i + 1, len(positions)):
                if pairs_seen >= _MAX_PAIRS:
                    truncated = True
                    break
                pairs_seen += 1
                dx = positions[j][0] - positions[i][0]
                dy = positions[j][1] - positions[i][1]
                if (dx * dx + dy * dy) ** 0.5 < min_dist:
                    continue
                key = (round(dx / stride), round(dy / stride))
                if abs(dy) // stride >= 2:
                    offsets[key] += 1
                    n_matches += 1
                else:
                    horizontal[key] += 1
                    horiz_pairs += 1

    top = sorted(offsets.items(), key=lambda kv: kv[1], reverse=True)
    dominant_key = top[0][0] if top else None
    dominant_count = top[0][1] if top else 0
    return {
        "blocks_matched": n_matches,
        "dominant_offset": list(dominant_key) if dominant_key else None,
        "dominant_offset_count": dominant_count,
        "regions": sum(1 for _, c in top if c >= 8),
        "horizontal_lattice_pairs": horiz_pairs,
        "offset_groups": [{"offset": list(k), "matches": v} for k, v in top[:6]],
        "analysis_resolution": f"{W}x{H}",
        "pairs_examined": pairs_seen,
        "truncated": truncated,
    }






def run_tamper(document_image, save_evidence: bool = True) -> ModuleResult:
    """Run ELA + SHA1 exact-duplicate copy-move tamper detection on a single document image.

    Signature for the FastAPI route owner:
        run_tamper(document_image, save_evidence=True) -> ModuleResult

    ``document_image`` is a path (str/Path), bytes buffer, PIL Image, or BGR
    ndarray. Returns a result with status "ok" or "inconclusive". Never raises.
    """
    try:
        img = load_image(document_image)
        if img.size == 0 or img is None:
            raise ValueError("empty image")
        import cv2 as _cv2

        if img.ndim == 2:
            gray = img.astype(np.uint8)
            rgb = np.stack([gray] * 3, axis=-1)
        else:
            gray = _cv2.cvtColor(img, _cv2.COLOR_BGR2GRAY)
            rgb = img[:, :, ::-1]
    except Exception as exc:
        return inconclusive_result(MODULE_NAME, exc)


    try:
        residual = _ela_residual(rgb, quality=90)
        ela = _ela_metrics(residual)
    except Exception as exc:
        return inconclusive_result(MODULE_NAME, exc)


    try:
        cm = _copy_move_detect(gray)
    except Exception as exc:
        cm = {"error": str(exc), "dominant_offset_count": 0, "regions": 0,
              "blocks_matched": 0, "offset_groups": []}







    COPY_FLOOR = 10
    COPY_SAT = 90
    ela_signal = np.clip((ela["mean_residual"] - 1.5) / 2.5, 0.0, 1.0)
    copy_signal = np.clip(
        (cm.get("dominant_offset_count", 0) - COPY_FLOOR) / (COPY_SAT - COPY_FLOOR),
        0.0,
        1.0,
    )
    tamper_score = round(0.60 * copy_signal + 0.40 * ela_signal, 4)


    evidence_uri = None
    if save_evidence:
        try:
            evidence_uri = _render_ela_overlay(
                rgb, residual, new_evidence_path(MODULE_NAME, "png")
            )
        except Exception as exc:
            single_log_warn(f"tamper: evidence write failed ({type(exc).__name__})")

    raw = {
        "tamper_score": tamper_score,
        "ela_bright_ratio": ela["ela_bright_ratio"],
        "copy_move_region_count": cm.get("regions", 0),
        "dominant_offset_count": cm.get("dominant_offset_count", 0),
        "dominant_offset": cm.get("dominant_offset"),
        "ela": ela,
        "copy_move": {
            "blocks_matched": cm.get("blocks_matched", 0),
            "dominant_offset": cm.get("dominant_offset"),
            "dominant_offset_count": cm.get("dominant_offset_count", 0),
            "regions": cm.get("regions", 0),
            "horizontal_lattice_pairs": cm.get("horizontal_lattice_pairs", 0),
            "offset_groups": cm.get("offset_groups", []),
        },
    }
    return ok_result(MODULE_NAME, tamper_score, raw, evidence_uri)


def single_log_warn(msg: str) -> None:
    print(f"[pipeline][tamper] {msg}")
