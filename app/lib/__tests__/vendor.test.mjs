// app/lib/vendor.js loads the vendored libraries on demand: once per library, resolving false when a file
// fails. A fake document stands in for the browser.
// Run: node --test app/lib/__tests__/
import { test } from 'node:test';
import assert from 'node:assert/strict';

function fakeDocument(outcome) {
  const added = [];
  const element = (tag) => {
    const listeners = {};
    return {
      tag,
      addEventListener: (event, fn) => { listeners[event] = fn; },
      fire: () => listeners[outcome](),
    };
  };
  return {
    added,
    createElement: (tag) => { const el = element(tag); added.push(el); return el; },
    head: { append: () => {} },
  };
}

test('vendorReady resolves false without a document, so tests and unknown names are safe', async () => {
  globalThis.window = {};
  try {
    const { vendorReady } = await import('../vendor.js?no-document');
    assert.equal(await vendorReady('maplibregl'), false);
    assert.equal(await vendorReady('nothing'), false);
  } finally {
    delete globalThis.window;
  }
});

test('vendorReady adds the script and stylesheet once and resolves when the global appears', async () => {
  const doc = fakeDocument('load');
  globalThis.window = {};
  globalThis.document = doc;
  try {
    const { vendorReady, LIBRARIES } = await import('../vendor.js?load');
    const first = vendorReady('maplibregl');
    const second = vendorReady('maplibregl');
    assert.equal(first, second, 'requested once');
    assert.deepEqual(doc.added.map((el) => el.tag), ['script', 'link']);
    assert.equal(doc.added[0].src, LIBRARIES.maplibregl.script);
    assert.equal(doc.added[1].href, LIBRARIES.maplibregl.style);
    globalThis.window.maplibregl = {};
    for (const el of doc.added) el.fire();
    assert.equal(await first, true);
    assert.equal(await vendorReady('maplibregl'), true, 'the global is enough afterwards');
  } finally {
    delete globalThis.window;
    delete globalThis.document;
  }
});

test('vendorReady resolves false when a file fails to load', async () => {
  const doc = fakeDocument('error');
  globalThis.window = {};
  globalThis.document = doc;
  try {
    const { vendorReady } = await import('../vendor.js?error');
    const ready = vendorReady('supabase');
    assert.deepEqual(doc.added.map((el) => el.tag), ['script']);
    for (const el of doc.added) el.fire();
    assert.equal(await ready, false);
    const again = vendorReady('supabase');
    assert.notEqual(again, ready, 'a failed load is tried again on the next call');
    assert.equal(doc.added.length, 2, 'a new script element');
  } finally {
    delete globalThis.window;
    delete globalThis.document;
  }
});
