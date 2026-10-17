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
  const context = {
    document: {getElementById: get, createElement: () => ({})},
    fetch: async (url, options) => {
      if (url === '/api/me') return {ok: true, json: async () => ({permissions: admin ? ['settings.manage', 'users.manage'] : ['settings.manage']})};
      if (url === '/api/settings') return {ok: true, json: async () => ({hsn_code: '85371090'})};
      assert.equal(url, '/api/departments');
      if (options) {
        const name = JSON.parse(options.body).name;
        if (names.includes(name)) return {ok: false, json: async () => ({error: 'This department already exists.'})};
        names.push(name);
      }
      return {ok: true, json: async () => ({departments: [...names]})};
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
  assert.equal(get('departmentsList').children[0].textContent, 'Sales');
});
