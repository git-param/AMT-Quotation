const title = document.getElementById('statusTitle');
const details = document.getElementById('statusText');
async function checkDevice() {
  try {
    const response = await fetch('/api/device/status', {cache: 'no-store'});
    if (response.status === 401) { location.href = '/login'; return; }
    if (!response.ok) throw new Error('Unable to check approval status.');
    const {status} = await response.json();
    if (status === 'approved') { location.href = '/'; return; }
    const messages = {
      pending: ['Waiting for Admin approval', 'Your device request was sent. This page checks automatically.'],
      rejected: ['Device request rejected', 'An Admin rejected this device. Contact your Admin.'],
      revoked: ['Device access revoked', 'An Admin revoked access for this device. Contact your Admin.'],
      missing: ['Device registration missing', 'Sign out and register a valid device.'],
      unavailable: ['Device unavailable', 'This MAC address belongs to another account. Contact your Admin.'],
    };
    [title.textContent, details.textContent] = messages[status] || ['Device unavailable', 'Contact your Admin.'];
  } catch (_) {
    title.textContent = 'Unable to check device status';
    details.textContent = 'Check your connection and try again.';
  }
}
document.getElementById('retry').onclick = checkDevice;
document.getElementById('signout').onclick = async () => {
  const match = document.cookie.match(/(?:^|; )amt_csrf_v2=([^;]*)/);
  await fetch('/logout', {method: 'POST', headers: match ? {'X-CSRF-Token': decodeURIComponent(match[1])} : {}});
  location.href = '/login';
};
checkDevice();
setInterval(checkDevice, 5000);
