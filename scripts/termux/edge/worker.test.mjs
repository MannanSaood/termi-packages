import test from 'node:test';
import assert from 'node:assert/strict';
import worker from './worker.mjs';
const env = {PUBLIC_REPOSITORY: 'MannanSaood/termi-packages', METADATA_ORIGIN: 'https://mannansaood.github.io/termi-packages'};
const tag = 'termi-main-' + 'a'.repeat(24);
test('release redirect preserves epoch filenames and never forwards credentials', async () => {
  const response = await worker.fetch(new Request(`https://example.test/apt/main/pool/${tag}/example_1%253A2_all.deb`, {
    headers: {Authorization: 'test-only'},
  }), env);
  assert.equal(response.status, 302);
  assert.equal(response.headers.get('Location'), `https://github.com/MannanSaood/termi-packages/releases/download/${tag}/example_1%253A2_all.deb`);
});
test('cross-channel tags and escaped traversal are rejected', async () => {
  for (const path of [`/apt/root/pool/${tag}/a.deb`, `/apt/main/pool/${tag}/%2Fetc.deb`, '/anything']) {
    assert.equal((await worker.fetch(new Request('https://example.test' + path), env)).status, 404);
  }
});
test('only immutable by-hash metadata gets long caching', async () => {
  const original = globalThis.fetch;
  const fetched = [];
  globalThis.fetch = async (url) => { fetched.push(url); return new Response('signed fixture'); };
  try {
    const release = await worker.fetch(new Request('https://example.test/apt/main/dists/stable/InRelease'), env);
    assert.equal(release.headers.get('Cache-Control'), 'no-store');
    const hash = await worker.fetch(new Request('https://example.test/apt/main/dists/stable/main/binary-aarch64/by-hash/SHA256/' + 'b'.repeat(64)), env);
    assert.match(hash.headers.get('Cache-Control'), /immutable/);
    assert.equal(fetched[0], 'https://mannansaood.github.io/termi-packages/apt/main/dists/stable/InRelease');
  } finally { globalThis.fetch = original; }
});
