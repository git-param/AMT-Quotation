const devicePage = {
  message: document.getElementById('deviceMessage'),
  pending: document.getElementById('pendingDevices'),
  reviewed: document.getElementById('reviewedDevices'),
  count: document.getElementById('pendingCount'),
  emptyPending: document.getElementById('emptyPending'),
  emptyReviewed: document.getElementById('emptyReviewed'),
  refresh: document.getElementById('refreshDevices'),
  currentUserId: null,
  busy: false,
};

function deviceCell(row, value) {
  const cell = row.insertCell();
  cell.textContent = value == null ? '' : String(value);
  return cell;
}

function requestedAt(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function deviceRow(device, pending) {
  const row = document.createElement('tr');
  deviceCell(row, device.username);
  deviceCell(row, device.device_name);
  deviceCell(row, device.mac_address);
  if (pending) deviceCell(row, requestedAt(device.requested_at));
  else {
    deviceCell(row, device.status);
    deviceCell(row, device.decided_by || '—');
  }
  const actions = deviceCell(row, '');
  actions.className = 'actions';
  if (device.user_id === devicePage.currentUserId) {
    actions.textContent = 'Your device';
  } else {
    for (const action of pending ? ['approve', 'reject'] : device.status === 'approved' ? ['revoke'] : []) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'btn-sm ' + action;
      button.textContent = action[0].toUpperCase() + action.slice(1);
      button.addEventListener('click', () => decideDevice(device, action));
      actions.append(button);
    }
  }
  return row;
}

async function loadDeviceRequests() {
  if (devicePage.busy) return;
  devicePage.message.classList.remove('is-error');
  try {
    const response = await fetch('/api/admin/devices');
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Unable to load device requests.');
    const pending = result.devices.filter(device => device.status === 'pending');
    const reviewed = result.devices.filter(device => device.status !== 'pending');
    devicePage.pending.replaceChildren(...pending.map(device => deviceRow(device, true)));
    devicePage.reviewed.replaceChildren(...reviewed.map(device => deviceRow(device, false)));
    devicePage.count.textContent = `(${pending.length})`;
    devicePage.emptyPending.hidden = pending.length > 0;
    devicePage.emptyReviewed.hidden = reviewed.length > 0;
    devicePage.message.textContent = '';
  } catch (error) {
    devicePage.message.textContent = error.message;
    devicePage.message.classList.add('is-error');
  }
}

async function decideDevice(device, action) {
  if (devicePage.busy) return;
  if (action !== 'approve' && !window.confirm(`${action === 'reject' ? 'Reject' : 'Revoke'} ${device.username}'s device ${device.device_name}?`)) return;
  devicePage.busy = true;
  devicePage.refresh.disabled = true;
  devicePage.message.classList.remove('is-error');
  try {
    const response = await fetch(`/api/admin/devices/${device.id}/${action}`, {method: 'POST'});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Unable to update this device.');
    devicePage.busy = false;
    await loadDeviceRequests();
    devicePage.message.textContent = `${device.username}'s device ${result.status}.`;
  } catch (error) {
    devicePage.message.textContent = error.message;
    devicePage.message.classList.add('is-error');
  } finally {
    devicePage.busy = false;
    devicePage.refresh.disabled = false;
  }
}

devicePage.refresh.addEventListener('click', loadDeviceRequests);
fetch('/api/me').then(async response => {
  if (!response.ok) throw new Error('Sign in to review device requests.');
  const user = await response.json();
  if (!(user.permissions || []).includes('devices.manage')) throw new Error('Device management access is required.');
  devicePage.currentUserId = user.id;
  await loadDeviceRequests();
}).catch(error => {
  devicePage.message.textContent = error.message;
  devicePage.message.classList.add('is-error');
});
setInterval(() => { if (!document.hidden) loadDeviceRequests(); }, 15000);
