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

        const _resuelto = await resolveArticleBySlug(env.DB, requestedSlug);
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
    if (!article) {
      return await next();
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
    tagsHtml += '    <meta property="og:site_name" content="NexoPress" />\n';
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
      'author': [{ '@type': 'Organization', 'name': 'NexoPress' }],
      'publisher': { '@type': 'Organization', 'name': 'NexoPress', 'logo': { '@type': 'ImageObject', 'url': image } },
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
