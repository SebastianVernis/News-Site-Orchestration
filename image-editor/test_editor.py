#!/usr/bin/env python3
"""Prueba el editor contra imágenes reales del pipeline.

Uso:
  python3 test_editor.py                # 6 variantes fieles
  python3 test_editor.py --ia           # además una variante IA
  python3 test_editor.py --url ... --slug ...
"""
import argparse
import hashlib
import json
import pathlib
import urllib.request

API = 'http://127.0.0.1:8090'

CASOS = [
    ('mujeres-cuauhtemoc-bonilla-escucha-propuestas', 'enfoquemexicano', 'https://pub-42bf42f47f554f9791e810e7d0f209d4.r2.dev/images/68720b7e-3a69-44ee-a994-a936e90ef1f9.jpg'),
    ('sheinbaum-evita-festejar-avance-democrata-relacion-bila', 'MÉXICOENRESUMEN', 'https://pub-98fc7afcc6f14264b5c779748d7de4b5.r2.dev/sheinbaum-evita-festejar-avance-democrata-relaci.jpg'),
    ('ventas-autos-mexico-record-enero-octubre-2026-nissan-li', 'RADIOREDMX', 'https://pub-98fc7afcc6f14264b5c779748d7de4b5.r2.dev/ventas-autos-mexico-record-enero-octubre-2026-ni.jpg'),
    ('fin-irresistible-vs-buen-fin-2026-fechas-tiendas-partic', 'REPÚBLICAMX', 'https://pub-98fc7afcc6f14264b5c779748d7de4b5.r2.dev/fin-irresistible-vs-buen-fin-2026-fechas-tiendas.jpg'),
    ('canva-despide-22-plantilla-industria-tecnologica-139000', 'WENEWSMÉXICO', 'https://pub-98fc7afcc6f14264b5c779748d7de4b5.r2.dev/canva-despide-22-plantilla-industria-tecnologica.jpg'),
    ('aguacate-mexicano-reanuda-exportacion-eu-sader-gusano-b', 'NACIÓNALINSTANTE', 'https://pub-98fc7afcc6f14264b5c779748d7de4b5.r2.dev/aguacate-mexicano-reanuda-exportacion-eu-sader-g.jpg'),
]


def edit(slug, site, url, mode='auto', out=None):
    body = json.dumps({'url': url, 'slug': slug, 'site': site, 'mode': mode}).encode()
    req = urllib.request.Request(API + '/edit', data=body, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=300) as r:
        data = r.read()
        h = {k.lower(): v for k, v in r.headers.items()}
    out = pathlib.Path(out or f"/tmp/edit_test/{slug[:40]}-{mode}.jpg")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return {
        'archivo': str(out),
        'bytes': len(data),
        'sha': hashlib.sha1(data).hexdigest()[:12],
        'modo': h.get('x-edit-mode'),
        'estilo': h.get('x-edit-style'),
        'seed': h.get('x-edit-seed'),
        'zoom': h.get('x-edit-zoom'),
        'angulo': h.get('x-edit-angle'),
        'caras': h.get('x-edit-faces'),
        'dim': f"{h.get('x-edit-width')}x{h.get('x-edit-height')}",
        'ia': h.get('x-edit-ai', ''),
    }


def load_casos():
    p = pathlib.Path(__file__).with_name('casos.json')
    if p.exists():
        return [(c['slug'], c.get('site', ''), c['url']) for c in json.loads(p.read_text(encoding='utf-8'))]
    return CASOS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ia', action='store_true')
    ap.add_argument('--slug', default='')
    ap.add_argument('--url', default='')
    ap.add_argument('--site', default='prueba')
    a = ap.parse_args()
    casos = [(a.slug, a.site, a.url)] if a.url else load_casos()
    hashes = {}
    for slug, site, url in casos:
        r = edit(slug, site, url)
        print(json.dumps(r, ensure_ascii=False))
        hashes.setdefault(r['sha'], []).append(slug)
    print('\nvariantes distintas:', len(hashes), 'de', len(casos))
    if a.ia:
        slug, site, url = casos[0]
        print(json.dumps(edit(slug, site, url, 'ia', '/tmp/edit_test/ia.jpg'), ensure_ascii=False))


if __name__ == '__main__':
    main()
