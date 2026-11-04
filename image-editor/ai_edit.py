"""Reencuadre generativo (modo IA) vía OpenRouter.

No inventa una escena nueva: pide un cambio de punto de vista conservando personas,
ropa, objetos y luz. Si el proveedor falla, el llamador cae al modo fiel.
"""
from __future__ import annotations

import base64
import io
import os
import time

import httpx
from PIL import Image

OPENROUTER_URL = os.getenv("OPENROUTER_URL", "https://openrouter.ai/api/v1/chat/completions")
DEFAULT_MODEL = os.getenv("IA_MODEL", "google/gemini-2.5-flash-image")
TIMEOUT = float(os.getenv("IA_TIMEOUT", "180"))
MAX_INPUT_BYTES = 12 * 1024 * 1024

PROMPTS = (
    "Re-frame this exact photograph from a slightly different camera position: move the "
    "viewpoint a few degrees to the left and slightly lower, keeping the same people, their "
    "faces, clothing, posture, the room, lighting and every object. Do not add, remove or "
    "replace anything. Photorealistic press photograph, same moment, same colours.",
    "Re-frame this exact photograph from a slightly different camera position: move the "
    "viewpoint a few degrees to the right and slightly higher, keeping the same people, their "
    "faces, clothing, posture, the room, lighting and every object. Do not add, remove or "
    "replace anything. Photorealistic press photograph, same moment, same colours.",
)


def _mime(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def ai_reframe(data: bytes, seed: int) -> tuple[bytes | None, str]:
    key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    if not key:
        return None, "sin OPENROUTER_API_KEY"
    if len(data) > MAX_INPUT_BYTES:
        return None, "imagen de entrada demasiado grande"
    payload = {
        "model": DEFAULT_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPTS[seed % len(PROMPTS)]},
                {"type": "image_url", "image_url": {"url": f"data:{_mime(data)};base64," + base64.b64encode(data).decode()}},
            ],
        }],
        "modalities": ["image", "text"],
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.getenv("OPENROUTER_REFERER", "https://news-sites.local"),
        "X-Title": "News Image Editor",
    }
    last = ""
    for attempt in range(2):
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                r = client.post(OPENROUTER_URL, json=payload, headers=headers)
            if r.status_code != 200:
                last = f"HTTP {r.status_code}: {r.text[:180]}"
                if r.status_code in (400, 401, 402, 403, 404):
                    break
                time.sleep(2)
                continue
            body = r.json()
            msg = (body.get("choices") or [{}])[0].get("message") or {}
            images = msg.get("images") or []
            if not images:
                last = "respuesta sin imagen: " + str(msg.get("content"))[:180]
                break
            url = images[0].get("image_url", {}).get("url", "") if isinstance(images[0], dict) else str(images[0])
            if not url.startswith("data:"):
                last = "formato de imagen inesperado"
                break
            raw = base64.b64decode(url.split(",", 1)[1])
            img = Image.open(io.BytesIO(raw)).convert("RGB")
            return raw, f"ok:{DEFAULT_MODEL}"
        except Exception as exc:  # noqa: BLE001
            last = f"{type(exc).__name__}: {exc}"[:180]
            time.sleep(2)
    return None, last
