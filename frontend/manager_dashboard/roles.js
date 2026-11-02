(() => {
  const $ = id => document.getElementById(id);
  let roles = [];
  let permissions = [];
  let editing = null;

  const setStatus = (message, kind = '') => {
    const status = $('status');
    status.textContent = message;
    status.className = `role-status${kind ? ` is-${kind}` : ''}`;
  };

  const call = async (url, options = {}) => {
    const method = String(options.method || 'GET').toUpperCase();
    const headers = new Headers(options.headers || {});
    headers.set('Content-Type', 'application/json');
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
      const match = document.cookie.match(/(?:^|; )amt_csrf_v2=([^;]*)/);
      if (match) headers.set('X-CSRF-Token', decodeURIComponent(match[1]));
    }
    const response = await fetch(url, {...options, headers});
    const body = await response.text();
    let data;
    try {
      data = JSON.parse(body);
    } catch (_) {
      const contentType = response.headers.get('content-type') || 'unknown content type';
      throw Error(`Roles API returned HTTP ${response.status} (${contentType}). Reload the page or contact an administrator.`);
    }
    if (!response.ok) throw Error(data.error || `Request failed (HTTP ${response.status})`);
    return data;
  };

  function renderRoles() {
    $('rolesCount').textContent = `${roles.length} ${roles.length === 1 ? 'role' : 'roles'}`;
    if (!roles.length) {
      const empty = document.createElement('div');
      empty.className = 'roles-loading';
      empty.textContent = 'No roles are configured yet.';
      $('roleList').replaceChildren(empty);
      return;
    }

    $('roleList').replaceChildren(...roles.map(role => {
      const card = document.createElement('article');
      card.className = 'role-card';
      const top = document.createElement('div');
      top.className = 'role-card-top';
      const identity = document.createElement('div');
      identity.className = 'role-card-name';
      const title = document.createElement('h3');
      title.textContent = role.description;
      const code = document.createElement('code');
      code.className = 'role-code';
      code.textContent = role.code;
      identity.append(title, code);

      const actions = document.createElement('div');
      actions.className = 'role-card-actions';
      const edit = document.createElement('button');
      edit.type = 'button';
      edit.className = 'role-action';
      edit.textContent = 'Edit access';
      edit.onclick = () => beginEdit(role);
      actions.append(edit);
      if (role.code !== 'admin') {
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'role-action role-action-danger';
        remove.textContent = 'Delete';
        remove.onclick = () => deleteRole(role);
        actions.append(remove);
      }
      top.append(identity, actions);

      const meta = document.createElement('div');
      meta.className = 'role-card-meta';
      const permissionsChip = document.createElement('span');
      permissionsChip.className = 'role-meta-chip';
      permissionsChip.textContent = `${role.permissions.length} ${role.permissions.length === 1 ? 'permission' : 'permissions'}`;
      const membersChip = document.createElement('span');
      membersChip.className = 'role-meta-chip members';
      membersChip.textContent = `${role.user_count || 0} ${role.user_count === 1 ? 'account' : 'accounts'}`;
      meta.append(permissionsChip, membersChip);

      const preview = document.createElement('div');
      preview.className = 'role-permission-preview';
      const visible = role.permissions.slice(0, 4);
      for (const permissionCode of visible) {
        const permission = permissions.find(item => item.code === permissionCode);
        const tag = document.createElement('span');
        tag.className = 'role-permission-tag';
        tag.textContent = permission ? permission.description : permissionCode;
        preview.append(tag);
      }
      if (role.permissions.length > visible.length) {
        const more = document.createElement('span');
        more.className = 'role-permission-tag more';
        more.textContent = `+${role.permissions.length - visible.length} more`;
        preview.append(more);
      }
      card.append(top, meta, preview);
      return card;
    }));
  }

  function renderPermissions(selected = []) {
    const groups = new Map();
    for (const permission of permissions) {
      const section = permission.code.includes('.')
        ? permission.code.split('.')[0]
        : 'other';
      if (!groups.has(section)) groups.set(section, []);
      groups.get(section).push(permission);
    }

    const containers = [];
    for (const [name, items] of groups) {
      const group = document.createElement('section');
      group.className = 'permission-group';
      const heading = document.createElement('h3');
      heading.textContent = name.replaceAll('_', ' ');
      group.append(heading);
      for (const permission of items) {
        const label = document.createElement('label');
        label.className = 'permission-option';
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.value = permission.code;
        checkbox.checked = selected.includes(permission.code);
        checkbox.addEventListener('change', updatePermissionCount);
        const text = document.createElement('span');
        const description = document.createElement('strong');
        description.textContent = permission.description;
        const code = document.createElement('code');
        code.textContent = permission.code;
        text.append(description, code);
        label.append(checkbox, text);
        group.append(label);
      }
      containers.push(group);
    }
    $('permissionList').replaceChildren(...containers);
    updatePermissionCount();
  }

  function updatePermissionCount() {
    const count = $('permissionList').querySelectorAll('input:checked').length;
    $('permissionCount').textContent = `${count} selected`;
  }

  function beginEdit(role) {
    editing = role;
    $('code').value = role.code;
    $('code').disabled = true;
    $('description').value = role.description;
    $('formTitle').textContent = `Edit ${role.description}`;
    $('formDescription').textContent = 'Changes apply immediately to every account assigned to this role.';
    $('saveRole').textContent = 'Save changes';
    $('cancel').hidden = false;
    renderPermissions(role.permissions);
    $('roleForm').scrollIntoView({behavior: 'smooth', block: 'start'});
    $('description').focus({preventScroll: true});
  }

  function resetForm() {
    editing = null;
    $('roleForm').reset();
    $('code').disabled = false;
    $('formTitle').textContent = 'Create a role';
    $('formDescription').textContent = 'Give the role a clear name, then select the modules it can use.';
    $('saveRole').textContent = 'Create role';
    $('cancel').hidden = true;
    renderPermissions([]);
    setStatus('');
  }

  async function load() {
    const data = await call('/api/admin/roles');
    roles = data.roles || [];
    permissions = data.permissions || [];
    renderRoles();
    renderPermissions(editing ? editing.permissions : []);
  }

  async function deleteRole(role) {
    if (!confirm(`Delete the “${role.description}” role? Roles with assigned accounts cannot be deleted.`)) return;
    try {
      await call(`/api/admin/roles/${encodeURIComponent(role.code)}`, {method: 'DELETE'});
      setStatus('Role deleted.', 'success');
      await load();
    } catch (error) {
      setStatus(error.message, 'error');
    }
  }

  $('cancel').addEventListener('click', resetForm);
  $('roleForm').addEventListener('submit', async event => {
    event.preventDefault();
    const body = {
      code: $('code').value.trim(),
      description: $('description').value.trim(),
      permissions: [...$('permissionList').querySelectorAll('input:checked')].map(input => input.value),
    };
    const button = $('saveRole');
    button.disabled = true;
    setStatus('Saving role…');
    try {
      await call(editing ? `/api/admin/roles/${encodeURIComponent(editing.code)}` : '/api/admin/roles', {
        method: editing ? 'PUT' : 'POST',
        body: JSON.stringify(body),
      });
      resetForm();
      setStatus('Role saved successfully.', 'success');
      await load();
    } catch (error) {
      setStatus(error.message, 'error');
    } finally {
      button.disabled = false;
    }
  });

  load().catch(error => {
    $('rolesCount').textContent = 'Unavailable';
    const message = document.createElement('div');
    message.className = 'roles-loading';
    message.textContent = error.message;
    $('roleList').replaceChildren(message);
    renderPermissions([]);
    setStatus(error.message, 'error');
  });
})();
