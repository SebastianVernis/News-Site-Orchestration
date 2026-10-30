#!/usr/bin/env python3
"""Cambia la app de Meta con la que publican los CMS del canónico (y opcionalmente MC).

Qué toca:
  1. Secretos del worker de cada CMS: FB_APP_ID y FB_APP_SECRET (wrangler secret put).
  2. Opcional (--update-source): el app id hardcodeado en el código y en las páginas
     generadas (meta fb:app_id y fallback de src/routes/facebook.js).
  3. Opcional (--update-n8n): appSecret de la credencial «Facebook Graph (App) account»
     del n8n, si existe el campo.

Qué verifica:
  - Que el par id/secreto sea válido: GET /{app_id} con token de app.
  - Que los secretos queden listados en el worker.
  - Qué app emitió cada page token (debug_token): si los tokens siguen siendo de la app
    vieja hay que volver a autorizar las páginas con la nueva.

Uso:
  python3 scripts/cambiar_app_meta.py --app-id 1234567890123456 --app-secret ABC...   # dry-run
  python3 scripts/cambiar_app_meta.py --app-id ... --app-secret ... --apply
  python3 scripts/cambiar_app_meta.py --check --app-id ... --app-secret ...           # solo auditoría
"""
import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SCRIPTS = '/home/sebastianvernis/.hermes/skills/devops/news-site-network-rollout/scripts'
sys.path.insert(0, SCRIPTS)
from estado_publicacion import token_de, REDES  # noqa: E402

ROOT = Path('/mnt/disco2/projects/News-Site-Orchestration')
MC_ROOT = Path('/mnt/disco2/projects/MC-News')
N8N_DB = '/mnt/disco2/projects/n8n/.n8n/database.sqlite'
N8N_APP_CRED = '8h2PR30IhySmfncO'          # «Facebook Graph (App) account»
ACCOUNTS = {
    'canon': REDES['canon']['acc'],
    'mc': '0c01f989043a34c8500034fd946eb00a',
}
FAMILIAS = ['cms-originaux', 'cms-nuevos', 'cms-nuevos2', 'cms-nuevos3']
TEXT_EXT = {'.js', '.html', '.htm', '.json', '.toml', '.mjs', '.css'}


def grafo(path, params, token):
    url = f'https://graph.facebook.com/v21.0{path}?' + urllib.parse.urlencode({**params, 'access_token': token})
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return {'error': json.load(e).get('error', {})}
        except Exception:
            return {'error': {'message': f'HTTP {e.code}'}}


def token_cf(kind):
    if kind == 'mc':
        sys.path.insert(0, SCRIPTS)
        from mc_d1 import cf_token
        return cf_token(), ACCOUNTS['mc']
    return token_de(REDES['canon']['cred']), ACCOUNTS['canon']


def wrangler(args, cwd, tok, acc, entrada=None):
    env = dict(os.environ, CLOUDFLARE_API_TOKEN=tok, CLOUDFLARE_ACCOUNT_ID=acc)
    p = subprocess.run(['npx', 'wrangler', *args], cwd=str(cwd), env=env,
                       capture_output=True, text=True, input=entrada, timeout=300)
    out = (p.stdout + p.stderr).replace(tok, '<token>')
    return p.returncode, out


def archivos_con_app_id(raiz, old_id):
    hits = []
    for p in raiz.rglob('*'):
        if not p.is_file() or p.suffix.lower() not in TEXT_EXT:
            continue
        if 'node_modules' in p.parts or '/.git' in str(p):
            continue
        try:
            if old_id in p.read_text(encoding='utf-8', errors='ignore'):
                hits.append(p)
        except Exception:
            continue
    return hits


def reemplazar(paths, old_id, new_id):
    tocados = 0
    for p in paths:
        try:
            t = p.read_text(encoding='utf-8', errors='ignore')
            if old_id not in t:
                continue
            p.write_text(t.replace(old_id, new_id), encoding='utf-8')
            tocados += 1
        except Exception as exc:
            print(f'   ! {p}: {exc}')
    return tocados


