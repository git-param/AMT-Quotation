const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

function setup(hash) {
  const nodes = new Map();
  const get = id => {
    if (!nodes.has(id)) nodes.set(id, {
      value: '', hidden: true, disabled: false, textContent: '', type: 'password',
      classList: {add() {}, remove() {}}, setAttribute() {}, addEventListener() {}, focus() {},
    });
    return nodes.get(id);
  };
  const calls = [];
  const location = {hash, pathname: '/login', search: ''};
  const context = {document: {getElementById: get}, location, window: {location},
    history: {replaceState(_a, _b, url) {calls.push({history: url});}}, URLSearchParams,
    fetch: async (url, options) => { calls.push({url, options}); return {ok: true, redirected: true, url: '/device/wait'}; },
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync('frontend/login/login.js', 'utf8'), context);
  return {get, calls, context, location};
}

test('direct browser login shows launcher guidance and has no manual MAC input', async () => {
  const html = fs.readFileSync('frontend/login/login.html', 'utf8');
  assert.doesNotMatch(html, /id="macAddress"|id="deviceName"/);
  const {get, calls, context} = setup('');
  assert.equal(get('loginBtn').disabled, true);
  assert.match(get('deviceNotice').textContent, /Windows desktop launcher/);
  await context.doLogin({preventDefault() {}});
  assert.equal(calls.length, 0);
});

test('launcher context is submitted automatically with credentials', async () => {
  const {get, calls, context, location} = setup('#mac=02%3A11%3A22%3A33%3A44%3A55&name=SALES-PC');
  assert.equal(get('deviceNotice').hidden, true);
  get('username').value = 'alice'; get('password').value = 'secret';
  await context.doLogin({preventDefault() {}});
  const request = calls.find(call => call.url === '/login');
  assert.equal(request.options.body.get('mac_address'), '02:11:22:33:44:55');
  assert.equal(request.options.body.get('device_name'), 'SALES-PC');
  assert.equal(location.href, '/device/wait');
  assert.ok(calls.some(call => call.history === '/login'));
});

test('invalid launcher context blocks login without a request', async () => {
  const {get, calls, context} = setup('#mac=random&name=PC');
  assert.equal(get('loginBtn').disabled, true);
  await context.doLogin({preventDefault() {}});
  assert.equal(calls.filter(call => call.url === '/login').length, 0);
});
