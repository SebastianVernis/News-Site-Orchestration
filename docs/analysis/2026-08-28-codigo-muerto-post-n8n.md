# Auditoría: código muerto post-migración a n8n (2026-08-28)

> Contexto: en junio 2026 (commit `0102e1f0`, 2026-06-10) se apagó el cron
> interno de Cloudflare Workers en los 5 CMS (`crons = [...]` comentado en
> `wrangler.toml` + `app.route('/cron', cronRoutes)` removido de
> `src/index.js`) porque **n8n pasó a controlar la ingesta**. Esta auditoría
> mapea qué quedó realmente muerto y qué sigue vivo por otra vía (HTTP).
>
> Prioridad actual: **Oaxaca-News** (`~/projects/Oaxaca-News/`) — este
> documento solo deja registro para retomar la limpieza de
> News-Site-Orchestration más adelante, no bloquea nada.

## Hallazgo estructural

`src/index.js` en los 5 CMS **no tiene `scheduled()`** — no es solo que el
cron esté comentado en `wrangler.toml`, el handler se eliminó del código.
Fue una deprecación deliberada y atómica en un solo commit, en los 5 CMS
a la vez.

## VIVO — no tocar

- **`src/cron/rss-ingest.js`**: ya no lo llama ningún cron, pero sigue
  invocado por HTTP vía `src/routes/jobs.js` (montado en `/api/jobs`,
  idéntico en los 5 CMS):
  - `GET /api/jobs/fuentes/:site` → `getFuentesForSite` (n8n consulta
    fuentes a scrapear)
  - `POST /api/jobs/ingest/:site` con `{articles:[{title, content,
    sourceUrl, imageUrl, category}]}` → `processPreScrapedArticle` —
    **este es el endpoint real que usa n8n** para entregar artículos ya
    scrapeados/limpiados (confirmado en
    `docs/superpowers/specs/2026-05-25-n8n-cloudflare-integration-design.md`)
  - También soporta modo legacy: `runRSSIngestForSite`,
    `runRSSIngest` (`/ingest/all`), `handleIngestGlobal` (`/ingest/global`)
  - `cleanArticleContent`, `cleanTitle`, `scrapeArticleFromURL` se usan
    internamente — no tocar.
  - **`decodeHTMLEntities()` en `src/utils/helpers.js` (el fix de límites
    de \b commiteado hoy) es código vivo**, usado por esta ruta, por
    `parseArticleRow()` y por `cron/facebook.js`.

- **`src/cron/facebook.js`**: usado por `/api/jobs/publish-fb/:site`,
  `/publish-fb/all`, `/retries/:site`, `/retries/all` (en `jobs.js`) y por
  `publishToFBIndividual` en `routes/cms.js` (montado en `/api/cms`,
  publicación manual desde el editor). Reglas de negocio de FB (ventana
  8-22h, cada 3h, máx 4/día, no republicar, solo últimas 48h) siguen
  activas.

- `src/cron/master.js` (vivo vía `/api/jobs/run`), `src/cron/ticker.js`
  (vivo vía `/api/jobs/ticker`), `routes/jobs.js`, `routes/cms.js`,
  `utils/helpers.js` (usado también por `routes/articles.js`).

## MUERTO — candidatos a borrar, alta confianza

Idénticos en los 5 CMS (`cms-originaux`, `cms-nuevos`, `cms-nuevos2`,
`cms-nuevos3`, `cms-nuevos4`), nunca importados/montados en `src/index.js`,
desmontados en el mismo commit que apagó el cron:

1. **`src/routes/cron.js`** (~19KB c/u) — `/status`, `/manual`,
   `/test-ingest`, `/ingest`, `/diagnostic`, `/test-fb`,
   `/debug-fb-timer`, `/run-fb-timer`, `/facebook`, `/scrape`.
2. **`src/routes/facebook.js`** (~23-25KB c/u) — endpoints de
   debug/monitor de FB, nunca montados.

**Pendiente de decisión del usuario:**

3. **`src/routes/rss.js`** (~4.7KB c/u) — feed RSS de salida
   (syndication). No relacionado con la migración a n8n, pero tampoco está
   montado. Sin confirmar si se quiere conservar para un futuro feed
   público antes de borrar.

## Nota de seguridad (aparte, no es limpieza)

`routes/jobs.js` **no tiene `checkAuth`**, pese a que
`docs/superpowers/specs/2026-05-25-n8n-cloudflare-integration-design.md`
dice que debería llevar `Authorization: Bearer`. Revisar si n8n ya envía
ese header y el Worker simplemente no lo valida (endpoint abierto en
producción) — flag para atender aparte, con el usuario.

## Siguiente paso (cuando se retome)

1. Confirmar con el usuario destino de `routes/rss.js`.
2. Borrar `routes/cron.js` y `routes/facebook.js` en los 5 CMS (10
   archivos), un commit por CMS siguiendo la convención del repo
   (`chore(cms-X): eliminar rutas cron/facebook muertas post-n8n`).
3. Revisar y cerrar el hueco de auth en `routes/jobs.js`.
