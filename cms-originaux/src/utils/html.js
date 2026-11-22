import { fetchWithTimeout, fetchWithRetry } from './helpers.js';
import { generateNewsArticleSchema } from './seo.js';

// src/utils/html.js — Utilidades HTML: meta tags, OG scraping, R2 upload

// ============================================================
// getOGImage — Extrae og:image de una URL remota
// ============================================================
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

// ============================================================
// uploadToR2 — Descarga imagen remota y la sube a R2
// Retorna null si la imagen no es accesible (404, etc.)
// ============================================================
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

// ============================================================
// injectMetaTags — Inyecta OG meta tags en páginas de artículo
// usando HTMLRewriter de Cloudflare Workers
// ============================================================
const plainText = (s) => {
  let t = String(s || '');
  t = t.replace(/<[^>]*>/g, ' ');
  t = t.replace(/&nbsp;/gi, ' ').replace(/&quot;/gi, '"')
       .replace(/&#39;|&apos;/gi, "'")
       .replace(/&lt;/gi, '<').replace(/&gt;/gi, '>').replace(/&amp;/gi, '&');
  return t.replace(/\s+/g, ' ').trim();
};

export const injectMetaTags = async (request, env, response) => {
  const url = new URL(request.url);
  const slug = url.searchParams.get('slug');
  if (!slug || !url.pathname.includes('/articulo')) return response;

  try {
    let article = await env.DB.prepare(
      'SELECT TITULO_PARAFRASEADO as t, DESCRIPCION_PARAFRASEADA as d, URL_IMAGEN as i FROM ARTICULOS_PARAFRASEADOS WHERE SLUG = ? LIMIT 1'
    ).bind(slug).first();

    if (!article) {
      article = await env.DB.prepare(
        'SELECT TITULO as t, DESCRIPCION as d, URL_IMAGEN as i FROM ARTICULOS_CMS WHERE SLUG = ? LIMIT 1'
      ).bind(slug).first();
    }

    if (!article) return response;

    let ogImg = `${url.origin}/logo.png`;
    if (article.i) {
      if (article.i.startsWith('/api/images/')) ogImg = `${url.origin}${article.i}`;
      else if (article.i.startsWith('http') && !article.i.includes('/logo.png')) ogImg = article.i;
    }

    const esc = (s) => (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    return new HTMLRewriter()
      .on('title', {
        element(el) { el.setInnerContent(article.t || ''); }
      })
      .on('meta#page-desc', { element(el) { el.setAttribute('content', esc(plainText(article.d))); } })
      // Borra TODO og:/twitter: que traiga el origen (shell vacío o function de Pages).
      // Con 2 og:url Meta responde 100/1611070 y publica sin imagen; el bloque de
      // abajo se prependea al final y HTMLRewriter no vuelve a procesarlo.
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
          el.prepend(
            `<meta property="fb:app_id" content="2355151528632792" />` +
            `<meta property="og:title" content="${esc(plainText(article.t))}" />` +
            `<meta property="og:description" content="${esc(plainText(article.d))}" />` +
            `<meta property="og:image" content="${esc(ogImg)}" />` +
            `<meta property="og:image:secure_url" content="${esc(ogImg)}" />` +
            `<meta property="og:image:alt" content="${esc(plainText(article.t))}" />` +
            `<meta property="og:url" content="${esc(url.href)}" />` +
            `<meta property="og:type" content="article" />` +
            `<meta property="og:locale" content="es_MX" />` +
            `<meta name="twitter:card" content="summary_large_image" />` +
            `<meta name="twitter:image" content="${esc(ogImg)}" />`,
            { html: true }
          );
        }
      })
      .transform(response);
  } catch (_) {
    return response;
  }
};
