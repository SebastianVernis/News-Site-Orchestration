async function getSiteName(db, siteSlug) {
  try {
    const row = await db.prepare('SELECT NOMBRE FROM SITIOS WHERE SLUG = ? LIMIT 1').bind(siteSlug).first();
    if (row?.NOMBRE) return row.NOMBRE;
  } catch (_) {}
  // Fallback: capitalize slug
  return siteSlug.charAt(0).toUpperCase() + siteSlug.slice(1).replace(/([A-Z])/g, ' $1');
}

async function resolveArticleBySlug(db, slug) {
  let article = await db.prepare(
    "SELECT ID as para_id, SLUG as canonical_slug, LEGACY_SLUG as legacy_slug, TITULO_PARAFRASEADO as title, DESCRIPCION_PARAFRASEADA as desc, URL_IMAGEN as image, META_TITLE as meta_title, META_DESCRIPTION as meta_desc, FOCUS_KEYWORD as focus_keyword, TAGS as tags, FECHA_PUBLICACION as fecha_publicacion FROM ARTICULOS_PARAFRASEADOS WHERE SLUG = ? AND ESTADO = 'PUBLICADO' LIMIT 1"
  ).bind(slug).first();

  let isCMS = false;

  if (!article) {
    article = await db.prepare(
      "SELECT ID as para_id, SLUG as canonical_slug, LEGACY_SLUG as legacy_slug, TITULO as title, DESCRIPCION as desc, URL_IMAGEN as image, META_TITLE as meta_title, META_DESCRIPTION as meta_desc, FOCUS_KEYWORD as focus_keyword, TAGS as tags, FECHA_PUBLICACION as fecha_publicacion FROM ARTICULOS_CMS WHERE SLUG = ? AND ESTADO = 'PUBLICADO' LIMIT 1"
    ).bind(slug).first();
    isCMS = Boolean(article);
  }

  if (!article) {
    article = await db.prepare(
      "SELECT ID as para_id, SLUG as canonical_slug, LEGACY_SLUG as legacy_slug, TITULO_PARAFRASEADO as title, DESCRIPCION_PARAFRASEADA as desc, URL_IMAGEN as image, META_TITLE as meta_title, META_DESCRIPTION as meta_desc, FOCUS_KEYWORD as focus_keyword, TAGS as tags, FECHA_PUBLICACION as fecha_publicacion FROM ARTICULOS_PARAFRASEADOS WHERE LEGACY_SLUG = ? AND ESTADO = 'PUBLICADO' LIMIT 1"
    ).bind(slug).first();
  }

  if (!article) {
    article = await db.prepare(
      "SELECT ID as para_id, SLUG as canonical_slug, LEGACY_SLUG as legacy_slug, TITULO as title, DESCRIPCION as desc, URL_IMAGEN as image, META_TITLE as meta_title, META_DESCRIPTION as meta_desc, FOCUS_KEYWORD as focus_keyword, TAGS as tags, FECHA_PUBLICACION as fecha_publicacion FROM ARTICULOS_CMS WHERE LEGACY_SLUG = ? AND ESTADO = 'PUBLICADO' LIMIT 1"
    ).bind(slug).first();
    isCMS = Boolean(article);
  }

  return { article, isCMS };
}


