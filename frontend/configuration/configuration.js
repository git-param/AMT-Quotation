(() => {
  const form = document.getElementById('settingsForm');
  const input = document.getElementById('hsnCode');
  const save = document.getElementById('save');
  const message = document.getElementById('message');
  async function request(options) {
    const response = await fetch('/api/settings', options);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Unable to load configuration.');
    return data;
  }
  form.onsubmit = async event => {
    event.preventDefault(); save.disabled = true;
    try {
      const data = await request({method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({hsn_code: input.value.trim()})});
      input.value = data.hsn_code; message.className = ''; message.textContent = 'Shared HSN code saved for all SKUs.';
    } catch (error) { message.className = 'error'; message.textContent = error.message; }
    finally { save.disabled = false; }
  };
  request().then(data => { input.value = data.hsn_code; save.disabled = false; })
    .catch(error => { message.className = 'error'; message.textContent = error.message; input.disabled = true; });

  const departmentForm = document.getElementById('departmentForm');
  const departmentName = document.getElementById('departmentName');
  const addDepartment = document.getElementById('addDepartment');
  const departmentMessage = document.getElementById('departmentMessage');
  function renderDepartments(names) {
    const list = document.getElementById('departmentsList');
    list.replaceChildren();
    names.forEach(name => {
      const item = document.createElement('li'); item.textContent = name; list.append(item);
    });
    if (!names.length) departmentMessage.textContent = 'No departments configured yet.';
  }
  async function departments(options) {
    const response = await fetch('/api/departments', options);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Unable to load departments.');
    return data;
  }
  departmentForm.onsubmit = async event => {
    event.preventDefault(); addDepartment.disabled = true;
    try {
      const data = await departments({method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name: departmentName.value.trim()})});
      renderDepartments(data.departments);
      departmentName.value = ''; departmentMessage.className = ''; departmentMessage.textContent = 'Department added.';
    } catch (error) { departmentMessage.className = 'error'; departmentMessage.textContent = error.message; }
    finally { addDepartment.disabled = false; }
  };
  Promise.all([
    fetch('/api/me').then(async response => { if (!response.ok) throw new Error('Unable to load permissions.'); return response.json(); }),
    departments(),
  ]).then(([user, data]) => {
    departmentForm.hidden = !user.permissions.includes('users.manage');
    renderDepartments(data.departments);
  }).catch(error => { departmentMessage.className = 'error'; departmentMessage.textContent = error.message; });
})();
