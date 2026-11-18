/** Keep complete field reports, including File objects, until the server confirms them. */
const OfflineQueue = (() => {
    const databaseName = 'proshield-offline-reports';
    const storeName = 'reports';
    let syncPromise = null;

    function open() {
        return new Promise((resolve, reject) => {
            const request = indexedDB.open(databaseName, 1);
            let expired = false;
            const timer = setTimeout(() => { expired = true; reject(new Error('לא ניתן לפתוח את הדוח השמור. סגרו לשוניות נוספות של האפליקציה ונסו שוב.')); }, 8000);
            request.onupgradeneeded = () => {
                const database = request.result;
                if (!database.objectStoreNames.contains(storeName)) {
                    database.createObjectStore(storeName, { keyPath: 'id' });
                }
            };
            request.onsuccess = () => {
                clearTimeout(timer);
                if (expired) { request.result.close(); return; }
                request.result.onversionchange = () => request.result.close();
                resolve(request.result);
            };
            request.onerror = () => { clearTimeout(timer); reject(request.error); };
            request.onblocked = () => { expired = true; clearTimeout(timer); reject(new Error('יש לסגור לשוניות נוספות של האפליקציה ולנסות שוב.')); };
        });
    }

    async function transaction(mode, operation) {
        const database = await open();
        try {
            return await new Promise((resolve, reject) => {
                const tx = database.transaction(storeName, mode);
                const timer = setTimeout(() => tx.abort(), 10000);
                const request = operation(tx.objectStore(storeName));
                let result;
                request.onsuccess = () => { result = request.result; };
                request.onerror = () => reject(request.error);
                tx.onerror = () => { clearTimeout(timer); reject(tx.error); };
                tx.onabort = () => { clearTimeout(timer); reject(tx.error || new Error('לא ניתן לקרוא את הדוח השמור. סגרו ופתחו את האפליקציה ונסו שוב.')); };
                tx.oncomplete = () => { clearTimeout(timer); resolve(result); };
            });
        } finally {
            database.close();
        }
    }

    async function save(formData, userId, id) {
        const existing = await get(id, userId);
        const fields = Array.from(formData.entries());
        await transaction('readwrite', store => store.put({
            id,
            userId: String(userId),
            fields,
            filenames: fields.map(([, value]) => value instanceof Blob ? value.name || '' : ''),
            createdAt: existing?.createdAt || new Date().toISOString()
        }));
    }

    async function list(userId) {
        const all = await transaction('readonly', store => store.getAll());
        return all.filter(report => report.userId === String(userId));
    }

    async function get(id, userId) {
        const report = await transaction('readonly', store => store.get(id));
        return report?.userId === String(userId) ? report : null;
    }

    function formDataFor(report) {
        const fields = new FormData();
        const extensions = {'image/jpeg':'jpg', 'image/png':'png', 'image/webp':'webp',
            'image/gif':'gif', 'application/pdf':'pdf'};
        report.fields.forEach(([name, value], index) => {
            if (value instanceof Blob) {
                const filename = report.filenames?.[index] || value.name ||
                    `${name === 'images' ? 'photo' : 'document'}.${extensions[value.type] || 'bin'}`;
                fields.append(name, value, filename);
            } else fields.append(name, value);
        });
        if (!fields.get('client_id')) fields.set('client_id', report.id);
        return fields;
    }

    function toDraft(report) {
        const fields = formDataFor(report);
        const json = name => JSON.parse(fields.get(name) || '[]');
        return {id: report.id, userId: report.userId, updatedAt: report.createdAt,
            fields: {
                reportType: fields.get('report_type') || '', address: fields.get('address') || '',
                customerName: fields.get('customer_name') || '', recipientName: fields.get('recipient_name') || '',
                companyProject: fields.get('company_project') || '', reportDateTime: fields.get('report_datetime') || '',
                installationTypes: json('installation_types'), installationTeam: fields.get('installation_team') || '',
                additionalWorkerIds: json('additional_worker_ids'), additionalWorkerName: fields.get('additional_worker_name') || '',
                products: [], customProducts: json('products'), status: fields.get('status') || '',
                notes: fields.get('notes') || '', signedDeliveryNoteId: fields.get('delivery_note_id') || ''
            }, photos: fields.getAll('images').filter(file => file instanceof Blob),
            deliveryNote: fields.get('delivery_note')};
    }

    async function remove(id) {
        await transaction('readwrite', store => store.delete(id));
    }

    async function clearForUser(userId) {
        for (const report of await list(userId)) {
            await remove(report.id);
        }
    }

    async function sync(userId, onProgress = () => {}) {
        if (syncPromise) return syncPromise;
        syncPromise = (async () => {
            const result = { synced: 0, failed: 0, errors: [] };
            for (const report of await list(userId)) {
                const formData = formDataFor(report);
                try {
                    onProgress(report);
                    await ReportTransport.send(formData, userId);
                    await remove(report.id);
                    result.synced++;
                } catch (error) {
                    result.failed++;
                    const detail = {id: report.id, message: error.message, code: error.code || 'storage', needsLogin: Boolean(error.needsLogin)};
                    result.errors.push(detail);
                    report.lastError = detail;
                    await transaction('readwrite', store => store.put(report));
                    if (error.needsLogin || ['network', 'timeout', 'server_response'].includes(error.code)) break;
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

    return { save, list, get, toDraft, remove, clearForUser, sync };
})();

window.OfflineQueue = OfflineQueue;
