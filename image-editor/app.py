"""Servicio de edición multimedia del pipeline editorial.

POST /edit  {url, slug, site, mode}  -> imagen JPEG editada
  mode = auto (fiel, por defecto) | ia (reencuadre generativo) | off (original)
  Si mode=ia falla, cae a auto salvo EDIT_STRICT=1.

La variante fiel es determinista por slug+sitio (editor.seed_for); el modo IA
también se puede activar por lista de slugs (POST /ia {"add": ["slug", ...]}).
"""
from __future__ import annotations

import io
import json
import os
import threading
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel
from PIL import Image

import editor
from ai_edit import ai_reframe

DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
IA_FILE = DATA_DIR / "ia_slugs.json"
UA = os.getenv("EDIT_UA", "Mozilla/5.0 (compatible; NewsImageEditor/1.0)")
MAX_DOWNLOAD = int(os.getenv("MAX_DOWNLOAD_BYTES", str(25 * 1024 * 1024)))
STRICT = os.getenv("EDIT_STRICT", "0") == "1"

app = FastAPI(title="News Image Editor", version="1.0")
_lock = threading.Lock()


class EditRequest(BaseModel):
    url: str
    slug: str = ""
    site: str = ""
    mode: str = "auto"


def _ia_slugs() -> set[str]:
    try:
        return set(json.loads(IA_FILE.read_text(encoding="utf-8")))
    except Exception:
        return set()


def _write_ia(slugs: set[str]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = IA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(sorted(slugs), ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(IA_FILE)


def _download(url: str) -> bytes:
    with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": UA, "Accept": "image/*,*/*;q=0.8"}) as client:
        with client.stream("GET", url) as r:
            if r.status_code != 200:
                raise HTTPException(502, f"origen respondió HTTP {r.status_code}")
            chunks, total = [], 0
            for chunk in r.iter_bytes():
                total += len(chunk)
                if total > MAX_DOWNLOAD:
                    raise HTTPException(413, "imagen de origen demasiado grande")
                chunks.append(chunk)
            data = b"".join(chunks)
    if not data:
        raise HTTPException(502, "origen devolvió 0 bytes")
    return data


def _mime(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "application/octet-stream"


def _as_jpeg(data: bytes) -> Image.Image:
    try:
        return Image.open(io.BytesIO(data)).convert("RGB")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(415, f"formato de imagen no soportado: {exc}") from exc


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "ia": bool(os.getenv("OPENROUTER_API_KEY")), "ia_slugs": sorted(_ia_slugs())}


@app.get("/ia")
def ia_list() -> dict:
    return {"slugs": sorted(_ia_slugs())}


@app.post("/ia")
async def ia_update(req: Request) -> dict:
    body = await req.json()
    with _lock:
        current = _ia_slugs()
        if isinstance(body.get("set"), list):
            current = {str(s).strip() for s in body["set"] if str(s).strip()}
        current |= {str(s).strip() for s in body.get("add", []) if str(s).strip()}
        current -= {str(s).strip() for s in body.get("remove", []) if str(s).strip()}
        _write_ia(current)
    return {"slugs": sorted(current)}


@app.post("/edit")
def edit(payload: EditRequest) -> Response:
    if not payload.url:
        raise HTTPException(400, "falta url")
    mode = (payload.mode or "auto").strip().lower()
    if mode not in ("auto", "ia", "off"):
        mode = "auto"
    original = _download(payload.url)
    if mode == "off":
        return Response(content=original, media_type=_mime(original),
                        headers={"X-Edit-Mode": "off", "X-Edit-Bytes": str(len(original))})

    seed = editor.seed_for(payload.slug, payload.site)
    want_ia = mode == "ia" or payload.slug in _ia_slugs()
    info: dict[str, str] = {}
    if want_ia:
        raw, detail = ai_reframe(original, seed)
        if raw:
            img = Image.open(io.BytesIO(raw)).convert("RGB")
            jpeg = editor.encode_jpeg(img)
            info = {"mode": "ia", "ai": detail, "width": str(img.width), "height": str(img.height),
                    "seed": str(seed), "bytes": str(len(jpeg))}
            return Response(content=jpeg, media_type="image/jpeg", headers=_headers(info))
        if STRICT:
            raise HTTPException(502, f"modo IA falló: {detail}")
        info["ai_error"] = detail

    try:
        jpeg, auto_info = editor.process(original, payload.slug, payload.site)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"no se pudo editar la imagen: {exc}") from exc
    info = {**auto_info, **info}
    info.setdefault("mode", "auto")
    if want_ia:
        info["mode"] = "auto-fallback"
    return Response(content=jpeg, media_type="image/jpeg", headers=_headers(info))


def _headers(info: dict[str, str]) -> dict[str, str]:
    out = {}
    for k, v in info.items():
        if v is None:
            continue
        key = "X-Edit-" + "".join(part.capitalize() for part in k.split("_"))
        out[key] = str(v)[:180]
    return out
