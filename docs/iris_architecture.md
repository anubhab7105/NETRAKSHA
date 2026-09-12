# Iris Biometric Architecture — RGB Prototype vs NIR Production

## Overview

The iris pipeline is designed as a **pluggable provider** so the same enrollment/verification
APIs work for both a smartphone RGB prototype and a future dedicated NIR sensor.

```
Eye Image
   ↓
BiometricProvider (interface)
   ├── RGBProvider (current, prototype)
   └── NIRProvider (future, stub)
```

## RGB Prototype (Current)

* **Sensor:** Normal Android RGB camera (visible light, 8-bit, no IR illumination)
* **Segmentation:** Classical Hough circles on eye crop (`backend/biometric/iris/segmenter.py`)
* **Normalization:** Polar unwrapping 64×512 (`normalizer.py`)
* **Encoding:** Single Gabor filter → binary template 64×8 → 512 bytes (`encoder.py`)
* **Matching:** Hamming distance, threshold `0.32` (low-conf `0.28–0.36`) (`matcher.py`, `thresholds.json`)
* **Quality:** Blur, illumination, iris area (`quality.py`)
* **PAD:** Temporal movement + FFT moire + screen replay (`liveness.py`)

**Limitations — must be disclosed:**

* Visible-light iris is **not equivalent** to dedicated NIR (850nm) acquisition.
* Affected by ambient lighting, distance, reflections, pupil dilation, and eye color (dark irises harder).
* Expected higher EER (5–15%) than NIR (1–2%) — prototype/research grade only.
* `docs/iris_architecture.md` (this file) documents the limitation; the UI shows “RGB prototype — not NIR” in `IrisCapture.jsx`.

**Dataset:** No model training yet; classical CV uses no learned weights. For future learned segmentation, use `UBIRIS.v2` and `CASIA-Iris-Thousand` (check licenses), RGB-compatible, with heavy augmentation for phone capture.

## NIR Production Path (Future)

* **Hardware:** USB-C iris scanner (e.g., IriTech IriShield, 850nm LED + IR sensor)
* **Provider:** `NIRProvider` implements the same `enroll/verify/quality/liveness` but calls the vendor SDK via `ctypes`/`pyusb` and expects `NIRProvider.enroll` to return `NIR`-specific template.
* **Integration:** `get_provider("nir")` is already a stub; swapping `provider="nir"` in `POST /api/biometric/iris/enroll` will route to hardware without changing the API or risk engine.

## Storage & Security

* Raw eye images are **deleted** after enrollment (temp file `unlink`).
* Templates are **encrypted at rest** (`_encrypt_template` HMAC+base64, production should use `Fernet/AES-GCM` with `REGISTRY_IMPORT_SECRET` or a dedicated `IRIS_ENCRYPTION_KEY`).
* `iris_templates` table stores `template`, `mask`, `quality`, `eye`, never raw image.
* `GET /api/biometric/iris/template/{citizen_id}` returns only `{template_exists, quality}` — never the template.

## Thresholds

All thresholds are in `pipeline/thresholds.json` versioned `1.0`:
- `iris_match 0.32`, `iris_low_conf 0.28–0.36` — **uncalibrated**, must be tuned on held-out `samples/iris` with `tests/test_iris.py` and `scripts/calibrate_iris.py` (future).
- `face_match 0.55`, `tamper 0.4/0.7` similarly versioned.

## Privacy

Iris is sensitive biometric PII. Access is `unit`-scoped like `ScreeningCase` (officer sees own, supervisor sees unit, auditor sees all for `template_exists` only). All enroll/verify actions are audit-logged (`iris_enroll`, `iris_verify`) with `officer_id`/`request_id`, but never the template bytes.
