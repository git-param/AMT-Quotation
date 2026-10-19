// ── Tiny canvas charts (no CDN needed) ───────────────────────────────────────
const FONT = '-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif';
const PALETTE = ['#2563EB', '#10B981', '#F59E0B', '#8B5CF6', '#F43F5E', '#06B6D4'];
let _lastStats = null;

// Sizes the canvas to its box and makes it sharp on high-DPI screens.
function prepCanvas(id) {
  const canvas = document.getElementById(id);
  if (!canvas) return null;
  const box = canvas.parentElement;
  const W = box.clientWidth, H = box.clientHeight;
  if (!W || !H) return null;                      // hidden tab → nothing to draw yet
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(W * dpr);
  canvas.height = Math.round(H * dpr);
  canvas.style.width = W + 'px';
  canvas.style.height = H + 'px';
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);
  return { ctx, W, H };
}

function emptyNote(ctx, W, H) {
  ctx.fillStyle = '#94A3B8';
  ctx.font = `500 13px ${FONT}`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText('No data yet', W / 2, H / 2);
}

function roundBar(ctx, x, y, w, h, r) {
  ctx.beginPath();
  if (ctx.roundRect) ctx.roundRect(x, y, w, Math.max(h, 0), r); else ctx.rect(x, y, w, Math.max(h, 0));
  ctx.fill();
}

function fitText(ctx, text, maxW) {
  if (ctx.measureText(text).width <= maxW) return text;
  while (text.length > 1 && ctx.measureText(text + '…').width > maxW) text = text.slice(0, -1);
  return text + '…';
}

function drawBarChart(canvasId, labels, values) {
  const c = prepCanvas(canvasId);
  if (!c) return;
  const { ctx, W, H } = c;
  if (!values.length || Math.max(...values) === 0) { emptyNote(ctx, W, H); return; }

  const pad = { top: 22, right: 8, bottom: 28, left: 36 };
  const cW = W - pad.left - pad.right, cH = H - pad.top - pad.bottom;
  const maxV = Math.max(4, Math.ceil(Math.max(...values) / 4) * 4);

  ctx.textBaseline = 'middle';
  for (let i = 0; i <= 4; i++) {
    const y = pad.top + cH - (i / 4) * cH;
    ctx.strokeStyle = '#EEF2F7'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(pad.left + cW, y); ctx.stroke();
    ctx.fillStyle = '#94A3B8'; ctx.font = `500 10px ${FONT}`; ctx.textAlign = 'right';
    ctx.fillText(Math.round((i / 4) * maxV), pad.left - 8, y);
  }

  const gap = cW / labels.length;
  const bW = Math.min(34, Math.max(6, gap * 0.58));
  const step = gap < 46 ? 2 : 1;                  // skip alternate labels on narrow screens
  const grad = ctx.createLinearGradient(0, pad.top, 0, pad.top + cH);
  grad.addColorStop(0, '#2563EB'); grad.addColorStop(1, '#93B4F8');

  values.forEach((v, i) => {
    const bH = (v / maxV) * cH;
    const x = pad.left + gap * i + (gap - bW) / 2;
    const y = pad.top + cH - bH;
    if (v > 0) {
      ctx.fillStyle = grad;
      roundBar(ctx, x, y, bW, bH, [5, 5, 0, 0]);
      ctx.fillStyle = '#334155'; ctx.font = `700 10px ${FONT}`; ctx.textAlign = 'center';
      ctx.fillText(v, x + bW / 2, y - 8);
    }
    if (i % step === 0) {
      ctx.fillStyle = '#64748B'; ctx.font = `500 10px ${FONT}`; ctx.textAlign = 'center';
      ctx.fillText(labels[i], x + bW / 2, pad.top + cH + 15);
    }
  });
}

