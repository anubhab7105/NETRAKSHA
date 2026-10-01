"""Generate specimen/sample test data for the ML/CV pipeline modules.

East-member script — NOT part of the runtime pipeline.

Produces, under ``samples/``:
  * faces/                 : sample face photos (openly-licensed academic data)
  * genuine_doc.png        : synthetic passport page w/ ICAO-valid MRZ + a face
  * tampered_doc.png       : the same doc, with a copied region (duplicate) and
                             re-encoded, to exercise ELA + SHA1 exact-duplicate copy-move
  * live_faces/            : frames used for face-match / liveness test assets

Only sample/specimen data is used — never a real person's government ID.

The face photos come from the Olivetti faces dataset (publicly-licensed
academic sample photographs; fetched via scikit-learn and cached here).
"""

from __future__ import annotations

import os
import pathlib
import sys

import numpy as np
import cv2

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pipeline.ocr_mrz import check_digit

SAMPLES = pathlib.Path(__file__).resolve().parent
FACES_DIR = SAMPLES / "faces"
LIVE_DIR = SAMPLES / "live"
EVIDENCE = SAMPLES / "evidence"


def _ensure_dirs():
    for d in (FACES_DIR, LIVE_DIR, EVIDENCE):
        d.mkdir(parents=True, exist_ok=True)






def _get_olivetti():
    from sklearn.datasets import fetch_olivetti_faces

    d = fetch_olivetti_faces(shuffle=False)
    return (d.images * 255).astype(np.uint8)


def _face_bgr(imgs, person, frame_idx, size=(96, 96)):
    gray = imgs[person * 10 + frame_idx]
    img = cv2.resize(np.stack([gray] * 3, -1), size)
    return img


def fetch_faces() -> None:
    imgs = _get_olivetti()

    cv2.imwrite(str(FACES_DIR / "person_a.png"), _face_bgr(imgs, 3, 0))
    cv2.imwrite(str(FACES_DIR / "person_a_2.png"), _face_bgr(imgs, 3, 5))
    cv2.imwrite(str(FACES_DIR / "person_b.png"), _face_bgr(imgs, 17, 0))
    print("face samples:", os.listdir(FACES_DIR))






def _font(size):
    for cand in ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
        if os.path.exists(cand):
            return ImageFont.truetype(cand, size)
    return ImageFont.load_default()


def _build_mrz(surname="SPECIMEN", given="JASMINE", doc_no="L898902C3",
               country="UTO", nationality="UTO", dob="691204", sex="F",
               expiry="280312", personal="Z3456789"):
    """Construct two valid ICAO TD3 MRZ lines (44 chars each)."""

    line1 = "P<" + country + surname + "<<" + given + "<" * 3
    line1 = line1.ljust(44, "<")


    doc_block = doc_no
    dob_block = dob
    exp_block = expiry
    pers = personal.ljust(14, "<")

    line2 = (
        doc_block
        + str(check_digit(doc_block))
        + nationality
        + dob_block
        + str(check_digit(dob_block))
        + sex
        + exp_block
        + str(check_digit(exp_block))
        + pers
    )

    composite_block = line2[0:10] + line2[13:20] + line2[21:43]
    comp = str(check_digit(composite_block))
    line2 = line2[:43] + comp
    line2 = line2.ljust(44, "<")
    return line1, line2, doc_block, dob_block, exp_block


def _paper_texture(size):
    """Return a non-repeating paper texture (BGR array).

    A random fine grain plus a soft diagonal gradient breaks up the otherwise
    flat page so exact-duplicate copy-move has real texture and the background does NOT
    self-similar-match (the failure mode of a flat, structurally-repeated
    synthetic page). Deterministic given the same rng so specimens are stable.
    """
    w, h = size
    rng = np.random.default_rng(20240901)
    grain = rng.integers(-22, 23, (h, w, 1), dtype=np.int16)
    img = np.full((h, w, 3), 243, dtype=np.uint8)
    img = img.astype(np.int16) + grain

    yy, xx = np.mgrid[0:h, 0:w]
    grad = ((xx + yy) / (w + h) * 26).astype(np.int16)
    img = img + grad[:, :, None]
    return np.clip(img, 0, 255).astype(np.uint8)


