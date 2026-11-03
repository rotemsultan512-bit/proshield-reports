/** Save unfinished reports, including File objects, on this device. */
const DraftStore = (() => {
    const databaseName = 'proshield-report-drafts';
    const storeName = 'drafts';

    function open() {
        return new Promise((resolve, reject) => {
            const request = indexedDB.open(databaseName, 1);
            request.onupgradeneeded = () => {
                request.result.createObjectStore(storeName, { keyPath: 'id' });
            };
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
        });
    }

    async function transact(mode, operation) {
        const database = await open();
        try {
            return await new Promise((resolve, reject) => {
                const tx = database.transaction(storeName, mode);
                const request = operation(tx.objectStore(storeName));
                let result;
                request.onsuccess = () => { result = request.result; };
                request.onerror = () => reject(request.error);
                tx.onerror = () => reject(tx.error);
                tx.onabort = () => reject(tx.error || new Error('Draft storage aborted'));
                tx.oncomplete = () => resolve(result);
            });
        } finally {
            database.close();
        }
    }

    async function save(draft) {
        await transact('readwrite', store => store.put(draft));
    }

    async function get(id, userId) {
        const draft = await transact('readonly', store => store.get(id));
        return draft?.userId === String(userId) ? draft : null;
    }

    async function list(userId) {
        const all = await transact('readonly', store => store.getAll());
        return all.filter(draft => draft.userId === String(userId))
            .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
    }

    async function remove(id) {
        await transact('readwrite', store => store.delete(id));
    }

    async function clearForUser(userId) {
        for (const draft of await list(userId)) await remove(draft.id);
    }

    return { save, get, list, remove, clearForUser };
})();

window.DraftStore = DraftStore;
