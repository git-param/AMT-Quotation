/* Regression checks for enquiry lookup requests without a browser dependency. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

class Element {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.value = '';
    this.classList = {add() {}};
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute() {}
  querySelectorAll() { return []; }
}

function setup(scope, fetch) {
  const context = {
    window: {}, document: {createElement: tag => new Element(tag)}, fetch,
  };
  vm.createContext(context);
  const file = path.join(__dirname, '../frontend/enquiries/sku-drafts.js');
  vm.runInContext(fs.readFileSync(file, 'utf8'), context);
  const host = new Element('div');
  const drafts = context.window.createSkuDraftEditor(host, scope, () => 'USD');
  const lookup = host.children[1];
  const input = lookup.children[1];
  input.value = '1258\n4657';
  return {button: lookup.children[2].children[0], status: lookup.children[2].children[2], drafts};
}

test('missing client produces a useful prompt and no API request', async () => {
  let requests = 0;
  const editor = setup(() => ({client_id: 0}), () => { requests++; });
  await editor.button.onclick();
  assert.equal(requests, 0);
  assert.match(editor.status.textContent, /Select a client/);
  assert.equal(editor.button.disabled, false);
});

test('creation client selection validates the actual selected option', () => {
  const file = path.join(__dirname, '../frontend/enquiries/enquiries.js');
  const source = fs.readFileSync(file, 'utf8');
  const start = source.indexOf('function creationScope()');
  const end = source.indexOf('const initialSkuEditor', start);
  let focused = false;
  const client = {value: '', selectedOptions: [{}], focus() { focused = true; }};
  const context = {byId: () => client};
  vm.createContext(context);
  vm.runInContext(source.slice(start, end), context);
  assert.throws(() => context.creationScope(), /Select an editable client/);
  assert.equal(focused, true);
  client.value = '7';
  assert.equal(context.creationScope().client_id, 7);
  client.selectedOptions[0].disabled = true;
  assert.throws(() => context.creationScope(), /Select an editable client/);
});

for (const key of ['client_id', 'enquiry_id']) {
  test(`lookup sends valid ${key} and separated SKU codes`, async () => {
    let payload;
    const line = {sku: '1258', description: 'Marine spare', quantity: '1',
      unit_price: '218.49', currency: 'USD'};
    const editor = setup(() => ({[key]: 7}), async (url, options) => {
      assert.equal(url, '/api/enquiries/sku-lookup');
      payload = JSON.parse(options.body);
      return {ok: true, json: async () => ({drafts: [line]})};
    });
    await editor.button.onclick();
    assert.deepEqual(payload, {[key]: 7, skus: ['1258', '4657'], currency: 'USD'});
    assert.match(editor.status.textContent, /draft rows added/);
    assert.deepEqual(JSON.parse(JSON.stringify(editor.drafts.values())), [line]);
  });
}

test('switching client during lookup rejects stale results', async () => {
  let clientId = 7;
  const editor = setup(() => ({client_id: clientId}), async () => {
    clientId = 8;
    return {ok: true, json: async () => ({drafts: []})};
  });
  await editor.button.onclick();
  assert.match(editor.status.textContent, /changed while fetching/);
});

test('lookup failures display the API message and allow retry', async () => {
  const editor = setup(() => ({enquiry_id: 7}), async () => ({
    ok: false, json: async () => ({error: 'Client access is read-only.'}),
  }));
  await editor.button.onclick();
  assert.equal(editor.status.textContent, 'Client access is read-only.');
  assert.equal(editor.button.disabled, false);
});
