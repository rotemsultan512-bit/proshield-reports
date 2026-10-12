/** Keep complete field reports, including File objects, until the server confirms them. */
const OfflineQueue = (() => {
    const databaseName = 'proshield-offline-reports';
    const storeName = 'reports';
    let syncPromise = null;

    function open() {
        return new Promise((resolve, reject) => {
            const request = indexedDB.open(databaseName, 1);
            request.onupgradeneeded = () => {
                const database = request.result;
                if (!database.objectStoreNames.contains(storeName)) {
                    database.createObjectStore(storeName, { keyPath: 'id' });
                }
            };
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
        });
    }

    async function transaction(mode, operation) {
        const database = await open();
        try {
            return await new Promise((resolve, reject) => {
                const tx = database.transaction(storeName, mode);
                const request = operation(tx.objectStore(storeName));
                let result;
                request.onsuccess = () => { result = request.result; };
                request.onerror = () => reject(request.error);
                tx.onerror = () => reject(tx.error);
                tx.onabort = () => reject(tx.error || new Error('Offline storage aborted'));
                tx.oncomplete = () => resolve(result);
            });
        } finally {
            database.close();
        }
    }

    async function save(formData, userId, id) {
        const fields = Array.from(formData.entries());
        await transaction('readwrite', store => store.put({
            id,
            userId: String(userId),
            fields,
            createdAt: new Date().toISOString()
        }));
    }

    async function list(userId) {
        const all = await transaction('readonly', store => store.getAll());
        return all.filter(report => report.userId === String(userId));
    }

    async function remove(id) {
        await transaction('readwrite', store => store.delete(id));
    }

    async function clearForUser(userId) {
        for (const report of await list(userId)) {
            await remove(report.id);
        }
    }

    async function sync(userId) {
        if (syncPromise) return syncPromise;
        syncPromise = (async () => {
            const result = { synced: 0, failed: 0 };
            for (const report of await list(userId)) {
                const formData = new FormData();
                for (const [name, value] of report.fields) formData.append(name, value);
                try {
                    const response = await fetch('/api/reports', { method: 'POST', body: formData });
                    const data = await response.json();
                    if (!response.ok || !data.success) {
                        result.failed++;
                        if (response.status === 401 || response.status === 403) break;
                        continue;
                    }
                    await remove(report.id);
                    result.synced++;
                } catch (error) {
                    result.failed++;
                    break;
                }
            }
            return result;
        })();
        try {
            return await syncPromise;
        } finally {
            syncPromise = null;
        }
    }

    return { save, list, remove, clearForUser, sync };
})();

window.OfflineQueue = OfflineQueue;