function drawHBarChart(canvasId, labels, values) {
  const c = prepCanvas(canvasId);
  if (!c) return;
  const { ctx, W, H } = c;
  if (!labels.length) { emptyNote(ctx, W, H); return; }

  ctx.font = `500 12px ${FONT}`;
  const labelW = Math.min(110, Math.max(...labels.map(l => ctx.measureText(l).width)) + 4);
  const left = labelW + 12, right = 36;
  const cW = W - left - right;
  const maxV = Math.max(...values) || 1;
  const rowH = Math.min(34, (H - 8) / labels.length);

  labels.forEach((lbl, i) => {
    const mid = 4 + rowH * i + rowH / 2;
    const bH = Math.min(14, rowH * 0.5);
    const bW = Math.max(3, (values[i] / maxV) * cW);
    ctx.fillStyle = '#EEF2F7'; roundBar(ctx, left, mid - bH / 2, cW, bH, bH / 2);
    ctx.fillStyle = PALETTE[1]; roundBar(ctx, left, mid - bH / 2, bW, bH, bH / 2);
    ctx.textBaseline = 'middle';
    ctx.fillStyle = '#334155'; ctx.font = `500 12px ${FONT}`; ctx.textAlign = 'right';
    ctx.fillText(fitText(ctx, lbl, labelW), left - 10, mid);
    ctx.fillStyle = '#475569'; ctx.font = `700 11px ${FONT}`; ctx.textAlign = 'left';
    ctx.fillText(values[i], left + cW + 8, mid);
  });
}

function drawPieChart(canvasId, labels, values) {
  const c = prepCanvas(canvasId);
  if (!c) return;
  const { ctx, W, H } = c;
  const total = values.reduce((a, b) => a + b, 0);
  if (!total) { emptyNote(ctx, W, H); return; }

  const cx = W * 0.3, cy = H / 2, r = Math.min(W * 0.27, H / 2 - 12);
  let angle = -Math.PI / 2;
  values.forEach((v, i) => {
    const slice = (v / total) * 2 * Math.PI;
    ctx.fillStyle = PALETTE[i % PALETTE.length];
    ctx.beginPath(); ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, r, angle, angle + slice); ctx.closePath(); ctx.fill();
    angle += slice;
  });
  ctx.fillStyle = '#fff';                         // donut hole
  ctx.beginPath(); ctx.arc(cx, cy, r * 0.6, 0, 2 * Math.PI); ctx.fill();
  ctx.fillStyle = '#0F172A'; ctx.font = `800 20px ${FONT}`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillText(total, cx, cy - 5);
  ctx.fillStyle = '#94A3B8'; ctx.font = `500 11px ${FONT}`;
  ctx.fillText('copies', cx, cy + 12);

  const lx = W * 0.3 + r + 18, maxW = W - lx - 4;
  labels.forEach((lbl, i) => {
    const ly = Math.max(14, H / 2 - (labels.length * 24) / 2 + 12) + i * 24;
    ctx.fillStyle = PALETTE[i % PALETTE.length];
    roundBar(ctx, lx, ly - 5, 10, 10, 3);
    const pct = Math.round((values[i] / total) * 100);
    const short = lbl.replace(/EMAIL_LETTER_/i, 'EML ').replace('formal_', '').replace('wa_', 'WA ').toUpperCase();
    ctx.fillStyle = '#334155'; ctx.font = `500 11px ${FONT}`; ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
    ctx.fillText(fitText(ctx, `${short} (${pct}%)`, maxW - 16), lx + 16, ly);
  });
}

