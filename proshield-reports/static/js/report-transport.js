/** Confirm the signed-in account and bound every report upload by a timeout. */
window.ReportTransport = (() => {
    function failure(message, code, status = 0) {
        return Object.assign(new Error(message), {code, status,
            needsLogin: code === 'authentication_required' || code === 'account_changed'});
    }

    async function request(url, options = {}, timeoutMs = 45000) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), timeoutMs);
        try {
            const response = await fetch(url, {...options, signal: controller.signal, cache: 'no-store'});
            if (response.status === 401 || response.redirected) {
                throw failure('ההתחברות פגה. התחברו מחדש ואז סנכרנו את הדוח השמור.', 'authentication_required', 401);
            }
            if (response.status === 413) {
                throw failure('הקבצים גדולים מדי לשליחה. פתחו את הדוח והקטינו את התמונות לפני ניסיון נוסף.', 'upload_size', 413);
            }
            let data;
            try { data = await response.json(); } catch (_) {
                throw failure('השרת לא אישר את השמירה. הדוח נשמר במכשיר; נסו שוב.', 'server_response', response.status);
            }
            if (!response.ok || data.success === false) {
                throw failure(data.error || 'השרת לא אישר את השמירה. נסו שוב.', data.code || 'server_error', response.status);
            }
            return data;
        } catch (error) {
            if (controller.signal.aborted) {
                throw failure('ההעלאה ארכה יותר מדי. הדוח נשמר במכשיר. בדקו את החיבור ונסו שוב.', 'timeout');
            }
            if (error.code) throw error;
            throw failure('לא הצלחנו להגיע לשרת. בדקו את החיבור ונסו שוב; הדוח נשמר במכשיר.', 'network');
        } finally {
            clearTimeout(timer);
        }
    }

    async function session(userId, timeoutMs) {
        const data = await request('/api/session', {}, Math.min(timeoutMs, 15000));
        if (String(data.user_id) !== String(userId)) {
            throw failure('מחובר חשבון אחר. יש להתחבר לחשבון שבו מולא הדוח כדי לשלוח אותו.', 'account_changed');
        }
        document.querySelector('meta[name="csrf-token"]').content = data.csrf_token;
        return data.csrf_token;
    }

    async function send(formData, userId, {url = '/api/reports', method = 'POST', timeoutMs = 45000} = {}) {
        for (let attempt = 0; attempt < 2; attempt++) {
            const token = await session(userId, timeoutMs);
            try {
                const data = await request(url, {method, body: formData,
                    headers: {'X-CSRFToken': token}}, timeoutMs);
                if (!data.success || !data.report_id) {
                    throw failure('השרת לא אישר את השמירה. הדוח נשמר במכשיר; נסו שוב.', 'server_response');
                }
                return data;
            } catch (error) {
                if (error.code !== 'csrf_expired' || attempt === 1) throw error;
            }
        }
    }

    return {send};
})();
