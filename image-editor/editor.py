"""Edición de imagen determinista para el pipeline editorial.

Dos modos:
  auto : transformaciones fieles (encuadre, ángulo leve, tono) derivadas del slug+sitio.
  ia   : reencuadre generativo con un modelo de imagen (OpenRouter), con fallback a auto.

La semilla es sha256(slug|site): la misma nota produce siempre la misma variante y dos
notas distintas (o la misma nota en dos sitios) producen variantes distintas.
"""
from __future__ import annotations

import hashlib
import io
import math
import os
import random

import numpy as np
from PIL import Image, ImageEnhance, ImageOps

try:  # opencv es opcional: sin él se usa saliencia por bordes
    import cv2

    _HAS_CV2 = True
except Exception:  # pragma: no cover
    _HAS_CV2 = False

MAX_SIDE = 1600
TARGET_BYTES = 600_000
TARGET_RATIO = 16 / 9

# estilo -> (r, g, b, saturación, contraste, brillo, viñeta, grano)
STYLES = {
    "neutro":       (1.000, 1.000, 1.000, 1.00, 1.00, 1.00, 0.00, 0.0),
    "calido":       (1.055, 1.015, 0.945, 1.08, 1.03, 1.01, 0.10, 0.006),
    "frio":         (0.955, 0.995, 1.060, 0.98, 1.05, 1.00, 0.12, 0.005),
    "contrastado":  (1.010, 1.005, 1.000, 1.10, 1.12, 0.99, 0.16, 0.008),
    "suave":        (1.015, 1.010, 1.005, 0.95, 0.96, 1.03, 0.06, 0.003),
    "documental":   (1.000, 1.000, 0.995, 0.90, 1.06, 1.00, 0.08, 0.010),
}
STYLE_NAMES = tuple(STYLES)


def seed_for(slug: str, site: str) -> int:
    raw = f"{(slug or '').strip().lower()}|{(site or '').strip().lower()}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")


def plan_variant(seed: int, width: int, height: int, faces: list[tuple]) -> dict:
    rnd = random.Random(seed)
    style = STYLE_NAMES[rnd.randrange(len(STYLE_NAMES))]
    if faces:
        # con caras localizadas se puede encuadrar con decisión
        zoom = rnd.uniform(1.06, 1.28)
        dx = rnd.uniform(-1.0, 1.0)
        dy = rnd.uniform(-1.0, 1.0)
    else:
        # sin caras no se arriesga el sujeto: recorte casi completo y desplazamiento corto
        zoom = rnd.uniform(1.00, 1.10)
        dx = rnd.uniform(-0.45, 0.45)
        dy = rnd.uniform(-0.45, 0.45)
    angle = rnd.uniform(-1.4, 1.4)
    keystone = rnd.uniform(-0.018, 0.018)
    return {"style": style, "zoom": zoom, "angle": angle, "keystone": keystone,
            "dx": dx, "dy": dy, "faces": faces, "seed": seed}


