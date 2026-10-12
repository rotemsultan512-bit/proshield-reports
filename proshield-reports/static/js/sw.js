/**
 * Proshield Reports - Service Worker
 * PWA Offline Support & Caching
 */

const STATIC_CACHE = 'proshield-static-v15';

// Static assets to cache
const STATIC_ASSETS = [
    '/static/css/style.css',
    '/static/css/field-ui.css',
    '/static/js/app.js',
    '/static/js/offline-queue.js',
    '/manifest.json',

    '/static/images/icon-192.png',
    '/static/images/icon-512.png'
];

// Install event - cache static assets
self.addEventListener('install', (event) => {
    console.log('[SW] Installing...');
    event.waitUntil(
        caches.open(STATIC_CACHE)
            .then((cache) => {
                console.log('[SW] Caching static assets');
                return cache.addAll(STATIC_ASSETS);
            })
            .then(() => self.skipWaiting())
    );
});

// Activate event - clean up old caches
self.addEventListener('activate', (event) => {
    console.log('[SW] Activating...');
    event.waitUntil(
        caches.keys()
            .then((keys) => {
                return Promise.all(
                    keys.filter((key) => {
                        return key !== STATIC_CACHE;
                    }).map((key) => {
                        console.log('[SW] Removing old cache:', key);
                        return caches.delete(key);
                    })
                );
            })
            .then(() => self.clients.claim())
    );
});

// Allow page to trigger immediate activation
self.addEventListener('message', (event) => {
    if (event.data && event.data.type === 'SKIP_WAITING') {
        self.skipWaiting();
    }
});

// Fetch event - serve from cache, fallback to network
self.addEventListener('fetch', (event) => {
    const { request } = event;
    const url = new URL(request.url);

    // Authenticated pages, API responses, and attachments must never enter CacheStorage.
    if (request.method !== 'GET' || url.origin !== self.location.origin) {
        return;
    }
    if (url.pathname.startsWith('/static/') || url.pathname === '/manifest.json') {
        event.respondWith(cacheFirst(request));
    }
});

// Cache-first strategy
async function cacheFirst(request) {
    const cached = await caches.match(request);
    if (cached) {
        return cached;
    }

    try {
        const response = await fetch(request);
        if (response.ok && response.type === 'basic') {
            const cache = await caches.open(STATIC_CACHE);
            cache.put(request, response.clone());
        }
        return response;
    } catch (error) {
        console.log('[SW] Fetch failed:', error);
        throw error;
    }
}

// Background sync for offline reports
self.addEventListener('sync', (event) => {
    console.log('[SW] Sync event:', event.tag);
    if (event.tag === 'sync-reports') {
        event.waitUntil(syncOfflineReports());
    }
});

async function syncOfflineReports() {
    // This will be handled by the main app
    // Just notify all clients to sync
    const clients = await self.clients.matchAll();
    clients.forEach((client) => {
        client.postMessage({
            type: 'SYNC_REPORTS'
        });
    });
}

// Push notifications (for future use)
self.addEventListener('push', (event) => {
    console.log('[SW] Push received');
    const data = event.data?.json() || {};
    const title = data.title || 'Proshield Reports';
    const options = {
        body: data.body || 'יש לך התראה חדשה',
        icon: '/static/images/icon-192.png',
        badge: '/static/images/icon-192.png',
        dir: 'rtl',
        lang: 'he',
        data: data.data
    };

    event.waitUntil(
        self.registration.showNotification(title, options)
    );
});

// Notification click handler
self.addEventListener('notificationclick', (event) => {
    console.log('[SW] Notification clicked');
    event.notification.close();

    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true })
            .then((clientList) => {
                // Focus existing window or open new one
                for (const client of clientList) {
                    if ('focus' in client) {
                        return client.focus();
                    }
                }
                return clients.openWindow('/dashboard');
            })
    );
});

// Message handler
self.addEventListener('message', (event) => {
    console.log('[SW] Message received:', event.data);

    if (event.data.type === 'SKIP_WAITING') {
        self.skipWaiting();
    }

    if (event.data.type === 'CLEAR_CACHE') {
        event.waitUntil(
            caches.keys().then((keys) => {
                return Promise.all(keys.map((key) => caches.delete(key)));
            })
        );
    }
});

console.log('[SW] Service Worker loaded');
