// Test shim for Agent Zero's /js/AlpineStore.js: registers the store on Alpine
// (immediately when Alpine already started, otherwise on alpine:init) and returns
// a live proxy to it, like the real createStore().
export function createStore(name, initial) {
  const register = () => window.Alpine.store(name, initial);
  if (window.Alpine) register();
  else document.addEventListener("alpine:init", register, { once: true });
  return new Proxy({}, {
    get(_target, prop) {
      const live = window.Alpine && window.Alpine.store(name);
      return live ? live[prop] : initial[prop];
    },
    set(_target, prop, value) {
      const live = window.Alpine && window.Alpine.store(name);
      (live || initial)[prop] = value;
      return true;
    },
  });
}
