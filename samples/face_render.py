
from __future__ import annotations

from PIL import Image, ImageDraw
import math

SKIN = (224, 172, 128)
SKIN_DARK = (176, 122, 84)
HAIR = (40, 28, 24)
WHITE = (255, 255, 255)
IRIS = (60, 90, 150)
BLACK = (20, 20, 20)
LIP = (180, 80, 90)


class FaceParams:
    __slots__ = ("skin", "hair", "face_width", "eye_spacing", "eye_size",
                 "eye_open", "iris", "brow", "nose_w", "mouth_w", "chin")

    def __init__(self, skin=SKIN, hair=HAIR, face_width=0.62, eye_spacing=0.5,
                 eye_size=0.34, eye_open=1.0, iris=IRIS, brow=0.10,
                 nose_w=0.11, mouth_w=0.30, chin=0.32):
        self.skin = skin
        self.hair = hair
        self.face_width = face_width
        self.eye_spacing = eye_spacing
        self.eye_size = eye_size
        self.eye_open = eye_open
        self.iris = iris
        self.brow = brow
        self.nose_w = nose_w
        self.mouth_w = mouth_w
        self.chin = chin


def render_face(size=512, p: FaceParams = None) -> Image.Image:
    p = p or FaceParams()
    img = Image.new("RGB", (size, size), (245, 245, 240))
    d = ImageDraw.Draw(img)
    cx = size / 2
    cy = size / 2


    hair_w = size * p.face_width * 1.25
    hair_h = size * 1.15
    d.ellipse([cx - hair_w / 2, cy - hair_h / 2, cx + hair_w / 2, cy + hair_h / 2],
              fill=p.hair)


    fw = size * p.face_width
    fh = size * p.face_width * 1.32
    d.ellipse([cx - fw / 2, cy - fh / 2, cx + fw / 2, cy + fh / 2], fill=p.skin)

    eye_y = cy - size * 0.06
    spacing = size * p.eye_spacing * 0.18
    eye_size = size * p.eye_size * 0.30
    eye_open_h = size * p.eye_open * 0.10 + size * 0.02

    for side in (-1, 1):
        ex = cx + side * spacing

        ew = eye_size
        eh = max(eye_open_h, size * 0.02)
        d.ellipse([ex - ew, eye_y - eh, ex + ew, eye_y + eh], fill=WHITE, outline=(0,0,0))

        ir_d = eye_size * 0.9
        squish = max(0.12, p.eye_open)
        ir_h = ir_d * (0.4 + 0.6 * p.eye_open)
        d.ellipse([ex - ir_d/2, eye_y - ir_h/2, ex + ir_d/2, eye_y + ir_h/2], fill=p.iris)
        d.ellipse([ex - ir_d*0.28, eye_y - ir_h*0.28, ex + ir_d*0.28, eye_y + ir_h*0.28],
                  fill=BLACK)

        brow_y = eye_y - size * (0.10 + p.brow)
        dl = side * (spacing + eye_size)
        d.line([cx + dl - eye_size * 0.7, brow_y,
                cx + dl + eye_size * 0.7, brow_y - size * 0.02],
               fill=BLACK, width=max(3, int(size * 0.018)))


    ny = cy + size * 0.10
    nw = size * p.nose_w
    d.line([cx, ny - size * 0.12, cx - nw, ny + size * 0.10], fill=BLACK, width=4)
    d.line([cx, ny - size * 0.12, cx + nw, ny + size * 0.10], fill=BLACK, width=4)


    my = cy + size * 0.24
    mw = size * p.mouth_w
    d.arc([cx - mw, my, cx + mw, my + size * 0.10], 0, 180, fill=LIP, width=6)

    return img


def vary_eye_open(base: FaceParams, open_val: float) -> FaceParams:
    return FaceParams(skin=base.skin, hair=base.hair, face_width=base.face_width,
                      eye_spacing=base.eye_spacing, eye_size=base.eye_size,
                      eye_open=open_val, iris=base.iris, brow=base.brow,
                      nose_w=base.nose_w, mouth_w=base.mouth_w, chin=base.chin)


def person_a() -> FaceParams:
    return FaceParams(skin=SKIN, hair=(35, 30, 25), face_width=0.60,
                      eye_spacing=0.52, eye_size=0.34, eye_open=1.0,
                      iris=(70, 100, 160), nose_w=0.10, mouth_w=0.30, chin=0.30)


def person_b() -> FaceParams:
    return FaceParams(skin=(170, 120, 88), hair=(15, 12, 10), face_width=0.70,
                      eye_spacing=0.46, eye_size=0.28, eye_open=1.0,
                      iris=(90, 60, 60), nose_w=0.14, mouth_w=0.36, chin=0.36)
