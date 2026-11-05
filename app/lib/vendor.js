// The vendored libraries (app/vendor/) are loaded on demand, not by the pages: MapLibre when a map is
// first drawn, supabase-js only if the data file fails to load. So the finder's first paint does not
// wait for 300 KB of map code (requirement P1), and the pages stay free of CDN tags (R3).
//
//   if (await vendorReady('maplibregl')) ...   // window.maplibregl exists
//
// Resolves true when the global exists, false when a file failed to load or there is no document (tests).
// To update a library, change its folder here and in app/vendor/README.md.
export const LIBRARIES = {
  maplibregl: { script: '/app/vendor/maplibre-gl@5.6.0/maplibre-gl.js', style: '/app/vendor/maplibre-gl@5.6.0/maplibre-gl.css' },
  supabase: { script: '/app/vendor/supabase-js@2.117.3/supabase.js' },
};

const loading = new Map(); // global name → Promise<boolean>, so each library is requested once

function add(tag, attributes) {
  return new Promise((resolve) => {
    const el = Object.assign(document.createElement(tag), attributes);
    el.addEventListener('load', () => resolve(true), { once: true });
    el.addEventListener('error', () => resolve(false), { once: true });
    document.head.append(el);
  });
}

export function vendorReady(name) {
  if (globalThis.window?.[name]) return Promise.resolve(true);
  const lib = LIBRARIES[name];
  if (!lib || !globalThis.document) return Promise.resolve(false);
  if (!loading.has(name)) {
    const files = [add('script', { src: lib.script })];
    if (lib.style) files.push(add('link', { rel: 'stylesheet', href: lib.style }));
    loading.set(name, Promise.all(files).then((ok) => ok.every(Boolean) && Boolean(window[name])));
  }
  return loading.get(name);
}
