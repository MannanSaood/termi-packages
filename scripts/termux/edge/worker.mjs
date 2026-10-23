// Free-plan redirect/proxy only: no R2, KV, database, secrets, or package bytes.
export default {
  async fetch(request, env) {
    if (!['GET', 'HEAD'].includes(request.method)) return new Response('Method not allowed', {status: 405});
    const url = new URL(request.url);
    if (url.search) return new Response('Not found', {status: 404});
    const asset = url.pathname.match(/^\/apt\/(main|root|x11)\/pool\/(termi-(?:main|root|x11)-[0-9a-f]{24})\/([^/]+)$/);
    if (asset) {
      const [, channel, tag, encoded] = asset;
      let filename;
      try { filename = decodeURIComponent(encoded); } catch { return new Response('Not found', {status: 404}); }
      if (!tag.startsWith(`termi-${channel}-`) || !/^[A-Za-z0-9%+._~-]+\.deb$/.test(filename)
          || !/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(env.PUBLIC_REPOSITORY)) {
        return new Response('Not found', {status: 404});
      }
      return new Response(null, {status: 302, headers: {
        Location: `https://github.com/${env.PUBLIC_REPOSITORY}/releases/download/${tag}/${encodeURIComponent(filename)}`,
        'Cache-Control': 'public, max-age=31536000, immutable',
      }});
    }
    const metadata = /^\/apt\/(main|root|x11)\/dists\/stable\/(?:InRelease|Release|Release\.gpg|main\/binary-aarch64\/(?:Packages|Packages\.gz|by-hash\/SHA256\/[0-9a-f]{64}))$/;
    if (!metadata.test(url.pathname)) return new Response('Not found', {status: 404});
    const origin = new URL(env.METADATA_ORIGIN);
    if (origin.protocol !== 'https:' || origin.hostname !== 'mannansaood.github.io'
        || origin.pathname !== '/termi-packages') return new Response('Invalid metadata origin', {status: 503});
    const response = await fetch(origin.href + url.pathname, {method: request.method, redirect: 'error'});
    const headers = new Headers(response.headers);
    headers.set('Cache-Control', url.pathname.includes('/by-hash/') ? 'public, max-age=31536000, immutable' : 'no-store');
    return new Response(response.body, {status: response.status, headers});
  },
};
