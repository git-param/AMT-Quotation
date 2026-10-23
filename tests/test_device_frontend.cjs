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

test('admin approvals page lists pending requests and approves a device', async () => {
  const nodes = new Map();
  const element = () => ({children: [], textContent: '', hidden: false, listeners: {},
    classList: {add() {}, remove() {}},
    insertCell() {const cell = element(); this.children.push(cell); return cell;},
    append(child) {this.children.push(child);},
    replaceChildren(...children) {this.children = children;},
    addEventListener(name, callback) {this.listeners[name] = callback;},
  });
  const get = id => { if (!nodes.has(id)) nodes.set(id, element()); return nodes.get(id); };
  const calls = [];
  let status = 'pending';
  const context = {document: {getElementById: get, createElement: element, hidden: false},
    window: {confirm: () => true}, setInterval: () => {},
    fetch: async (url, options) => {
      calls.push(url);
      if (url === '/api/me') return {ok: true, json: async () => ({id: 1, permissions: ['devices.manage']})};
      if (url === '/api/admin/devices') return {ok: true, json: async () => ({devices: [
        {id: 2, user_id: 2, username: '<employee>', device_name: 'PC', mac_address: '02:aa:bb:cc:dd:02', requested_at: '2026-10-23T10:00:00Z', status},
      ]})};
      if (url === '/api/admin/devices/2/approve' && options?.method === 'POST') {
        status = 'approved';
        return {ok: true, json: async () => ({status})};
      }
      throw Error(`Unexpected request: ${url}`);
    },
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync('frontend/manager_dashboard/devices.js', 'utf8'), context);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(get('pendingCount').textContent, '(1)');
  const row = get('pendingDevices').children[0];
  assert.equal(row.children[0].textContent, '<employee>');
  assert.equal(row.children[4].children.length, 2);
  await row.children[4].children[0].listeners.click();
  assert.ok(calls.includes('/api/admin/devices/2/approve'));
  assert.equal(get('pendingCount').textContent, '(0)');
  assert.equal(get('reviewedDevices').children.length, 1);
});
