// ── Chart.js inline (minimal bar/pie renderer, no CDN needed) ────────────────
// We'll use a lightweight canvas drawing approach

let _charts = {};

function drawBarChart(canvasId, labels, values, color) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const W = canvas.offsetWidth; canvas.width = W;
  const H = canvas.height;
  ctx.clearRect(0,0,W,H);

  if (!values.length || Math.max(...values) === 0) {
    ctx.fillStyle = '#9CA3AF'; ctx.font = '13px Segoe UI';
    ctx.textAlign = 'center'; ctx.fillText('No data yet', W/2, H/2);
    return;
  }

  const pad = {top:10, right:10, bottom:55, left:36};
  const cW = W - pad.left - pad.right;
  const cH = H - pad.top - pad.bottom;
  const maxV = Math.max(...values) || 1;

  // Grid lines
  ctx.strokeStyle = '#F3F4F6'; ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = pad.top + cH - (i/4)*cH;
    ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(pad.left+cW, y); ctx.stroke();
    ctx.fillStyle = '#9CA3AF'; ctx.font = '10px Segoe UI'; ctx.textAlign = 'right';
    ctx.fillText(Math.round((i/4)*maxV), pad.left-4, y+3);
  }

  const bW = Math.max(6, cW / labels.length * 0.6);
  const gap = cW / labels.length;
  values.forEach((v, i) => {
    const bH = (v / maxV) * cH;
    const x  = pad.left + gap * i + (gap - bW) / 2;
    const y  = pad.top + cH - bH;
    // Bar
    ctx.fillStyle = color || '#1A56DB';
    ctx.beginPath();
    ctx.roundRect ? ctx.roundRect(x, y, bW, bH, [3,3,0,0]) : ctx.rect(x, y, bW, bH);
    ctx.fill();
    // Value label on top
    if (v > 0) {
      ctx.fillStyle = '#374151'; ctx.font = 'bold 10px Segoe UI'; ctx.textAlign = 'center';
      ctx.fillText(v, x + bW/2, y - 3);
    }
    // X label -- rotated to avoid overlap
    const lbl = String(labels[i]);
    const short = lbl.length > 8 ? lbl.slice(-5) : lbl;
    ctx.save();
    ctx.translate(x + bW/2, pad.top + cH + 8);
    ctx.rotate(-Math.PI / 4);
    ctx.fillStyle = '#6B7280'; ctx.font = '10px Segoe UI'; ctx.textAlign = 'right';
    ctx.fillText(short, 0, 0);
    ctx.restore();
  });
}

function drawHBarChart(canvasId, labels, values, color) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const W = canvas.offsetWidth; canvas.width = W;
  const H = Math.max(canvas.height, labels.length * 28 + 20);
  canvas.height = H;
  ctx.clearRect(0,0,W,H);

  if (!labels.length) {
    ctx.fillStyle = '#9CA3AF'; ctx.font = '13px Segoe UI';
    ctx.textAlign = 'center'; ctx.fillText('No data yet', W/2, H/2); return;
  }

  const pad = {top:8, right:50, bottom:8, left:10};
  const maxLblW = Math.min(labels.reduce((m,l)=>Math.max(m,l.length),0)*7, 110);
  const chartL  = pad.left + maxLblW + 8;
  const cW = W - chartL - pad.right;
  const maxV = Math.max(...values) || 1;
  const rowH = (H - pad.top - pad.bottom) / labels.length;

  labels.forEach((lbl, i) => {
    const y   = pad.top + i * rowH;
    const bH  = Math.max(2, rowH * 0.55);
    const bY  = y + (rowH - bH) / 2;
    const bW  = (values[i] / maxV) * cW;
    ctx.fillStyle = color || '#1A56DB';
    ctx.beginPath();
    ctx.roundRect ? ctx.roundRect(chartL, bY, bW, bH, 3) : ctx.rect(chartL, bY, bW, bH);
    ctx.fill();
    // Label
    ctx.fillStyle = '#374151'; ctx.font = '11px Segoe UI'; ctx.textAlign = 'right';
    ctx.fillText(lbl.length > 14 ? lbl.slice(0,14)+'…' : lbl, chartL - 6, bY + bH/2 + 4);
    // Value
    ctx.fillStyle = '#6B7280'; ctx.font = 'bold 10px Segoe UI'; ctx.textAlign = 'left';
    ctx.fillText(values[i], chartL + bW + 5, bY + bH/2 + 4);
  });
}