// ── Load stats ───────────────────────────────────────────────────────────────
async function loadStats() {
  try {
    const resp = await fetch('/api/manager/stats');
    if (!resp.ok) { showAccessError(resp.status); return; }
    _lastStats = await resp.json();
    renderStats(_lastStats);
    document.getElementById('lastUpdated').textContent = 'Updated ' + new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch (e) {
    console.error(e);
  }
}

function dayLabel(day) {
  if (!day) return '';
  const date = new Date(day + 'T00:00:00');
  return Number.isNaN(date.getTime()) ? day.slice(5) : date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
}

function renderStats(d) {
  // Cards
  document.getElementById('c-searches').textContent = d.today.searches;
  document.getElementById('c-skus').textContent     = d.today.skus_searched;
  document.getElementById('c-found').textContent    = d.today.found;
  document.getElementById('c-copies').textContent   = d.today.copies;

  // Charts
  drawCharts(d);

  // Recent searches
  const tR = document.getElementById('tblRecent');
  if (!d.recent.length) {
    tR.innerHTML = '<tr><td colspan="5" class="empty">No searches yet</td></tr>';
  } else {
    tR.innerHTML = d.recent.map(r => {
      const found = r.found_count || 0;
      const nf    = r.not_found || 0;
      const ts    = r.ts ? r.ts.slice(5, 16) : '';
      return `<tr>
        <td><strong>${esc(r.user_name || 'Unknown')}</strong></td>
        <td class="skus-cell" title="${esc(r.skus || '')}">${esc(r.skus || '—')}</td>
        <td><span class="badge badge-ok">${found}</span></td>
        <td>${nf > 0 ? `<span class="badge badge-err">${nf}</span>` : '<span class="badge-zero">0</span>'}</td>
        <td class="muted-sm">${esc(ts)}</td>
      </tr>`;
    }).join('');
  }

  // Top SKUs
  const tS = document.getElementById('tblTopSkus');
  if (!d.top_skus.length) {
    tS.innerHTML = '<tr><td colspan="2" class="empty">No data yet</td></tr>';
  } else {
    tS.innerHTML = d.top_skus.map(r => `
      <tr>
        <td><span class="sku-chip">${esc(r.sku)}</span></td>
        <td><span class="badge badge-ok">${r.count}</span></td>
      </tr>`).join('');
  }

  // User activity
  const tU = document.getElementById('tblUsers');
  if (!d.by_user.length) {
    tU.innerHTML = '<tr><td colspan="6" class="empty">No data yet</td></tr>';
  } else {
    tU.innerHTML = d.by_user.map(r => {
      const hit = r.skus > 0 ? Math.round(r.found / r.skus * 100) : 0;
      const badgeCls = hit >= 80 ? 'badge-ok' : hit >= 50 ? 'badge-warn' : 'badge-err';
      const last = r.last_seen ? r.last_seen.slice(0, 16) : '—';
      return `<tr>
        <td><strong>${esc(r.user_name || 'Unknown')}</strong></td>
        <td>${r.searches}</td>
        <td>${r.skus}</td>
        <td>${r.found}</td>
        <td><span class="badge ${badgeCls}">${hit}%</span></td>
        <td class="muted-sm">${esc(last)}</td>
      </tr>`;
    }).join('');
  }
}

function drawCharts(d) {
  requestAnimationFrame(() => {
    drawBarChart('chartDays', d.by_day.map(r => dayLabel(r.day)), d.by_day.map(r => r.skus || 0));
    drawHBarChart('chartUsers', d.by_user.slice(0, 8).map(r => r.user_name || 'Unknown'), d.by_user.slice(0, 8).map(r => r.skus || 0));
    drawPieChart('chartCopies', d.copy_types.map(r => r.copy_type || ''), d.copy_types.map(r => r.cnt || 0));
  });
}

function esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ── Tabs ─────────────────────────────────────────────────────────────────────
function showTab(name) {
  document.querySelectorAll('.tab').forEach(tab => {
    const on = tab.dataset.tab === name;
    tab.classList.toggle('is-active', on);
    tab.setAttribute('aria-selected', String(on));
  });
  document.getElementById('viewOverview').hidden = name !== 'overview';
  document.getElementById('viewUsers').hidden = name !== 'users';
  document.getElementById('dashboardTitle').textContent = name === 'users' ? 'Team & access' : 'Team activity at a glance';
  document.getElementById('dashboardSubtitle').textContent = name === 'users'
    ? 'Manage user accounts, departments, and access for your team.'
    : 'See how your team is using the quotation tool today.';
  document.getElementById('activityActions').hidden = name === 'users';
  if (name === 'overview' && _lastStats) drawCharts(_lastStats);   // canvases need a visible box
}
document.querySelectorAll('.tab').forEach(tab => tab.addEventListener('click', () => showTab(tab.dataset.tab)));

// ── Boot ─────────────────────────────────────────────────────────────────────
let _currentUserId = null;
function showAccessError(status) {
  document.getElementById('accessStatus').textContent = status === 401
    ? 'Session ended. Please sign in again.' : 'Access denied for your role.';
  document.getElementById('dashboardContent').hidden = true;
}
fetch('/api/me').then(async response => {
  if (!response.ok) { showAccessError(response.status); return; }
  const user = await response.json();
  document.getElementById('hdrUser').textContent = user.username;
  if (!user.permissions.includes('management.view')) { showAccessError(403); return; }
  document.getElementById('sourcesLink').style.display = user.permissions.includes('sources.manage') ? 'inline-flex' : 'none';
  document.getElementById('accessLink').style.display = user.permissions.includes('leads.share_manage') ? 'inline-flex' : 'none';
  _currentUserId = user.id;
  const manage = user.permissions.includes('users.manage');
  document.getElementById('dashboardContent').hidden = false;
  document.getElementById('tabs').hidden = !manage;        // tabs only make sense with 2+ views
  loadStats();
  if (manage) loadUsers();
  setInterval(loadStats, 60000);                           // auto-refresh every 60s
}).catch(() => { document.getElementById('accessStatus').textContent = 'Unable to load permissions. Reload to retry.'; });

let _resizeTimer;
window.addEventListener('resize', () => {
  clearTimeout(_resizeTimer);
  _resizeTimer = setTimeout(() => { if (_lastStats) drawCharts(_lastStats); }, 150);
});

// ── User management ───────────────────────────────────────────────────────────
let _users = [];
let _departments = [];
let _selectedUserId = null;
let _savingUser = false;
const userRoleLabels = {user: 'Sales Executive', manager: 'Admin', sales_executive: 'Sales Executive', sales_tl: 'Sales TL', admin: 'Admin'};

async function loadUsers() {
  const resp = await fetch('/api/manager/users').catch(() => null);
  if (!resp) { showMsg(document.getElementById('deleteMsg'), 'Unable to load users. Reload to retry.', false); return; }
  if (!resp.ok) { showAccessError(resp.status); return; }
  const data = await resp.json();
  _users = data.users || [];
  _departments = data.departments || [];
  const departmentInput = document.getElementById('newDepartment');
  const currentDepartment = departmentInput.value;
  fillDepartmentOptions(departmentInput, currentDepartment);
  const tbody = document.getElementById('usersList');
  tbody.replaceChildren();
  _users.forEach(user => {
    const row = document.createElement('tr');
    row.className = 'user-row';
    const name = document.createElement('td');
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'user-name-button';
    button.textContent = user.username;
    button.setAttribute('aria-label', `View details for ${user.username}`);
    button.setAttribute('aria-haspopup', 'dialog');
    name.append(button);
    const role = document.createElement('td');
    role.textContent = userRoleLabels[user.role] || user.role;
    const status = document.createElement('td');
    const badge = document.createElement('span');
    badge.className = `account-status ${user.is_active ? 'is-active' : 'is-inactive'}`;
    badge.textContent = user.is_active ? 'Active' : 'Inactive';
    status.append(badge);
    row.append(name, role, status);
    row.onclick = () => openUserDetails(user.id);
    tbody.append(row);
  });
  if (!_users.length) {
    const row = document.createElement('tr');
    const cell = document.createElement('td');
    cell.colSpan = 3; cell.className = 'empty'; cell.textContent = 'No users found.';
    row.append(cell); tbody.append(row);
  }
  document.getElementById('resetUserId').replaceChildren(..._users.map(u => new Option(u.username, u.id)));
}

function fillDepartmentOptions(select, selected = '') {
  select.replaceChildren(new Option(_departments.length ? 'Choose department' : 'Add departments in Configuration', ''),
    ..._departments.map(name => new Option(name, name)));
  select.value = _departments.find(name => name.toLowerCase() === String(selected || '').trim().toLowerCase()) || '';
}

function openUserDetails(id) {
  const user = _users.find(u => u.id === id);
  if (!user) return;
  _selectedUserId = id;
  document.getElementById('userDetailsTitle').textContent = user.username;
  document.getElementById('userDetailsMsg').className = 'msg';
  document.getElementById('editUserForm').hidden = true;
  document.getElementById('userDetailsActions').hidden = false;
  const toggleStatus = document.getElementById('toggleUserStatus');
  toggleStatus.textContent = user.is_active ? 'Deactivate user' : 'Activate user';
  toggleStatus.className = `btn-sm ${user.is_active ? 'btn-del' : 'btn-activate'}`;
  toggleStatus.disabled = user.id === _currentUserId;
  const details = document.getElementById('userDetails');
  details.hidden = false;
  details.replaceChildren();
  const supervisor = _users.find(u => u.id === user.supervisor_user_id);
  const date = new Date((user.created_at || '').replace(' ', 'T'));
  const values = [
    ['User ID', user.id], ['Name / username', user.username],
    ['Department', user.department || 'Not assigned'],
    ['Role', userRoleLabels[user.role] || user.role],
    ['Supervisor', supervisor ? supervisor.username : user.supervisor_user_id ? 'Unavailable supervisor' : 'Unassigned'],
    ['Created', Number.isNaN(date.getTime()) ? 'Not recorded' : date.toLocaleString('en-GB')],
    ['Status', user.is_active ? 'Active' : 'Inactive'],
    ['Phone number', user.phone_number ? `${user.phone_country_code || ''} ${user.phone_number}`.trim() : 'Not provided'],
  ];
  values.forEach(([label, value]) => {
    const dt = document.createElement('dt'); dt.textContent = label;
    const dd = document.createElement('dd'); dd.textContent = value;
    details.append(dt, dd);
  });
  const dialog = document.getElementById('userDetailsDialog');
  if (!dialog.open) dialog.showModal();
}

function editSelectedUser() {
  const user = _users.find(u => u.id === _selectedUserId);
  if (!user) return;
  document.getElementById('editUsername').value = user.username;
  fillDepartmentOptions(document.getElementById('editDepartment'), user.department);
  document.getElementById('editPhoneCountryCode').value = user.phone_country_code || '';
  document.getElementById('editPhoneNumber').value = user.phone_number || '';
  const roles = document.getElementById('editRole');
  const choices = {sales_executive: 'Sales Executive', sales_tl: 'Sales TL', admin: 'Admin'};
  if (!Object.hasOwn(choices, user.role)) choices[user.role] = userRoleLabels[user.role] || user.role;
  roles.replaceChildren(...Object.entries(choices).map(([code, label]) => new Option(label, code)));
  roles.value = user.role;
  roles.disabled = user.id === _currentUserId;
  const status = document.getElementById('editStatus');
  status.value = String(user.is_active);
  status.disabled = user.id === _currentUserId;
  const supervisor = document.getElementById('editSupervisor');
  supervisor.replaceChildren(new Option('Unassigned', ''), ..._users
    .filter(u => u.id !== user.id && u.role === 'sales_tl' && u.is_active)
    .map(u => new Option(u.username, u.id)));
  if (user.supervisor_user_id && ![...supervisor.options].some(o => Number(o.value) === user.supervisor_user_id)) {
    supervisor.add(new Option('Unavailable supervisor', user.supervisor_user_id));
  }
  supervisor.value = user.supervisor_user_id ? String(user.supervisor_user_id) : '';
  updateEditSupervisor();
  document.getElementById('userDetails').hidden = true;
  document.getElementById('userDetailsActions').hidden = true;
  document.getElementById('editUserForm').hidden = false;
  document.getElementById('editUsername').focus();
}

function updateEditSupervisor() {
  const disabled = document.getElementById('editStatus').value !== '1' ||
    !['user', 'sales_executive'].includes(document.getElementById('editRole').value);
  const supervisor = document.getElementById('editSupervisor');
  supervisor.disabled = disabled;
  if (disabled) supervisor.value = '';
}

document.getElementById('editRole').onchange = updateEditSupervisor;
document.getElementById('editStatus').onchange = updateEditSupervisor;
document.getElementById('editUserButton').onclick = editSelectedUser;
document.getElementById('toggleUserStatus').onclick = async () => {
  const user = _users.find(u => u.id === _selectedUserId);
  if (!user || _savingUser || user.id === _currentUserId) return;
  const button = document.getElementById('toggleUserStatus');
  const msg = document.getElementById('userDetailsMsg');
  const active = user.is_active ? 0 : 1;
  _savingUser = true;
  button.disabled = true;
  document.getElementById('editUserButton').disabled = true;
  try {
    const response = await fetch(`/api/manager/users/${user.id}/${active ? 'activate' : 'deactivate'}`, {method: 'POST'});
    if ([401, 403].includes(response.status)) {
      document.getElementById('userDetailsDialog').close(); showAccessError(response.status); return;
    }
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Unable to change account status');
    user.is_active = active;
    openUserDetails(user.id);
    showMsg(msg, active ? 'User activated.' : 'User deactivated.', true);
    try { await loadUsers(); } catch (_) { showMsg(msg, 'Status saved. Reload to refresh the list.', true); }
  } catch (error) { showMsg(msg, error.message || 'Unable to change account status', false); }
  finally {
    _savingUser = false;
    button.disabled = user.id === _currentUserId;
    document.getElementById('editUserButton').disabled = false;
  }
};
document.getElementById('cancelUserEdit').onclick = () => { if (!_savingUser) openUserDetails(_selectedUserId); };
document.getElementById('closeUserDetails').onclick = () => { if (!_savingUser) document.getElementById('userDetailsDialog').close(); };
document.getElementById('userDetailsDialog').addEventListener('cancel', event => { if (_savingUser) event.preventDefault(); });
function userPhoneFields(prefix) {
  let code = document.getElementById(`${prefix}PhoneCountryCode`).value.trim();
  let number = document.getElementById(`${prefix}PhoneNumber`).value.trim();
  if (!code && !number) return {phone_country_code: '', phone_number: ''};
  if (!/^\+?[1-9][0-9]{0,2}$/.test(code)) throw new Error('Enter a country code such as +91 or +1');
  if (number.length > 40 || !/^[0-9 ()-]+$/.test(number)) throw new Error('Enter a valid phone number');
  code = '+' + code.replace(/^\+/, '');
  number = number.replace(/[^0-9]/g, '');
  const length = code.length - 1 + number.length;
  if (number.length < 4 || length < 7 || length > 15) throw new Error('Enter a phone number with 7 to 15 digits including the country code');
  return {phone_country_code: code, phone_number: number};
}
document.getElementById('editUserForm').onsubmit = async event => {
  event.preventDefault();
  if (_savingUser) return;
  const id = _selectedUserId;
  const msg = document.getElementById('userDetailsMsg');
  const body = {
    username: document.getElementById('editUsername').value.trim(),
    department: document.getElementById('editDepartment').value.trim(),
    role: document.getElementById('editRole').value,
    is_active: Number(document.getElementById('editStatus').value),
    supervisor_user_id: document.getElementById('editSupervisor').value ? Number(document.getElementById('editSupervisor').value) : null,
  };
  if (!body.username || !body.department) { showMsg(msg, 'Name and department are required', false); return; }
  try { Object.assign(body, userPhoneFields('edit')); }
  catch (error) { showMsg(msg, error.message, false); return; }
  _savingUser = true;
  document.getElementById('saveUserEdit').disabled = true;
  try {
    const response = await fetch(`/api/manager/users/${id}/edit`, {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
    });
    if ([401, 403].includes(response.status)) {
      document.getElementById('userDetailsDialog').close(); showAccessError(response.status); return;
    }
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Unable to save user');
    // Keep the open details accurate even if refreshing the list fails.
    Object.assign(_users.find(u => u.id === id), body);
    if (id === _currentUserId) document.getElementById('hdrUser').textContent = body.username;
    openUserDetails(id);
    showMsg(msg, 'User updated successfully', true);
    try { await loadUsers(); } catch (_) { showMsg(msg, 'User saved. Reload to refresh the list.', true); }
  } catch (error) { showMsg(msg, error.message || 'Unable to save user', false); }
  finally { _savingUser = false; document.getElementById('saveUserEdit').disabled = false; }
};

async function addUser() {
  const username = document.getElementById('newUsername').value.trim();
  const password = document.getElementById('newPassword').value.trim();
  const role     = document.getElementById('newRole').value;
  const department = document.getElementById('newDepartment').value.trim();
  const msg      = document.getElementById('addMsg');
  msg.className  = 'msg';

  if (!username || !password) { showMsg(msg, 'Username and password are required', false); return; }
  if (password.length < 12) { showMsg(msg, 'Password must be at least 12 characters', false); return; }
  if (!department) { showMsg(msg, 'Department is required', false); document.getElementById('newDepartment').focus(); return; }
  if (department.length > 100) { showMsg(msg, 'Department must be 100 characters or fewer', false); return; }
  let phone;
  try { phone = userPhoneFields('new'); }
  catch (error) { showMsg(msg, error.message, false); return; }

  const resp = await fetch('/api/manager/users/add', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ username, password, role, department, ...phone })
  });
  if ([401, 403].includes(resp.status)) { showAccessError(resp.status); return; }
  const data = await resp.json();
  if (resp.ok) {
    showMsg(msg, `User "${username}" added successfully`, true);
    document.getElementById('newUsername').value = '';
    document.getElementById('newPassword').value = '';
    document.getElementById('newDepartment').value = '';
    document.getElementById('newPhoneCountryCode').value = '';
    document.getElementById('newPhoneNumber').value = '';
    loadUsers();
  } else {
    showMsg(msg, data.error || 'Failed to add user', false);
  }
}