def _guilloche_band(size, y0, y1):
    """Faint sine-wave detail band (mild periodic accent on the background)."""
    w, h = size
    img = np.zeros((h, w), dtype=np.float32)
    for i in range(y0, y1, 3):
        x = np.arange(w)
        img[i, :] = 14 * (np.sin(2 * np.pi * 0.02 * x + 0.06 * i) + 1)
    return img


def render_genuine_doc(face_bgr, size=(1000, 700)) -> np.ndarray:
    """Render a photo-realistic passport page on a textured (non-repeating)
    paper background. Texture-rich background gives exact-duplicate copy-move a real
    signal base and avoids the periodic-structure false positives seen on a
    flat synthetic page."""
    w, h = size
    base = _paper_texture(size)
    img = Image.fromarray(cv2.cvtColor(base, cv2.COLOR_BGR2RGB))
    d = ImageDraw.Draw(img)

    title = _font(46)
    label = _font(26)
    mono = _font(40)


    g = _guilloche_band(size, 140, 170)
    band = Image.fromarray(np.clip(g, 0, 255).astype(np.uint8)).convert("RGB")
    img = Image.blend(img, band, 0.35)
    d = ImageDraw.Draw(img)

    d.text((40, 30), "REPUBLIC OF UTOPIA", font=title, fill=(20, 30, 60))
    d.text((40, 88), "PASSPORT - SPECIMEN", font=label, fill=(90, 90, 95))
    d.text((40, 122), "Not a real identity document", font=label, fill=(150, 40, 40))


    photo_x, photo_y, photo_w, photo_h = 700, 90, 240, 220
    d.rectangle([photo_x - 8, photo_y - 8, photo_x + photo_w + 8, photo_y + photo_h + 8],
                outline=(40, 40, 40), width=2)
    face_pil = Image.fromarray(cv2.cvtColor(face_bgr, cv2.COLOR_BGR2RGB)).resize(
        (photo_w, photo_h)
    )
    img.paste(face_pil, (photo_x, photo_y))


    fields = [
        ("SURNAME:", "SPECIMEN"),
        ("GIVEN NAME(S):", "JASMINE"),
        ("NATIONALITY:", "UTO"),
        ("DATE OF BIRTH:", "69 12 04"),
        ("SEX:", "F"),
        ("PASSPORT NO:", "L898902C3"),
        ("DATE OF EXPIRY:", "28 03 12"),
    ]
    y = 175
    for lab, val in fields:
        d.text((40, y), lab, font=_font(24), fill=(60, 60, 60))
        d.text((320, y), val, font=mono, fill=(10, 10, 10))
        y += 50


    line1, line2, *_ = _build_mrz()
    bw = d.textlength(line1, font=mono)
    if bw > w - 60:
        mono = ImageFont.truetype("DejaVuSansMono.ttf", int(40 * (w - 60) / bw))
    mrz_y = h - 210
    d.rectangle([0, mrz_y - 12, w, h], fill=(255, 255, 255))
    d.text((30, mrz_y), line1, font=mono, fill=(5, 5, 5))
    d.text((30, mrz_y + 70), line2, font=mono, fill=(5, 5, 5))

    return np.asarray(img)


def render_tampered_doc(genuine: np.ndarray) -> np.ndarray:
    """Create a tampered specimen with two hard-to-spoof signatures:
      1) a copy-move: a distinctive textured region is duplicated exactly at a
         second location (SHA1 copy-move gives a dominant large-offset cluster);
      2) a locally spliced region stored at lower quality (localized ELA bump).
    Both operate on the photo-realistic textured background so the signals are
    clearly separable from the genuine specimen. Returns a BGR array.
    """
    import io
    from PIL import Image

    bgr = genuine.copy()


    src = bgr[120:260, 40:240].copy()
    bgr[400:540, 760:960] = src



    roi = bgr[470:560, 20:160].copy()
    pil_roi = Image.fromarray(cv2.cvtColor(roi, cv2.COLOR_BGR2RGB))
    buf = io.BytesIO()
    pil_roi.save(buf, format="JPEG", quality=30)
    roi_re = np.asarray(Image.open(io.BytesIO(buf.getvalue())).convert("RGB"))
    bgr[470:560, 20:160] = cv2.cvtColor(roi_re, cv2.COLOR_RGB2BGR)

    cv2.putText(
        bgr, "TAMPERED SPECIMEN", (40, 640),
        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (180, 0, 0), 2, cv2.LINE_AA,
    )
    return bgr






