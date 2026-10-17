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
async function loadUsers() {
  const resp = await fetch('/api/manager/users').catch(() => null);
  if (!resp) return;
  if (!resp.ok) { showAccessError(resp.status); return; }
  const data = await resp.json();
  const users = data.users || [];

  // Populate users table
  const tbody = document.getElementById('usersList');
  tbody.replaceChildren();
  users.forEach(user => {
    const row = document.createElement('tr');
    const name = document.createElement('td');
    name.textContent = user.username;
    name.className = 'account-name';
    const role = document.createElement('td');
    const select = document.createElement('select');
    select.className = 'role-select';
    select.setAttribute('aria-label', `Role for ${user.username}`);
    const roles = {sales_executive: 'Sales Executive', sales_tl: 'Sales TL', admin: 'Admin'};
    const currentRole = {user: 'sales_executive', manager: 'admin'}[user.role] || user.role;
    Object.entries(roles).forEach(([code, label]) => select.add(new Option(label, code, false, code === currentRole)));
    select.disabled = user.id === _currentUserId;
    select.onchange = () => updateUser(user.id, 'role', {role: select.value});
    role.append(select);
    const created = document.createElement('td');
    const date = new Date((user.created_at || '').replace(' ', 'T'));
    created.textContent = Number.isNaN(date.getTime()) ? '?' : date.toLocaleDateString('en-GB', {day: '2-digit', month: 'short', year: 'numeric'});
    created.title = user.created_at || '';
    created.className = 'account-created';
    const actions = document.createElement('td');
    const button = document.createElement('button');
    button.textContent = user.is_active ? 'Deactivate' : 'Activate';
    button.className = `btn-sm ${user.is_active ? 'btn-del' : 'btn-activate'}`;
    button.disabled = user.id === _currentUserId;
    button.setAttribute('aria-label', `${user.is_active ? 'Deactivate' : 'Activate'} ${user.username}`);
    button.onclick = () => updateUser(user.id, user.is_active ? 'deactivate' : 'activate');
    const status = document.createElement('span');
    status.className = `account-status ${user.is_active ? 'is-active' : 'is-inactive'}`;
    status.textContent = user.is_active ? 'Active' : 'Inactive';
    const controls = document.createElement('div');
    controls.className = 'account-actions';
    controls.append(status, button);
    actions.append(controls);
    const supervisorCell = document.createElement('td');
    const supervisor = document.createElement('select');
    supervisor.className = 'role-select';
    supervisor.setAttribute('aria-label', `Supervisor for ${user.username}`);
    supervisor.add(new Option('Unassigned', '', false, !user.supervisor_user_id));
    users.filter(u => u.role === 'sales_tl' && u.is_active).forEach(tl => {
      supervisor.add(new Option(tl.username, tl.id, false, tl.id === user.supervisor_user_id));
    });
    if (user.supervisor_user_id && ![...supervisor.options].some(o => Number(o.value) === user.supervisor_user_id)) {
      supervisor.add(new Option('Unavailable supervisor', user.supervisor_user_id, false, true));
    }
    supervisor.disabled = !user.is_active || !['user', 'sales_executive'].includes(user.role);
    supervisor.onchange = () => updateUser(user.id, 'supervisor', {supervisor_user_id: supervisor.value ? Number(supervisor.value) : null});
    supervisorCell.append(supervisor);
    row.append(name, role, supervisorCell, created, actions);
    tbody.append(row);
  });
  // Populate reset-password dropdown
  const sel = document.getElementById('resetUserId');
  sel.replaceChildren(...users.map(u => new Option(u.username, u.id)));
}

async function addUser() {
  const username = document.getElementById('newUsername').value.trim();
  const password = document.getElementById('newPassword').value.trim();
  const role     = document.getElementById('newRole').value;
  const msg      = document.getElementById('addMsg');
  msg.className  = 'msg';

  if (!username || !password) { showMsg(msg, 'Username and password are required', false); return; }

  const resp = await fetch('/api/manager/users/add', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ username, password, role })
  });
  if ([401, 403].includes(resp.status)) { showAccessError(resp.status); return; }
  const data = await resp.json();
  if (resp.ok) {
    showMsg(msg, `User "${username}" added successfully`, true);
    document.getElementById('newUsername').value = '';
    document.getElementById('newPassword').value = '';
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

  if (!password || password.length < 4) { showMsg(msg, 'Password must be at least 4 characters', false); return; }

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