function drawPieChart(canvasId, labels, values, colors) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const W = canvas.offsetWidth; canvas.width = W;
  const H = canvas.height; ctx.clearRect(0,0,W,H);

  const total = values.reduce((a,b)=>a+b,0);
  if (!total) {
    ctx.fillStyle='#9CA3AF'; ctx.font='13px Segoe UI';
    ctx.textAlign='center'; ctx.fillText('No data yet',W/2,H/2); return;
  }

  const cx = W * 0.31, cy = H/2, r = Math.min(cx*0.9, cy) - 10;
  const COLORS = colors || ['#1A56DB','#057A55','#B45309','#6C2BD9','#DC2626','#0891B2'];
  let angle = -Math.PI/2;

  values.forEach((v, i) => {
    const slice = (v / total) * 2 * Math.PI;
    ctx.fillStyle = COLORS[i % COLORS.length];
    ctx.beginPath(); ctx.moveTo(cx,cy);
    ctx.arc(cx, cy, r, angle, angle+slice); ctx.closePath(); ctx.fill();
    angle += slice;
  });

  // Donut hole
  ctx.fillStyle = '#fff';
  ctx.beginPath(); ctx.arc(cx, cy, r*0.5, 0, 2*Math.PI); ctx.fill();
  ctx.fillStyle = '#374151'; ctx.font = 'bold 13px Segoe UI'; ctx.textAlign='center';
  ctx.fillText(total, cx, cy+2); ctx.font='10px Segoe UI'; ctx.fillText('total',cx,cy+14);

  // Legend
  const lx = W * 0.64;
  labels.forEach((lbl, i) => {
    const ly = 20 + i * 22;
    ctx.fillStyle = COLORS[i % COLORS.length];
    ctx.fillRect(lx-16, ly, 12, 12);
    ctx.fillStyle = '#374151'; ctx.font = '11px Segoe UI'; ctx.textAlign='left';
    const pct = Math.round(values[i]/total*100);
    const short = lbl.replace(/EMAIL_LETTER_/i,'EML ').replace('formal_','').replace('wa_','WA ').toUpperCase();
    ctx.fillText(`${short} (${pct}%)`, lx, ly+10);
  });
}

// ── Load stats ───────────────────────────────────────────────────────────────
async function loadStats() {
  try {
    const resp = await fetch('/api/manager/stats');
    const d    = await resp.json();
    renderStats(d);
    document.getElementById('lastUpdated').textContent = 'Updated ' + new Date().toLocaleTimeString();
  } catch(e) {
    console.error(e);
  }
}

