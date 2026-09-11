"""Module 2b — Physical forgery detection (beyond ELA / copy-move).

ELA + copy-move catch digital pastes, but high-quality physical counterfeits
(re-typeset data pages, swapped portraits, screen/print recaptures) sail
through them. This module adds six independent, deterministic checks that run
on the document still with only OpenCV/numpy/PIL (+ pyzbar when present):

  1. ``layout``            — page aspect vs known travel-doc ratios, MRZ text-
                             line structure, portrait-zone occupancy.
  2. ``font_consistency``  — MRZ OCR-B monospace regularity (glyph-advance +
                             stroke-width variation). Re-typeset characters in
                             a proportional font break the monospace lattice.
  3. ``photo_boundary``    — portrait-frame geometric integrity (Hough frame
                             completeness, border-width uniformity, edge-step
                             consistency). Swapped portraits break the frame.
  4. ``print_scan``        — recapture tells: display/half-tone periodic FFT
                             peaks (moire) + micro-text edge acutance loss.
  5. ``qr_barcode``        — machine-readable zones *where available*: decode
                             (OpenCV + pyzbar) and cross-check the payload
                             against the MRZ/document number when supplied.
  6. ``security_features`` — guilloche/laminate presence cues. Holograms and
                             OVI genuinely need tilt-series captures, so those
                             are reported as not-verifiable (physical referral)
                             and never scored — no fabricated verdicts.

Each sub-check returns ``(score 0..1, status, details)``; the module score is
the weight-renormalised mean over AVAILABLE sub-checks. Unavailable checks
(no QR printed, no MRZ on this doc type, …) contribute nothing and are
reported as such. Fewer than 2 available sub-checks → inconclusive.

Never raises: any failure degrades to status="inconclusive", score=None.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .common import (
    ModuleResult,
    inconclusive_result,
    load_image,
    new_evidence_path,
    ok_result,
)

MODULE_NAME = "physical_forgery"

# ---------------------------------------------------------------------------
# Thresholds (env-overridable; calibrated on the repo specimen pages)
# ---------------------------------------------------------------------------

def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


#: Page aspect (w/h) expectations per doc family.
_ASPECTS = {
    "passport": 1.42,   # 125 x 88 mm data page
    "aadhaar": 1.586,   # ID-1 85.6 x 53.98 mm
    "pan": 1.586,
    "voter_id": 1.50,   # varies — wide tolerance
    "unknown": None,
}
ASPECT_TOL = _env_float("PHYS_ASPECT_TOL", 0.10)
#: Expected MRZ text lines (None = this doc type carries no MRZ assertion).
_MRZ_LINES = {"passport": 2, "aadhaar": 0, "pan": 0, "voter_id": 0, "unknown": None}
#: Sub-check weights (renormalised over available checks).
_WEIGHTS = {
    "layout": 0.22, "font_consistency": 0.16, "photo_boundary": 0.22,
    "print_scan": 0.20, "qr_barcode": 0.10, "security_features": 0.10,
}
#: Module risk mapping mirrors the tamper module (Red ≥ .7, Yellow ≥ .4).
PHYS_HIGH = _env_float("PHYS_HIGH", 0.70)
PHYS_MODERATE = _env_float("PHYS_MODERATE", 0.40)

_CHECK_ORDER = ["layout", "font_consistency", "photo_boundary",
                "print_scan", "qr_barcode", "security_features"]


def _clamp01(x: float) -> float:
    try:
        return max(0.0, min(1.0, float(x)))
    except Exception:
        return 0.0


def _norm_type(hint: Optional[str]) -> str:
    t = (hint or "").strip().lower()
    return t if t in _ASPECTS else "unknown"


# ---------------------------------------------------------------------------
# Shared image helpers
# ---------------------------------------------------------------------------

def _gray(bgr: np.ndarray) -> np.ndarray:
    import cv2

    return cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)


def _mrz_band(gray: np.ndarray, frac: float = 0.32) -> np.ndarray:
    """Bottom band where MRZ rows live on TD3 pages."""
    h = gray.shape[0]
    return gray[int(h * (1.0 - frac)):, :]


def _text_line_rows(band: np.ndarray) -> List[Tuple[int, int]]:
    """Find text-line row spans in a band via smoothed projection profile."""
    import cv2

    h, w = band.shape
    _, bw = cv2.threshold(band, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    text = (bw < 128).astype(np.float32)
    rowsum = text.mean(axis=1)
    # Smooth over ~ a glyph height so each text line forms ONE hump.
    ksize = int(h * 0.09) | 1
    sm = cv2.GaussianBlur(rowsum.reshape(-1, 1), (1, max(7, ksize)), 0).ravel()
    peaks = [i for i in range(1, len(sm) - 1)
             if sm[i] > 0.03 and sm[i] >= sm[i - 1] and sm[i] >= sm[i + 1]]
    groups: List[List[int]] = []
    for p in peaks:
        if groups and p - groups[-1][-1] <= max(8, int(h * 0.07)):
            groups[-1].append(p)
        else:
            groups.append([p])
    spans = []
    for gseg in groups:
        c = int(np.mean(gseg))
        half = max(4, int(h * 0.035))
        spans.append((max(0, c - half), min(h, c + half)))
    return spans


# ---------------------------------------------------------------------------
# 1. Layout validation (+ structural template match)
# ---------------------------------------------------------------------------

def _check_layout(bgr: np.ndarray, gray: np.ndarray, doc_type: str) -> Tuple[float, str, dict]:
    import cv2

    h, w = gray.shape
    details: Dict[str, Any] = {"aspect": round(w / max(1, h), 3)}
    penalties: List[Tuple[float, str]] = []

    # (a) page aspect vs known travel-doc ratios
    expected = _ASPECTS.get(doc_type)
    candidates = [a for a in _ASPECTS.values() if a] if expected is None else [expected]
    aspect = w / max(1, h)
    if candidates and min(abs(aspect - c) for c in candidates) > ASPECT_TOL:
        penalties.append((0.55, f"aspect {aspect:.2f} matches no known document ratio"))
        details["aspect_ok"] = False
    else:
        details["aspect_ok"] = True

    # (b) MRZ text-line structure (TD3 passports carry exactly 2 rows)
    band = _mrz_band(gray)
    lines = _text_line_rows(band)
    details["mrz_lines"] = len(lines)
    want = _MRZ_LINES.get(doc_type)
    if want is not None:
        if len(lines) != want:
            penalties.append((0.75 if want == 2 and len(lines) < 2 else 0.6,
                              f"MRZ band has {len(lines)} text lines, expected {want}"))
            details["mrz_ok"] = False
        else:
            details["mrz_ok"] = True
    else:
        details["mrz_ok"] = "not_asserted"

    # (c) portrait-zone occupancy — a travel doc carries a portrait; an empty
    # photo zone (covered / cropped page) breaks the template.
    ph, pw = int(h * 0.42), int(w * 0.34)
    zone = gray[0:ph, w - pw:w]
    edges = cv2.Canny(zone, 60, 140)
    edge_density = float(edges.mean()) / 255.0
    details["photo_zone_edge_density"] = round(edge_density, 4)
    if edge_density < 0.008:
        penalties.append((0.65, "portrait zone is blank — photo missing or covered"))
        details["photo_zone_ok"] = False
    else:
        details["photo_zone_ok"] = True

    if not penalties:
        return 0.05, "ok", details
    score = max(p for p, _ in penalties)
    return _clamp01(score), "ok", {**details, "findings": [m for _, m in penalties]}


# ---------------------------------------------------------------------------
# 2. Font consistency (MRZ monospace lattice)
# ---------------------------------------------------------------------------

def _glyph_advance_regularity(line_img: np.ndarray) -> Tuple[float, int, float]:
    """Monospace regularity of one text line.

    Returns (inlier_frac, glyph_count, mode_advance): the fraction of
    glyph advances within ±15% of the dominant (modal) advance. OCR-B
    monospace → ≈1.0; re-typeset proportional characters scatter it.
    """
    import cv2

    _, bw = cv2.threshold(line_img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    ink = (bw < 128).astype(np.float32)
    colsum = ink.mean(axis=0)
    thresh = max(0.02, float(colsum.max()) * 0.08)
    ink_cols = colsum > thresh
    runs, in_run, start = [], False, 0
    for i, v in enumerate(ink_cols):
        if v and not in_run:
            in_run, start = True, i
        elif not v and in_run:
            in_run = False
            runs.append((start, i))
    if in_run:
        runs.append((start, len(ink_cols)))
    starts = [a for a, b in runs if b - a >= 2]
    if len(starts) < 8:
        return 0.0, 0, 0.0  # too few glyphs to judge — caller treats as unavailable
    adv = np.diff(np.asarray(starts, dtype=float))
    adv = adv[adv > 0]
    if len(adv) < 6:
        return 0.0, 0, 0.0
    # Dominant advance via 1px histogram peak (robust to fragment outliers).
    hist, edges = np.histogram(adv, bins=np.arange(0, adv.max() + 2) - 0.5)
    mode = float(edges[np.argmax(hist)] + 0.5)
    if mode < 1e-6:
        return 0.0, len(starts), 0.0
    inliers = np.abs(adv - mode) <= 0.15 * mode
    return float(inliers.mean()), len(starts), mode


def _stroke_cv(line_img: np.ndarray) -> float:
    """Variation of per-glyph stroke widths across one text line.

    Median distance-transform value inside each glyph cell ≈ half stroke
    width; uniform type → near-zero CV, mixed fonts → high CV.
    """
    import cv2

    _, bw = cv2.threshold(line_img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    ink = (bw < 128).astype(np.uint8)
    dist = cv2.distanceTransform(ink, cv2.DIST_L2, 3)
    colsum = ink.mean(axis=0)
    thresh = max(0.02, float(colsum.max()) * 0.08)
    ink_cols = colsum > thresh
    runs, in_run, start = [], False, 0
    for i, v in enumerate(ink_cols):
        if v and not in_run:
            in_run, start = True, i
        elif not v and in_run:
            in_run = False
            runs.append((start, i))
    if in_run:
        runs.append((start, len(ink_cols)))
    medians = []
    for a, b in runs:
        if b - a >= 2:
            cell = dist[:, a:b]
            vals = cell[cell > 0]
            if vals.size >= 8:
                medians.append(float(np.median(vals)))
    if len(medians) < 6:
        return 0.0
    medians = np.asarray(medians)
    return float(medians.std() / (medians.mean() + 1e-9))


def _check_font(gray: np.ndarray, doc_type: str) -> Tuple[float, str, dict]:
    if doc_type not in ("passport", "unknown"):
        return 0.0, "not_available", {"reason": f"no MRZ font assertion for {doc_type}"}
    band = _mrz_band(gray)
    lines = _text_line_rows(band)
    if len(lines) != 2:
        return 0.0, "not_available", {"reason": f"needs 2 MRZ lines, found {len(lines)}"}
    inliers, counts, strokes = [], [], []
    expand = max(20, int(band.shape[0] * 0.09))
    for y1, y2 in lines:
        c = (y1 + y2) // 2
        line = band[max(0, c - expand):c + expand, 30:max(31, band.shape[1] - 30)]
        if line.size == 0:
            continue
        inlier_frac, n, _mode = _glyph_advance_regularity(line)
        if n:
            inliers.append(inlier_frac)
            counts.append(n)
            strokes.append(_stroke_cv(line))
    if not inliers:
        return 0.0, "not_available", {"reason": "glyph lattice unreadable"}
    # A single re-typeset line is enough: score the WORST line, not the mean.
    worst_inlier = min(inliers)
    line_score = _clamp01((0.92 - worst_inlier) / 0.30)
    cv_stroke = float(np.mean(strokes)) if strokes else 0.0
    # TD3 MRZ lines hold exactly 44 character cells — merged/split glyphs
    # corroborate a re-set line.
    count_term = 0.0 if all(n == 44 for n in counts) else 0.7
    score = 0.55 * line_score + 0.20 * _clamp01((cv_stroke - 0.30) / 0.55) + 0.25 * count_term
    details = {"advance_inlier_min": round(worst_inlier, 3),
               "advance_inlier_all": [round(v, 3) for v in inliers],
               "stroke_cv": round(cv_stroke, 3),
               "glyphs": counts, "method": "monospace-lattice"}
    if score >= 0.5:
        details["findings"] = [f"irregular glyph spacing (worst-line inlier {worst_inlier:.2f}) — possible re-typeset characters"]
    return _clamp01(score), "ok", details


# ---------------------------------------------------------------------------
# 3. Photo-boundary integrity (portrait frame geometry)
# ---------------------------------------------------------------------------

def _portrait_quad(gray: np.ndarray):
    """Largest near-rectangular contour in the portrait zone (or None).

    Returns (quad_4x2, rectangularity 0..1). The genuine frame is a clean
    axis-aligned rectangle; a pasted substitute leaves either no closed
    quad or a deformed one.
    """
    import cv2

    h, w = gray.shape
    ph, pw = int(h * 0.52), int(w * 0.44)
    roi = gray[0:ph, w - pw:w]
    edges = cv2.Canny(roi, 50, 150)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    page_area = float(h * w)
    best, best_rect = None, 0.0
    for cnt in contours:
        area = float(cv2.contourArea(cnt))
        if not (0.015 * page_area <= area <= 0.16 * page_area):
            continue
        peri = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
        if len(approx) != 4 or not cv2.isContourConvex(approx):
            continue
        pts = approx.reshape(4, 2).astype(float)
        # rectangularity: corner angles near 90° + opposite sides equal
        def _ang(a, b, c):
            v1, v2 = a - b, c - b
            n = (np.linalg.norm(v1) * np.linalg.norm(v2)) + 1e-9
            return float(np.degrees(np.arccos(np.clip(np.dot(v1, v2) / n, -1, 1))))
        angs = [_ang(pts[(i - 1) % 4], pts[i], pts[(i + 1) % 4]) for i in range(4)]
        ang_ok = sum(abs(a - 90) < 14 for a in angs) / 4.0
        sides = [float(np.linalg.norm(pts[(i + 1) % 4] - pts[i])) for i in range(4)]
        side_ok = 1.0 - min(1.0, abs(sides[0] - sides[2]) / max(1, sides[0] + sides[2])
                            + abs(sides[1] - sides[3]) / max(1, sides[1] + sides[3]))
        rect = 0.5 * ang_ok + 0.5 * side_ok
        if rect > best_rect:
            best_rect = rect
            best = pts + np.array([w - pw, 0])
    return best, best_rect


def _check_photo_boundary(bgr: np.ndarray, gray: np.ndarray) -> Tuple[float, str, dict]:
    import cv2

    h, w = gray.shape
    quad, rectangularity = _portrait_quad(gray)
    details: Dict[str, Any] = {"rectangularity": round(rectangularity, 3)}
    if quad is None:
        # No closed portrait quad — the frame is destroyed (or a frameless
        # design). Face presence itself is asserted by the layout check.
        return 0.6, "ok", {**details, "portrait_quad": False,
                            "findings": ["no closed portrait frame detected — possible frame destruction"]}
    details["portrait_quad"] = True
    # Frame-line presence: at sample points along the quad, the 11×11 patch
    # must contain a dark VALLEY (the outline) between brighter borders —
    # depth = max(border means) − patch min. A genuine outline scores ≈1;
    # a substitute pasted over the frame leaves a mere content step (≈0).
    # Valley logic tolerates the ±2px contour offset that defeats exact
    # pixel-masks.
    n_side = 20
    hits = 0
    total = 0
    h, w = gray.shape
    for i in range(4):
        a, b = quad[i], quad[(i + 1) % 4]
        for t in np.linspace(0.05, 0.95, n_side):
            p = a + t * (b - a)
            x, y = int(round(p[0])), int(round(p[1]))
            patch = gray[max(0, y - 5):y + 6, max(0, x - 5):x + 6].astype(float)
            if patch.size == 0:
                continue
            total += 1
            ends = max(patch[0, :].mean(), patch[-1, :].mean(),
                       patch[:, 0].mean(), patch[:, -1].mean())
            if ends - patch.min() > 120.0:
                hits += 1
    dark_frac = hits / max(1, total)
    # Step uniformity sampled within the portrait x-span and the middle
    # 60% of rows (edge rows run along the horizontal frame lines and
    # would pollute the statistic; rows outside the x-span cross
    # unrelated text).
    steps = []
    x_lo, x_hi = int(np.clip(quad[:, 0].min(), 6, w - 7)), int(np.clip(quad[:, 0].max(), 6, w - 7))
    y_lo, y_hi = quad[:, 1].min(), quad[:, 1].max()
    y_mid_lo, y_mid_hi = y_lo + 0.2 * (y_hi - y_lo), y_lo + 0.8 * (y_hi - y_lo)
    for yy in np.linspace(y_mid_lo, y_mid_hi, 12):
        yy = int(np.clip(yy, 2, h - 3))
        row = gray[yy, x_lo:x_hi + 1].astype(float)
        if row.size > 4:
            steps.append(float(np.abs(np.diff(row)).max()))
    step_cv = float(np.std(steps) / (np.mean(steps) + 1e-9)) if steps else 1.0
    details.update({"frame_dark_frac": round(dark_frac, 3), "border_step_cv": round(step_cv, 3)})
    if dark_frac > 0.60 and step_cv < 0.30 and rectangularity > 0.7:
        return 0.05, "ok", details
    if dark_frac < 0.45 or step_cv > 0.60 or rectangularity < 0.45:
        return 0.8, "ok", {**details,
                            "findings": ["portrait frame border is broken/irregular — possible photo substitution"]}
    return 0.4, "ok", {**details, "findings": ["portrait frame is degraded — manual inspection advised"]}


# ---------------------------------------------------------------------------
# 4. Print-scan / recapture detection (moire + acutance)
# ---------------------------------------------------------------------------

def _moire_metrics(gray: np.ndarray) -> dict:
    """Periodic screen/half-tone energy + micro-text acutance.

    The FFT runs on a NATIVE-resolution centre crop (never a resampled
    thumbnail — resampling destroys the few-px periods screen moire lives
    at). A Hanning window suppresses edge leakage.
    """
    import cv2

    h, w = gray.shape
    cw, chh = min(512, w), min(512, h)
    x0, y0 = (w - cw) // 2, (h - chh) // 2
    crop = gray[y0:y0 + chh, x0:x0 + cw]
    hh, ww = crop.shape
    win = cv2.createHanningWindow((ww, hh), cv2.CV_64F)
    f = np.fft.fft2(crop.astype(np.float64) * win)
    mag = np.log1p(np.abs(np.fft.fftshift(f)))
    cy, cx = hh // 2, ww // 2
    yy, xx = np.mgrid[0:hh, 0:ww]
    rr = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
    nyq = min(cy, cx)
    ring = (rr > nyq * 0.12) & (rr < nyq * 0.55)
    band = mag[ring]
    base = float(np.percentile(band, 50)) + 1e-9
    peakedness = float(np.percentile(band, 99.5) / base)
    # directional moire: periodic display grids concentrate energy in single
    # rows/columns of the spectrum. High-pass first so the legitimate
    # document lattice (MRZ glyph grid ≈ 22px period) does not count: screen
    # moire lives at a few px period, genuine micro-text does not.
    hp = crop.astype(np.float64) - cv2.GaussianBlur(crop.astype(np.float64), (0, 0), 2.0)
    det = hp - hp.mean(axis=1, keepdims=True)
    row_e = np.abs(np.fft.fft(det, axis=1)).mean(axis=0)
    det2 = hp - hp.mean(axis=0, keepdims=True)
    col_e = np.abs(np.fft.fft(det2, axis=0)).mean(axis=1)
    directionality = float(max(row_e.max() / (np.median(row_e) + 1e-9),
                               col_e.max() / (np.median(col_e) + 1e-9)))
    # acutance: edge strength on the MRZ band (copies lose micro-text bite)
    mrz = _mrz_band(gray)
    sx = cv2.Sobel(mrz, cv2.CV_64F, 1, 0, ksize=3)
    sy = cv2.Sobel(mrz, cv2.CV_64F, 0, 1, ksize=3)
    acutance = float(np.sqrt(sx ** 2 + sy ** 2).mean())
    return {"spectral_peakedness": round(peakedness, 3),
            "directionality": round(directionality, 3),
            "acutance": round(acutance, 2)}


def _check_print_scan(gray: np.ndarray) -> Tuple[float, str, dict]:
    m = _moire_metrics(gray)
    # A clean digital render / first-generation capture: smooth spectrum
    # (peakedness ≈ 1, directionality ≈ 4) and crisp micro-text. Display
    # grids push directionality past ~9; multi-generation copies blur edges.
    moire = _clamp01((m["spectral_peakedness"] - 1.6) / 2.2)
    screen = _clamp01((m["directionality"] - 4.5) / 5.0)
    blur_copy = _clamp01((14.0 - m["acutance"]) / 12.0)
    score = 0.30 * moire + 0.55 * screen + 0.15 * blur_copy
    details = {**m, "components": {"moire": round(moire, 3), "screen": round(screen, 3),
                                   "soft_copy": round(blur_copy, 3)}}
    if score >= 0.5:
        details["findings"] = ["periodic recapture artefacts and/or soft micro-text — possible screen photo or multi-generation copy"]
    return _clamp01(score), "ok", details


# ---------------------------------------------------------------------------
# 5. QR / barcode validation (where available)
# ---------------------------------------------------------------------------

def _decode_barcodes(bgr: np.ndarray) -> List[dict]:
    found: List[dict] = []
    seen = set()
    # OpenCV QR detector (no extra dependency)
    try:
        import cv2

        qd = cv2.QRCodeDetector()
        try:
            ok, decoded, points, _ = qd.detectAndDecodeMulti(bgr)
            if ok and decoded is not None:
                for i, payload in enumerate(decoded):
                    key = ("qr", (payload or "").strip())
                    if key[1] and key not in seen:
                        seen.add(key)
                        found.append({"format": "QR", "payload": key[1]})
        except Exception:
            pass
        payload = qd.detectAndDecode(bgr)[0] if hasattr(qd, "detectAndDecode") else ""
        if payload and ("qr", payload.strip()) not in seen:
            seen.add(("qr", payload.strip()))
            found.append({"format": "QR", "payload": payload.strip()})
    except Exception:
        pass
    # pyzbar for 1D + 2D symbologies (optional system lib — guarded)
    try:
        from pyzbar.pyzbar import decode as _zbar

        for sym in _zbar(bgr):
            try:
                payload = sym.data.decode("utf-8", errors="replace").strip()
            except Exception:
                continue
            key = (str(getattr(sym, "type", "?")), payload)
            if payload and key not in seen:
                seen.add(key)
                found.append({"format": key[0], "payload": payload})
    except Exception:
        pass
    return found


def _check_qr(bgr: np.ndarray, doc_number_hint: Optional[str]) -> Tuple[float, str, dict]:
    codes = _decode_barcodes(bgr)
    if not codes:
        return 0.0, "not_available", {"codes_found": 0,
                                      "reason": "no machine-readable code printed on this capture"}
    details: Dict[str, Any] = {"codes_found": len(codes),
                               "formats": sorted({c["format"] for c in codes})}
    norm_doc = "".join(ch for ch in (doc_number_hint or "").upper() if ch.isalnum())
    consistent, undecodable = 0, 0
    for c in codes:
        payload = c.get("payload", "")
        if not payload:
            undecodable += 1
            continue
        norm_pay = "".join(ch for ch in payload.upper() if ch.isalnum())
        if norm_doc and (norm_doc in norm_pay or norm_pay in norm_doc):
            consistent += 1
            c["cross_check"] = "consistent_with_document_number"
        else:
            c["cross_check"] = "no_document_link_asserted" if not norm_doc else "payload_differs_from_document_number"
    details["codes"] = [{**c, "payload": c["payload"][:120]} for c in codes]
    if undecodable:
        return 0.8, "ok", {**details, "findings": ["machine-readable pattern detected but undecodable — possible damaged/forged code"]}
    if norm_doc and consistent == 0:
        return 0.65, "ok", {**details, "findings": ["decoded payload does not reference the document number — possible swapped/cloned code"]}
    return 0.05, "ok", details


# ---------------------------------------------------------------------------
# 6. Security features (guilloche/laminate cues; holograms need tilt-series)
# ---------------------------------------------------------------------------

def _check_security_features(bgr: np.ndarray, gray: np.ndarray) -> Tuple[float, str, dict]:
    h, w = gray.shape
    # Guilloche cue: the specimen header carries a faint sine band
    # (~50px period along x). Detect that periodicity directly: column-mean
    # profile of the header strip → FFT → peak in the 20–120px period range.
    # Plain paper has no such peak; a scanned counterfeit smears it.
    header = gray[int(h * 0.16):int(h * 0.26), :]
    details: Dict[str, Any] = {}
    try:
        profile = header.mean(axis=0).astype(np.float64)
        profile = profile - np.linspace(profile[0], profile[-1], len(profile))
        spec = np.abs(np.fft.rfft(profile - profile.mean()))
        freqs = np.fft.rfftfreq(len(profile), d=1.0)
        with np.errstate(divide="ignore", invalid="ignore"):
            periods = np.divide(1.0, freqs, out=np.full_like(freqs, np.inf), where=freqs > 0)
        sel = (periods >= 20) & (periods <= 120)
        peak = float(spec[sel].max()) if sel.any() else 0.0
        floor = float(np.median(spec[sel])) + 1e-9 if sel.any() else 1.0
        prom = peak / floor
    except Exception:
        prom = 0.0
    details["guilloche_prominence"] = round(prom, 3)
    if prom > 3.0:
        details["guilloche"] = "present"
        score = 0.05
    elif prom > 1.8:
        details["guilloche"] = "weak"
        score = 0.35
    else:
        details["guilloche"] = "absent"
        score = 0.6
        details["findings"] = ["no guilloche/security-print texture where expected — possible plain-paper counterfeit"]
    details["hologram"] = ("not_verifiable_single_image — optically variable features need "
                           "tilt-series/multi-illumination capture; refer to physical inspection")
    return _clamp01(score), "ok", details


# ---------------------------------------------------------------------------
# Aggregation + evidence + entry point
# ---------------------------------------------------------------------------

def _render_evidence(bgr: np.ndarray, gray: np.ndarray, per_check: dict,
                     score: float, out_path) -> str:
    import cv2

    h, w = gray.shape
    canvas = bgr.copy()
    # MRZ band box
    y0 = int(h * (1.0 - 0.32))
    cv2.rectangle(canvas, (8, y0), (w - 8, h - 8), (255, 180, 0), 2)
    cv2.putText(canvas, "MRZ", (12, y0 - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 180, 0), 2, cv2.LINE_AA)
    # portrait zone box
    ph, pw = int(h * 0.50), int(w * 0.42)
    cv2.rectangle(canvas, (w - pw, 0), (w, ph), (0, 255, 160), 2)
    cv2.putText(canvas, "PHOTO", (w - pw + 6, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 160), 2, cv2.LINE_AA)
    # verdict strip
    bar = np.zeros((54, w, 3), np.uint8)
    colour = (60, 60, 200) if score >= PHYS_HIGH else ((0, 170, 230) if score >= PHYS_MODERATE else (40, 160, 60))
    cv2.rectangle(bar, (0, 0), (w, 54), colour, -1)
    fired = [k for k, v in per_check.items() if v.get("status") == "ok" and v.get("score", 0) >= 0.5]
    txt = f"physical forgery {score:.2f} | " + (", ".join(fired) if fired else "no check fired")
    cv2.putText(bar, txt[:110], (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2, cv2.LINE_AA)
    out = np.vstack([canvas, bar])
    cv2.imwrite(str(out_path), out)
    return str(out_path)


def run_physical_forgery(
    document_image,
    document_type_hint: Optional[str] = None,
    doc_number_hint: Optional[str] = None,
    save_evidence: bool = True,
) -> ModuleResult:
    """Run physical-forgery checks on a document still. Never raises.

    Args:
        document_image: path / bytes / PIL / BGR ndarray of the document.
        document_type_hint: aadhaar | pan | voter_id | passport | unknown.
        doc_number_hint: MRZ/document number for QR cross-checks (optional).
        save_evidence: render the zone-overlay evidence image.
    """
    try:
        img = load_image(document_image)
        if img is None or img.size == 0:
            raise ValueError("empty image")
        bgr = img if (img.ndim == 3 and img.shape[2] == 3) else np.stack([img] * 3, axis=-1)
        gray = _gray(bgr)
        if min(gray.shape) < 200:
            return inconclusive_result(MODULE_NAME, "image too small for physical checks")
    except Exception as exc:  # noqa: BLE001
        return inconclusive_result(MODULE_NAME, exc)

    doc_type = _norm_type(document_type_hint)
    per_check: Dict[str, dict] = {}
    for name in _CHECK_ORDER:
        try:
            if name == "layout":
                s, st, d = _check_layout(bgr, gray, doc_type)
            elif name == "font_consistency":
                s, st, d = _check_font(gray, doc_type)
            elif name == "photo_boundary":
                s, st, d = _check_photo_boundary(bgr, gray)
            elif name == "print_scan":
                s, st, d = _check_print_scan(gray)
            elif name == "qr_barcode":
                s, st, d = _check_qr(bgr, doc_number_hint)
            else:
                s, st, d = _check_security_features(bgr, gray)
            per_check[name] = {"score": round(_clamp01(s), 4), "status": st, "details": d,
                               "weight": _WEIGHTS[name]}
        except Exception as exc:  # noqa: BLE001 — one broken check never kills the module
            per_check[name] = {"score": 0.0, "status": "error",
                               "details": {"error": f"{type(exc).__name__}"}, "weight": _WEIGHTS[name]}

    available = {k: v for k, v in per_check.items() if v["status"] == "ok"}
    if len(available) < 2:
        return ModuleResult(
            module_name=MODULE_NAME, score=None, status="inconclusive",
            raw_output={"error": "inconclusive",
                        "reason": "fewer than 2 physical checks applied — image unsuitable",
                        "checks": {k: {"status": v["status"]} for k, v in per_check.items()}},
            evidence_uri=None,
        )

    wsum = sum(v["weight"] for v in available.values())
    physical_score = round(sum(v["score"] * v["weight"] for v in available.values()) / max(1e-9, wsum), 4)
    fired = sorted([k for k, v in available.items() if v["score"] >= 0.5])

    evidence_uri = None
    if save_evidence:
        try:
            evidence_uri = _render_evidence(bgr, gray, per_check, physical_score,
                                            new_evidence_path(MODULE_NAME, "png"))
        except Exception:
            evidence_uri = None

    raw = {
        "physical_score": physical_score,
        "checks_fired": fired,
        "checks_available": sorted(available),
        "document_type_hint": doc_type,
        "checks": {k: {"score": v["score"], "status": v["status"],
                       "weight": v["weight"], "details": v["details"]}
                   for k, v in per_check.items()},
    }
    return ok_result(MODULE_NAME, physical_score, raw, evidence_uri)
