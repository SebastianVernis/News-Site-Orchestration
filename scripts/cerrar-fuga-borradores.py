#!/usr/bin/env python3
"""Cierra la fuga de borradores en los middlewares de artículo.

1) Añade `AND ESTADO = 'PUBLICADO'` a las consultas que no lo tenían.
2) Inserta una verificación final: si la fila resuelta no está PUBLICADA,
   el middleware no inyecta metadatos y sirve el shell normal.
"""
import pathlib
import re
import sys

GUARD = """    const _resuelto = await resolveArticleBySlug(env.DB, requestedSlug);
    const article = _resuelto.article;
    if (article) {
      // Un borrador no se sirve: sin esta verificación el middleware inyectaba
      // título, descripción y OG de artículos con ESTADO distinto de PUBLICADO.
      let _estado = null;
      try {
        const _fila = await env.DB.prepare(
          "SELECT ESTADO as estado FROM ARTICULOS_PARAFRASEADOS WHERE ID = ? LIMIT 1"
        ).bind(article.para_id).first()
          || await env.DB.prepare(
            "SELECT ESTADO as estado FROM ARTICULOS_CMS WHERE ID = ? LIMIT 1"
          ).bind(article.para_id).first();
        _estado = _fila ? String(_fila.estado || "").toUpperCase() : null;
      } catch (_) {
        _estado = null;
      }
      if (_estado !== "PUBLICADO") return await next();
    }
"""

SELECTORES = [
    "const { article } = await resolveArticleBySlug(env.DB, requestedSlug);",
    "const { article } = await resolveArticleBySlug(env.DB, requestedSlug)",
]


def filtrar(sql: str) -> str:
    if "ESTADO" in sql.upper():
        return sql
    return re.sub(r"(\s+LIMIT\s+1)", r" AND ESTADO = 'PUBLICADO'\1", sql, count=1, flags=re.I)


def procesar(path: pathlib.Path) -> tuple[bool, list[str]]:
    src = path.read_text(encoding="utf-8")
    orig = src
    notas = []

    # 1) consultas sin filtro de estado
    def repl(m):
        sql = m.group(0)
        nuevo = filtrar(sql)
        if nuevo != sql:
            notas.append("filtro ESTADO")
        return nuevo

    src = re.sub(r'"[^"]*FROM ARTICULOS_(?:PARAFRASEADOS|CMS)[^"]*"', repl, src)

    # 2) guardia final
    if "const _resuelto" not in src:
        for sel in SELECTORES:
            if sel in src:
                src = src.replace(sel, GUARD.rstrip("\n"), 1)
                notas.append("guardia")
                break
        else:
            notas.append("SIN PUNTO DE INSERCIÓN")

    if src != orig:
        path.write_text(src, encoding="utf-8")
        return True, notas
    return False, notas


def main(raices: list[str]) -> int:
    total = 0
    problemas = 0
    for raiz in raices:
        for p in sorted(pathlib.Path(raiz).rglob("article-middleware.js")):
            if "node_modules" in p.parts:
                continue
            cambiado, notas = procesar(p)
            if cambiado:
                total += 1
                print(f"  ✓ {p}  ({', '.join(notas)})")
            if "SIN PUNTO" in notas:
                problemas += 1
                print(f"  ! {p}  no se pudo insertar la guardia")
    print(f"\narchivos modificados: {total} · sin guardia: {problemas}")
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["."]))
