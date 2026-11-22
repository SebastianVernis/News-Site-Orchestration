import { fetchWithTimeout, fetchWithRetry } from './helpers.js';
import { generateNewsArticleSchema } from './seo.js';

// src/utils/html.js — Utilidades HTML: meta tags, OG scraping, R2 upload

export const getOGImage = async (url) => {
  try {
    const res = await fetchWithTimeout(url, { headers: { 'User-Agent': 'Mozilla/5.0' } }, 8000);
    const html = await res.text();
    const ogMatch =
      html.match(/<meta[^>]*property=["']og:image["'][^>]*content=["']([^"']+)["']/i) ||
      html.match(/<meta[^>]*content=["']([^"']+)["'][^>]*property=["']og:image["']/i);
    return ogMatch ? ogMatch[1] : null;
  } catch (_) {
    return null;
  }
};

export const uploadToR2 = async (url, env) => {
  try {
    const res = await fetchWithRetry(url, { headers: { 'User-Agent': 'Mozilla/5.0' } }, { maxRetries: 2, timeoutMs: 8000 });
    const contentType = res.headers.get('content-type') || 'image/jpeg';
    if (!contentType.startsWith('image/')) {
      console.log('[R2] Not an image:', contentType, url);
      return null;
    }
    const buffer = await res.arrayBuffer();
    const key = `auto/${crypto.randomUUID()}.jpg`;
    await env.UPLOADS.put(key, buffer, { httpMetadata: { contentType } });
    return `https://pub-42bf42f47f554f9791e810e7d0f209d4.r2.dev/${key}`;
  } catch (e) {
    console.log('[R2] Upload error:', e.message);
    return null;
  }
};

const API_BASE = 'https://cms-nuevos3.sebastianvernis.workers.dev';

const plainText = (s) => {
  let t = String(s || '');
  t = t.replace(/<[^>]*>/g, ' ');
  t = t.replace(/&nbsp;/gi, ' ').replace(/&quot;/gi, '"')
       .replace(/&#39;|&apos;/gi, "'")
       .replace(/&lt;/gi, '<').replace(/&gt;/gi, '>').replace(/&amp;/gi, '&');
  return t.replace(/\s+/g, ' ').trim();
};

const escapeHtml = (s) => {
  if (!s) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
};

const VALID_SITE_SLUGS = new Set([
  'enfoquemexicano', 'adnmexicano', 'pulsorepublicanonoticias', 'mexicannewsoftheworld',
  'expresomexicano', 'mexicodaily', 'aztecamexiconoticias', 'elanalisismexicano',
  'nacionalinstante', 'mexicoandtheworld', 'diariomexicano', 'politicasalvajealminuto',
  'elobservadorrepublicano', 'mexicoplus', 'actualidadsinfronteras', 'noticiasalinstante',
  'republicamx', 'diariomexico', 'financemarketsmx', 'monitorrepublicano',
  'elprofetamexicano', 'mexicoenresumen', 'radioredmx', 'perspectivamexicana',
  'wenewsmexico',
]);

function extractSiteSlug(hostname) {
  const firstPart = hostname.split('.')[0];
  if (firstPart === 'www') {
    const secondPart = hostname.split('.')[1];
    return VALID_SITE_SLUGS.has(secondPart) ? secondPart : null;
  }
  if (VALID_SITE_SLUGS.has(firstPart)) return firstPart;
  const withoutWWW = hostname.replace(/^www\./, '');
  const candidate = withoutWWW.split('.')[0];
  return VALID_SITE_SLUGS.has(candidate) ? candidate : null;
}

async function fetchArticlesForHomepage(db, siteSlug, limit = 12) {
  const tableName = `ARTICULOS_SITIO_${siteSlug.toUpperCase()}`;
  try {
    const result = await db.prepare(`
      SELECT
        p.TITULO_PARAFRASEADO as title,
        p.SLUG as slug,
        p.DESCRIPCION_PARAFRASEADA as excerpt,
        p.URL_IMAGEN as image,
        p.CATEGORIA as category
      FROM ${tableName} s
      JOIN ARTICULOS_PARAFRASEADOS p ON s.ID_PARAFRASEADO = p.ID
      WHERE p.ESTADO = 'PUBLICADO'
        AND p.URL_IMAGEN IS NOT NULL
        AND p.URL_IMAGEN != ''
        AND p.URL_IMAGEN NOT LIKE '%logo.png%'
      ORDER BY p.FECHA_PUBLICACION DESC
      LIMIT ?
    `).bind(limit).all();
    return result.results || [];
  } catch (e) {
    console.error(`[SSR HOMEPAGE] DB error for ${siteSlug}:`, e.message);
    return [];
  }
}

async function fetchFullArticle(db, slug) {
  let article = await db.prepare(
    'SELECT TITULO_PARAFRASEADO as t, DESCRIPCION_PARAFRASEADA as d, CONTENIDO as c, URL_IMAGEN as i FROM ARTICULOS_PARAFRASEADOS WHERE SLUG = ? LIMIT 1'
  ).bind(slug).first();
  if (!article) {
    article = await db.prepare(
      'SELECT TITULO as t, DESCRIPCION as d, CONTENIDO as c, URL_IMAGEN as i FROM ARTICULOS_CMS WHERE SLUG = ? LIMIT 1'
    ).bind(slug).first();
  }
  return article;
}

function buildArticleCard(a, index) {
  const title = (a.title || '').replace(/"/g, '&quot;');
  const img = a.image || '';
  const cat = a.category || 'Noticias';
  const excerpt = (a.excerpt || '').substring(0, 140);
  const slug = encodeURIComponent(a.slug || '');

  if (index < 2) {
    const isPrimary = index === 0;
    return '<a href="/articulo/?slug=' + slug + '" class="bold-hero ' + (isPrimary ? 'hero-primary' : 'hero-secondary') + '">' +
      '<img src="' + img + '" alt="' + title + '" loading="' + (isPrimary ? 'eager' : 'lazy') + '">' +
      '<div class="bold-overlay"><span class="bold-cat">' + cat + '</span>' +
      '<h2>' + title + '</h2><p>' + (excerpt ? excerpt.substring(0, isPrimary ? 200 : 120) + '...' : '') + '</p></div></a>';
  }
  return '<a href="/articulo/?slug=' + slug + '" class="bold-card">' +
    '<div class="bold-img-wrap"><img src="' + img + '" alt="' + title + '" loading="lazy"></div>' +
    '<div class="bold-card-body"><span class="bold-cat">' + cat + '</span>' +
    '<h3>' + title + '</h3><p>' + (excerpt ? excerpt + '...' : '') + '</p></div></a>';
}

function safeArticleBody(content) {
  if (!content) return '<p></p>';
  if (!content.includes('<p>') && !content.includes('<div>') && !content.includes('<blockquote') && !content.includes('<iframe')) {
    return content.split(/\n\n+/).map(p => '<p>' + p.trim() + '</p>').join('');
  }
  return content;
}

// ============================================================
// notFoundPage — un post que apunta a una nota inexistente no
// debe recibir el shell SPA (su <title> es "Cargando..." y Meta
// publica la tarjeta con ese texto). Servimos una pagina real
// con OG propio para que la tarjeta de Facebook/Instagram
// muestre marca en lugar de "Cargando...".
// ============================================================
async function notFoundPage(url, db, siteSlug) {
  let siteName = '';
  try {
    const row = await db.prepare('SELECT NOMBRE FROM SITIOS WHERE SLUG = ? LIMIT 1').bind(siteSlug).first();
    siteName = (row && row.NOMBRE) || '';
  } catch (_) { /* sin nombre: seguimos con el generico */ }

  const name = escapeHtml(siteName || siteSlug.replace(/[-_]/g, ' '));
  const home = url.origin + '/';
  const canonical = url.origin + '/articulo/?slug=' + encodeURIComponent(url.searchParams.get('slug') || '');
  const img = home + 'logo-header.png';
  const desc = 'La nota que buscas ya no esta disponible. Te invitamos a leer las mas recientes de ' + name + '.';

  const html = [
    '<!doctype html><html lang="es"><head><meta charset="utf-8">',
    '<meta name="viewport" content="width=device-width, initial-scale=1">',
    '<title>' + name + ' - Nota no disponible</title>',
    '<meta name="robots" content="noindex, follow">',
    '<meta name="description" content="' + desc + '">',
    '<meta property="og:type" content="website">',
    '<meta property="og:site_name" content="' + name + '">',
    '<meta property="og:title" content="' + name + ' - Nota no disponible">',
    '<meta property="og:description" content="' + desc + '">',
    '<meta property="og:url" content="' + escapeHtml(canonical) + '">',
    '<meta property="og:image" content="' + img + '">',
    '<meta property="og:image:secure_url" content="' + img + '">',
    '<meta name="twitter:card" content="summary_large_image">',
    '<meta name="twitter:title" content="' + name + ' - Nota no disponible">',
    '<meta name="twitter:description" content="' + desc + '">',
    '<meta name="twitter:image" content="' + img + '">',
    '<meta http-equiv="refresh" content="6;url=' + home + '">',
    '<style>body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0;display:flex;min-height:100vh;align-items:center;justify-content:center;background:#0f1115;color:#e8eaed;text-align:center;padding:24px}a{color:#4da3ff}</style>',
    '</head><body><main>',
    '<h1 style="font-size:1.35rem;margin:0 0 12px">Esta nota ya no esta disponible</h1>',
    '<p style="opacity:.8;margin:0 0 20px">Puede que haya sido retirada o que el enlace este incompleto.</p>',
    '<p><a href="' + home + '">Ir a la portada de ' + name + '</a></p>',
    '</main></body></html>'
  ].join('');

  return new Response(html, {
    status: 200,
    headers: {
      'content-type': 'text/html; charset=utf-8',
      'cache-control': 'public, max-age=120',
      'x-og-fallback': 'not-found'
    }
  });
}

// ============================================================
// injectMetaTags — SSR: homepage articles + article OG tags
// ============================================================
export const injectMetaTags = async (request, env, response) => {
  const url = new URL(request.url);
  const siteSlug = extractSiteSlug(url.hostname);
  if (!siteSlug) return response;

  const pathname = url.pathname;
  const slug = url.searchParams.get('slug');

  // ── HOMEPAGE (/ o /index.html) ──────────────────────────
  if ((pathname === '/' || pathname === '/index.html' || pathname === '') && !slug) {
    try {
      const articles = await fetchArticlesForHomepage(env.DB, siteSlug, 12);
      if (!articles.length) return response;

      const heroHTML = articles.slice(0, 2).map((a, i) => buildArticleCard(a, i)).join('');
      const gridHTML = articles.slice(2).map((a, i) => buildArticleCard(a, i + 2)).join('');

      return new HTMLRewriter()
        .on('.main-content', {
          element(el) {
            el.setInnerContent(
              '<div class="bold-hero-row">' + heroHTML + '</div>' +
              '<h2 class="bold-section-title">Noticias Destacadas</h2>' +
              '<div class="bold-grid">' + gridHTML + '</div>',
              { html: true }
            );
          }
        })
        .transform(response);
    } catch (_) {
      return response;
    }
  }

  // ── ARTÍCULO (/articulo/) ────────────────────────────────
  if (pathname.includes('/articulo') && slug) {
    try {
      const article = await fetchFullArticle(env.DB, slug);
      if (!article) return await notFoundPage(url, env.DB, siteSlug);

      let ogImg = `${url.origin}/logo.png`;
      if (article.i) {
        if (article.i.startsWith('/api/images/')) ogImg = `${API_BASE}${article.i}`;
        else if (article.i.startsWith('http') && !article.i.includes('/logo.png')) ogImg = article.i;
      }

      const safeTitle = escapeHtml(plainText(article.t));
      const safeDesc = escapeHtml(plainText(article.d).substring(0, 200));
      const safeImg = escapeHtml(ogImg);
      const bodyHtml = safeArticleBody(article.c);

      return new HTMLRewriter()
        .on('title', { element(el) { el.setInnerContent(safeTitle); } })
        .on('meta#page-desc', { element(el) { el.setAttribute('content', safeDesc); } })
        .on('#article-loading', { element(el) { el.remove(); } })
        .on('#article-content', { element(el) { el.setAttribute('style', 'display:block;'); } })
        .on('#art-body', { element(el) { el.setInnerContent(bodyHtml, { html: true }); } })
        // Borra og:/twitter: que traiga el origin (shell o function de Pages):
        // si ambos inyectan quedan 2+ og:url y Facebook aborta el scrape
        // (100/1611070), publicando el post como enlace sin imagen.
        .on('meta[property="og:title"]',       { element(el) { el.remove(); } })
        .on('meta[property="og:description"]', { element(el) { el.remove(); } })
        .on('meta[property="og:image"]',       { element(el) { el.remove(); } })
        .on('meta[property="og:image:secure_url"]', { element(el) { el.remove(); } })
        .on('meta[property="og:image:alt"]',   { element(el) { el.remove(); } })
        .on('meta[property="og:url"]',         { element(el) { el.remove(); } })
        .on('meta[property="og:type"]',        { element(el) { el.remove(); } })
        .on('meta[property="og:locale"]',      { element(el) { el.remove(); } })
        .on('meta[property="fb:app_id"]',      { element(el) { el.remove(); } })
        .on('meta[name="twitter:card"]',       { element(el) { el.remove(); } })
        .on('meta[name="twitter:image"]',      { element(el) { el.remove(); } })
        .on('head', {
          element(el) {
            const schemaData = {
              title: article.t || '',
              description: article.d || '',
              imageUrl: ogImg,
              publishedAt: null,
              author: 'Redacción',
              category: 'Nacional',
              tags: [],
              siteName: siteSlug,
              siteLogo: `${url.origin}/logo.png`,
            };
            const schema = generateNewsArticleSchema(schemaData);
            const schemaJson = JSON.stringify(schema);

            el.prepend(
              `<meta property="og:title" content="${safeTitle}" />` +
              `<meta property="og:description" content="${safeDesc}" />` +
              `<meta property="og:image" content="${safeImg}" />` +
              `<meta property="og:url" content="${escapeHtml(url.href)}" />` +
              `<meta property="og:type" content="article" />` +
              `<meta property="og:locale" content="es_MX" />` +
              `<meta name="twitter:card" content="summary_large_image" />` +
              `<meta name="twitter:title" content="${safeTitle}" />` +
              `<meta name="twitter:description" content="${safeDesc}" />` +
              `<meta name="twitter:image" content="${safeImg}" />` +
              `<script type="application/ld+json">${schemaJson}</script>`,
              { html: true }
            );
          }
        })
        .transform(response);
    } catch (_) {
      return response;
    }
  }

  return response;
};
