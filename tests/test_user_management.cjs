const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

class Element {
  constructor(tag = 'div') { this.tag = tag; this.children = []; this.attributes = {}; this.value = ''; this.hidden = false; this.disabled = false; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; }
  setAttribute(name, value) { this.attributes[name] = value; }
  add(node) { this.children.push(node); }
  get options() { return this.children; }
  addEventListener(name, handler) { this[name] = handler; }
  focus() { this.focused = true; }
  showModal() { this.open = true; }
  close() { this.open = false; }
}
function setup() {
  const fields = new Map();
  const get = id => { if (!fields.has(id)) fields.set(id, new Element()); return fields.get(id); };
  let users = [
    {id: 1, username: 'Admin', department: 'Management', role: 'manager', is_active: 1, created_at: '2026-10-17 12:00:00', supervisor_user_id: null},
    {id: 2, username: '<Sales Person>', department: 'Sales', role: 'sales_executive', is_active: 1, created_at: '2026-10-17 12:00:00', supervisor_user_id: 3},
    {id: 3, username: 'Team Lead', department: 'Sales', role: 'sales_tl', is_active: 1, created_at: '2026-10-17 12:00:00', supervisor_user_id: null},
  ];
  const calls = [];
  let failure = false;
  const context = {
    document: {getElementById: get, createElement: tag => new Element(tag)},
    Option: function(text, value) { return {textContent: text, value: String(value)}; },
    _currentUserId: 1,
    showMsg(el, text, ok) { el.textContent = text; el.className = ok ? 'msg ok' : 'msg err'; },
    showAccessError() {},
    fetch: async (url, options) => {
      if (!options) return {ok: true, json: async () => ({users: structuredClone(users), departments: ['Management', 'Operations', 'Sales']})};
      const body = options.body ? JSON.parse(options.body) : undefined; calls.push({url, body});
      if (failure) return {ok: false, status: 409, json: async () => ({error: 'Username already exists'})};
      const target = users.find(u => u.id === Number(url.split('/')[4]));
      if (url.endsWith('/add')) users.push({id: 4, ...body});
      else if (url.endsWith('/deactivate')) target.is_active = 0;
      else if (url.endsWith('/activate')) target.is_active = 1;
      else Object.assign(target, body);
      return {ok: true, status: 200, json: async () => ({ok: true})};
    },
  };
  vm.createContext(context);
  const source = fs.readFileSync('frontend/manager_dashboard/manager.js', 'utf8');
  vm.runInContext(source.slice(source.indexOf('let _users ='), source.indexOf('async function updateUser(')), context);
  return {get, context, calls, fail: () => {failure = true;}};
}

test('compact rows open full details with safe text and an explicit edit mode', async () => {
  const {get, context} = setup(); await context.loadUsers();
  const row = get('usersList').children[1];
  assert.equal(row.children.length, 3);
  assert.equal(row.children[0].children[0].textContent, '<Sales Person>');
  assert.equal(row.children[0].children[0].attributes['aria-haspopup'], 'dialog');
  row.onclick();
  assert.equal(get('userDetailsDialog').open, true);
  assert.equal(get('editUserForm').hidden, true);
  assert.equal(get('userDetails').children.length, 16);
  assert.equal(get('userDetails').children[9].textContent, 'Team Lead');
  context.editSelectedUser();
  assert.equal(get('editUserForm').hidden, false);
  assert.equal(get('editDepartment').value, 'Sales');
  assert.deepEqual(get('editDepartment').options.map(o => o.value), ['', 'Management', 'Operations', 'Sales']);
  assert.deepEqual(get('newDepartment').options.map(o => o.value), ['', 'Management', 'Operations', 'Sales']);
  context.fillDepartmentOptions(get('editDepartment'), 'sales');
  assert.equal(get('editDepartment').value, 'Sales');
  get('editDepartment').value = 'Cancelled';
  get('cancelUserEdit').onclick();
  assert.equal(get('editUserForm').hidden, true);
  assert.equal(get('userDetails').children[5].textContent, 'Sales');
});