function renderStats(d) {
  // Cards
  document.getElementById('c-searches').textContent = d.today.searches;
  document.getElementById('c-skus').textContent     = d.today.skus_searched;
  document.getElementById('c-found').textContent    = d.today.found;
  document.getElementById('c-copies').textContent   = d.today.copies;

  // Days chart
  const days   = d.by_day.map(r => r.day ? r.day.slice(5) : '');
  const dSkus  = d.by_day.map(r => r.skus || 0);
  setTimeout(() => drawBarChart('chartDays', days, dSkus, '#1A56DB'), 50);

  // Users chart
  const uNames = d.by_user.slice(0,8).map(r => r.user_name || 'Unknown');
  const uSkus  = d.by_user.slice(0,8).map(r => r.skus || 0);
  setTimeout(() => drawHBarChart('chartUsers', uNames, uSkus, '#057A55'), 50);

  // Copy types chart
  const ctLabels = d.copy_types.map(r => r.copy_type || '');
  const ctVals   = d.copy_types.map(r => r.cnt || 0);
  setTimeout(() => drawPieChart('chartCopies', ctLabels, ctVals), 50);

  // Recent searches table
  const tR = document.getElementById('tblRecent');
  if (!d.recent.length) {
    tR.innerHTML = '<tr><td colspan="5" class="empty">No searches yet</td></tr>';
  } else {
    tR.innerHTML = d.recent.map(r => {
      const found = r.found_count || 0;
      const nf    = r.not_found || 0;
      const ts    = r.ts ? r.ts.slice(5,16) : '';
      return `<tr>
        <td><strong>${esc(r.user_name||'Unknown')}</strong></td>
        <td class="skus-cell" title="${esc(r.skus||'')}">${esc(r.skus||'—')}</td>
        <td><span class="badge badge-ok">${found}</span></td>
        <td>${nf > 0 ? `<span class="badge badge-err">${nf}</span>` : '<span style="color:#9CA3AF">0</span>'}</td>
        <td style="color:#6B7280;font-size:11.5px">${esc(ts)}</td>
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
        <td><strong>${esc(r.sku)}</strong></td>
        <td><span class="badge badge-ok">${r.count}</span></td>
      </tr>`).join('');
  }

  // User table
  const tU = document.getElementById('tblUsers');
  if (!d.by_user.length) {
    tU.innerHTML = '<tr><td colspan="6" class="empty">No data yet</td></tr>';
  } else {
    tU.innerHTML = d.by_user.map(r => {
      const hit = r.skus > 0 ? Math.round(r.found / r.skus * 100) : 0;
      const badgeCls = hit >= 80 ? 'badge-ok' : hit >= 50 ? 'badge-warn' : 'badge-err';
      const last = r.last_seen ? r.last_seen.slice(0,16) : '—';
      return `<tr>
        <td><strong>${esc(r.user_name||'Unknown')}</strong></td>
        <td>${r.searches}</td>
        <td>${r.skus}</td>
        <td>${r.found}</td>
        <td><span class="badge ${badgeCls}">${hit}%</span></td>
        <td style="color:#6B7280;font-size:11.5px">${esc(last)}</td>
      </tr>`;
    }).join('');
  }
}

function esc(s) {
  return String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ── Boot ─────────────────────────────────────────────────────────────────────
fetch('/api/me').then(r => r.json()).then(u => {
  document.getElementById('hdrUser').textContent = '👤 ' + u.username;
  if (u.role !== 'manager') window.location.href = '/';
}).catch(() => { window.location.href = '/login'; });

// Auto-refresh every 60s
loadStats();
loadUsers();
setInterval(loadStats, 60000);
window.addEventListener('resize', () => { loadStats(); });

// ── User management ───────────────────────────────────────────────────────────
async function loadUsers() {
  const resp = await fetch('/api/manager/users').catch(() => null);
  if (!resp || !resp.ok) return;
  const data = await resp.json();
  const users = data.users || [];

  // Populate users table
  const tbody = document.getElementById('usersList');
  tbody.innerHTML = users.length ? users.map(u => `
    <tr>
      <td><strong>${esc(u.username)}</strong></td>
      <td><span class="role-badge ${u.role === 'manager' ? 'role-manager' : 'role-user'}">${u.role}</span></td>
      <td style="color:#6B7280;font-size:12px">${esc((u.created_at||'').slice(0,16))}</td>
      <td>
        ${u.username === 'manager' ? '<span style="font-size:11px;color:#9CA3AF">Protected</span>' : `<button class="btn-sm btn-del" onclick="deleteUser(${u.id},'${esc(u.username)}')">Delete</button>`}
      </td>
    </tr>`).join('') : '<tr><td colspan="4" class="empty">No users yet</td></tr>';

  // Populate reset-password dropdown
  const sel = document.getElementById('resetUserId');
  sel.innerHTML = users.map(u => `<option value="${u.id}">${esc(u.username)} (${u.role})</option>`).join('');
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

async function deleteUser(uid, username) {
  if (!confirm(`Delete user "${username}"? This cannot be undone.`)) return;
  const msg  = document.getElementById('deleteMsg');
  const resp = await fetch(`/api/manager/users/${uid}/delete`, { method: 'POST' });
  const data = await resp.json();
  if (resp.ok) {
    showMsg(msg, `User "${username}" deleted`, true);
    loadUsers();
  } else {
    showMsg(msg, data.error || 'Failed to delete', false);
  }
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
