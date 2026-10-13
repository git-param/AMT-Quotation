async function doLogin(e) {
  e.preventDefault();
  const btn  = document.getElementById('loginBtn');
  const err  = document.getElementById('errMsg');
  err.classList.remove('show');
  btn.disabled = true; btn.textContent = 'Signing in…';

  const body = new URLSearchParams({
    username: document.getElementById('username').value,
    password: document.getElementById('password').value,
  });

  const resp = await fetch('/login', { method:'POST', body });
  if (resp.ok && resp.redirected) {
    window.location.href = resp.url;
  } else if (resp.ok) {
    window.location.href = '/';
  } else {
    err.textContent = 'Invalid username or password. Please try again.';
    err.classList.add('show');
    btn.disabled = false; btn.textContent = 'Sign In';
    document.getElementById('password').value = '';
    document.getElementById('password').focus();
  }
}