def _face_boxes(img: Image.Image) -> list[tuple[int, int, int, int]]:
    if not _HAS_CV2:
        return []
    try:
        gray = np.asarray(img.convert("L").resize((img.width // 2 or 1, img.height // 2 or 1)))
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        found = cascade.detectMultiScale(gray, scaleFactor=1.08, minNeighbors=4,
                                         minSize=(max(20, img.width // 30), max(20, img.height // 30)))
        if len(found) == 0:
            full = np.asarray(img.convert("L"))
            found = cascade.detectMultiScale(full, scaleFactor=1.06, minNeighbors=3,
                                             minSize=(max(24, img.width // 25), max(24, img.height // 25)))
            return [(int(x), int(y), int(w), int(h)) for (x, y, w, h) in found]
        return [(int(x) * 2, int(y) * 2, int(w) * 2, int(h) * 2) for (x, y, w, h) in found]
    except Exception:
        return []


def _saliency_center(img: Image.Image) -> tuple[float, float]:
    try:
        small = img.convert("L").resize((160, max(1, int(160 * img.height / img.width))))
        arr = np.asarray(small, dtype=np.float32)
        gy, gx = np.gradient(arr)
        energy = np.hypot(gx, gy)
        energy = np.clip(energy - energy.mean(), 0, None) + 1e-6
        total = energy.sum()
        ys, xs = np.mgrid[0:energy.shape[0], 0:energy.shape[1]]
        return float((xs * energy).sum() / total) / energy.shape[1], float((ys * energy).sum() / total) / energy.shape[0]
    except Exception:
        return 0.5, 0.45


def _crop(img: Image.Image, plan: dict) -> Image.Image:
    w, h = img.size
    faces = plan["faces"]
    if faces:
        fx = [f[0] + f[2] / 2 for f in faces]
        fy = [f[1] + f[3] / 2 for f in faces]
        cx, cy = sum(fx) / len(fx) / w, sum(fy) / len(fy) / h
    else:
        cx, cy = _saliency_center(img)

    # recorte base a 16:9 y luego zoom
    if w / h > TARGET_RATIO:
        ch = h
        cw = h * TARGET_RATIO
    else:
        cw = w
        ch = w / TARGET_RATIO
    cw, ch = cw / plan["zoom"], ch / plan["zoom"]
    cw, ch = min(cw, w), min(ch, h)

    max_dx = max(0.0, (w - cw) / 2 / w)
    max_dy = max(0.0, (h - ch) / 2 / h)
    # limitar el desplazamiento si hay caras: que el grupo quede dentro del 82% central
    if faces:
        x0, x1 = min(f[0] for f in faces) / w, max(f[0] + f[2] for f in faces) / w
        y0, y1 = min(f[1] for f in faces) / h, max(f[1] + f[3] for f in faces) / h
        max_dx = min(max_dx, max(0.0, (cw / w) / 2 - max(cx - x0, x1 - cx) - 0.02))
        max_dy = min(max_dy, max(0.0, (ch / h) / 2 - max(cy - y0, y1 - cy) - 0.02))
    left = (cx + plan["dx"] * max_dx) * w - cw / 2
    top = (cy + plan["dy"] * max_dy) * h - ch / 2
    left = min(max(0.0, left), w - cw)
    top = min(max(0.0, top), h - ch)
    img = img.crop((round(left), round(top), round(left + cw), round(top + ch)))

    if img.width > MAX_SIDE or img.height > MAX_SIDE:
        img = img.resize((MAX_SIDE, round(MAX_SIDE * img.height / img.width)), Image.LANCZOS)
    return img


def _find_coeffs(src: list[tuple[float, float]], dst: list[tuple[float, float]]) -> list[float]:
    matrix = []
    for (x, y), (u, v) in zip(src, dst):
        matrix.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        matrix.append([0, 0, 0, x, y, 1, -v * x, -v * y])
    a = np.asarray(matrix, dtype=np.float64)
    b = np.asarray([c for p in dst for c in p], dtype=np.float64)
    return np.linalg.solve(a, b).tolist()


def _perspective(img: Image.Image, angle: float, keystone: float) -> Image.Image:
    w, h = img.size
    rad = math.radians(angle)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    margin = 0.06
    k = keystone * h
    src = [(0, 0), (w, 0), (w, h), (0, h)]
    dst = [
        (margin * w - math.sin(rad) * h * 0.0, k),
        (w - margin * w, -k),
        (w - margin * w, h + k),
        (margin * w, h - k),
    ]
    # rotación leve alrededor del centro aplicada a los destinos
    cx, cy = w / 2, h / 2
    dst = [((x - cx) * cos_a - (y - cy) * sin_a + cx, (x - cx) * sin_a + (y - cy) * cos_a + cy) for x, y in dst]
    try:
        coeffs = _find_coeffs(dst, src)
        return img.transform((w, h), Image.PERSPECTIVE, coeffs, Image.BICUBIC)
    except Exception:
        return img


def _grade(img: Image.Image, style: str, seed: int) -> Image.Image:
    r_m, g_m, b_m, sat, contrast, bright, vignette, grain_amt = STYLES.get(style, STYLES["neutro"])
    rnd = random.Random(seed ^ 0x5F3759DF)
    jitter = rnd.uniform(-0.015, 0.015)
    arr = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    arr[..., 0] = np.clip(arr[..., 0] * (r_m + jitter), 0, 1)
    arr[..., 1] = np.clip(arr[..., 1] * g_m, 0, 1)
    arr[..., 2] = np.clip(arr[..., 2] * (b_m - jitter), 0, 1)
    out = Image.fromarray((arr * 255).round().astype(np.uint8), "RGB")
    out = ImageEnhance.Color(out).enhance(sat)
    out = ImageEnhance.Contrast(out).enhance(contrast)
    out = ImageEnhance.Brightness(out).enhance(bright)

    if vignette > 0:
        w, h = out.size
        yy, xx = np.mgrid[0:h, 0:w]
        nx = (xx - w / 2) / (w / 2)
        ny = (yy - h / 2) / (h / 2)
        mask = np.clip(1.0 - vignette * (nx ** 2 + ny ** 2), 0.0, 1.0).astype(np.float32)
        a = np.asarray(out, dtype=np.float32) * mask[..., None]
        out = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGB")

    if grain_amt > 0:
        a = np.asarray(out, dtype=np.float32)
        noise = np.random.default_rng(seed).normal(0, grain_amt * 255, a.shape[:2])[..., None]
        out = Image.fromarray(np.clip(a + noise, 0, 255).astype(np.uint8), "RGB")
    return out


def encode_jpeg(img: Image.Image, target_bytes: int = TARGET_BYTES) -> bytes:
    for quality in (88, 85, 82, 78, 74, 70):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
        data = buf.getvalue()
        if len(data) <= target_bytes:
            return data
    return data


def process(data: bytes, slug: str, site: str) -> tuple[bytes, dict]:
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img).convert("RGB")
    seed = seed_for(slug, site)
    plan = plan_variant(seed, img.width, img.height, _face_boxes(img))
    out = _crop(img, plan)
    out = _perspective(out, plan["angle"], plan["keystone"])
    out = _grade(out, plan["style"], seed)
    jpeg = encode_jpeg(out)
    info = {"mode": "auto", "style": plan["style"], "seed": str(seed),
            "zoom": f"{plan['zoom']:.3f}", "angle": f"{plan['angle']:.2f}",
            "faces": str(len(plan["faces"])), "width": str(out.width), "height": str(out.height),
            "bytes": str(len(jpeg))}
    return jpeg, info