test('edit saves all settings together and refreshes details and compact list', async () => {
  const {get, context, calls} = setup(); await context.loadUsers(); context.openUserDetails(2); context.editSelectedUser();
  get('editUsername').value = ' Updated ';
  get('editDepartment').value = ' Operations ';
  get('editStatus').value = '0'; context.updateEditSupervisor();
  assert.equal(get('editSupervisor').disabled, true);
  assert.equal(get('editSupervisor').value, '');
  await get('editUserForm').onsubmit({preventDefault() {}});
  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0].body, {username: 'Updated', department: 'Operations', role: 'sales_executive', is_active: 0, supervisor_user_id: null, phone_country_code: '', phone_number: ''});
  assert.equal(get('editUserForm').hidden, true);
  assert.equal(get('userDetails').children[5].textContent, 'Operations');
  assert.equal(get('usersList').children[1].children[0].children[0].textContent, 'Updated');
  assert.equal(get('usersList').children[1].children[2].children[0].textContent, 'Inactive');
});

test('self controls stay disabled and rejected edits preserve inputs for correction', async () => {
  const {get, context, fail} = setup(); await context.loadUsers(); context.openUserDetails(1); context.editSelectedUser();
  assert.equal(get('editRole').value, 'manager');
  assert.equal(get('editRole').disabled, true);
  assert.equal(get('editStatus').disabled, true);
  assert.equal(get('toggleUserStatus').disabled, true);
  get('editUsername').value = 'Duplicate'; fail();
  await get('editUserForm').onsubmit({preventDefault() {}});
  assert.equal(get('editUserForm').hidden, false);
  assert.equal(get('editUsername').value, 'Duplicate');
  assert.equal(get('userDetailsMsg').textContent, 'Username already exists');
  assert.equal(get('saveUserEdit').disabled, false);
});

test('details provide deactivate and reactivate without requiring a department edit', async () => {
  const {get, context, calls} = setup();
  await context.loadUsers(); context.openUserDetails(2);
  assert.equal(get('toggleUserStatus').textContent, 'Deactivate user');
  await get('toggleUserStatus').onclick();
  assert.equal(calls[0].url, '/api/manager/users/2/deactivate');
  assert.equal(get('toggleUserStatus').textContent, 'Activate user');
  assert.equal(get('usersList').children[1].children[2].children[0].textContent, 'Inactive');
  await get('toggleUserStatus').onclick();
  assert.equal(calls[1].url, '/api/manager/users/2/activate');
  assert.equal(get('toggleUserStatus').textContent, 'Deactivate user');
  assert.equal(get('usersList').children[1].children[2].children[0].textContent, 'Active');
});

test('phone fields validate pairs, save international numbers, populate edits and display details', async () => {
  const {get, context, calls} = setup();
  await context.loadUsers(); context.openUserDetails(2); context.editSelectedUser();
  get('editPhoneCountryCode').value = '+91';
  get('editPhoneNumber').value = '';
  await get('editUserForm').onsubmit({preventDefault() {}});
  assert.equal(calls.length, 0);
  get('editPhoneNumber').value = '(98765) 43210';
  await get('editUserForm').onsubmit({preventDefault() {}});
  assert.equal(calls[0].body.phone_country_code, '+91');
  assert.equal(calls[0].body.phone_number, '9876543210');
  assert.equal(get('userDetails').children[15].textContent, '+91 9876543210');
  context.editSelectedUser();
  assert.equal(get('editPhoneCountryCode').value, '+91');
  assert.equal(get('editPhoneNumber').value, '9876543210');
  get('newUsername').value = 'New phone user'; get('newPassword').value = 'fixture-pass';
  get('newRole').value = 'sales_executive'; get('newDepartment').value = 'Sales';
  get('newPhoneCountryCode').value = '1'; get('newPhoneNumber').value = '202-555-0123';
  await context.addUser();
  assert.equal(calls[1].body.phone_country_code, '+1');
  assert.equal(calls[1].body.phone_number, '2025550123');
  assert.equal(get('newPhoneCountryCode').value, '');
  assert.equal(get('newPhoneNumber').value, '');
});
