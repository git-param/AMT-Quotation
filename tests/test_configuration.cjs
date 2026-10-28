const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

async function setup(admin) {
  const nodes = new Map();
  const get = id => {
    if (!nodes.has(id)) nodes.set(id, {value: '', hidden: true, children: [], append(child) {this.children.push(child);}, replaceChildren() {this.children = [];}});
    return nodes.get(id);
  };
  let names = ['Sales'];
  const prefixes = {};
  let rates = {};
  let lookupLimit = 50;
  let discountLimit = "0";
  const context = {
    document: {getElementById: get, createElement: () => ({})},
    setInterval: () => 0,
    fetch: async (url, options) => {
      if (url === '/api/me') return {ok: true, json: async () => ({role:admin?'admin':'sales_tl',permissions: admin ? ['settings.manage', 'users.manage'] : ['settings.manage']})};
      if (url === '/api/pi-discount-limit') {
        if(options)discountLimit=JSON.parse(options.body).maximum_percent;
        return {ok:true,json:async()=>({maximum_percent:discountLimit})};
      }
      if (url === '/api/settings') return {ok: true, json: async () => ({hsn_code: '85371090'})};
      if (url === '/api/sku-lookup-limit') {
        if (options) lookupLimit = JSON.parse(options.body).max_sku_lookup;
        return {ok:true,json:async()=>({max_sku_lookup:lookupLimit})};
      }
      if (url === '/api/currency-rates') {
        if (options) rates = JSON.parse(options.body).rates;
        return {ok:true,json:async()=>({rates})};
      }
      if (url === '/api/currency-rates/schedule') {
        return {ok:true,json:async()=>({rates,refresh_hours:JSON.parse(options.body).refresh_hours})};
      }
      if (url.endsWith('/pi-prefix')) {
        prefixes[names[Number(url.split('/')[3]) - 1]] = JSON.parse(options.body).pi_prefix;
      } else if (options) {
        assert.equal(url, '/api/departments');
        const name = JSON.parse(options.body).name;
        if (names.includes(name)) return {ok: false, json: async () => ({error: 'This department already exists.'})};
        names.push(name);
        prefixes[name] = JSON.parse(options.body).pi_prefix || '';
      }
      return {ok: true, json: async () => ({departments: [...names], department_settings: names.map((name,i)=>({id:i+1,name,pi_prefix:prefixes[name]||''}))})};
    },
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync('frontend/configuration/configuration.js', 'utf8'), context);
  await new Promise(resolve => setImmediate(resolve));
  return {get};
}

test('admin adds departments in Configuration and duplicate errors preserve input', async () => {
  const {get} = await setup(true);
  assert.equal(get('departmentForm').hidden, false);
  assert.equal(get('departmentsList').children[0].textContent, 'Sales');
  get('departmentName').value = '  Operations  ';
  await get('departmentForm').onsubmit({preventDefault() {}});
  assert.deepEqual(get('departmentsList').children.map(n => n.textContent), ['Sales', 'Operations']);
  assert.equal(get('departmentName').value, '');
  get('departmentName').value = 'Sales';
  await get('departmentForm').onsubmit({preventDefault() {}});
  assert.equal(get('departmentMessage').textContent, 'This department already exists.');
  assert.equal(get('departmentName').value, 'Sales');
  assert.equal(get('addDepartment').disabled, false);
});

test('team leads can view departments while the admin form stays hidden', async () => {
  const {get} = await setup(false);
  assert.equal(get('departmentForm').hidden, true);
  assert.equal(get('departmentPrefixForm').hidden, true);
  assert.equal(get('departmentsList').children[0].textContent, 'Sales');
});

test('admins can configure and reload a department PI prefix', async () => {
  const {get} = await setup(true);
  assert.equal(get('departmentPrefixForm').hidden, false);
  assert.equal(get('prefixDepartment').value, '1');
  get('piPrefix').value = 'AMT';
  await get('departmentPrefixForm').onsubmit({preventDefault() {}});
  assert.equal(get('departmentsList').children[0].textContent, 'Sales · AMT/');
  assert.equal(get('piPrefix').value, 'AMT');
  assert.equal(get('prefixMessage').textContent, 'PI prefix saved.');
});

test('admin can configure the shared SKU lookup limit', async () => {
  const {get} = await setup(true);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(get('skuLookupLimitSection').hidden, false);
  assert.equal(get('skuLookupLimit').value, 50);
  get('skuLookupLimit').value = '25';
  await get('skuLookupLimitForm').onsubmit({preventDefault() {}});
  assert.equal(get('skuLookupLimitMessage').textContent, 'SKU lookup limit saved.');
  const viewer = await setup(false);
  assert.equal(viewer.get('skuLookupLimitSection').hidden, true);
});

test('admin can save the currency rate refresh interval', async () => {
  const {get} = await setup(true);
  assert.equal(get('currencyRatesSection').hidden,false);
  get('rateRefreshHours').value='12';
  await get('currencyRatesForm').onsubmit({preventDefault(){}});
  assert.equal(get('currencyRatesMessage').textContent,'Refresh interval saved.');
  assert.equal(get('rateRefreshHours').value,12);
});


test('only admins see and save the maximum PI discount', async () => {
  const {get}=await setup(true);
  assert.equal(get('discountLimitSection').hidden,false);
  assert.equal(get('discountLimit').value,'0');
  get('discountLimit').value='12.50';
  await get('discountLimitForm').onsubmit({preventDefault(){}});
  assert.equal(get('discountLimitMessage').textContent,'Maximum discount saved.');
  const viewer=await setup(false);
  assert.equal(viewer.get('discountLimitSection').hidden,true);
});