async function updateUser(uid, action, body = {}) {
  const msg = document.getElementById('deleteMsg');
  try {
    const response = await fetch(`/api/manager/users/${uid}/${action}`, {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
    });
    if ([401, 403].includes(response.status)) { showAccessError(response.status); return; }
    const data = await response.json();
    showMsg(msg, response.ok ? 'Account updated.' : data.error, response.ok);
    loadUsers();
  } catch (error) { showMsg(msg, 'Unable to update account.', false); }
}

async function resetPassword() {
  const uid      = document.getElementById('resetUserId').value;
  const password = document.getElementById('resetPassword').value.trim();
  const msg      = document.getElementById('resetMsg');
  msg.className  = 'msg';

  if (!password || password.length < 12) { showMsg(msg, 'Password must be at least 12 characters', false); return; }

  const resp = await fetch(`/api/manager/users/${uid}/reset-password`, {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ password })
  });
  if ([401, 403].includes(resp.status)) { showAccessError(resp.status); return; }
  const data = await resp.json();
  if (resp.ok) {
    showMsg(msg, 'Password reset successfully', true);
    document.getElementById('resetPassword').value = '';
  } else {
    showMsg(msg, data.error || 'Failed to reset password', false);
  }
}

function showMsg(el, text, ok) {
  el.textContent = text;
  el.className   = 'msg ' + (ok ? 'ok' : 'err');
  setTimeout(() => { el.className = 'msg'; }, 4000);
}
