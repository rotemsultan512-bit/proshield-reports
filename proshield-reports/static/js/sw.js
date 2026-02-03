/**
 * Proshield Reports - Service Worker
 * PWA Offline Support & Caching
 */

const CACHE_NAME = 'proshield-reports-v5';
const STATIC_CACHE = 'proshield-static-v5';
const DYNAMIC_CACHE = 'proshield-dynamic-v5';

const ASSET_VERSION = '20260203-04';

// Static assets to cache
const STATIC_ASSETS = [
    '/',
    '/login',
    '/dashboard',
    '/report/new',
    '/settings',

    // Versioned assets (force update)
    `/static/css/style.css?v=${ASSET_VERSION}`,
    `/static/js/app.js?v=${ASSET_VERSION}`,
    `/manifest.json?v=${ASSET_VERSION}`,

    // Fallback non-versioned (some browsers request these)
    '/static/css/style.css',
    '/static/js/app.js',
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
                        return key !== STATIC_CACHE && key !== DYNAMIC_CACHE;
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

    // Skip non-GET requests
    if (request.method !== 'GET') {
        return;
    }

    // Skip API calls (let them go to network)
    if (url.pathname.startsWith('/api/')) {
        event.respondWith(networkFirst(request));
        return;
    }

    // Skip file uploads
    if (url.pathname.startsWith('/uploads/')) {
        event.respondWith(networkFirst(request));
        return;
    }

    // For HTML pages - network first, fallback to cache
    if (request.headers.get('Accept')?.includes('text/html')) {
        event.respondWith(networkFirst(request));
        return;
    }

    // For static assets - cache first
    event.respondWith(cacheFirst(request));
});

// Cache-first strategy
async function cacheFirst(request) {
    const cached = await caches.match(request);
    if (cached) {
        return cached;
    }

    try {
        const response = await fetch(request);
        if (response.ok) {
            const cache = await caches.open(DYNAMIC_CACHE);
            cache.put(request, response.clone());
        }
        return response;
    } catch (error) {
        console.log('[SW] Fetch failed:', error);
        // Return offline fallback if available
        return caches.match('/');
    }
}

// Network-first strategy
async function networkFirst(request) {
    try {
        const response = await fetch(request);
        if (response.ok) {
            const cache = await caches.open(DYNAMIC_CACHE);
            cache.put(request, response.clone());
        }
        return response;
    } catch (error) {
        console.log('[SW] Network failed, trying cache:', error);
        const cached = await caches.match(request);
        if (cached) {
            return cached;
        }
        // Return offline page for HTML requests
        if (request.headers.get('Accept')?.includes('text/html')) {
            return caches.match('/');
        }
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
