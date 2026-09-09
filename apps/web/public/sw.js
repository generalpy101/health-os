/* HealthOS service worker — app shell + safe API caching. */
const SHELL_CACHE = "healthos-shell-v1";
const DATA_CACHE = "healthos-data-v1";

const SHELL = ["/manifest.webmanifest", "/icons/icon.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL_CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== SHELL_CACHE && k !== DATA_CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return; // mutations go through the app outbox
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // API GET: network-first, fall back to cache (read-only offline viewing)
  if (url.pathname.startsWith("/api/")) {
    event.respondWith(
      fetch(request)
        .then((res) => {
          if (res.ok) {
            const clone = res.clone();
            caches.open(DATA_CACHE).then((c) => c.put(request, clone));
          }
          return res;
        })
        .catch(() => caches.match(request).then((r) => r || Response.error()))
    );
    return;
  }

  // HTML pages: network-first (a redeploy must never serve stale HTML that
  // references deleted JS chunks — that white-screens the app); cache is only
  // an offline fallback
  if (request.mode === "navigate" || (request.headers.get("accept") || "").includes("text/html")) {
    event.respondWith(
      fetch(request)
        .then((res) => {
          if (res.ok) {
            const clone = res.clone();
            caches.open(SHELL_CACHE).then((c) => c.put(request, clone));
          }
          return res;
        })
        .catch(() => caches.match(request).then((r) => r || Response.error()))
    );
    return;
  }

  // Static assets: stale-while-revalidate (hashed chunks are immutable)
  event.respondWith(
    caches.match(request).then((cached) => {
      const fresh = fetch(request)
        .then((res) => {
          if (res.ok) {
            const clone = res.clone();
            caches.open(SHELL_CACHE).then((c) => c.put(request, clone));
          }
          return res;
        })
        .catch(() => cached);
      return cached || fresh;
    })
  );
});

// ---------- push notifications ----------

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = { body: event.data ? event.data.text() : "" };
  }
  const title = data.title || "HealthOS";
  event.waitUntil(
    self.registration.showNotification(title, {
      body: data.body || "",
      icon: "/icons/icon.svg",
      badge: "/icons/icon.svg",
      data: { url: data.url || "/today" },
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/today";
  event.waitUntil(
    clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((list) => {
        for (const client of list) {
          if ("focus" in client) {
            client.navigate(url);
            return client.focus();
          }
        }
        return clients.openWindow(url);
      })
  );
});
