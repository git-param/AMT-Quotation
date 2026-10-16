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

function setup(scope, fetch, currency = 'USD', commercial = false) {
  const context = {
    window: {}, document: {createElement: tag => new Element(tag)}, fetch,
  };
  vm.createContext(context);
  const file = path.join(__dirname, '../frontend/enquiries/sku-drafts.js');
  vm.runInContext(fs.readFileSync(file, 'utf8'), context);
  const host = new Element('div');
  const drafts = context.window.createSkuDraftEditor(host, scope, () => currency, null, commercial);
  const lookup = host.children[1];
  const input = lookup.children[1];
  input.value = '1258\n4657';
  return {button: lookup.children[2].children[0], status: lookup.children[2].children[2], drafts, host, input};
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

test('quotation table retains editable deal details and selected items', async () => {
  const line = {sku: '1258', description: 'Marine spare', quantity: '1',
    unit_price: '10.00', currency: 'USD', found: true, stock: 0,
    catalog_prices: {USD: {price: '20.00', sale_price: '10.00'},
      INR: {price: '1800.00', sale_price: '900.00'}}};
  const editor = setup(() => ({client_id: 7}), async () => ({
    ok: true, json: async () => ({drafts: [line]}),
  }));
  await editor.button.onclick();
  const table = editor.host.children[2].children[0];
  const head = table.children[0].children[0];
  assert.equal(head.children.length, 12);
  assert.equal(head.children[7].textContent, 'Rate/Pcs (USD)');
  const row = table.children[1].children[0];
  assert.equal(row.children[6].textContent, '0 Pcs');
  assert.equal(row.children[7].children[0].textContent, '$ 20.00');
  assert.equal(row.children[7].children[2].textContent, '50% off');
  const fields = editor.host.children[3].children[1];
  const quantity = fields.children[2].children[0];
  quantity.value = '2';quantity.oninput();
  const price = fields.children[3].children[0];
  price.value = '8.75';price.oninput();
  assert.equal(editor.drafts.values()[0].quantity, '2');
  assert.equal(editor.drafts.values()[0].unit_price, '8.75');
  const all = head.children[0].children[0];all.checked = false;all.onchange();
  assert.throws(() => editor.drafts.values(), /Select at least one/);
  all.checked = true;all.onchange();
  assert.equal(editor.drafts.values().length, 1);
});

test('order lookup retains HSN, condition and units after refreshing catalog details', async () => {
  const line={sku:'1258',description:'Part',quantity:'1',unit_price:'10.00',currency:'USD',condition:'Used',catalog_prices:{}};
  const editor=setup(()=>({client_id:7}),async()=>({ok:true,json:async()=>({drafts:[{...line}]})}),'USD',true);
  await editor.button.onclick();
  const fields=editor.host.children[3].children[1];
  for(const [index,value] of [[4,'85371090'],[5,'Refurbished'],[6,'Kit']]){
    const control=fields.children[index].children[0];control.value=value;control.oninput();
  }
  await editor.button.onclick();
  const saved=editor.drafts.values()[0];
  assert.equal(saved.hsn_code,'85371090');assert.equal(saved.item_condition,'Refurbished');assert.equal(saved.uom,'Kit');
});

test('order lookup fills shared HSN and offers the four supported UOM choices',async()=>{
  const editor=setup(()=>({client_id:7}),async()=>({ok:true,json:async()=>({shared_hsn_code:'85371090',drafts:[{
    sku:'1258',description:'Part',quantity:'1',unit_price:'10.00',currency:'USD',found:true,stock:3,catalog_prices:{}
  }]})}),'USD',true);
  await editor.button.onclick();
  const fields=editor.host.children[3].children[1];
  const hsn=fields.children[4].children[0],uom=fields.children[6].children[0];
  assert.equal(hsn.value,'85371090');assert.equal(hsn.readOnly,true);
  assert.equal(uom.tag,'select');assert.deepEqual(uom.children.map(option=>option.value),['PCs','Lot','Kit','set']);
});

test('order lookup explains zero stock, zero quantity and excess quantity before adding',async()=>{
  for(const [stock,quantity,message]of [[0,'1',/out of stock.*0 available/],[2,'0',/at least 1/],[2,'3',/requested 3.*only 2 available/]]){
    const editor=setup(()=>({client_id:7}),async()=>({ok:true,json:async()=>({drafts:[{
      sku:'1258',description:'Part',quantity:'1',unit_price:'10.00',currency:'USD',found:true,stock,catalog_prices:{}
    }]})}),'USD',true);
    await editor.button.onclick();
    const control=editor.host.children[3].children[1].children[2].children[0];control.value=quantity;control.oninput();
    assert.throws(()=>editor.drafts.values(),message);assert.match(editor.status.textContent,message);
  }
});

test('repeated lookup merges identical SKUs and preserves user edits', async () => {
  const line = {sku: '1258', description: 'Original part', quantity: '1',
    unit_price: '10.00', currency: 'USD', catalog_prices: {}};
  let payload;
  const editor = setup(() => ({client_id: 7}), async (url, options) => {
    payload = JSON.parse(options.body);
    return {ok: true, json: async () => ({drafts: [line, {...line}]})};
  });
  editor.input.value = '1258, 1258\n1258';
  await editor.button.onclick();
  assert.deepEqual(payload.skus, ['1258']);
  const fields = editor.host.children[3].children[1];
  for (const [index, value] of [[1, 'Custom description'], [2, '2'], [3, '8.75']]) {
    const control = fields.children[index].children[0];
    control.value = value;control.oninput();
  }
  await editor.button.onclick();
  const saved = editor.drafts.values();
  assert.equal(saved.length, 1);
  assert.equal(saved[0].description, 'Custom description');
  assert.equal(saved[0].quantity, '2');
  assert.equal(saved[0].unit_price, '8.75');
  assert.equal(editor.host.children[2].children[0].children[1].children.length, 1);
});

for (const currency of ['USD', 'INR']) {
  test(`legacy ${currency} draft prices remain visible in both currencies`, async () => {
    const editor = setup(() => ({client_id: 7}), async url => {
      if (url === '/api/rate') return {ok: true, json: async () => ({rate: 90})};
      return {ok: true, json: async () => ({drafts: [{sku: '1258',
        description: 'Part', quantity: '1', unit_price: currency === 'USD' ? '10.00' : '900.00',
        currency}]})};
    }, currency);
    await editor.button.onclick();
    const row = editor.host.children[2].children[0].children[1].children[0];
    assert.equal(row.children[7].textContent, '$ 10.00');
    assert.equal(row.children[8].textContent, '\u20b9 900.00');
  });
}

test('missing conversion never hides a zero USD price or invents an INR price', async () => {
  const editor = setup(() => ({client_id: 7}), async url => {
    if (url === '/api/rate') throw new Error('Offline');
    return {ok: true, json: async () => ({drafts: [{sku: '1258',
      description: 'Part', quantity: '1', unit_price: '0.00', currency: 'USD'}]})};
  });
  await editor.button.onclick();
  const row = editor.host.children[2].children[0].children[1].children[0];
  assert.equal(row.children[7].textContent, '$ 0.00');
  assert.equal(row.children[8].textContent, 'Unavailable');
});

test('item picker shows only SKU and quantity entry accepts whole numbers', async () => {
  const editor = setup(() => ({client_id: 7}), async () => ({
    ok: true, json: async () => ({drafts: [{sku: '25673', description: 'Part',
      quantity: '1.000', unit_price: '540.54', currency: 'USD', catalog_prices: {}}]}),
  }));
  await editor.button.onclick();
  const editBox = editor.host.children[3];
  const picker = editBox.children[0].children[1];
  assert.equal(picker.children[0].textContent, '25673');
  const quantity = editBox.children[1].children[2].children[0];
  assert.equal(quantity.value, '1');
  assert.equal(quantity.step, '1');
  assert.equal(quantity.min, '1');
  quantity.value = '1.5';quantity.oninput();
  assert.throws(() => editor.drafts.values(), /whole-number quantity/);
  quantity.value = '3';quantity.oninput();
  assert.equal(editor.drafts.values()[0].quantity, '3');
});

test('manual order SKU loads and prints configured HSN before any lookup',async()=>{
  const requests=[];
  const editor=setup(()=>({client_id:7}),async url=>{requests.push(url);return {ok:true,json:async()=>({shared_hsn_code:'85371090'})};},'USD',true);
  const manual=editor.host.children[1].children[2].children[1];
  await manual.onclick();
  let fields=editor.host.children[3].children[1];
  assert.equal(fields.children[4].children[0].value,'85371090');assert.equal(fields.children[4].children[0].readOnly,true);
  for(const [index,value] of [[0,'MANUAL'],[1,'Manual part'],[3,'12.50']]){const input=fields.children[index].children[0];input.value=value;input.oninput();}
  assert.equal(editor.drafts.values()[0].hsn_code,'85371090');
  await manual.onclick();fields=editor.host.children[3].children[1];assert.equal(fields.children[4].children[0].value,'85371090');
  assert.deepEqual(requests,['/api/sku-defaults']);
});

test('missing lookup SKU does not block valid items and offers a prefilled manual action',async()=>{
  const editor=setup(()=>({client_id:7}),async()=>({ok:true,json:async()=>({shared_hsn_code:'85371090',drafts:[
    {sku:'1258',description:'Available part',quantity:'1',unit_price:'10.00',currency:'USD',found:true,stock:3,catalog_prices:{}},
    {sku:'4657',description:'',quantity:'1',unit_price:'',currency:'USD',found:false,lookup_status:'not_found'},
  ]})}),'USD',true);
  await editor.button.onclick();
  assert.equal(editor.drafts.values().length,1);assert.equal(editor.drafts.values()[0].sku,'1258');
  const notice=editor.host.children[1].children[3];assert.equal(notice.hidden,false);
  assert.match(notice.children[1].children[0].textContent,/4657.*not found.*manually/);
  await notice.children[1].children[1].onclick();
  const fields=editor.host.children[3].children[1];
  assert.equal(fields.children[0].children[0].value,'4657');assert.equal(fields.children[4].children[0].value,'85371090');
  assert.equal(notice.hidden,true);
  for(const [index,value] of [[1,'Manually entered part'],[3,'5.00']]){const input=fields.children[index].children[0];input.value=value;input.oninput();}
  const saved=editor.drafts.values();assert.equal(saved.length,2);assert.equal(saved[0].description,'Available part');assert.equal(saved[1].sku,'4657');
  // A later missing result must preserve a manually completed item.
  await editor.button.onclick();assert.equal(editor.drafts.values().length,2);assert.equal(editor.drafts.values()[1].description,'Manually entered part');
});

test('lookup failures are distinguished from missing catalog SKUs',async()=>{
  const editor=setup(()=>({client_id:7}),async()=>({ok:true,json:async()=>({usd_inr_rate:90,drafts:[{sku:'OFFLINE',found:false,lookup_status:'unavailable',error:'Lookup unavailable'}]})}),'USD',true);
  await editor.button.onclick();
  const notice=editor.host.children[1].children[3];assert.match(notice.children[1].children[0].textContent,/Could not look up.*Retry/);
  assert.doesNotMatch(notice.children[1].children[0].textContent,/not found/);
  assert.throws(()=>editor.drafts.values(),/Select at least one/);
});

test('manual HSN loading failure allows retry without creating an empty item',async()=>{
  let fail=true;
  const editor=setup(()=>({client_id:7}),async()=>({ok:!fail,json:async()=>fail?{error:'Unable to load defaults'}:{shared_hsn_code:'85371090'}}),'USD',true);
  const manual=editor.host.children[1].children[2].children[1];
  await manual.onclick();assert.match(editor.status.textContent,/Unable to load defaults/);assert.equal(manual.disabled,false);
  assert.throws(()=>editor.drafts.values(),/Select at least one/);
  fail=false;await manual.onclick();assert.equal(editor.host.children[3].children[1].children[4].children[0].value,'85371090');
});

test('reset during asynchronous HSN loading does not restore a discarded manual item',async()=>{
  let finish;
  const editor=setup(()=>({client_id:7}),()=>new Promise(resolve=>{finish=resolve;}),'USD',true);
  const manual=editor.host.children[1].children[2].children[1];
  const pending=manual.onclick();assert.throws(()=>editor.drafts.values(),/Wait for the shared HSN/);
  editor.drafts.reset();finish({ok:true,json:async()=>({shared_hsn_code:'85371090'})});await pending;
  assert.throws(()=>editor.drafts.values(),/Select at least one/);assert.equal(manual.disabled,false);
});
