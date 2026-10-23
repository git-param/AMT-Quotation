const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

function waiting(status, fail = false) {
  const nodes = new Map();
  const get = id => { if (!nodes.has(id)) nodes.set(id, {textContent: '', onclick: null}); return nodes.get(id); };
  const location = {href: ''};
  const context = {document: {getElementById: get, cookie: ''}, location,
    fetch: async () => { if (fail) throw Error('offline'); return {ok: true, status: 200, json: async () => ({status})}; },
    setInterval: () => {}, decodeURIComponent};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync('frontend/login/device-wait.js', 'utf8'), context);
  return new Promise(resolve => setImmediate(() => resolve({get, location, context})));
}

test('waiting page shows pending, rejection, and network errors', async () => {
  assert.match(fs.readFileSync('frontend/login/device-wait.html', 'utf8'), /Checking device status/);
  const pending = await waiting('pending');
  assert.match(pending.get('statusTitle').textContent, /Waiting/);
  const rejected = await waiting('rejected');
  assert.match(rejected.get('statusTitle').textContent, /rejected/);
  const offline = await waiting('pending', true);
  assert.match(offline.get('statusTitle').textContent, /Unable/);
});

test('approved device navigates to the application', async () => {
  const approved = await waiting('approved');
  assert.equal(approved.location.href, '/');
});

test('device management renders safe text and actions', async () => {
  const nodes = new Map();
  const element = () => ({children: [], textContent: '', insertCell() {const cell = element(); this.children.push(cell); return cell;}, append(child) {this.children.push(child);}, replaceChildren() {this.children = [];}});
  const get = id => { if (!nodes.has(id)) nodes.set(id, element()); return nodes.get(id); };
  const calls = [];
  const context = {document: {getElementById: get, createElement: element}, fetch: async (url, options) => {
    calls.push(url);
    if (options) return {ok: true, json: async () => ({status: 'approved'})};
    return {ok: true, json: async () => ({devices: [{id: 2, username: '<employee>', mac_address: '02:aa:bb:cc:dd:02', device_name: 'PC', requested_at: 'now', status: 'pending', decided_by: null}]})};
  }};
  vm.createContext(context);
  const source = fs.readFileSync('frontend/manager_dashboard/manager.js', 'utf8');
  vm.runInContext(source.slice(source.indexOf('async function loadDevices()'), source.indexOf('let _resizeTimer;')), context);
  await context.loadDevices();
  const row = get('deviceRows').children[0];
  assert.equal(row.children[0].textContent, '<employee>');
  assert.equal(row.children[6].children.length, 2);
  await row.children[6].children[0].onclick();
  assert.ok(calls.includes('/api/admin/devices/2/approve'));
});
