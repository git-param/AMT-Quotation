async function doLogin(e) {
  e.preventDefault();
  const btn  = document.getElementById('loginBtn');
  const err  = document.getElementById('errMsg');
  if (!deviceContext) { showDeviceNotice(); return; }
  err.classList.remove('show');
  btn.disabled = true; btn.textContent = 'Signing in…';

  const body = new URLSearchParams({
    username: document.getElementById('username').value,
    password: document.getElementById('password').value,
    mac_address: deviceContext.mac,
    device_name: deviceContext.name,
  });
  let resp;
  try { resp = await fetch('/login', { method:'POST', body }); }
  catch (_) { err.textContent = 'Unable to connect. Please try again.'; err.classList.add('show'); btn.disabled = false; btn.textContent = 'Sign In'; return; }
  if (resp.ok && resp.redirected) {
    window.location.href = resp.url;
  } else if (resp.ok) {
    window.location.href = '/';
  } else {
    const data = await resp.json().catch(() => ({}));
    err.textContent = data.error || 'Unable to sign in. Please try again.';
    err.classList.add('show');
    btn.disabled = false; btn.textContent = 'Sign In';
    document.getElementById('password').value = '';
    document.getElementById('password').focus();
  }
}

const deviceParams = new URLSearchParams(location.hash.slice(1));
const mac = deviceParams.get('mac') || '';
const name = deviceParams.get('name') || '';
const deviceContext = /^(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}$/.test(mac) && name.trim()
  ? {mac, name: name.trim().slice(0, 120)} : null;
if (location.hash) history.replaceState(null, '', location.pathname + location.search);
function showDeviceNotice() {
  const notice = document.getElementById('deviceNotice');
  notice.textContent = 'This browser cannot read your network adapter MAC address. Open AMT Quotation through the Windows desktop launcher to register or sign in on this device.';
  notice.hidden = false;
  document.getElementById('loginBtn').disabled = true;
}
if (!deviceContext) showDeviceNotice();

const password = document.getElementById('password');
const passwordToggle = document.getElementById('passwordToggle');
passwordToggle.addEventListener('click', () => {
  const visible = password.type === 'text';
  password.type = visible ? 'password' : 'text';
  passwordToggle.textContent = visible ? 'Show' : 'Hide';
  passwordToggle.setAttribute('aria-label', visible ? 'Show password' : 'Hide password');
  passwordToggle.setAttribute('aria-pressed', String(!visible));
});