function notFoundResponse(url, siteName, requestedSlug) {
  const name = (siteName || 'Noticias').toString();
  const esc = (t) => String(t || '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
  const home = url.origin + '/';
  const canonical = url.origin + '/articulo/?slug=' + encodeURIComponent(requestedSlug || '');
  const html = `<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(name)}</title>
<meta name="robots" content="noindex, follow">
<meta property="og:type" content="website">
<meta property="og:site_name" content="${esc(name)}">
<meta property="og:title" content="${esc(name)}">
<meta property="og:description" content="La nota que buscas ya no esta disponible. Te invitamos a leer las mas recientes.">
<meta property="og:url" content="${canonical}">
<meta property="og:image" content="${home}logo-header.png">
<meta property="og:image:secure_url" content="${home}logo-header.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="${esc(name)}">
<meta name="twitter:description" content="La nota que buscas ya no esta disponible. Te invitamos a leer las mas recientes.">
<meta name="twitter:image" content="${home}logo-header.png">
<meta http-equiv="refresh" content="6;url=${home}">
<style>body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0;display:flex;min-height:100vh;align-items:center;justify-content:center;background:#0f1115;color:#e8eaed;text-align:center;padding:24px}a{color:#4da3ff}</style>
</head>
<body>
<main>
<h1 style="font-size:1.35rem;margin:0 0 12px">Esta nota ya no esta disponible</h1>
<p style="opacity:.8;margin:0 0 20px">Puede que haya sido retirada o que el enlace este incompleto.</p>
<p><a href="${home}">Ir a la portada de ${esc(name)}</a></p>
</main>
</body>
</html>`;
  return new Response(html, {
    status: 200,
    headers: {
      'content-type': 'text/html; charset=utf-8',
      'cache-control': 'public, max-age=120',
      'x-og-fallback': 'not-found'
    }
  });
}

export async function handleArticleRequest(context, siteSlug) {
  const { request, env, next } = context;
  const url = new URL(request.url);

  const pathname = url.pathname;
  if (/\.(css|js|json|png|jpg|jpeg|gif|svg|webp|ico|woff|woff2|ttf|eot)$/i.test(pathname)) {
    return await next();
  }

  const requestedSlug = url.searchParams.get('slug');
  const canonicalUrl = url.toString();

  if (!requestedSlug) {
    return Response.redirect(url.origin, 302);
  }

  try {
    if (!env.DB) {
      console.warn('[OG MIDDLEWARE] ' + siteSlug + ': env.DB not available');
      return await next();
    }

    const [{ article }, siteName] = await Promise.all([
      resolveArticleBySlug(env.DB, requestedSlug),
      getSiteName(env.DB, siteSlug)
    ]);
    if (!article) {
      return notFoundResponse(url, siteName, requestedSlug);
    }

    if (article.canonical_slug && article.canonical_slug !== requestedSlug) {
      const redirectUrl = new URL(url.href);
      redirectUrl.searchParams.set('slug', article.canonical_slug);
      return Response.redirect(redirectUrl.toString(), 302);
    }

    const response = await next();

    const seoTitle = article.meta_title || article.title;
    const seoDescription = article.meta_desc || article.desc;

    const stripHtml = (html) => {
      if (!html) return '';
      return String(html)
        .replace(/<script[\s\S]*?<\/script>/gi, ' ')
        .replace(/<style[\s\S]*?<\/style>/gi, ' ')
        .replace(/<[^>]+>/g, ' ')
        .replace(/&nbsp;/gi, ' ')
        .replace(/&amp;/gi, '&')
        .replace(/\s+/g, ' ')
        .trim();
    };

    const description = seoDescription || stripHtml(article.desc || '').substring(0, 160);

    const normalizeImageUrl = (value) => {
      if (!value || typeof value !== 'string') return url.origin + '/logo.png';
      let n = value.trim();
      if (!n || n.includes('undefined')) return url.origin + '/logo.png';
      if (n.startsWith('//')) n = 'https:' + n;
      else if (n.startsWith('/')) n = url.origin + n;
      if (/^http:\/\//i.test(n)) n = n.replace(/^http:\/\//i, 'https://');
      if (!/^https:\/\//i.test(n)) return url.origin + '/logo.png';
      return n;
    };

    const image = normalizeImageUrl(article.image || '/logo.png');

    // Update visit tracking
    const tableName = 'ARTICULOS_SITIO_' + siteSlug.toUpperCase();
    try {
      await env.DB.prepare(
        'UPDATE ' + tableName + ' SET WEB_URL = ?, WEB_FECHA = CASE WHEN WEB_FECHA IS NULL THEN datetime(\'now\') ELSE WEB_FECHA END WHERE ID_PARAFRASEADO = ?'
      ).bind(url.href, article.para_id).run();
    } catch (_) {}

    const escapeHtml = (text) => {
      if (!text) return '';
      return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    };

    const esc = (s) => escapeHtml(s || '');
    const now = new Date().toISOString();

    // Build SEO tags
    let tagsHtml = '\n';
    tagsHtml += '    <meta property="fb:app_id" content="2355151528632792" />\n';
    tagsHtml += '    <meta property="og:type" content="article" />\n';
    tagsHtml += '    <meta property="og:title" content="' + esc(seoTitle) + '" />\n';
    tagsHtml += '    <meta property="og:description" content="' + esc(description) + '" />\n';
    tagsHtml += '    <meta property="og:image" content="' + esc(image) + '" />\n';
    tagsHtml += '    <meta property="og:image:secure_url" content="' + esc(image) + '" />\n';
    tagsHtml += '    <meta property="og:image:alt" content="' + esc(seoTitle) + '" />\n';
    tagsHtml += '    <meta property="og:url" content="' + esc(canonicalUrl) + '" />\n';
    tagsHtml += '    <meta property="og:site_name" content="' + esc(siteName) + '" />\n';
    tagsHtml += '    <meta property="og:locale" content="es_MX" />\n';
    tagsHtml += '    <meta property="og:updated_time" content="' + now + '" />\n';
    tagsHtml += '    <meta name="twitter:card" content="summary_large_image" />\n';
    tagsHtml += '    <meta name="twitter:title" content="' + esc(seoTitle) + '" />\n';
    tagsHtml += '    <meta name="twitter:description" content="' + esc(description) + '" />\n';
    tagsHtml += '    <meta name="twitter:image" content="' + esc(image) + '" />\n';
    tagsHtml += '    <meta name="twitter:image:alt" content="' + esc(seoTitle) + '" />\n';
    tagsHtml += '    <meta name="description" content="' + esc(description) + '" />\n';
    tagsHtml += '    <meta name="robots" content="index, follow" />\n';

    // Keywords
    if (article.focus_keyword || article.tags) {
      let kwParts = [];
      if (article.focus_keyword) kwParts.push(article.focus_keyword);
      if (article.tags) {
        try { const p = JSON.parse(article.tags); if (Array.isArray(p)) kwParts.push(...p); } catch (_) {}
      }
      if (kwParts.length) {
        tagsHtml += '    <meta name="keywords" content="' + esc(kwParts.join(', ')) + '" />\n';
      }
    }

    // JSON-LD NewsArticle
    const jsonLd = {
      '@context': 'https://schema.org',
      '@type': 'NewsArticle',
      'headline': seoTitle,
      'description': description,
      'image': [image],
      'datePublished': article.fecha_publicacion || now,
      'dateModified': now,
      'author': [{ '@type': 'Organization', 'name': siteName }],
      'publisher': { '@type': 'Organization', 'name': siteName, 'logo': { '@type': 'ImageObject', 'url': image } },
      'mainEntityOfPage': { '@type': 'WebPage', '@id': canonicalUrl },
      'inLanguage': 'es_MX'
    };
    tagsHtml += '    <script type="application/ld+json">' + JSON.stringify(jsonLd) + '</script>\n';

    // Read original body and inject
    const originalBody = await response.text();

    // Replace title
    let body = originalBody.replace(
      /<title[^>]*>[^<]*<\/title>/,
      '<title>' + esc(seoTitle) + '</title>'
    );

    // Deduplicar metadatos sociales: si el shell estatico o el worker del CMS
    // ya pusieron og:*, nos quedariamos con 2+ og:url y Facebook rechaza el
    // scrape (error 100/1611070 "More Than One OG URL Specified"), dejando el
    // post como enlace sin imagen.
    body = body
      .replace(/<meta\s+property=["'](?:og|fb|article):[^"']*["'][^>]*>\s*/gi, '')
      .replace(/<meta\s+name=["']twitter:[^"']*["'][^>]*>\s*/gi, '')
      .replace(/<meta\s+name=["']description["'][^>]*>\s*/gi, '')
      .replace(/<script\s+type=["']application\/ld\+json["'][^>]*>[\s\S]*?<\/script>\s*/gi, '');

    // Inject SEO tags before </head>
    const headCloseIdx = body.indexOf('</head>');
    if (headCloseIdx !== -1) {
      body = body.substring(0, headCloseIdx) + tagsHtml + '</head>' + body.substring(headCloseIdx + 7);
    }

    return new Response(body, {
      status: response.status,
      statusText: response.statusText,
      headers: response.headers
    });
  } catch (e) {
    console.error('SEO Middleware Error:', e.message);
    return await next();
  }
}
