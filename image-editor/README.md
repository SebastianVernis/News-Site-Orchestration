# image-editor

Paso de edición multimedia del pipeline editorial (Canónica). Se intercala entre
`Download Image` y `Upload a file` del workflow `Image Uploader - Article Post`
(`w22AfLPD4OT910b4`).

## Qué hace

- **Modo fiel (`auto`, por defecto)**: reencuadra a 16:9 con foco en las caras
  (OpenCV) o en la zona de más detalle, aplica zoom, desplazamiento a tercios,
  una rotación/perspectiva leve y un grado de color (cálido, frío, contraste,
  suave, documental, neutro). La variante es determinista por `slug+sitio`: la
  misma nota sale siempre igual, dos notas distintas —o la misma nota en dos
  sitios— salen diferentes.
- **Modo IA (`ia`)**: pide a `google/gemini-2.5-flash-image` (OpenRouter) un
  reencuadre desde otro punto de vista conservando personas, ropa, objetos y
  luz. Si falla, cae a `auto` (salvo `EDIT_STRICT=1`).
- **Modo `off`**: devuelve el original sin tocar.
- Salida siempre JPEG ≤1600 px y ≤600 KB (umbral de las tarjetas de Facebook y
  WhatsApp). Si el original no se puede leer, responde 415/422 y n8n reintenta.

## API

```
GET  /healthz
POST /edit    {"url": "...", "slug": "...", "site": "...", "mode": "auto|ia|off"}
GET  /ia
POST /ia     {"add": ["slug", ...]} | {"remove": [...]} | {"set": [...]}
```

`/edit` devuelve `image/jpeg` con cabeceras de trazabilidad:
`X-Edit-Mode`, `X-Edit-Style`, `X-Edit-Seed`, `X-Edit-Zoom`, `X-Edit-Angle`,
`X-Edit-Faces`, `X-Edit-Width/Height`, `X-Edit-Bytes`, y `X-Edit-Ai` /
`X-Edit-Ai-Error` cuando aplica.

## Activar la IA en una nota

La vía normal es la lista del servicio (persistida en `data/ia_slugs.json`):

```bash
curl -s -X POST http://127.0.0.1:8090/ia -H 'Content-Type: application/json' \
  -d '{"add":["slug-de-la-nota"]}'
```

Una nota en esa lista se edita con IA aunque el workflow mande `mode=auto`.
También se puede mandar `mode=ia` explícito en el item (`MULTIMEDIA_MODE`).

## Operación

```bash
docker network create news-pipeline           # una vez
docker network connect news-pipeline n8n      # una vez
docker compose up -d --build
docker logs -f image-editor
```

`.env` necesita `OPENROUTER_API_KEY` (se toma de la credencial «OpenRouter
account» de n8n). Costo medido: **$0.039 por imagen** y ~8 s; el modo fiel no
cuesta y tarda ~1 s.

## Pruebas

```bash
python3 test_editor.py        # 6 imágenes reales, variantes fieles
python3 test_editor.py --ia   # una variante generativa
```

Salidas en `/tmp/edit_test/`. Compara el campo `sha`: debe haber una variante
distinta por nota.
