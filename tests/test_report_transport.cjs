/* Run with: node --test tests/test_report_transport.cjs */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const vm = require('node:vm');

function transport(fetch) {
    const meta = {content: 'old-token'};
    const context = {fetch, document: {querySelector: () => meta}, AbortController, setTimeout, clearTimeout};
    context.window = context;
    vm.createContext(context);
    vm.runInContext(readFileSync(join(__dirname, '../proshield-reports/static/js/report-transport.js'), 'utf8'), context);
    return context.ReportTransport;
}
const session = () => Response.json({user_id: 7, csrf_token: 'fresh-token'});

test('a fresh token and the original multipart files are used for every send', async () => {
    const form = new FormData();
    form.append('client_id', 'keep-original-id');
    form.append('images', new Blob(['photo-bytes'], {type:'image/jpeg'}), 'site.jpg');
    const api = transport(async (url, options) => {
        if (url === '/api/session') return session();
        assert.equal(options.headers['X-CSRFToken'], 'fresh-token');
        assert.equal(options.body, form);
        assert.equal(options.body.get('client_id'), 'keep-original-id');
        assert.equal(options.body.get('images').name, 'site.jpg');
        return Response.json({success:true, report_id:19});
    });
    assert.equal((await api.send(form, 7)).report_id, 19);
});

test('CSRF expiration refreshes once and keeps the same idempotency key', async () => {
    let uploads = 0, sessions = 0;
    const form = new FormData();
    form.append('client_id', 'original');
    const api = transport(async (url, options) => {
        if (url === '/api/session') { sessions++; return session(); }
        assert.equal(options.body.get('client_id'), 'original');
        uploads++;
        return uploads === 1 ? Response.json({success:false, code:'csrf_expired'}, {status:400}) :
            Response.json({success:true, report_id:23});
    });
    assert.equal((await api.send(form, 7)).report_id, 23);
    assert.equal(sessions, 2);
    assert.equal(uploads, 2);
});

test('expired login and a changed account never upload a stored report', async () => {
    for (const response of [() => Response.json({}, {status:401}),
        () => Response.json({user_id:8, csrf_token:'different-account'})]) {
        let calls = 0;
        const api = transport(async () => { calls++; return response(); });
        await assert.rejects(api.send(new FormData(), 7), error => error.needsLogin === true);
        assert.equal(calls, 1);
    }
});

test('a login redirect is reported as expired authentication', async () => {
    const api = transport(async () => ({status:200, redirected:true}));
    await assert.rejects(api.send(new FormData(), 7), error => error.code === 'authentication_required');
});

test('validation errors retain the server message and are not retried', async () => {
    let uploads = 0;
    const api = transport(async url => {
        if (url === '/api/session') return session();
        uploads++;
        return Response.json({success:false, error:'יש להזין שם מקבל הסחורה'}, {status:400});
    });
    await assert.rejects(api.send(new FormData(), 7), error => error.message === 'יש להזין שם מקבל הסחורה');
    assert.equal(uploads, 1);
});

test('HTML server failures are visible instead of being treated as saved', async () => {
    const api = transport(async url => url === '/api/session' ? session() : new Response('<html>502</html>', {status:502}));
    await assert.rejects(api.send(new FormData(), 7), error => error.code === 'server_response');
});

test('network and timeout failures finish with an actionable result', async () => {
    const disconnected = transport(async () => { throw new TypeError('Failed to fetch'); });
    await assert.rejects(disconnected.send(new FormData(), 7), error => error.code === 'network');
    const hanging = transport(async (url, {signal}) => new Promise((resolve, reject) => {
        signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
    }));
    await assert.rejects(hanging.send(new FormData(), 7, {timeoutMs:15}), error => error.code === 'timeout');
});