def audit_tokens(app_id, app_secret, etiqueta, app_old):
    """debug_token de cada page token: qué app lo emitió y si sigue vivo."""
    if not app_id or not app_secret:
        print('   (sin app id/secreto: no se puede auditar quién emitió los tokens)')
        return []
    app_token = f'{app_id}|{app_secret}'
    con = sqlite3.connect(f'file:{N8N_DB}?mode=ro', uri=True)
    rows = con.execute('SELECT slug, access_token FROM data_table_user_WNHvvflkL9HMVqIV').fetchall()
    con.close()
    resumen = {'vigentes': 0, 'muertos': 0, 'de_la_app_nueva': 0, 'de_otra_app': 0, 'detalle': []}
    for slug, ptok in rows:
        d = grafo('/debug_token', {'input_token': ptok}, app_token)
        info = (d or {}).get('data') or {}
        item = {'slug': slug, 'app_id': info.get('app_id'), 'is_valid': info.get('is_valid'),
                'expires_at': info.get('expires_at'), 'scopes': info.get('scopes')}
        if not info:
            item['error'] = str((d or {}).get('error', {}).get('message'))[:80]
        resumen['detalle'].append(item)
        if item['is_valid']:
            resumen['vigentes'] += 1
        elif info:
            resumen['muertos'] += 1
        if str(item['app_id']) == str(app_id):
            resumen['de_la_app_nueva'] += 1
        elif item['app_id']:
            resumen['de_otra_app'] += 1
    print(f'   tokens: {resumen["vigentes"]} vigentes / {resumen["muertos"]} muertos · '
          f'{resumen["de_la_app_nueva"]} de la app nueva · {resumen["de_otra_app"]} de otra app')
    return resumen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--app-id', default=os.environ.get('FB_NEW_APP_ID', ''))
    ap.add_argument('--app-secret', default=os.environ.get('FB_NEW_APP_SECRET', ''))
    ap.add_argument('--apply', action='store_true', help='escribir cambios (por defecto dry-run)')
    ap.add_argument('--check', action='store_true', help='solo auditar, no cambiar nada')
    ap.add_argument('--families', default=','.join(FAMILIAS))
    ap.add_argument('--include-mc', action='store_true')
    ap.add_argument('--no-secrets', action='store_true', help='no tocar wrangler secrets')
    ap.add_argument('--update-source', action='store_true', help='reescribir el app id en código y sitios')
    ap.add_argument('--update-n8n', action='store_true', help='actualizar appSecret de la credencial de n8n')
    ap.add_argument('--page-tokens', help='JSON {slug: page_token} para reemitir FB_TOKEN_<SLUG>')
    ap.add_argument('--report', default='/tmp/cambio_app_meta.json')
    a = ap.parse_args()

    app_id = (a.app_id or '').strip()
    app_secret = (a.app_secret or '').strip()
    if not app_id:
        sys.exit('falta --app-id (o FB_NEW_APP_ID)')
    if app_id and not re.fullmatch(r'\d{6,20}', app_id):
        sys.exit('el app id debe ser numérico (6 a 20 dígitos)')
    if app_secret and len(app_secret) < 20:
        sys.exit('el app secret parece incompleto (menos de 20 caracteres)')

    fams = [f.strip() for f in a.families.split(',') if f.strip()]
    informe = {'app_id': app_id, 'modo': 'check' if a.check else ('apply' if a.apply else 'dry-run'),
               'familias': {}, 'n8n': None, 'tokens': None}

    # 1. validar credenciales contra Graph
    if app_secret:
        d = grafo(f'/{app_id}', {'fields': 'name,link,category'}, f'{app_id}|{app_secret}')
        if 'error' in d:
            print(f"X el par id/secreto no valida: {d['error'].get('message')}")
            sys.exit(2)
        print(f"app válida: {d.get('name')} ({app_id})")
        informe['app_name'] = d.get('name')
    else:
        print('(sin secreto: se omite la validación contra Graph)')

    # 2. app id viejo, para el reemplazo de código
    old_ids = set()
    for fam in fams:
        base = ROOT / fam
        if not base.exists():
            continue
        for f in [base / 'src' / 'utils' / 'html.js', base / 'src' / 'routes' / 'facebook.js']:
            if f.exists():
                old_ids.update(re.findall(r'\b(\d{15,16})\b', f.read_text(encoding='utf-8', errors='ignore')))
    if MC_ROOT.exists():
        for f in [MC_ROOT / 'cms-mc' / 'src' / 'utils' / 'html.js',
                  MC_ROOT / 'cms-mc' / 'src' / 'routes' / 'facebook.js']:
            if f.exists():
                old_ids.update(re.findall(r'\b(\d{15,16})\b', f.read_text(encoding='utf-8', errors='ignore')))
    old_ids.discard(app_id)
    print('app id viejo detectado:', ', '.join(sorted(old_ids)) or '(ninguno)')
    informe['old_app_ids'] = sorted(old_ids)

    # 3. por familia
    for fam in fams:
        base = ROOT / fam
        if not base.exists():
            print(f'! {fam}: no existe'); continue
        kind = 'canon'
        print(f'\n== {fam}')
        tok, acc = token_cf(kind)
        entrada = {'secretos': None, 'archivos': 0, 'deploy': None}
        if not a.check and not a.no_secrets:
            if a.apply:
                for nombre, valor in (('FB_APP_ID', app_id), ('FB_APP_SECRET', app_secret)):
                    if not valor:
                        print(f'   ! {nombre}: sin valor, se omite'); continue
                    rc, out = wrangler(['secret', 'put', nombre, '--config', 'wrangler.toml'],
                                       base, tok, acc, entrada=valor)
                    print(f'   secret {nombre}: {"ok" if rc == 0 else "ERROR"}')
                    if rc != 0:
                        print('     ', out.strip().splitlines()[-1][:160])
            else:
                print('   (dry-run) wrangler secret put FB_APP_ID / FB_APP_SECRET')
        rc, out = wrangler(['secret', 'list', '--config', 'wrangler.toml'], base, tok, acc)
        if rc == 0:
            nombres = re.findall(r'"name"\s*:\s*"([^"]+)"', out)
            entrada['secretos'] = nombres or [l.strip('- "') for l in out.splitlines() if 'FB_APP' in l]
            print('   secretos en el worker:', ', '.join(entrada['secretos']) or '(ninguno)')
        fb_tokens = [x for x in (entrada['secretos'] or []) if x.startswith('FB_TOKEN_')]
        if fb_tokens:
            print(f'   tokens de página en el worker: {len(fb_tokens)} (ligados a la app anterior)')
            entrada['fb_tokens'] = fb_tokens
        if a.page_tokens and a.apply and not a.no_secrets:
            try:
                tokens = json.loads(Path(a.page_tokens).read_text())
            except Exception as exc:
                print('   ! --page-tokens ilegible:', exc); tokens = {}
            puestos = 0
            for slug, ptok in tokens.items():
                nombre = f'FB_TOKEN_{slug.upper()}'
                if nombre not in fb_tokens:
                    continue
                if app_secret:
                    d = grafo('/debug_token', {'input_token': ptok}, f'{app_id}|{app_secret}')
                    info = (d or {}).get('data') or {}
                    if not info.get('is_valid'):
                        print(f'   ! {slug}: token inválido, no se instala')
                        continue
                rc, _ = wrangler(['secret', 'put', nombre, '--config', 'wrangler.toml'],
                                 base, tok, acc, entrada=ptok)
                if rc == 0:
                    puestos += 1
            print(f'   tokens instalados: {puestos}')
            entrada['tokens_instalados'] = puestos
        if a.update_source:
            hits = archivos_con_app_id(base, sorted(old_ids)[0]) if old_ids else []
            for viejo in old_ids:
                hits = sorted(set(hits) | set(archivos_con_app_id(base, viejo)))
            print(f'   archivos con el app id viejo: {len(hits)}')
            if a.apply and hits:
                entrada['archivos'] = reemplazar(hits, sorted(old_ids)[0], app_id) if len(old_ids) == 1 else 0
                if len(old_ids) > 1:
                    n = 0
                    for viejo in old_ids:
                        n += reemplazar(archivos_con_app_id(base, viejo), viejo, app_id)
                    entrada['archivos'] = n
                print(f'   reescritos: {entrada["archivos"]}')
            entrada['deploy'] = (f'cd {base} && npx wrangler deploy --config wrangler.toml'
                                 + ('  # y redesplegar los sitios generados' if hits else ''))
        informe['familias'][fam] = entrada

    if a.include_mc:
        print('\n== cms-mc (MC-News)')
        base = MC_ROOT / 'cms-mc'
        tok, acc = token_cf('mc')
        entrada = {'secretos': None}
        if a.apply and not a.no_secrets and app_secret:
            for nombre, valor in (('FB_APP_ID', app_id), ('FB_APP_SECRET', app_secret)):
                rc, out = wrangler(['secret', 'put', nombre, '--config', 'wrangler.toml'],
                                   base, tok, acc, entrada=valor)
                print(f'   secret {nombre}: {"ok" if rc == 0 else "ERROR"}')
        if a.update_source and old_ids:
            hits = []
            for viejo in old_ids:
                hits = sorted(set(hits) | set(archivos_con_app_id(base, viejo)))
            print(f'   archivos con el app id viejo: {len(hits)}')
            if a.apply:
                n = 0
                for viejo in old_ids:
                    n += reemplazar(archivos_con_app_id(base, viejo), viejo, app_id)
                entrada['archivos'] = n
                print(f'   reescritos: {n}')
        informe['familias']['cms-mc'] = entrada

    # 4. n8n
    if a.update_n8n and app_secret:
        print('\n== n8n: credencial Facebook Graph (App)')
        try:
            import n8n_cred
            con = sqlite3.connect(f'file:{N8N_DB}?mode=ro', uri=True)
            row = con.execute('SELECT data FROM credentials_entity WHERE id=?', (N8N_APP_CRED,)).fetchone()
            con.close()
            actual = json.loads(n8n_cred.nodecrypt(n8n_cred.JS_DECRYPT, 'CIPH', row[0]))
            antes = set(actual)
            actual['appSecret'] = app_secret
            if 'appId' in actual:
                actual['appId'] = app_id
            if a.apply:
                with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as fh:
                    json.dump(actual, fh)
                    tmp = fh.name
                rc = subprocess.run([sys.executable, f'{SCRIPTS}/n8n_cred.py', 'set-json', N8N_APP_CRED, tmp],
                                    capture_output=True, text=True)
                print('   ', (rc.stdout or rc.stderr).strip()[:120])
                informe['n8n'] = {'campos': sorted(antes), 'actualizado': rc.returncode == 0}
            else:
                print('   (dry-run) appSecret' + (' y appId' if 'appId' in antes else '') + ' se actualizarían')
                informe['n8n'] = {'campos': sorted(antes), 'actualizado': False}
        except Exception as exc:
            print('   ! no se pudo actualizar n8n:', str(exc)[:160])

    # 5. auditoría de tokens
    print('\n== tokens de página')
    informe['tokens'] = audit_tokens(app_id, app_secret, 'canon', sorted(old_ids)[0] if old_ids else None)

    pendientes = sum(len(v.get('fb_tokens') or []) for v in informe['familias'].values())
    if pendientes and not a.page_tokens:
        print(f'\nOJO: {pendientes} tokens de página viven como secretos FB_TOKEN_* en los workers.')
        print('     Al cambiar de app hay que reemitirlos (OAuth de cada página con la app nueva)')
        print('     e instalarlos con --page-tokens file.json.')
    Path(a.report).write_text(json.dumps(informe, ensure_ascii=False, indent=1))
    print(f'\ninforme: {a.report}')
    if not a.apply and not a.check:
        print('DRY-RUN: no se escribió nada. Repite con --apply para aplicar.')


if __name__ == '__main__':
    main()
