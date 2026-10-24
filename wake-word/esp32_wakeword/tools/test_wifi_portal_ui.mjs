import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';

const html = readFileSync(new URL('../main/wifi_portal.h', import.meta.url), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const defaultUrl = 'https://voice-gateway.200-129-37-25.sslip.io';

function portal() {
  const elements = new Map();
  for (const tag of html.matchAll(/<(input|button|form|select|p)\b([^>]*)>/g)) {
    const id = tag[2].match(/\bid="([^"]+)"/)?.[1];
    if (!id) continue;
    const value = tag[2].match(/\bvalue="([^"]*)"/)?.[1] ?? '';
    elements.set(id, {
      value, defaultValue: value, readOnly: /\breadonly\b/.test(tag[2]),
      disabled: /\bdisabled\b/.test(tag[2]),
      focus() { this.focused = true; },
      replaceChildren() {}, add() {},
    });
  }
  const requests = [];
  const timers = [];
  vm.runInNewContext(script, {
    document: { getElementById: id => elements.get(id) },
    fetch: (path, options) => new Promise((resolve, reject) => {
      requests.push({ path, options, resolve, reject });
    }),
    setTimeout: callback => timers.push(callback),
    Option: function () {},
  });
  return {
    get: id => elements.get(id), requests,
    async status(data) {
      const index = requests.findIndex(request => request.path === '/api/status');
      assert.notEqual(index, -1);
      requests.splice(index, 1)[0].resolve({ ok: true, json: async () => data });
      await new Promise(setImmediate);
    },
    async failStatus() {
      requests.splice(requests.findIndex(r => r.path === '/api/status'), 1)[0]
        .reject(new Error('offline'));
      await new Promise(setImmediate);
    },
    poll() { timers.shift()(); },
  };
}

test('new or blank configuration shows the locked default gateway', async () => {
  const page = portal();
  assert.equal(page.get('base_url').value, defaultUrl);
  assert.equal(page.get('base_url').readOnly, true);
  await page.status({ ssid: '', base_url: '' });
  assert.equal(page.get('base_url').value, defaultUrl);
});

test('reopening loads the saved custom URL and Wi-Fi name', async () => {
  for (let reopen = 0; reopen < 2; reopen++) {
    const page = portal();
    await page.status({ ssid: 'Saved network', base_url: 'https://custom.example' });
    assert.equal(page.get('base_url').value, 'https://custom.example');
    assert.equal(page.get('ssid').value, 'Saved network');
    assert.equal(page.get('base_url').readOnly, true);
  }
});

test('edit unlocks and keeps a blurred draft across late and repeated status replies', async () => {
  const page = portal();
  assert.equal(typeof page.get('edit_url')?.onclick, 'function');
  page.get('edit_url').onclick();
  assert.equal(page.get('base_url').readOnly, false);
  assert.equal(page.get('base_url').focused, true);
  page.get('base_url').value = 'https://draft.example';
  page.get('base_url').focused = false;
  await page.status({ ssid: 'Saved network', base_url: 'https://old.example' });
  page.poll();
  await page.status({ base_url: 'https://old.example' });
  assert.equal(page.get('base_url').value, 'https://draft.example');
  page.get('password').value = 'wifi-password';
  page.get('config').onsubmit({ preventDefault() {} });
  const request = page.requests.find(r => r.path === '/api/config');
  assert.deepEqual(JSON.parse(request.options.body), {
    ssid: 'Saved network', password: 'wifi-password', base_url: 'https://draft.example',
  });
});

test('a failed initial status can recover the saved URL on the next poll', async () => {
  const page = portal();
  await page.failStatus();
  page.poll();
  await page.status({ base_url: 'https://custom.example' });
  assert.equal(page.get('base_url').value, 'https://custom.example');
});

test('key stays masked and is submitted only as a replacement, never read from status', async () => {
  const page = portal();
  assert.match(html, /id="auth_key" type="password"/);
  await page.status({ ssid: 'Saved network', auth_configured: true, auth_key: 'never-render-this' });
  assert.equal(page.get('auth_key').value, '');
  assert.equal(page.get('auth_status').textContent, 'Chave salva.');
  assert.equal(page.get('auth_key').readOnly, true);
  page.get('edit_key').onclick();
  assert.equal(page.get('auth_key').readOnly, false);
  const key = 'test-only-new-key-' + 'a'.repeat(40);
  page.get('auth_key').value = key;
  page.get('config').onsubmit({ preventDefault() {} });
  const request = page.requests.find(r => r.path === '/api/config');
  assert.equal(JSON.parse(request.options.body).auth_key, key);
});

test('saving Wi-Fi without editing keeps gateway and key out of the request', async () => {
  const page = portal();
  await page.status({ ssid: 'Saved network', base_url: 'https://saved.example', auth_configured: true });
  // Even an autofilled password field must not replace the key without opting in.
  page.get('auth_key').value = 'unrequested-autofill';
  page.get('password').value = 'wifi-password';
  page.get('config').onsubmit({ preventDefault() {} });
  const body = JSON.parse(page.requests.find(r => r.path === '/api/config').options.body);
  assert.deepEqual(body, { ssid: 'Saved network', password: 'wifi-password' });
});