def _eye_boxes(landmarker, img, h, w):
    import mediapipe as mp
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    res = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
    if not res.face_landmarks:
        return None
    lm = res.face_landmarks[0]
    L = dict(left=[33, 160, 158, 133, 153, 144], right=[362, 385, 387, 263, 373, 380])
    boxes = {}
    for name, idx in L.items():
        pts = np.array([(lm[i].x * w, lm[i].y * h) for i in idx], np.float32)
        x1, y1, x2, y2 = int(pts[:, 0].min()), int(pts[:, 1].min()), int(pts[:, 0].max()), int(pts[:, 1].max())
        boxes[name] = (x1, y1, x2, y2)
    return boxes


def make_liveness_bursts(frame_face_bgr) -> None:
    """Write blink_burst (a real blink) and static_burst (no blink) to disk.

    A blink is synthesised by painting the eye regions skin-coloured plus a
    dark closed-lid line for a few consecutive frames. The landmarker must
    still find the face AND read the eyes as closed, so the face is upscaled
    to 1024px first (the raw synthetic faces have ~13px eyes where any paint
    knocks mediapipe offline entirely). The closed-eye paint drops the EAR
    comfortably below the adaptive closed threshold -> a validated blink.
    """
    from mediapipe.tasks import python as mp_py
    from mediapipe.tasks.python import vision

    task = pathlib.Path(__file__).resolve().parent.parent / "pipeline" / "vendor" / "models" / "face_landmarker.task"
    landmarker = vision.FaceLandmarker.create_from_options(
        vision.FaceLandmarkerOptions(
            base_options=mp_py.BaseOptions(model_asset_path=str(task)),
            running_mode=vision.RunningMode.IMAGE,
            num_faces=1,
        )
    )
    base = frame_face_bgr
    if max(base.shape[:2]) < 900:
        base = cv2.resize(base, (1024, 1024), interpolation=cv2.INTER_CUBIC)
    h, w = base.shape[:2]
    boxes = _eye_boxes(landmarker, base, h, w)
    if not boxes:
        raise RuntimeError("could not detect eyes on the liveness sample face")

    def _close_eyes(img):
        for (x1, y1, x2, y2) in boxes.values():
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            padx = (x2 - x1) // 2 + 16
            pady = (y2 - y1) // 2 + 8
            skin = tuple(int(v) for v in img[cy + pady, cx])
            cv2.ellipse(img, (cx, cy), (padx, pady), 0, 0, 360, skin, -1)
            cv2.line(img, (x1 - padx // 2, cy), (x2 + padx // 2, cy),
                     (35, 35, 35), 5, cv2.LINE_AA)
        return img


    blink_frames = []

    pattern = ["open"] * 3 + ["closed"] * 4 + ["open"] * 5
    for state in pattern:
        img = base.copy()
        if state == "closed":
            img = _close_eyes(img)
        blink_frames.append(img)
    _write_burst(blink_frames, LIVE_DIR / "blink_burst")


    static = [base.copy() for _ in range(8)]
    _write_burst(static, LIVE_DIR / "static_burst")
    landmarker.close()
    print("liveness bursts written")


def _write_burst(frames, stem: pathlib.Path):
    for i, f in enumerate(frames):
        cv2.imwrite(str(stem.with_name(f"{stem.name}_{i:02d}.png")), f)






def main():
    _ensure_dirs()
    imgs = _get_olivetti()


    cv2.imwrite(str(FACES_DIR / "person_a.png"), _face_bgr(imgs, 3, 0))
    cv2.imwrite(str(FACES_DIR / "person_a_2.png"), _face_bgr(imgs, 3, 5))
    cv2.imwrite(str(FACES_DIR / "person_b.png"), _face_bgr(imgs, 17, 0))
    print("faces written")


    doc_face = _face_bgr(imgs, 3, 0, size=(220, 280))
    genuine = render_genuine_doc(doc_face)
    cv2.imwrite(str(SAMPLES / "genuine_doc.png"), genuine)

    tampered = render_tampered_doc(genuine)
    cv2.imwrite(str(SAMPLES / "tampered_doc.png"), tampered)
    print("documents written")



    burst_face = _face_bgr(imgs, 3, 0, size=(512, 512))
    make_liveness_bursts(burst_face)

    print("sample assets ready under", SAMPLES)


if __name__ == "__main__":
    main()
